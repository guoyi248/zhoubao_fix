"""
周报视图：
- me: 写草稿、查看自己的周报、提交
- admin: 查看全员已提交周报、添加备注
"""

from uuid import UUID

from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from audit.events import record_report
from audit.models import AuditEvent

from system_config.attachment_limits import policy
from .periods import current_period, missing_members
from .models import (
    ReportingPeriod,
    WeeklyReport,
    WeeklyReportRevision,
    WeeklyReminder,
    AdminReportNote,
    ReportStatus,
)
from .serializers import (
    SaveDraftSerializer,
    SubmitReportSerializer,
    WeeklyReportListSerializer,
    WeeklyReportDetailSerializer,
    RevisionDetailSerializer,
    AdminNoteSerializer,
    CreateAdminNoteSerializer,
    ReminderEmailSerializer,
    ReportingPeriodSerializer,
)
from common.exceptions import (
    PermissionDeniedError,
    ObjectNotFound,
    VersionConflictError,
)


# ═══════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════



def _get_or_create_report(user, period):
    """获取或创建用户的当前周期周报（草稿）。"""
    report, _created = WeeklyReport.objects.get_or_create(
        owner=user,
        reporting_period=period,
        defaults={"status": ReportStatus.DRAFT},
    )
    return report


# ═══════════════════════════════════════════════════════════════
# Me: 成员周报 CRUD
# ═══════════════════════════════════════════════════════════════


@api_view(["GET"])
def current_report(request):
    """GET /api/v1/me/reports/current —— 获取或自动创建当前周期的周报。"""
    period = current_period()
    report = _get_or_create_report(request.user, period)
    return Response({
        **WeeklyReportDetailSerializer(report).data,
        "attachment_count": report.attachments.filter(is_current=True).count(),
        "attachment_limits": policy()["limits"],
    })


@api_view(["GET"])
def list_my_reports(request):
    """GET /api/v1/me/reports —— 我的历史周报。"""
    qs = WeeklyReport.objects.filter(owner=request.user).select_related(
        "owner", "reporting_period", "current_revision__confirmed_pdf_attachment"
    ).order_by("-reporting_period__iso_year", "-reporting_period__iso_week")[:50]
    return Response(WeeklyReportListSerializer(qs, many=True).data)


@api_view(["GET"])
def get_my_report(request, report_id):
    """GET /api/v1/me/reports/{id}"""
    report = get_object_or_404(WeeklyReport, id=report_id, owner=request.user)
    return Response(WeeklyReportDetailSerializer(report).data)


@api_view(["PATCH"])
@transaction.atomic
def save_draft(request, report_id):
    """PATCH /api/v1/me/reports/{id} —— 乐观锁保存草稿。"""
    serializer = SaveDraftSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    report = get_object_or_404(WeeklyReport, id=report_id, owner=request.user)
    if report.status not in {ReportStatus.DRAFT, ReportStatus.RESUBMITTED}:
        return Response(
            {"code": "REPORT_NOT_EDITABLE", "message": "当前状态不允许编辑"},
            status=status.HTTP_409_CONFLICT,
        )

    try:
        report.save_draft(data["content"], data["version"])
    except VersionConflictError:
        return Response(
            {
                "code": "REPORT_VERSION_CONFLICT",
                "message": "文档已被其他标签页修改，请刷新后重试",
                "server_version": report.optimistic_version,
            },
            status=status.HTTP_409_CONFLICT,
        )

    record_report(request, AuditEvent.EventType.DRAFT_UPDATED, report, f"保存草稿 v{report.optimistic_version}")
    return Response({
        "version": report.optimistic_version,
        "detail": "草稿已保存",
    })


