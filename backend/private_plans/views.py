"""个人计划视图——仅计划所有者可访问。"""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import PrivatePlan
from common.exceptions import PermissionDeniedError


class PlanSerializer:
    """内联序列化器（避免文件碎片化）。"""
    @staticmethod
    def serialize(plan):
        return {
            "id": str(plan.id),
            "title": plan.title,
            "description": plan.description,
            "status": plan.status,
            "due_date": plan.due_date.isoformat() if plan.due_date else None,
            "notes": plan.notes,
            "created_at": plan.created_at.isoformat(),
            "updated_at": plan.updated_at.isoformat(),
        }


@api_view(["GET", "POST"])
def plan_list(request):
    """GET /api/v1/me/private-plans  or  POST 创建"""
    if request.method == "GET":
        plans = PrivatePlan.objects.filter(owner=request.user).order_by("-created_at")[:100]
        return Response([PlanSerializer.serialize(p) for p in plans])

    plan = PrivatePlan.objects.create(
        owner=request.user,
        title=request.data.get("title", ""),
        description=request.data.get("description", ""),
        due_date=request.data.get("due_date") or None,
    )
    return Response(PlanSerializer.serialize(plan), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
def plan_detail(request, plan_id):
    """GET/PATCH/DELETE /api/v1/me/private-plans/{id}"""
    plan = get_object_or_404(PrivatePlan, id=plan_id)

    if plan.owner != request.user:
        raise PermissionDeniedError()

    if request.method == "GET":
        return Response(PlanSerializer.serialize(plan))

    if request.method == "DELETE":
        plan.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # PATCH
    for field in ["title", "description", "status", "due_date", "notes"]:
        if field in request.data:
            setattr(plan, field, request.data[field])
    plan.save()
    return Response(PlanSerializer.serialize(plan))
