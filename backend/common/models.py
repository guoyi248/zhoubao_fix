"""
共享抽象基类：UUID 主键、时间戳。
"""

import uuid

from django.db import models


class UUIDPrimaryKeyModel(models.Model):
    """使用 UUID 作为主键的抽象基类。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimestampedModel(models.Model):
    """自动记录创建和更新时间。"""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BaseModel(UUIDPrimaryKeyModel, TimestampedModel):
    """UUID 主键 + 时间戳的通用基类。"""

    class Meta:
        abstract = True
