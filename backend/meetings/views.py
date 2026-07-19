"""
组会视图：
- 创建组会（锁定所有已提交周报的当前 Revision 快照）
- 开始/结束组会
- 标记已讨论
- 行动项 CRUD
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from reporting.models import ReportingPeriod, WeeklyReport, ReportStatus
from common.exceptions import PermissionDeniedError, ObjectNotFound

from .models import (
    Meeting,
    MeetingReportSnapshot,
    MeetingReportState,
    ActionItem,
    MeetingStatus,
)
from .serializers import (
    MeetingDetailSerializer,
    MeetingListSerializer,
    ActionItemSerializer,
    CreateActionItemSerializer,
    UpdateActionItemSerializer,
    MarkDiscussedSerializer,
)


def _require_admin(user):
    if not user.is_authenticated or not user.is_active or not user.is_admin:
        raise PermissionDeniedError()


# ═══════════════════════════════════════════════════════════════
# 创建组会
# ═══════════════════════════════════════════════════════════════

@api_view(["POST"])
@transaction.atomic
def create_meeting(request):
    """
    POST /api/v1/admin/meetings
    创建组会，锁定当前周期所有已提交/补交周报的 Revision 快照。
    """
    _require_admin(request.user)

    # 获取当前周期
    period_id = request.data.get("reporting_period_id")
    if not period_id:
        # 默认当前周期
        today = timezone.now().date()
        iso = today.isocalendar()
        period = get_object_or_404(
            ReportingPeriod, iso_year=iso[0], iso_week=iso[1]
        )
    else:
        period = get_object_or_404(ReportingPeriod, id=period_id)

    # 检查已有进行中的会议
    active_meeting = Meeting.objects.filter(
        reporting_period=period, status=MeetingStatus.IN_PROGRESS
    ).first()
    if active_meeting:
        return Response(
            {
                "code": "MEETING_IN_PROGRESS",
                "message": "此周期已有进行中的组会",
                "meeting_id": str(active_meeting.id),
            },
            status=status.HTTP_409_CONFLICT,
        )

    # 获取所有已提交的周报
    reports = WeeklyReport.objects.filter(
        reporting_period=period,
        status__in={
            ReportStatus.SUBMITTED,
            ReportStatus.RESUBMITTED,
            ReportStatus.ARCHIVED,
        },
    ).select_related("owner", "current_revision")

    if not reports:
        return Response(
            {"code": "NO_REPORTS", "message": "此周期没有已提交的周报"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 创建会议
    meeting = Meeting.objects.create(
        reporting_period=period,
        created_by=request.user,
        status=MeetingStatus.PLANNED,
    )

    # 创建周报快照（固定 Revision）
    member_order = []
    for idx, report in enumerate(reports):
        if report.current_revision:
            MeetingReportSnapshot.objects.create(
                meeting=meeting,
                member=report.owner,
                report_revision=report.current_revision,
                display_order=idx,
            )
            member_order.append(str(report.owner_id))

            # 初始化讨论状态
            MeetingReportState.objects.create(
                meeting=meeting,
                report=report,
                discussed=False,
            )

    meeting.member_order_json = member_order
    meeting.save(update_fields=["member_order_json"])

    return Response(
        MeetingDetailSerializer(meeting).data,
        status=status.HTTP_201_CREATED,
    )


# ═══════════════════════════════════════════════════════════════
# 获取组会详情
# ═══════════════════════════════════════════════════════════════

@api_view(["GET"])
def get_meeting(request, meeting_id):
    """GET /api/v1/admin/meetings/{id}"""
    _require_admin(request.user)
    meeting = get_object_or_404(Meeting, id=meeting_id)
    return Response(MeetingDetailSerializer(meeting).data)


@api_view(["GET"])
def list_meetings(request):
    """GET /api/v1/admin/meetings"""
    _require_admin(request.user)

    period = request.GET.get("period")
    qs = Meeting.objects.select_related("reporting_period", "created_by").order_by("-created_at")

    if period:
        qs = qs.filter(reporting_period_id=period)

    qs = qs[:50]
    return Response(MeetingListSerializer(qs, many=True).data)


# ═══════════════════════════════════════════════════════════════
# 开始/结束组会
# ═══════════════════════════════════════════════════════════════

@api_view(["POST"])
def start_meeting(request, meeting_id):
    """POST /api/v1/admin/meetings/{id}/start"""
    _require_admin(request.user)
    meeting = get_object_or_404(Meeting, id=meeting_id)

    if meeting.status != MeetingStatus.PLANNED:
        return Response(
            {"code": "INVALID_STATUS", "message": f"当前状态 {meeting.status} 不允许开始"},
            status=status.HTTP_409_CONFLICT,
        )

    meeting.status = MeetingStatus.IN_PROGRESS
    meeting.started_at = timezone.now()
    meeting.save(update_fields=["status", "started_at"])

    return Response({"status": "in_progress", "started_at": meeting.started_at.isoformat()})


@api_view(["POST"])
def finish_meeting(request, meeting_id):
    """POST /api/v1/admin/meetings/{id}/finish"""
    _require_admin(request.user)
    meeting = get_object_or_404(Meeting, id=meeting_id)

    if meeting.status != MeetingStatus.IN_PROGRESS:
        return Response(
            {"code": "INVALID_STATUS", "message": "只有进行中的会议可以结束"},
            status=status.HTTP_409_CONFLICT,
        )

    meeting.status = MeetingStatus.FINISHED
    meeting.ended_at = timezone.now()
    meeting.notes = request.data.get("notes", meeting.notes)
    meeting.save(update_fields=["status", "ended_at", "notes"])

    return Response({"status": "finished", "ended_at": meeting.ended_at.isoformat()})


# ═══════════════════════════════════════════════════════════════
# 讨论状态
# ═══════════════════════════════════════════════════════════════

@api_view(["PATCH"])
def mark_discussed(request, meeting_id, snapshot_id):
    """
    PATCH /api/v1/admin/meetings/{id}/reports/{snapshot_id}
    标记某成员周报已讨论。
    """
    _require_admin(request.user)
    meeting = get_object_or_404(Meeting, id=meeting_id)

    serializer = MarkDiscussedSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    snapshot = get_object_or_404(MeetingReportSnapshot, id=snapshot_id, meeting=meeting)

    state, _ = MeetingReportState.objects.get_or_create(
        meeting=meeting,
        report=snapshot.report_revision.report,
        defaults={"discussed": False},
    )

    state.discussed = serializer.validated_data["discussed"]
    if state.discussed:
        state.discussed_at = timezone.now()
        state.discussed_by = request.user
    state.note = serializer.validated_data.get("note", state.note)
    state.save()

    return Response({
        "snapshot_id": str(snapshot_id),
        "discussed": state.discussed,
        "discussed_at": state.discussed_at.isoformat() if state.discussed_at else None,
    })


# ═══════════════════════════════════════════════════════════════
# 行动项
# ═══════════════════════════════════════════════════════════════

@api_view(["POST"])
def create_action_item(request, meeting_id):
    """POST /api/v1/admin/meetings/{id}/action-items"""
    _require_admin(request.user)
    meeting = get_object_or_404(Meeting, id=meeting_id)

    serializer = CreateActionItemSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    item = ActionItem.objects.create(
        meeting=meeting,
        source_report_id=data.get("source_report_id"),
        title=data["title"],
        owner_id=data.get("owner_id"),
        due_date=data.get("due_date"),
        created_by=request.user,
    )

    return Response(
        ActionItemSerializer(item).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(["PATCH"])
def update_action_item(request, action_item_id):
    """PATCH /api/v1/admin/action-items/{id}"""
    _require_admin(request.user)
    item = get_object_or_404(ActionItem, id=action_item_id)

    serializer = UpdateActionItemSerializer(data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    for field in ["title", "owner_id", "due_date", "status", "resolution_note"]:
        if field in data:
            setattr(item, field, data[field])

    if data.get("status") in {"done", "cancelled"} and not item.resolved_at:
        item.resolved_at = timezone.now()

    item.save()
    return Response(ActionItemSerializer(item).data)


# ═══════════════════════════════════════════════════════════════
# 刷新快照（管理员手动刷新到最新修订——需审计）
# ═══════════════════════════════════════════════════════════════

@api_view(["POST"])
def refresh_snapshot(request, meeting_id, snapshot_id):
    """
    POST /api/v1/admin/meetings/{id}/reports/{snapshot_id}/refresh
    将快照刷新为最新 Revision（成员在组会期间补交后的操作）。
    """
    _require_admin(request.user)
    meeting = get_object_or_404(Meeting, id=meeting_id)
    snapshot = get_object_or_404(MeetingReportSnapshot, id=snapshot_id, meeting=meeting)

    report = snapshot.report_revision.report
    if report.current_revision and report.current_revision != snapshot.report_revision:
        snapshot.report_revision = report.current_revision
        snapshot.save(update_fields=["report_revision"])

        # 审计日志
        from audit.models import AuditEvent
        AuditEvent.objects.create(
            event_type="REPORT_SNAPSHOT_REFRESHED",
            actor=request.user,
            target_type="MeetingReportSnapshot",
            target_id=str(snapshot_id),
            summary=f"组会 {meeting.id} 中 {report.owner.display_name} 的快照已刷新到 Revision {report.current_revision.revision_no}",
        )

        return Response({
            "detail": "快照已刷新到最新修订",
            "new_revision_id": str(report.current_revision.id),
        })

    return Response({"detail": "已经是最新修订"})
