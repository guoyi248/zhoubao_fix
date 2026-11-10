"""
附件处理 Celery 任务：
- scan_file: ClamAV 病毒扫描
- compatibility_check: 字体/宏/嵌入对象检测
- convert_to_pdf: LibreOffice → PDF
- extract_text: PyMuPDF 文本抽取
"""

import logging
from contextlib import closing

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.exceptions import MalwareDetectedError, ScanUnavailableError
from common.storage import storage
from .scanning import scan_stream
from .models import (
    Attachment,
    AttachmentStatus,
    AttachmentProcessingEvent,
    AttachmentCompatibilityReport,
    AttachmentPreview,
    AttachmentExtractedText,
)
from .mime_utils import (
    is_office_file,
    is_pdf,
    is_image,
    is_text,
    is_macro_enabled,
)

logger = logging.getLogger(__name__)


def _record_event(attachment: Attachment, to_status: str, **kwargs):
    """记录状态变更事件。"""
    from_status = attachment.status
    AttachmentProcessingEvent.objects.create(
        attachment=attachment,
        from_status=from_status,
        to_status=to_status,
        **kwargs,
    )
    attachment.status = to_status
    attachment.save(update_fields=["status", "updated_at"])


# ═══════════════════════════════════════════════════════════════
# 1. ClamAV 病毒扫描
# ═══════════════════════════════════════════════════════════════

@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def scan_file(self, attachment_id: str):
    """ClamAV 扫描附件。"""
    try:
        attachment = Attachment.objects.get(id=attachment_id)
    except Attachment.DoesNotExist:
        logger.error("Attachment %s not found", attachment_id)
        return

    if attachment.status != AttachmentStatus.QUARANTINED:
        return

    _record_event(attachment, AttachmentStatus.SCANNING)

    try:
        with closing(storage.generate_download_stream(
            settings.S3_BUCKET_ORIGINALS, attachment.original_object_key,
        )) as stream:
            scan_stream(stream)

        # 扫描通过 → 进入兼容性检测
        _record_event(attachment, AttachmentStatus.STORED)

        # 触发兼容性检测
        compatibility_check.delay(str(attachment.id))

    except MalwareDetectedError:
        _record_event(attachment, AttachmentStatus.REJECTED, error_code="MALWARE_DETECTED",
                      user_message="文件安全扫描未通过")
    except Exception as exc:
        code = "CLAMAV_UNAVAILABLE" if isinstance(exc, ScanUnavailableError) else "SCAN_FAILED"
        _record_event(attachment, AttachmentStatus.QUARANTINED, error_code=code,
                      user_message="扫描未完成，文件仍在隔离中")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        logger.exception("Scan failed for %s", attachment_id)


# ═══════════════════════════════════════════════════════════════
# 2. 兼容性检测
# ═══════════════════════════════════════════════════════════════

@shared_task(bind=True, max_retries=1)
def compatibility_check(self, attachment_id: str):
    """检测文件格式、字体、宏、嵌入对象。"""
    try:
        attachment = Attachment.objects.get(id=attachment_id)
    except Attachment.DoesNotExist:
        return

    _record_event(attachment, AttachmentStatus.COMPATIBILITY_CHECK)

    try:
        mime = attachment.detected_mime
        report = AttachmentCompatibilityReport.objects.create(
            attachment=attachment,
            detected_mime=mime,
            extension_matches_mime=True,
            format_family=_classify_format(mime),
            legacy_format=mime in {
                "application/msword",
                "application/vnd.ms-excel",
                "application/vnd.ms-powerpoint",
            },
            macro_enabled=is_macro_enabled(mime),
            encrypted=False,  # TODO: 检测加密
            external_links=False,
        )

        # 对 Office 文件进行 OOXML 字体检测
        if is_office_file(mime) and mime.startswith("application/vnd.openxmlformats"):
            _check_ooxml_fonts(attachment, report)

        # PDF 文件直接进入 preview_ready
        if is_pdf(mime):
            AttachmentPreview.objects.create(
                attachment=attachment,
                preview_object_key=attachment.original_object_key,
                source_sha256=attachment.source_sha256,
                converter_name="passthrough",
                converter_version="1.0",
                converter_image_digest="",
                output_sha256=attachment.source_sha256,
                page_count=0,
                status="ready",
            )
            _record_event(attachment, AttachmentStatus.PREVIEW_READY)
            return

        # 图片文件直接进入 preview_ready
        if is_image(mime):
            _record_event(attachment, AttachmentStatus.PREVIEW_READY)
            return

        # Office 文件 → 转换
        if is_office_file(mime):
            _record_event(attachment, AttachmentStatus.CONVERTING)
            convert_to_pdf.delay(str(attachment.id))
            return

        # 文本文件直接创建安全预览
        if is_text(mime):
            _record_event(attachment, AttachmentStatus.PREVIEW_READY)
            return

        # 不支持的格式
        _record_event(attachment, AttachmentStatus.UNSUPPORTED)

    except Exception as exc:
        logger.exception("Compatibility check failed for %s", attachment_id)
        _record_event(attachment, AttachmentStatus.READY_WITH_WARNING)


