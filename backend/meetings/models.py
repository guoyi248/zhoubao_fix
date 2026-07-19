"""
组会模型：
- Meeting：组会记录
- MeetingReportSnapshot：成员周报快照
- MeetingReportState：讨论状态
- ActionItem：行动项
"""

from django.conf import settings
from django.db import models
from common.models import BaseModel


class MeetingStatus(models.TextChoices):
    PLANNED = "planned", "已计划"
    IN_PROGRESS = "in_progress", "进行中"
    FINISHED = "finished", "已结束"


class Meeting(BaseModel):
    """一次组会。"""

    reporting_period = models.ForeignKey(
        "reporting.ReportingPeriod",
        on_delete=models.CASCADE,
        related_name="meetings",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="meetings_created",
    )
    status = models.CharField(
        "状态",
        max_length=20,
        choices=MeetingStatus.choices,
        default=MeetingStatus.PLANNED,
    )
    member_order_json = models.JSONField("成员顺序", default=list)
    started_at = models.DateTimeField("开始时间", null=True, blank=True)
    ended_at = models.DateTimeField("结束时间", null=True, blank=True)
    notes = models.TextField("会议备注", blank=True, default="")

    class Meta:
        db_table = "meetings"
        verbose_name = "组会"
        verbose_name_plural = "组会"


class MeetingReportSnapshot(BaseModel):
    """组会中某个成员的周报快照——固定 Revision，防止会议中内容变化。"""

    meeting = models.ForeignKey(
        Meeting,
        on_delete=models.CASCADE,
        related_name="report_snapshots",
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="meeting_snapshots",
    )
    report_revision = models.ForeignKey(
        "reporting.WeeklyReportRevision",
        on_delete=models.CASCADE,
        related_name="meeting_snapshots",
    )
    display_order = models.IntegerField("展示顺序", default=0)

    class Meta:
        db_table = "meeting_report_snapshots"
        verbose_name = "组会周报快照"
        verbose_name_plural = "组会周报快照"
        unique_together = [("meeting", "member")]


class MeetingReportState(BaseModel):
    """某份周报在组会中的讨论状态。"""

    meeting = models.ForeignKey(
        Meeting,
        on_delete=models.CASCADE,
        related_name="report_states",
    )
    report = models.ForeignKey(
        "reporting.WeeklyReport",
        on_delete=models.CASCADE,
        related_name="meeting_states",
    )
    discussed = models.BooleanField("已讨论", default=False)
    discussed_at = models.DateTimeField("讨论时间", null=True, blank=True)
    discussed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="discussion_marks",
    )
    note = models.TextField("会议备注", blank=True, default="")

    class Meta:
        db_table = "meeting_report_states"
        verbose_name = "讨论状态"
        verbose_name_plural = "讨论状态"


class ActionItem(BaseModel):
    """会议行动项。"""

    class ActionStatus(models.TextChoices):
        OPEN = "open", "待处理"
        IN_PROGRESS = "in_progress", "处理中"
        DONE = "done", "已完成"
        CANCELLED = "cancelled", "已取消"

    meeting = models.ForeignKey(
        Meeting,
        on_delete=models.CASCADE,
        related_name="action_items",
    )
    source_report = models.ForeignKey(
        "reporting.WeeklyReport",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="action_items",
    )
    title = models.CharField("行动项", max_length=500)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_action_items",
    )
    due_date = models.DateField("截止日期", null=True, blank=True)
    status = models.CharField(
        "状态",
        max_length=20,
        choices=ActionStatus.choices,
        default=ActionStatus.OPEN,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="action_items_created",
    )
    resolved_at = models.DateTimeField("解决时间", null=True, blank=True)
    resolution_note = models.TextField("解决备注", blank=True, default="")

    class Meta:
        db_table = "action_items"
        verbose_name = "行动项"
        verbose_name_plural = "行动项"
        indexes = [
            models.Index(fields=["owner", "due_date", "status"]),
        ]
