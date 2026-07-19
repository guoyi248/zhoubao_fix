"""Root URL configuration."""

from django.conf import settings
from django.urls import include, path
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse

# ── 健康检查 ──────────────────────────────────────────────


def health_live(request):
    """存活检查：进程能否响应。"""
    return JsonResponse({"status": "ok"})


def health_ready(request):
    """就绪检查：关键依赖是否可用。"""
    from django.db import connections
    from django.core.cache import cache

    checks = {"database": False, "cache": False}

    try:
        connections["default"].cursor()
        checks["database"] = True
    except Exception:
        pass

    try:
        cache.set("__healthcheck__", 1, 1)
        checks["cache"] = True
    except Exception:
        pass

    healthy = all(checks.values())
    status_code = 200 if healthy else 503
    return JsonResponse({"status": "ready" if healthy else "degraded", "checks": checks}, status=status_code)


@ensure_csrf_cookie
def csrf_token_view(request):
    """返回 CSRF Token。"""
    return JsonResponse({"detail": "CSRF cookie set"})


# ── URL 路由 ──────────────────────────────────────────────
from meetings import views as meetings_views

urlpatterns = [
    # 健康检查
    path("health/live", health_live, name="health-live"),
    path("health/ready", health_ready, name="health-ready"),

    # CSRF
    path("api/v1/auth/csrf", csrf_token_view, name="auth-csrf"),

    # API v1
    path("api/v1/auth/", include("accounts.urls_auth")),
    path("api/v1/me/", include("accounts.urls_me")),
    path("api/v1/admin/", include("accounts.urls_admin")),
    path("api/v1/me/reports/", include("reporting.urls_me")),
    path("api/v1/admin/reports/", include("reporting.urls_admin")),
    path("api/v1/attachments/", include("attachments.urls")),
    path("api/v1/reports/", include("analysis.urls_reports")),
    path("api/v1/", include("analysis.urls")),
    path("api/v1/admin/team-summary/", include("analysis.urls_admin")),
    path("api/v1/admin/meetings/", include("meetings.urls")),
    path("api/v1/admin/action-items/<uuid:action_item_id>", meetings_views.update_action_item, name="update-action-item"),
    path("api/v1/me/private-plans/", include("private_plans.urls")),
    path("api/v1/admin/audit/", include("audit.urls")),
    path("api/v1/admin/config/", include("system_config.urls")),
]

if settings.DEBUG:
    urlpatterns += [
        path("api/v1/auth/", include("rest_framework.urls", namespace="rest_framework")),
    ]
