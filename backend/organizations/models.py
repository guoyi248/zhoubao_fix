"""
组织模型：Department（部门）。
"""

from django.db import models
from common.models import BaseModel


class Department(BaseModel):
    """部门。"""

    name = models.CharField("部门名称", max_length=200, unique=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    code = models.CharField("部门编码", max_length=50, blank=True, default="")
    is_active = models.BooleanField("启用", default=True)
    sort_order = models.IntegerField("排序", default=0)

    class Meta:
        db_table = "departments"
        verbose_name = "部门"
        verbose_name_plural = "部门"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name
