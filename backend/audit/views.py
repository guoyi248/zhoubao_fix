"""管理员按成员、时间和操作类型查询审计记录。"""

from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import AuditEvent
from common.exceptions import PermissionDeniedError


@api_view(["GET"])
def audit_list(request):
    if not request.user.is_admin:
        raise PermissionDeniedError()
    try:
        days = int(request.GET.get("days", 7))
        if not 1 <= days <= 365:
            raise ValueError
    except ValueError:
        return Response({"message": "时间范围应为 1 至 365 天"}, status=400)
    qs = AuditEvent.objects.select_related("actor").filter(created_at__gte=timezone.now() - timedelta(days=days))
    if actor_id := request.GET.get("actor_id"):
        if not actor_id.isascii() or not actor_id.isdigit() or len(actor_id) > 18:
            return Response({"message": "用户标识无效"}, status=400)
        qs = qs.filter(actor_id=int(actor_id))
    if event := request.GET.get("event_type"):
        qs = qs.filter(event_type=event)
    if actor := request.GET.get("actor", "").strip():
        qs = qs.filter(Q(actor__username__icontains=actor) | Q(actor__display_name__icontains=actor)
                       | Q(event_type="LOGIN_FAILURE", actor__isnull=True, summary__icontains=actor))
    groups = {
        "login": ["LOGIN_SUCCESS", "LOGIN_FAILURE"],
        "report": ["DRAFT_UPDATED", "REPORT_SUBMITTED", "REPORT_RESUBMITTED", "REPORT_REOPENED",
                   "ATTACHMENT_UPLOADED", "ATTACHMENT_REPLACED", "ATTACHMENT_REMOVED"],
        "account": ["USER_CREATED", "USER_UPDATED", "USER_DELETED", "USER_DISABLED", "USER_ENABLED",
                    "ROLE_CHANGED", "PASSWORD_RESET"],
    }
    if group := request.GET.get("group"):
        if group in groups:
            qs = qs.filter(event_type__in=groups[group])
    page = Paginator(qs.order_by("-created_at", "-event_id"), 30).get_page(request.GET.get("page"))
    events = [{
        "event_id": str(e.pk), "event_type": e.event_type, "event_label": e.get_event_type_display(),
        "created_at": e.created_at, "actor_name": e.actor.display_name if e.actor else "",
        "actor_username": e.actor.username if e.actor else "", "actor_ip": e.actor_ip,
        "actor_location": e.actor_location or "未记录地点", "target_type": e.target_type,
        "target_id": e.target_id, "result": e.result, "summary": e.summary, "risk_level": e.risk_level,
    } for e in page.object_list]
    return Response({"events": events, "count": page.paginator.count, "page": page.number, "page_size": 30})
