"""组会 URL 路由。"""

from django.urls import path
from . import views

app_name = "meetings"

urlpatterns = [
    # 创建 + 列表
    path("", views.create_meeting, name="create-meeting"),
    path("list", views.list_meetings, name="list-meetings"),

    # 单个组会
    path("<uuid:meeting_id>", views.get_meeting, name="get-meeting"),
    path("<uuid:meeting_id>/start", views.start_meeting, name="start-meeting"),
    path("<uuid:meeting_id>/finish", views.finish_meeting, name="finish-meeting"),

    # 讨论状态
    path("<uuid:meeting_id>/reports/<uuid:snapshot_id>", views.mark_discussed, name="mark-discussed"),
    path("<uuid:meeting_id>/reports/<uuid:snapshot_id>/refresh", views.refresh_snapshot, name="refresh-snapshot"),

    # 行动项
    path("<uuid:meeting_id>/action-items", views.create_action_item, name="create-action-item"),
]
