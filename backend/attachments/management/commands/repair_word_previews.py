"""从 Word 原件重建旧版文字预览及包含 Office Math 的旧版式预览。"""

from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.db.models.functions import Lower

from attachments.converter import convert_and_store, is_word_document
from attachments.models import Attachment, AttachmentExtractedText, AttachmentPreview, PDF_AVAILABLE_STATES
from attachments.services import record_ready_preview
from attachments.word_preview_versions import EQUATION_VERSION, has_omml


def needs_repair(attachment, previous):
    from common.storage import storage

    renderer = previous.converter_name.lower()
    if renderer == "fpdf2":
        return True
    if renderer not in {"libreoffice", "gotenberg"} or previous.converter_version.endswith(EQUATION_VERSION):
        return False
    if Path(attachment.original_filename).suffix.lower() not in {".docx", ".docm"}:
        return False
    return has_omml(storage.download_to_bytes(settings.S3_BUCKET_ORIGINALS, attachment.original_object_key))


def repair(attachment, previous):
    if previous.source_sha256 and previous.source_sha256 != attachment.source_sha256:
        raise CommandError("原件校验值与历史预览记录不符，请检查原件。")
    converted = convert_and_store(attachment, require_office_layout=True)
    if not converted or converted["converter_name"].lower() == "fpdf2":
        raise CommandError("未能生成保留版式的 PDF，请检查 Word 转换服务后重试。")
    if previous.converter_name.lower() != "fpdf2" and not converted["converter_version"].endswith(EQUATION_VERSION):
        raise CommandError("转换结果未确认完成公式处理。")
    # 在独立的对象键生成完整 PDF 后，只在一个短事务内发布预览。
    with transaction.atomic():
        current = Attachment.objects.select_for_update().filter(
            id=attachment.pk, source_sha256=attachment.source_sha256,
            original_object_key=attachment.original_object_key, status__in=PDF_AVAILABLE_STATES,
        ).first()
        if not current or not current.ready_preview or current.ready_preview.pk != previous.pk:
            return False
        replaced = AttachmentPreview.objects.filter(pk=previous.pk, status="ready").update(status="superseded")
        if not replaced:
            return False
        record_ready_preview(current, converted)
        AttachmentExtractedText.objects.filter(attachment=current).delete()
        return True


class Command(BaseCommand):
    help = "从 Word 原件重建旧版纯文本预览以及含公式的旧版式预览。"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="仅列出需修复的附件")
        parser.add_argument("--attachment", type=UUID, help="仅检查指定附件")

    def handle(self, *args, **options):
        latest_ready = AttachmentPreview.objects.filter(
            attachment_id=OuterRef("pk"), status="ready",
        ).order_by("-created_at", "-id")
        candidates = Attachment.objects.alias(
            renderer=Lower(Subquery(latest_ready.values("converter_name")[:1])),
        ).filter(status__in=PDF_AVAILABLE_STATES, renderer__in=("fpdf2", "libreoffice", "gotenberg"))
        if options["attachment"]:
            candidates = candidates.filter(pk=options["attachment"])

        count = upgraded = failed = 0
        for attachment in candidates.order_by("pk"):
            if not is_word_document(attachment.detected_mime, attachment.original_filename):
                continue
            previous = attachment.ready_preview
            try:
                if not previous or not needs_repair(attachment, previous):
                    continue
                count += 1
                if options["dry_run"]:
                    self.stdout.write(f"{attachment.pk}  {attachment.uploaded_filename or attachment.original_filename}")
                    continue
                if repair(attachment, previous):
                    upgraded += 1
                    self.stdout.write(f"已修复 {attachment.pk}")
            except Exception as exc:
                failed += 1
                self.stderr.write(f"{attachment.pk} 修复失败，已保留原预览。{exc}")
        self.stdout.write(f"匹配 {count} 份旧 Word 预览，已修复 {upgraded} 份。")
        if failed:
            raise CommandError(f"{failed} 份未能修复，解决上述问题后可重新运行。")
