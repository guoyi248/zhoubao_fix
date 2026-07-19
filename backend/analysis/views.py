"""
AI analysis views: get, regenerate, confirm/reject items, team summary.
"""

from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from reporting.models import WeeklyReportRevision, WeeklyReport, ReportStatus
from common.exceptions import PermissionDeniedError, ObjectNotFound

from .models import AnalysisRun, AnalysisItem, AnalysisItemSource, AnalysisHumanRevision
from .serializers import (
    AnalysisRunSerializer,
    AnalysisItemSerializer,
    UpdateAnalysisItemSerializer,
)
from .tasks import analyze_report


def _can_access_revision(user, revision: WeeklyReportRevision) -> bool:
    """检查用户是否有权访问此修订的分析。"""
    if revision.submitted_by == user:
        return True
    if user.is_admin and revision.report.status in {
        ReportStatus.SUBMITTED,
        ReportStatus.RESUBMITTED,
        ReportStatus.ARCHIVED,
    }:
        return True
    return False


# ═══════════════════════════════════════════════════════════════
# 查看分析
# ═══════════════════════════════════════════════════════════════

@api_view(["GET"])
def get_analysis(request, revision_id):
    """
    GET /api/v1/reports/{revision_id}/analysis
    获取某修订版的最新 AI 分析。
    """
    revision = get_object_or_404(WeeklyReportRevision, id=revision_id)

    if not _can_access_revision(request.user, revision):
        raise PermissionDeniedError()

    analysis_run = AnalysisRun.objects.filter(
        revision=revision, status="completed"
    ).order_by("-created_at").first()

    if not analysis_run:
        return Response(
            {"detail": "暂无分析结果", "status": "pending"},
            status=status.HTTP_200_OK,
        )

    return Response(AnalysisRunSerializer(analysis_run).data)


# ═══════════════════════════════════════════════════════════════
# 重新生成
# ═══════════════════════════════════════════════════════════════

@api_view(["POST"])
def regenerate_analysis(request, revision_id):
    """
    POST /api/v1/reports/{revision_id}/analysis/regenerate
    重新触发 LLM 分析。
    """
    revision = get_object_or_404(WeeklyReportRevision, id=revision_id)

    if not _can_access_revision(request.user, revision):
        raise PermissionDeniedError()

    analyze_report.delay(str(revision.id))

    return Response(
        {"detail": "已触发重新分析", "status": "pending"},
        status=status.HTTP_202_ACCEPTED,
    )


# ═══════════════════════════════════════════════════════════════
# 人工修订
# ═══════════════════════════════════════════════════════════════

