"""团队总表 URL 路由。"""
from django.urls import path
from . import views

app_name = "analysis_admin"

urlpatterns = [
    path("", views.team_summary, name="team-summary"),
    path("rebuild", views.rebuild_team_summary, name="rebuild-summary"),
]
