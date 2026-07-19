"""成员周报 URL 路由。"""

from django.urls import path
from . import views
from attachments import views as attachment_views

app_name = "reporting_me"

urlpatterns = [
    path("current", views.current_report, name="current-report"),
    path("<uuid:report_id>", views.get_my_report, name="get-report"),
    path("<uuid:report_id>/save", views.save_draft, name="save-draft"),
    path("<uuid:report_id>/submit", views.submit_report, name="submit"),
    path("<uuid:report_id>/resubmit", views.resubmit_report, name="resubmit"),
    path("<uuid:report_id>/revisions", views.list_my_revisions, name="list-revisions"),
    path("<uuid:report_id>/revisions/<uuid:revision_id>", views.get_revision, name="get-revision"),
    path("<uuid:report_id>/attachments", attachment_views.upload_attachment, name="upload-attachment"),
]
