"""
AI analysis views: get, regenerate, confirm/reject items, team summary.
"""

from django.db.models import F, OuterRef, Subquery
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
from .tasks import queue_revision
from system_config.integrations import get_config, model_issues, setup_info


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
def analysis_service(request):
    config = get_config("model")
    issues = model_issues(config)
    data = {"enabled": config["enabled"], "configured": not issues}
    if request.user.is_admin:
        data.update(provider=config["provider"], model=config["model"], setup=setup_info(issues))
    return Response(data)


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
        revision=revision
    ).order_by("-created_at").first()

    config = get_config("model")
    available = config["enabled"] and not model_issues(config)
    idle = "available" if available else ("unconfigured" if config["enabled"] else "disabled")
    if not analysis_run:
        return Response(
            {"detail": "暂无分析结果", "status": idle, "enabled": bool(available)},
            status=status.HTTP_200_OK,
        )

    data = dict(AnalysisRunSerializer(analysis_run).data, enabled=bool(available))
    if analysis_run.status == "failed":
        data["error_message"] = analysis_run.error_message if analysis_run.prompt_version == "v2" else "解析失败，可重新生成。"
    if not available and data["status"] in {"queued", "running"}:
        data["status"] = idle
    return Response(data)


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

    config = get_config("model")
    if not config["enabled"]:
        return Response({"message": "工作区尚未启用大模型解析"}, status=409)
    if model_issues(config):
        return Response({"message": "模型服务配置不完整，请查看 AI 周报解析页面"}, status=409)
    run = queue_revision(revision, force=True)

    return Response(
        {"detail": "已加入解析队列", "status": run.status},
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


def _current_items(period_id):
    latest = AnalysisRun.objects.filter(revision_id=OuterRef("analysis_run__revision_id"), status="completed").order_by("-created_at")
    return AnalysisItem.objects.filter(
        analysis_run__revision__report__reporting_period_id=period_id,
        analysis_run__revision_id=F("analysis_run__revision__report__current_revision_id"),
        analysis_run_id=Subquery(latest.values("pk")[:1]),
    ).exclude(human_status="rejected")


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

    items = _current_items(period_id).select_related(
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
    items = _current_items(period.pk)

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
