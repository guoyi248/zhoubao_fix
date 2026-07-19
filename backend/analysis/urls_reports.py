"""AI 分析 URL 路由（按 revision——查看和重新生成）。"""

from django.urls import path
from . import views

app_name = "analysis_reports"

urlpatterns = [
    # 查看 + 重新生成
    path("<uuid:revision_id>/analysis", views.get_analysis, name="get-analysis"),
    path("<uuid:revision_id>/analysis/regenerate", views.regenerate_analysis, name="regenerate-analysis"),
]
