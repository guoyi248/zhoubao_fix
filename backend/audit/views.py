"""审计日志视图——仅管理员可查看。"""

from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import AuditEvent
from common.exceptions import PermissionDeniedError


@api_view(["GET"])
def audit_list(request):
    """GET /api/v1/admin/audit?event_type=&actor=&days=7"""
    if not request.user.is_admin:
        raise PermissionDeniedError()

    qs = AuditEvent.objects.select_related("actor").order_by("-created_at")

    event_type = request.GET.get("event_type")
    actor = request.GET.get("actor")
    days = int(request.GET.get("days", "7"))

    if event_type:
        qs = qs.filter(event_type=event_type)
    if actor:
        qs = qs.filter(actor__username=actor)

    from django.utils import timezone
    cutoff = timezone.now() - timezone.timedelta(days=days)
    qs = qs.filter(created_at__gte=cutoff)

    results = []
    for e in qs[:200]:
        results.append({
            "event_id": str(e.event_id),
            "event_type": e.event_type,
            "created_at": e.created_at.isoformat(),
            "actor_name": e.actor.display_name if e.actor else "",
            "actor_ip": e.actor_ip,
            "target_type": e.target_type,
            "target_id": e.target_id,
            "result": e.result,
            "summary": e.summary,
            "risk_level": e.risk_level,
        })

    return Response({"events": results, "count": len(results)})
