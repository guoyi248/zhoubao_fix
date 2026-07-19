"""系统配置视图——管理员可读写。"""

from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import SystemSetting
from common.exceptions import PermissionDeniedError


@api_view(["GET"])
def list_config(request):
    """GET /api/v1/admin/config"""
    if not request.user.is_admin:
        raise PermissionDeniedError()

    settings = SystemSetting.objects.all()
    return Response({
        s.key: s.value for s in settings
    })
