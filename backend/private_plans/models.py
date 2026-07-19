"""
个人计划模型——独立私密数据域。
仅计划所有者可通过业务接口访问，管理员和 LLM 均不触碰。
"""

from django.conf import settings
from django.db import models
from common.models import BaseModel


class PrivatePlan(BaseModel):
    """个人计划。"""

    class PlanStatus(models.TextChoices):
        ACTIVE = "active", "进行中"
        COMPLETED = "completed", "已完成"
        CANCELLED = "cancelled", "已取消"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="private_plans",
    )
    title = models.CharField("标题", max_length=500)
    description = models.TextField("描述", blank=True, default="")
    status = models.CharField(
        "状态",
        max_length=20,
        choices=PlanStatus.choices,
        default=PlanStatus.ACTIVE,
    )
    due_date = models.DateField("截止日期", null=True, blank=True)
    notes = models.TextField("备注", blank=True, default="")

    class Meta:
        db_table = "private_plans"
        verbose_name = "个人计划"
        verbose_name_plural = "个人计划"
        indexes = [
            models.Index(fields=["owner", "status", "due_date"]),
        ]

    def __str__(self):
        return self.title


class PrivatePlanAttachment(BaseModel):
    """个人计划附件——独立权限类，与周报附件隔离。"""

    plan = models.ForeignKey(
        PrivatePlan,
        on_delete=models.CASCADE,
        related_name="plan_attachments",
    )
    attachment = models.ForeignKey(
        "attachments.Attachment",
        on_delete=models.CASCADE,
        related_name="plan_links",
    )

    class Meta:
        db_table = "private_plan_attachments"
        verbose_name = "个人计划附件"
        verbose_name_plural = "个人计划附件"
