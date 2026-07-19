"""AI 分析 URL 路由（全局——analysis items 操作）。"""

from django.urls import path
from . import views

app_name = "analysis"

urlpatterns = [
    # 人工修订（全局端点）
    path("analysis/items/<uuid:item_id>", views.update_analysis_item, name="update-item"),
    path("analysis/items/<uuid:item_id>/confirm", views.confirm_analysis_item, name="confirm-item"),
    path("analysis/items/<uuid:item_id>/reject", views.reject_analysis_item, name="reject-item"),
]
