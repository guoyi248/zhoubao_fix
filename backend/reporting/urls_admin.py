"""管理员周报 URL 路由。"""

from django.urls import path
from . import views

app_name = "reporting_admin"

urlpatterns = [
    path("", views.admin_list_reports, name="list-reports"),
    path("<uuid:report_id>", views.admin_get_report, name="get-report"),
    path("<uuid:report_id>/revisions/<uuid:revision_id>", views.admin_get_revision, name="get-revision"),
    path("<uuid:report_id>/notes", views.admin_add_note, name="add-note"),
]
