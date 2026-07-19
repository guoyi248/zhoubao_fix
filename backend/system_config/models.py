"""
系统配置模型——功能开关、周报模板、周期配置。
"""

from django.db import models
from common.models import BaseModel


class SystemSetting(BaseModel):
    """系统级设置。"""

    key = models.CharField("配置键", max_length=200, unique=True)
    value = models.JSONField("配置值")
    description = models.CharField("说明", max_length=500, blank=True, default="")
    is_public = models.BooleanField("是否公开", default=False)

    class Meta:
        db_table = "system_settings"
        verbose_name = "系统设置"
        verbose_name_plural = "系统设置"

    def __str__(self):
        return self.key
