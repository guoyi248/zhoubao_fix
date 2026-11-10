"""系统配置 URL 路由。"""
from django.urls import path
from . import views

app_name = "system_config"

urlpatterns = [
    path("attachment-limits", views.attachment_policy, name="attachment-limits"),
    path("integrations", views.integrations, name="integrations"),
    path("", views.list_config, name="list"),
]
