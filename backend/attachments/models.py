"""
附件模型：
- Attachment：上传文件
- AttachmentProcessingEvent：处理状态事件
- AttachmentCompatibilityReport：兼容性报告
- AttachmentPreview：预览记录
- AttachmentExtractedText：抽取文本
"""

import uuid

from django.conf import settings
from django.db import models
from common.models import BaseModel


class AttachmentStatus(models.TextChoices):
    UPLOADING = "uploading", "上传中"
    QUARANTINED = "quarantined", "已隔离"
    SCANNING = "scanning", "扫描中"
    REJECTED = "rejected", "已拒绝"
    STORED = "stored", "已存储"
    COMPATIBILITY_CHECK = "compatibility_check", "兼容性检测中"
    CONVERTING = "converting", "转换中"
    PREVIEW_READY = "preview_ready", "预览已生成"
    PREVIEW_WARNING = "preview_warning", "预览有警告"
    USER_CONFIRMED = "user_confirmed", "成员已确认"
    EXTRACTING = "extracting", "文本抽取中"
    ANALYZING = "analyzing", "AI 分析中"
    READY = "ready", "就绪"
    READY_WITH_WARNING = "ready_with_warning", "就绪（有警告）"
    FAILED = "failed", "失败"
    PASSWORD_PROTECTED = "password_protected", "有密码保护"
    UNSUPPORTED = "unsupported", "不支持"


class Attachment(BaseModel):
    """上传的附件。"""

    # 所属关系
    report = models.ForeignKey(
        "reporting.WeeklyReport",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
    )
    private_plan = models.ForeignKey(
        "private_plans.PrivatePlan",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attachments",
    )

    # 文件元数据
    original_filename = models.CharField("原始文件名", max_length=500)
    safe_filename = models.CharField("安全文件名", max_length=500)
    detected_mime = models.CharField("检测的 MIME", max_length=255)
    source_sha256 = models.CharField("原件 SHA-256", max_length=64)
    file_size_bytes = models.BigIntegerField("文件大小", default=0)

    # 对象存储
    original_object_key = models.CharField("原件对象键", max_length=500, blank=True, default="")

    # 状态机
    status = models.CharField(
        "状态",
        max_length=30,
        choices=AttachmentStatus.choices,
        default=AttachmentStatus.UPLOADING,
    )
    retry_count = models.IntegerField("重试次数", default=0)

    # 作者 PDF 关联（成员自行导出的 PDF 优先于系统转换）
    author_pdf_for = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="author_pdfs",
    )

    class Meta:
        db_table = "attachments"
        verbose_name = "附件"
        verbose_name_plural = "附件"
        indexes = [
            models.Index(fields=["report", "status"]),
            models.Index(fields=["source_sha256"]),
        ]

    def __str__(self):
        return self.original_filename


class AttachmentProcessingEvent(BaseModel):
    """附件处理事件日志。"""

    attachment = models.ForeignKey(
        Attachment,
        on_delete=models.CASCADE,
        related_name="processing_events",
    )
    from_status = models.CharField("旧状态", max_length=30, blank=True, default="")
    to_status = models.CharField("新状态", max_length=30)
    task_id = models.CharField("Celery 任务 ID", max_length=100, blank=True, default="")
    error_code = models.CharField("错误代码", max_length=100, blank=True, default="")
    user_message = models.CharField("用户可读消息", max_length=500, blank=True, default="")
    tech_diagnostic = models.JSONField("技术诊断", default=dict)
    processor_version = models.CharField("处理组件版本", max_length=100, blank=True, default="")

    class Meta:
        db_table = "attachment_processing_events"
        verbose_name = "处理事件"
        verbose_name_plural = "处理事件"


class AttachmentCompatibilityReport(BaseModel):
    """兼容性检测报告。"""

    attachment = models.OneToOneField(
        Attachment,
        on_delete=models.CASCADE,
        related_name="compatibility_report",
    )
    detected_mime = models.CharField("实际 MIME", max_length=255)
    extension_matches_mime = models.BooleanField("扩展名与 MIME 一致", default=True)
    format_family = models.CharField("格式家族", max_length=50, blank=True, default="")
    legacy_format = models.BooleanField("旧版格式", default=False)
    macro_enabled = models.BooleanField("含宏", default=False)
    encrypted = models.BooleanField("已加密", default=False)
    external_links = models.BooleanField("含外部链接", default=False)
    declared_fonts = models.JSONField("声明字体", default=list)
    font_matches = models.JSONField("字体匹配结果", default=dict)
    missing_or_substituted_fonts = models.JSONField("缺失/替换字体", default=list)
    embedded_objects = models.JSONField("嵌入对象", default=list)
    preview_level = models.CharField("预览等级", max_length=20, default="normal")  # normal / warning / unavailable
    warnings = models.JSONField("警告列表", default=list)

    class Meta:
        db_table = "attachment_compatibility_reports"
        verbose_name = "兼容性报告"
        verbose_name_plural = "兼容性报告"


class AttachmentPreview(BaseModel):
    """预览记录。"""

    attachment = models.ForeignKey(
        Attachment,
        on_delete=models.CASCADE,
        related_name="previews",
    )
    preview_object_key = models.CharField("预览对象键", max_length=500)
    source_sha256 = models.CharField("源文件 SHA-256", max_length=64)
    converter_name = models.CharField("转换器名称", max_length=100)
    converter_version = models.CharField("转换器版本", max_length=100)
    converter_image_digest = models.CharField("转换器镜像 digest", max_length=100)
    font_bundle_version = models.CharField("字体包版本", max_length=100, blank=True, default="")
    output_sha256 = models.CharField("输出 SHA-256", max_length=64)
    page_count = models.IntegerField("页数", default=0)
    status = models.CharField("预览状态", max_length=30)
    warnings_json = models.JSONField("警告", default=dict)

    class Meta:
        db_table = "attachment_previews"
        verbose_name = "预览记录"
        verbose_name_plural = "预览记录"


class AttachmentExtractedText(BaseModel):
    """抽取的文本内容。"""

    attachment = models.OneToOneField(
        Attachment,
        on_delete=models.CASCADE,
        related_name="extracted_text",
    )
    content = models.TextField("抽取文本")
    completeness = models.CharField(
        "完整程度",
        max_length=20,
        default="full",  # full / partial / empty
    )
    extractor_name = models.CharField("抽取器名称", max_length=100)
    warnings = models.JSONField("警告", default=list)

    class Meta:
        db_table = "attachment_extracted_texts"
        verbose_name = "抽取文本"
        verbose_name_plural = "抽取文本"
