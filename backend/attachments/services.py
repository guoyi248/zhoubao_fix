"""首次上传、替换及周报更正共用的文件处理。调用方在事务内锁定周报。"""

import uuid
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Sum

from common.exceptions import (
    AttachmentLimitError, FileTooLargeError, FileTypeMismatchError, FileTypeNotAllowed, PreviewFailedError,
)
from common.storage import storage
from system_config.attachment_limits import byte_label, policy
from .converter import convert_and_store, is_word_document
from .mime_utils import check_extension, detect_mime, get_level, is_office_file, is_pdf, is_text
from .models import Attachment, AttachmentPreview, AttachmentStatus
from .scanning import scan_stream


def store_report_file(report, uploaded_file, user, require_preview=False):
    ext = Path(uploaded_file.name).suffix
    if not check_extension(ext):
        raise FileTypeNotAllowed(detail=f"不支持的文件类型：{ext}")
    limits = policy()["limits"]
    if uploaded_file.size > limits["file_bytes"]:
        raise FileTooLargeError(detail="单个附件不能超过 " + byte_label(limits["file_bytes"]))
    usage = report.attachments.filter(is_current=True).aggregate(count=Count("pk"), size=Sum("file_size_bytes"))
    if usage["count"] >= limits["count"]:
        raise AttachmentLimitError(detail=f"每份周报最多 {limits['count']} 个附件")
    if (usage["size"] or 0) + uploaded_file.size > limits["total_bytes"]:
        raise AttachmentLimitError(detail="本份周报附件合计不能超过 " + byte_label(limits["total_bytes"]))

    header = uploaded_file.read(4096)
    uploaded_file.seek(0)
    mime = detect_mime(header, uploaded_file.name)
    if (ext.lower() == ".pdf" or is_pdf(mime)) and not header.lstrip().startswith(b"%PDF-"):
        raise FileTypeMismatchError()
    if settings.CLAMAV_SCAN_UPLOADS:
        scan_stream(uploaded_file)
        uploaded_file.seek(0)

    file_id = uuid.uuid4()
    key = f"originals/{file_id}/source"
    result = storage.upload_stream(settings.S3_BUCKET_ORIGINALS, key, uploaded_file)
    attachment = Attachment.objects.create(
        report=report, uploaded_by=user,
        original_filename=f"hubu_{user.display_name}_{report.reporting_period.end_date:%Y%m%d}{ext}",
        uploaded_filename=uploaded_file.name,
        safe_filename=f"{file_id}{ext}", detected_mime=mime, source_sha256=result["sha256"],
        file_size_bytes=result["size"], original_object_key=key,
        status=AttachmentStatus.STORED,
    )
    prepare_preview(attachment)
    if require_preview and attachment.status != AttachmentStatus.PREVIEW_READY:
        storage.delete_object(settings.S3_BUCKET_ORIGINALS, key)
        raise PreviewFailedError(detail="新文件无法生成 PDF 预览，原文件已保留。请上传可预览的文件。")
    return attachment


def prepare_preview(attachment):
    mime = attachment.detected_mime
    attachment.status = AttachmentStatus.STORED
    if is_pdf(mime):
        attachment.status = AttachmentStatus.PREVIEW_READY
    elif is_office_file(mime) or is_text(mime) or is_word_document(mime, attachment.original_filename):
        converted = convert_and_store(attachment)
        if converted:
            record_ready_preview(attachment, converted)
            attachment.status = AttachmentStatus.PREVIEW_READY
        elif is_word_document(mime, attachment.original_filename):
            attachment.status = AttachmentStatus.FAILED
    elif get_level(mime) == "C":
        attachment.status = AttachmentStatus.READY
    attachment.save(update_fields=["status", "updated_at"])


def record_ready_preview(attachment, converted):
    return AttachmentPreview.objects.create(
        attachment=attachment, preview_object_key=converted["object_key"],
        source_sha256=attachment.source_sha256, converter_name=converted["converter_name"],
        converter_version=converted["converter_version"], output_sha256=converted["sha256"],
        page_count=converted["page_count"], status="ready",
    )


def retire_attachments(attachments):
    """从草稿移除，同时保留已提交版本引用的记录及文件。"""
    attachments.filter(submitted_revisions__isnull=True, confirmed_for_revisions__isnull=True).delete()
    attachments.update(is_current=False)