def _classify_format(mime: str) -> str:
    if "openxmlformats" in mime:
        return "ooxml"
    if mime in {"application/msword", "application/vnd.ms-excel", "application/vnd.ms-powerpoint"}:
        return "ole2"
    if "opendocument" in mime:
        return "odf"
    if mime == "application/pdf":
        return "pdf"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("text/"):
        return "text"
    return "unknown"


def _check_ooxml_fonts(attachment, report):
    """从 OOXML 文件中提取声明字体并检查服务器匹配。"""
    import zipfile
    from io import BytesIO

    declared_fonts = set()
    font_matches = {}
    warnings = []

    try:
        file_bytes = storage.download_to_bytes(
            settings.S3_BUCKET_ORIGINALS, attachment.original_object_key
        )
        with zipfile.ZipFile(BytesIO(file_bytes)) as zf:
            for name in zf.namelist():
                if "fontTable.xml" in name or "styles.xml" in name or "theme" in name:
                    content = zf.read(name)
                    # 简单提取字体名称
                    text = content.decode("utf-8", errors="ignore")
                    import re
                    for m in re.finditer(r'(?:fontName|typeface|majorFont|latin)\s*=\s*"([^"]+)"', text, re.IGNORECASE):
                        declared_fonts.add(m.group(1))
                    for m in re.finditer(r'<a:latin[^>]*typeface="([^"]+)"', text):
                        declared_fonts.add(m.group(1))
    except Exception:
        pass

    report.declared_fonts = sorted(declared_fonts)
    report.font_matches = font_matches
    if warnings:
        report.warnings = warnings
    report.save()


# ═══════════════════════════════════════════════════════════════
# 3. LibreOffice → PDF 转换
# ═══════════════════════════════════════════════════════════════

@shared_task(bind=True, max_retries=1)
def convert_to_pdf(self, attachment_id: str):
    """使用 LibreOffice Headless 将 Office 文件转为 PDF。"""
    try:
        attachment = Attachment.objects.get(id=attachment_id)
    except Attachment.DoesNotExist:
        return

    if attachment.status != AttachmentStatus.CONVERTING:
        return

    from .converter import convert_and_store
    from .services import record_ready_preview

    try:
        converted = convert_and_store(attachment, require_office_layout=True)
        if not converted:
            raise ValueError("No layout preview generated")
        with transaction.atomic():
            attachment = Attachment.objects.select_for_update().get(pk=attachment_id)
            if attachment.status != AttachmentStatus.CONVERTING:
                return
            record_ready_preview(attachment, converted)
            compat = AttachmentCompatibilityReport.objects.filter(attachment=attachment).first()
            has_warnings = compat and (compat.missing_or_substituted_fonts or compat.warnings)
            _record_event(attachment, AttachmentStatus.PREVIEW_WARNING if has_warnings else AttachmentStatus.PREVIEW_READY)
    except Exception:
        logger.exception("Conversion failed for %s", attachment_id)
        with transaction.atomic():
            attachment = Attachment.objects.select_for_update().filter(pk=attachment_id).first()
            if attachment and attachment.status == AttachmentStatus.CONVERTING:
                _record_event(attachment, AttachmentStatus.FAILED, error_code="OFFICE_CONVERSION_FAILED",
                              user_message="文件转换失败，请重试或上传从原文导出的 PDF")


# ═══════════════════════════════════════════════════════════════
# 4. 文本抽取（从 PDF）
# ═══════════════════════════════════════════════════════════════

def read_attachment_text(attachment):
    """缓存同一附件的原始文本或 PDF 文本层，供已提交的各版本复用。"""
    from pathlib import Path
    import fitz

    cached = AttachmentExtractedText.objects.filter(attachment=attachment).first()
    if cached and cached.content.strip() and cached.extractor_name != "error":
        return cached.content
    limit = 5_000_000
    source = None
    if attachment.detected_mime.startswith("text/") or Path(attachment.original_filename).suffix.lower() in {".txt", ".md", ".csv"}:
        raw = storage.download_to_bytes(settings.S3_BUCKET_ORIGINALS, attachment.original_object_key)
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16", errors="replace")
        else:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("gb18030", errors="replace")
        extractor = "plain-text"
    else:
        source = attachment.pdf_source
        if not source:
            return ""
        pages = []
        length = 0
        with fitz.open(stream=storage.download_to_bytes(*source), filetype="pdf") as doc:
            for page in doc:
                part = page.get_text()
                pages.append(part)
                length += len(part) + 2
                if length > limit:
                    break
        text = "\n\n".join(pages)
        extractor = "PyMuPDF"
    text = text.replace("\x00", "").strip()
    completeness = "empty" if not text else "partial" if len(text) > limit else "full"
    text = text[:limit]
    with transaction.atomic():
        if source:
            current = Attachment.objects.select_for_update().filter(pk=attachment.pk).first()
            if not current or current.pdf_source != source:
                # 读取过程中可能已从 Word 原件重建预览，旧文字不可覆盖新缓存。
                return text
        AttachmentExtractedText.objects.update_or_create(
            attachment=attachment, defaults={"content": text, "completeness": completeness,
            "extractor_name": extractor, "warnings": [] if text else ["没有可提取的文字层"]},
        )
    return text


@shared_task(ignore_result=True)
def extract_text(attachment_id: str):
    attachment = Attachment.objects.filter(pk=attachment_id).first()
    if attachment:
        read_attachment_text(attachment)