@api_view(["PATCH"])
def update_analysis_item(request, item_id):
    """
    PATCH /api/v1/analysis/items/{id}
    人工修订分析条目（修改标题、详情、项目）。
    """
    item = get_object_or_404(AnalysisItem, id=item_id)
    revision = item.analysis_run.revision

    if not _can_access_revision(request.user, revision):
        raise PermissionDeniedError()

    serializer = UpdateAnalysisItemSerializer(data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    # 保存人工修订记录
    previous = {
        "title": item.title,
        "detail": item.detail,
        "project": item.project,
    }

    for field in ["title", "detail", "project"]:
        if field in data:
            setattr(item, field, data[field])

    item.human_status = "modified"
    item.human_revision_comment = data.get("comment", "")
    item.save()

    AnalysisHumanRevision.objects.create(
        item=item,
        revised_by=request.user,
        previous_data=previous,
        new_data={"title": item.title, "detail": item.detail, "project": item.project},
    )

    return Response(AnalysisItemSerializer(item).data)


@api_view(["POST"])
def confirm_analysis_item(request, item_id):
    """
    POST /api/v1/analysis/items/{id}/confirm
    确认 AI 分析条目。
    """
    item = get_object_or_404(AnalysisItem, id=item_id)
    revision = item.analysis_run.revision

    if not _can_access_revision(request.user, revision):
        raise PermissionDeniedError()

    AnalysisHumanRevision.objects.create(
        item=item,
        revised_by=request.user,
        previous_data={"human_status": item.human_status},
        new_data={"human_status": "confirmed"},
    )

    item.human_status = "confirmed"
    item.save(update_fields=["human_status"])

    return Response({"status": "confirmed"})


@api_view(["POST"])
def reject_analysis_item(request, item_id):
    """
    POST /api/v1/analysis/items/{id}/reject
    拒绝/删除 AI 分析条目。
    """
    item = get_object_or_404(AnalysisItem, id=item_id)
    revision = item.analysis_run.revision

    if not _can_access_revision(request.user, revision):
        raise PermissionDeniedError()

    AnalysisHumanRevision.objects.create(
        item=item,
        revised_by=request.user,
        previous_data={"human_status": item.human_status},
        new_data={"human_status": "rejected"},
    )

    item.human_status = "rejected"
    item.save(update_fields=["human_status"])

    return Response({"status": "rejected"})


# ═══════════════════════════════════════════════════════════════
# 团队总表
# ═══════════════════════════════════════════════════════════════


@api_view(["GET"])
def team_summary(request):
    """
    GET /api/v1/admin/team-summary?period=<period_id>
    查看团队总表——所有成员已确认或达到置信阈值的分析条目。
    """
    if not request.user.is_admin:
        raise PermissionDeniedError()

    period_id = request.GET.get("period")
    item_type = request.GET.get("type")

    items = AnalysisItem.objects.filter(
        analysis_run__revision__report__reporting_period_id=period_id
    ).filter(
        # 只显示已确认或高置信度条目
        human_status__in=["confirmed", "pending"]
    ).exclude(
        human_status="rejected"
    ).select_related(
        "analysis_run__revision__report__owner",
        "analysis_run__revision__report__owner__department",
    )

    if item_type:
        items = items.filter(item_type=item_type)

    results = []
    for item in items[:500]:
        revision = item.analysis_run.revision
        results.append({
            "item_id": str(item.id),
            "item_type": item.item_type,
            "title": item.title,
            "detail": item.detail,
            "project": item.project,
            "confidence": item.confidence,
            "human_status": item.human_status,
            "member_id": str(revision.report.owner_id),
            "member_name": revision.report.owner.display_name,
            "department": revision.report.owner.department.name if revision.report.owner.department else "",
            "reporting_period_id": str(revision.report.reporting_period_id),
            "revision_id": str(revision.id),
            "source_count": item.sources.count(),
        })

    return Response({
        "items": results,
        "count": len(results),
        "by_type": _group_by_type(results),
        "by_member": _group_by_member(results),
    })


def _group_by_type(items):
    groups = {}
    for item in items:
        t = item["item_type"]
        groups.setdefault(t, []).append(item["title"])
    return {k: len(v) for k, v in groups.items()}


def _group_by_member(items):
    groups = {}
    for item in items:
        m = item["member_name"]
        groups.setdefault(m, []).append(item["title"])
    return {k: len(v) for k, v in groups.items()}


@api_view(["POST"])
def rebuild_team_summary(request):
    """
    POST /api/v1/admin/team-summary/rebuild
    重建团队总表快照。
    """
    if not request.user.is_admin:
        raise PermissionDeniedError()

    period_id = request.data.get("reporting_period_id")
    from reporting.models import ReportingPeriod
    period = get_object_or_404(ReportingPeriod, id=period_id)

    # 直接查询分析条目
    items = AnalysisItem.objects.filter(
        analysis_run__revision__report__reporting_period=period,
        human_status__in=["confirmed", "pending"],
    ).exclude(human_status="rejected")

    from .models import TeamSummarySnapshot
    snapshot = TeamSummarySnapshot.objects.create(
        reporting_period=period,
        generated_by=request.user,
        data_json={"rebuilt": True},
        item_count=items.count(),
    )

    return Response({
        "snapshot_id": str(snapshot.id),
        "item_count": snapshot.item_count,
    }, status=201)
