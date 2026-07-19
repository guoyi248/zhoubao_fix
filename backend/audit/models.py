"""
审计模型——只追加，不修改不删除。
记录所有高风险操作：登录、权限变更、文件下载、组会、导出等。
"""

from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    """审计事件。"""

    class EventType(models.TextChoices):
        LOGIN_SUCCESS = "LOGIN_SUCCESS", "登录成功"
        LOGIN_FAILURE = "LOGIN_FAILURE", "登录失败"
        USER_CREATED = "USER_CREATED", "创建用户"
        USER_DISABLED = "USER_DISABLED", "禁用用户"
        USER_ENABLED = "USER_ENABLED", "恢复用户"
        ROLE_CHANGED = "ROLE_CHANGED", "角色变更"
        PASSWORD_RESET = "PASSWORD_RESET", "密码重置"
        REPORT_SUBMITTED = "REPORT_SUBMITTED", "周报提交"
        REPORT_RESUBMITTED = "REPORT_RESUBMITTED", "周报补交"
        REPORT_VIEWED_BY_ADMIN = "REPORT_VIEWED_BY_ADMIN", "管理员查看周报"
        ATTACHMENT_UPLOADED = "ATTACHMENT_UPLOADED", "附件上传"
        ATTACHMENT_DOWNLOADED = "ATTACHMENT_DOWNLOADED", "附件下载"
        ATTACHMENT_REJECTED = "ATTACHMENT_REJECTED", "附件拒绝"
        PREVIEW_RETRIED = "PREVIEW_RETRIED", "预览重试"
        AI_REGENERATED = "AI_REGENERATED", "AI 重新生成"
        AI_ITEM_EDITED = "AI_ITEM_EDITED", "AI 条目人工修改"
        MEETING_STARTED = "MEETING_STARTED", "组会开始"
        REPORT_MARKED_DISCUSSED = "REPORT_MARKED_DISCUSSED", "标记已讨论"
        EXPORT_CREATED = "EXPORT_CREATED", "导出创建"
        EXPORT_DOWNLOADED = "EXPORT_DOWNLOADED", "导出下载"
        SYSTEM_SETTING_CHANGED = "SYSTEM_SETTING_CHANGED", "系统配置变更"
        EMERGENCY_ACCOUNT_ENABLED = "EMERGENCY_ACCOUNT_ENABLED", "应急账号启用"

    # 事件元数据
    event_id = models.UUIDField("事件 ID", auto_created=True, primary_key=True, editable=False)
    event_type = models.CharField("事件类型", max_length=50, choices=EventType.choices)
    created_at = models.DateTimeField("时间", auto_now_add=True, db_index=True)

    # 操作人
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    actor_ip = models.GenericIPAddressField("操作人 IP", null=True, blank=True)
    actor_user_agent = models.TextField("User-Agent 摘要", blank=True, default="")

    # 操作对象
    target_type = models.CharField("目标类型", max_length=100, blank=True, default="")
    target_id = models.CharField("目标 ID", max_length=255, blank=True, default="")

    # 结果
    result = models.CharField("结果", max_length=20, default="success")  # success / failure / denied
    summary = models.TextField("变更摘要", blank=True, default="")
    risk_level = models.CharField("风险级别", max_length=20, default="low")  # low / medium / high

    # 关联
    request_id = models.CharField("请求 ID", max_length=64, blank=True, default="")

    class Meta:
        db_table = "audit_events"
        verbose_name = "审计事件"
        verbose_name_plural = "审计事件"
        indexes = [
            models.Index(fields=["created_at", "event_type"]),
            models.Index(fields=["actor", "created_at"]),
            models.Index(fields=["target_type", "target_id"]),
        ]
        ordering = ["-created_at"]
