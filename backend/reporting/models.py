"""
周报模型：
- ReportingPeriod：ISO 周周期
- WeeklyReport：逻辑周报（含草稿字段）
- WeeklyReportRevision：不可变提交快照
- AdminReportNote：管理员备注
"""

import hashlib
import json

from django.conf import settings
from django.db import models, transaction
from common.models import BaseModel
from common.exceptions import VersionConflictError


class PeriodStatus(models.TextChoices):
    OPEN = "open", "开放提交"
    CLOSED = "closed", "已截止"
    ARCHIVED = "archived", "已归档"


class ReportStatus(models.TextChoices):
    DRAFT = "draft", "草稿"
    SUBMITTED = "submitted", "已提交"
    RESUBMITTED = "resubmitted", "补交"
    ARCHIVED = "archived", "已归档"


class ReportingPeriod(BaseModel):
    """ISO 周周期。"""

    iso_year = models.IntegerField("ISO 年份")
    iso_week = models.IntegerField("ISO 周数")
    start_date = models.DateField("开始日期")
    end_date = models.DateField("结束日期")
    deadline = models.DateTimeField("提交截止时间")
    status = models.CharField(
        "状态",
        max_length=20,
        choices=PeriodStatus.choices,
        default=PeriodStatus.OPEN,
    )

    class Meta:
        db_table = "reporting_periods"
        verbose_name = "周报周期"
        verbose_name_plural = "周报周期"
        unique_together = [("iso_year", "iso_week")]
        ordering = ["-iso_year", "-iso_week"]

    def __str__(self):
        return f"{self.iso_year}-W{self.iso_week:02d}"


class WeeklyReportQuerySet(models.QuerySet):
    def visible_to(self, user):
        """权限范围：管理员看已提交，成员只看自己的。"""
        if not user.is_authenticated or not user.is_active:
            return self.none()
        if user.is_admin:
            return self.filter(
                status__in={
                    ReportStatus.SUBMITTED,
                    ReportStatus.RESUBMITTED,
                    ReportStatus.ARCHIVED,
                }
            )
        return self.filter(owner=user)


class WeeklyReport(BaseModel):
    """逻辑周报——一个成员在一个周期内只有一份。"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reports",
    )
    reporting_period = models.ForeignKey(
        ReportingPeriod,
        on_delete=models.CASCADE,
        related_name="reports",
    )

    # 草稿字段（仅 owner 可见）
    draft_content_json = models.JSONField("草稿内容", default=dict)

    # 状态
    status = models.CharField(
        "状态",
        max_length=20,
        choices=ReportStatus.choices,
        default=ReportStatus.DRAFT,
    )
    current_revision = models.OneToOneField(
        "WeeklyReportRevision",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    # 乐观锁
    optimistic_version = models.IntegerField("乐观锁版本", default=0)

    objects = WeeklyReportQuerySet.as_manager()

    class Meta:
        db_table = "weekly_reports"
        verbose_name = "周报"
        verbose_name_plural = "周报"
        unique_together = [("owner", "reporting_period")]
        indexes = [
            models.Index(fields=["status", "reporting_period"]),
            models.Index(fields=["owner", "reporting_period"]),
        ]

    def __str__(self):
        return f"{self.owner.display_name} — {self.reporting_period}"

    def save_draft(self, content: dict, expected_version: int) -> "WeeklyReport":
        """乐观锁保存草稿。"""
        if self.optimistic_version != expected_version:
            raise VersionConflictError()
        self.draft_content_json = content
        self.optimistic_version += 1
        self.save(update_fields=["draft_content_json", "optimistic_version", "updated_at"])
        return self

    @transaction.atomic
    def submit(self, submitted_by, confirmed_pdf_attachment=None) -> "WeeklyReportRevision":
        """提交周报，创建不可变修订版。"""
        if self.status not in {ReportStatus.DRAFT, ReportStatus.RESUBMITTED}:
            raise ValueError(f"无法提交状态为 {self.status} 的周报")

        content_json = json.dumps(self.draft_content_json, ensure_ascii=False, sort_keys=True)
        content_sha256 = hashlib.sha256(content_json.encode()).hexdigest()

        revision = WeeklyReportRevision.objects.create(
            report=self,
            revision_no=self.revisions.count() + 1,
            structured_content_json=self.draft_content_json,
            submitted_by=submitted_by,
            content_sha256=content_sha256,
            confirmed_pdf_attachment=confirmed_pdf_attachment,
        )

        new_status = ReportStatus.RESUBMITTED if self.status == ReportStatus.SUBMITTED else ReportStatus.SUBMITTED

        self.status = new_status
        self.current_revision = revision
        self.optimistic_version += 1
        self.save(update_fields=["status", "current_revision", "optimistic_version", "updated_at"])

        return revision


class WeeklyReportRevision(BaseModel):
    """不可变提交快照。"""

    report = models.ForeignKey(
        WeeklyReport,
        on_delete=models.CASCADE,
        related_name="revisions",
    )
    revision_no = models.IntegerField("修订编号")
    structured_content_json = models.JSONField("结构化内容快照")
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="submitted_revisions",
    )
    submitted_at = models.DateTimeField("提交时间", auto_now_add=True)
    content_sha256 = models.CharField("内容哈希", max_length=64)
    confirmed_pdf_attachment = models.ForeignKey(
        "attachments.Attachment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_for_revisions",
        verbose_name="成员确认的 PDF",
    )
    reason = models.CharField("提交/修改原因", max_length=500, blank=True, default="")

    class Meta:
        db_table = "weekly_report_revisions"
        verbose_name = "周报修订版"
        verbose_name_plural = "周报修订版"
        unique_together = [("report", "revision_no")]
        ordering = ["-revision_no"]

    def __str__(self):
        return f"{self.report} rev.{self.revision_no}"


class AdminReportNote(BaseModel):
    """管理员备注（不覆盖成员原文）。"""

    report = models.ForeignKey(
        WeeklyReport,
        on_delete=models.CASCADE,
        related_name="admin_notes",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="report_notes_authored",
    )
    content = models.TextField("备注内容")

    class Meta:
        db_table = "admin_report_notes"
        verbose_name = "管理员备注"
        verbose_name_plural = "管理员备注"