@api_view(["POST"])
@transaction.atomic
def submit_report(request, report_id):
    """POST /api/v1/me/reports/{id}/submit —— 提交周报，创建不可变修订版。"""
    serializer = SubmitReportSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    report = get_object_or_404(WeeklyReport.objects.select_for_update(), id=report_id, owner=request.user)
    if report.status not in {ReportStatus.DRAFT, ReportStatus.RESUBMITTED}:
        return Response(
            {"code": "ALREADY_SUBMITTED", "message": "周报已提交，请使用重新提交"},
            status=status.HTTP_409_CONFLICT,
        )

    from attachments.models import AttachmentStatus
    attachments = report.attachments.filter(is_current=True)
    still_processing = attachments.filter(status__in={
        AttachmentStatus.UPLOADING, AttachmentStatus.QUARANTINED, AttachmentStatus.SCANNING,
        AttachmentStatus.COMPATIBILITY_CHECK, AttachmentStatus.CONVERTING,
    })
    if still_processing.exists():
        names = ", ".join(still_processing.values_list("original_filename", flat=True)[:5])
        return Response(
            {
                "code": "ATTACHMENTS_STILL_PROCESSING",
                "message": f"以下附件仍在处理中：{names}",
            },
            status=status.HTTP_409_CONFLICT,
        )

    if attachments.filter(status=AttachmentStatus.REJECTED).exists():
        return Response({"code": "ATTACHMENT_REJECTED", "message": "请先移除未通过安全扫描的附件"}, status=409)
    candidates = attachments.order_by("-created_at", "id")
    selected_id = data.get("confirmed_pdf_attachment_id")
    if selected_id:
        confirmed_pdf = get_object_or_404(candidates, pk=selected_id)
        if not confirmed_pdf.pdf_source:
            return Response({"code": "NO_PREVIEW", "message": "选中的附件没有可用的 PDF 预览"}, status=409)
    else:
        # 优先选择成员已确认的预览，同等条件下使用最近上传的文件。
        from django.db.models import Case, When, Value, IntegerField
        candidates = candidates.order_by(
            Case(When(status=AttachmentStatus.USER_CONFIRMED, then=Value(0)), default=Value(1),
                 output_field=IntegerField()), "-created_at", "id",
        )
        confirmed_pdf = next((a for a in candidates if a.pdf_source), None)
        if not confirmed_pdf and attachments.exists() and not report.draft_content_json:
            return Response({"code": "NO_PREVIEW", "message": "附件尚无可展示的 PDF，请重新生成预览或替换文件"}, status=409)

    revision = report.submit(submitted_by=request.user, confirmed_pdf_attachment=confirmed_pdf,
                             reason=data["reason"])
    event = AuditEvent.EventType.REPORT_SUBMITTED if revision.revision_no == 1 else AuditEvent.EventType.REPORT_RESUBMITTED
    record_report(request, event, report, f"提交第 {revision.revision_no} 版周报")

    return Response(
        {
            "revision_id": str(revision.id),
            "revision_no": revision.revision_no,
            "detail": "周报已提交",
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@transaction.atomic
def resubmit_report(request, report_id):
    """POST /api/v1/me/reports/{id}/resubmit —— 重新提交（修改已提交周报后再次提交）。"""
    report = get_object_or_404(WeeklyReport.objects.select_for_update(), id=report_id, owner=request.user)
    if report.status not in {ReportStatus.SUBMITTED, ReportStatus.RESUBMITTED}:
        return Response(
            {"code": "NOT_SUBMITTED", "message": "草稿请使用直接提交"},
            status=status.HTTP_409_CONFLICT,
        )

    # 保持 RESUBMITTED 状态（管理员可见，成员可编辑）
    if report.status != ReportStatus.RESUBMITTED:
        report.status = ReportStatus.RESUBMITTED
        report.save(update_fields=["status"])
        record_report(request, AuditEvent.EventType.REPORT_REOPENED, report, "重新打开周报进行更正")
    return Response({"detail": "周报已重新打开，可以上传新文件", "status": "resubmitted"})


@api_view(["POST"])
@parser_classes([MultiPartParser])
@transaction.atomic
def correct_report(request, report_id):
    """用可预览的新文件创建修订，保留所有已提交版本。"""
    from attachments.models import AttachmentStatus
    from attachments.services import retire_attachments, store_report_file

    report = get_object_or_404(WeeklyReport.objects.select_for_update(), id=report_id, owner=request.user)
    if report.status not in {ReportStatus.SUBMITTED, ReportStatus.RESUBMITTED}:
        return Response({"code": "NOT_SUBMITTED", "message": "只能更正已提交的周报"}, status=409)
    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return Response({"code": "NO_FILE", "message": "请选择文件"}, status=400)

    retire_attachments(report.attachments.filter(is_current=True))
    attachment = store_report_file(report, uploaded_file, request.user, require_preview=True)
    attachment.status = AttachmentStatus.USER_CONFIRMED
    attachment.save(update_fields=["status", "updated_at"])
    report.status = ReportStatus.RESUBMITTED
    revision = report.submit(request.user, confirmed_pdf_attachment=attachment)
    record_report(request, AuditEvent.EventType.REPORT_RESUBMITTED, report,
                  f"上传更正版 {revision.revision_no} · {uploaded_file.name}")
    return Response({
        "detail": "周报已更正",
        "revision_id": str(revision.pk),
        "revision_no": revision.revision_no,
        "attachment_id": str(attachment.id),
        "status": attachment.status,
    }, status=201)


@api_view(["GET"])
def list_my_revisions(request, report_id):
    """GET /api/v1/me/reports/{id}/revisions"""
    report = get_object_or_404(WeeklyReport, id=report_id, owner=request.user)
    revisions = report.revisions.select_related("submitted_by").all()
    from .serializers import RevisionSerializer
    return Response(RevisionSerializer(revisions, many=True).data)


@api_view(["GET"])
def get_revision(request, report_id, revision_id):
    """GET /api/v1/me/reports/{id}/revisions/{revision_id}"""
    report = get_object_or_404(WeeklyReport, id=report_id, owner=request.user)
    revision = get_object_or_404(WeeklyReportRevision, id=revision_id, report=report)
    return Response(RevisionDetailSerializer(revision).data)


# ═══════════════════════════════════════════════════════════════
# Admin: 全员周报查看
# ═══════════════════════════════════════════════════════════════


def _require_admin(user):
    if not user.is_authenticated or not user.is_active or not user.is_admin:
        raise PermissionDeniedError()


@api_view(["GET"])
def admin_list_reports(request):
    """GET /api/v1/admin/reports —— 管理员查看全员已提交周报。"""
    _require_admin(request.user)

    qs = WeeklyReport.objects.visible_to(request.user).select_related(
        "owner", "owner__department", "reporting_period", "current_revision__confirmed_pdf_attachment"
    )

    period = request.GET.get("period")
    department = request.GET.get("department")
    report_status = request.GET.get("status")
    member = request.GET.get("member")

    if period:
        qs = qs.filter(reporting_period_id=period)
    if department:
        qs = qs.filter(owner__department_id=department)
    if report_status:
        qs = qs.filter(status=report_status)
    if member:
        qs = qs.filter(owner_id=member)

    qs = qs.order_by("-reporting_period__iso_year", "-reporting_period__iso_week", "owner__display_name")[:200]
    return Response(WeeklyReportListSerializer(qs, many=True).data)


@api_view(["GET"])
def admin_get_report(request, report_id):
    """GET /api/v1/admin/reports/{id} —— 管理员查看某份周报详情。"""
    _require_admin(request.user)

    report = get_object_or_404(WeeklyReport, id=report_id)
    # 二次鉴权：管理员只能看已提交/补交/归档
    if not request.user.is_admin or report.status not in {
        ReportStatus.SUBMITTED,
        ReportStatus.RESUBMITTED,
        ReportStatus.ARCHIVED,
    }:
        raise PermissionDeniedError()

    return Response(WeeklyReportDetailSerializer(report, context={"published": True}).data)


@api_view(["GET"])
def admin_get_revision(request, report_id, revision_id):
    """GET /api/v1/admin/reports/{id}/revisions/{revision_id}"""
    _require_admin(request.user)
    report = get_object_or_404(WeeklyReport, id=report_id)
    if report.status not in {ReportStatus.SUBMITTED, ReportStatus.RESUBMITTED, ReportStatus.ARCHIVED}:
        raise PermissionDeniedError()
    revision = get_object_or_404(WeeklyReportRevision, id=revision_id, report=report)
    return Response(RevisionDetailSerializer(revision).data)


@api_view(["POST"])
def admin_add_note(request, report_id):
    """POST /api/v1/admin/reports/{id}/notes —— 管理员添加备注。"""
    _require_admin(request.user)
    report = get_object_or_404(WeeklyReport.objects.visible_to(request.user), id=report_id)

    serializer = CreateAdminNoteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    note = AdminReportNote.objects.create(
        report=report,
        author=request.user,
        content=serializer.validated_data["content"],
    )
    return Response(AdminNoteSerializer(note).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
def reminder_center(request):
    from system_config.integrations import get_config, mail_issues, setup_info
    from .reminders import scheduled_time, reminder_message

    user = request.user
    if request.method == "PATCH":
        form = ReminderEmailSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        user.email = form.validated_data["email"]
        user.save(update_fields=["email"])

    period = current_period()
    receipts = WeeklyReminder.objects.filter(period=period, sent_at__isnull=False)
    config = get_config("mail")
    issues = mail_issues(config)
    data = {
        "enabled": config["enabled"],
        "configured": not issues,
        "weekday": config["weekday"],
        "time": config["time"],
        "timezone": str(timezone.get_current_timezone()),
        "scheduled_at": scheduled_time(period.start_date, config),
        "period": ReportingPeriodSerializer(period).data,
        "email": user.email,
        "submitted": period.reports.filter(owner=user, current_revision__isnull=False).exists(),
        "sent_at": receipts.filter(user=user).values_list("sent_at", flat=True).first(),
    }
    if user.is_admin:
        data["setup"] = setup_info(issues)
        delivery = list(receipts.order_by("-sent_at").values("user_id", "user__display_name", "sent_at"))
        times = {r["user_id"]: r["sent_at"] for r in delivery}
        data["team"] = {
            "missing": [{"id": u.pk, "name": u.display_name, "email": u.email, "sent_at": times.get(u.pk)}
                        for u in missing_members(period)],
            "sent": [{"name": r["user__display_name"], "sent_at": r["sent_at"]} for r in delivery],
        }
    # Same template used by the scheduled delivery. Configuration can contain credentials in a URL.
    subject, body = reminder_message(period, user.display_name, "〔工作区网址〕")
    data["preview"] = {"subject": subject, "body": body}
    return Response(data)


@api_view(["GET"])
def admin_week_overview(request):
    _require_admin(request.user)
    current = current_period()
    period = current
    if requested := request.query_params.get("period"):
        try:
            period = get_object_or_404(ReportingPeriod, pk=UUID(requested))
        except ValueError:
            return Response({"message": "周期无效"}, status=400)
    submitted = period.reports.filter(current_revision__isnull=False).select_related(
        "owner", "reporting_period", "current_revision__confirmed_pdf_attachment"
    ).order_by("owner__display_name", "owner_id")
    from analysis.models import AnalysisRun
    latest = AnalysisRun.objects.filter(revision_id=OuterRef("revision_id")).order_by("-created_at")
    runs = AnalysisRun.objects.filter(
        revision_id__in=submitted.values("current_revision_id"), pk=Subquery(latest.values("pk")[:1])
    ).values_list("revision_id", "status", "output_json__summary")
    summaries = {str(revision): {"analysis_status": state, "progress_summary": summary or ""}
                 for revision, state, summary in runs}
    from system_config.integrations import get_config, model_issues
    config = get_config("model")
    idle_state = "disabled" if not config["enabled"] else ("unconfigured" if model_issues(config) else "available")
    empty = {"analysis_status": idle_state, "progress_summary": ""}
    submitted_data = [
        {**row, **summaries.get(str(row["current_revision_id"]), empty)}
        for row in WeeklyReportListSerializer(submitted, many=True).data
    ]
    is_current = period.pk == current.pk
    return Response({
        "period": ReportingPeriodSerializer(period).data,
        "periods": ReportingPeriodSerializer(ReportingPeriod.objects.all(), many=True).data,
        "is_current": is_current,
        "submitted": submitted_data,
        "missing": [{"id": u.pk, "name": u.display_name} for u in missing_members(period)] if is_current else [],
    })
