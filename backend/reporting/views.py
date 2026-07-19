"""
周报视图：
- me: 写草稿、查看自己的周报、提交
- admin: 查看全员已提交周报、添加备注
"""

from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import (
    ReportingPeriod,
    WeeklyReport,
    WeeklyReportRevision,
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

def _get_current_period():
    """获取当前 ISO 周周期。"""
    from datetime import timedelta, datetime

    today = timezone.now().date()
    iso = today.isocalendar()
    period = ReportingPeriod.objects.filter(
        iso_year=iso[0], iso_week=iso[1]
    ).first()
    if not period:
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        deadline_naive = datetime.combine(week_end + timedelta(days=1), datetime.min.time())
        deadline = timezone.make_aware(deadline_naive)
        period = ReportingPeriod.objects.create(
            iso_year=iso[0],
            iso_week=iso[1],
            start_date=week_start,
            end_date=week_end,
            deadline=deadline,
        )
    return period


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
    period = _get_current_period()
    report = _get_or_create_report(request.user, period)
    return Response(WeeklyReportDetailSerializer(report).data)


@api_view(["GET"])
def list_my_reports(request):
    """GET /api/v1/me/reports —— 我的历史周报。"""
    qs = WeeklyReport.objects.filter(owner=request.user).select_related(
        "owner", "reporting_period"
    ).order_by("-created_at")[:50]
    return Response(WeeklyReportListSerializer(qs, many=True).data)


@api_view(["GET"])
def get_my_report(request, report_id):
    """GET /api/v1/me/reports/{id}"""
    report = get_object_or_404(WeeklyReport, id=report_id, owner=request.user)
    return Response(WeeklyReportDetailSerializer(report).data)


@api_view(["PATCH"])
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

    report = get_object_or_404(WeeklyReport, id=report_id, owner=request.user)
    if report.status not in {ReportStatus.DRAFT, ReportStatus.RESUBMITTED}:
        return Response(
            {"code": "ALREADY_SUBMITTED", "message": "周报已提交，请使用重新提交"},
            status=status.HTTP_409_CONFLICT,
        )

    # 校验附件：只阻止还在处理中的文件，preview_ready/ready/user_confirmed 都允许
    from attachments.models import Attachment, AttachmentStatus
    still_processing = Attachment.objects.filter(
        report=report,
        status__in={
            AttachmentStatus.UPLOADING,
            AttachmentStatus.QUARANTINED,
            AttachmentStatus.SCANNING,
            AttachmentStatus.CONVERTING,
        },
    )
    if still_processing.exists():
        names = ", ".join(still_processing.values_list("original_filename", flat=True)[:5])
        return Response(
            {
                "code": "ATTACHMENTS_STILL_PROCESSING",
                "message": f"以下附件仍在处理中：{names}",
            },
            status=status.HTTP_409_CONFLICT,
        )

    confirmed_pdf = None
    if data.get("confirmed_pdf_attachment_id"):
        from attachments.models import Attachment
        confirmed_pdf = get_object_or_404(
            Attachment, id=data["confirmed_pdf_attachment_id"], report=report
        )
    else:
        # 自动选第一个 user_confirmed 或 preview_ready 或 ready 的附件
        from attachments.models import Attachment
        confirmed_pdf = Attachment.objects.filter(
            report=report,
            status__in=["user_confirmed", "preview_ready", "ready", "ready_with_warning"],
        ).first()

    revision = report.submit(
        submitted_by=request.user,
        confirmed_pdf_attachment=confirmed_pdf,
    )

    # 事务提交后触发异步分析（TODO: 对接 Celery）
    # from analysis.tasks import analyze_report
    # analyze_report.delay(str(revision.id))

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
    report = get_object_or_404(WeeklyReport, id=report_id, owner=request.user)
    if report.status not in {ReportStatus.SUBMITTED, ReportStatus.RESUBMITTED}:
        return Response(
            {"code": "NOT_SUBMITTED", "message": "草稿请使用直接提交"},
            status=status.HTTP_409_CONFLICT,
        )

    # 重新打开编辑
    report.status = ReportStatus.DRAFT
    report.save(update_fields=["status"])
    return Response({"detail": "周报已重新打开，可以上传新文件", "status": "draft"})


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
        "owner", "owner__department", "reporting_period"
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

    return Response(WeeklyReportDetailSerializer(report).data)


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
    report = get_object_or_404(WeeklyReport, id=report_id)

    serializer = CreateAdminNoteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    note = AdminReportNote.objects.create(
        report=report,
        author=request.user,
        content=serializer.validated_data["content"],
    )
    return Response(AdminNoteSerializer(note).data, status=status.HTTP_201_CREATED)
