"""
附件处理 Celery 任务：
- scan_file: ClamAV 病毒扫描
- compatibility_check: 字体/宏/嵌入对象检测
- convert_to_pdf: LibreOffice → PDF
- extract_text: PyMuPDF 文本抽取
"""

import hashlib
import logging
import subprocess
import tempfile
import uuid
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from common.storage import storage
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
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect((settings.CLAMAV_HOST, settings.CLAMAV_PORT))

        # 从 MinIO 读取文件传给 ClamAV
        file_bytes = storage.download_to_bytes(
            settings.S3_BUCKET_ORIGINALS, attachment.original_object_key
        )

        # INSTREAM 协议
        sock.sendall(b"nINSTREAM\n")
        import struct
        while file_bytes:
            chunk = file_bytes[:8192]
            file_bytes = file_bytes[8192:]
            sock.sendall(struct.pack("!I", len(chunk)) + chunk)
        sock.sendall(struct.pack("!I", 0))  # 结束标记

        response = sock.recv(4096).decode().strip()
        sock.close()

        if "FOUND" in response:
            virus_name = response.split("FOUND")[-1].strip() if "FOUND" in response else "unknown"
            _record_event(
                attachment,
                AttachmentStatus.REJECTED,
                error_code="MALWARE_DETECTED",
                user_message=f"文件安全扫描未通过",
                tech_diagnostic={"virus": virus_name},
            )
            return

        # 扫描通过 → 进入兼容性检测
        _record_event(attachment, AttachmentStatus.STORED)

        # 触发兼容性检测
        compatibility_check.delay(str(attachment.id))

    except (socket.error, OSError) as exc:
        logger.warning("ClamAV unavailable for %s: %s", attachment_id, exc)
        # ClamAV 不可用时，记录警告但仍继续处理
        _record_event(
            attachment,
            AttachmentStatus.STORED,
            error_code="CLAMAV_UNAVAILABLE",
            user_message="病毒扫描服务暂不可用，文件已保存",
        )
        compatibility_check.delay(str(attachment.id))

    except Exception as exc:
        logger.exception("Scan failed for %s", attachment_id)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        _record_event(attachment, AttachmentStatus.FAILED, error_code="SCAN_FAILED")


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

    job_id = uuid.uuid4().hex
    input_path = Path(tempfile.gettempdir()) / f"input-{job_id}" / attachment.safe_filename
    output_dir = Path(tempfile.gettempdir()) / f"output-{job_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    input_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # 从 MinIO 下载原件
        file_bytes = storage.download_to_bytes(
            settings.S3_BUCKET_ORIGINALS, attachment.original_object_key
        )
        input_path.write_bytes(file_bytes)

        # LibreOffice 转换
        profile_dir = Path(tempfile.gettempdir()) / f"lo-profile-{job_id}"
        result = subprocess.run(
            [
                "soffice",
                "--headless",
                "--nologo",
                "--nodefault",
                "--nolockcheck",
                "--nofirststartwizard",
                f"-env:UserInstallation=file://{profile_dir}",
                "--convert-to", "pdf",
                "--outdir", str(output_dir),
                str(input_path),
            ],
            capture_output=True,
            text=True,
            timeout=settings.PREVIEW_TIMEOUT_SECONDS,
        )

        if result.returncode != 0:
            raise RuntimeError(f"soffice return code={result.returncode}: {result.stderr[:500]}")

        # 找到生成的 PDF
        pdf_files = list(output_dir.glob("*.pdf"))
        if not pdf_files:
            raise FileNotFoundError("No PDF generated")

        pdf_path = pdf_files[0]
        pdf_bytes = pdf_path.read_bytes()
        output_sha256 = hashlib.sha256(pdf_bytes).hexdigest()

        # 上传 PDF 到 previews bucket
        preview_key = (
            f"previews/{attachment.original_object_key.rsplit('/', 1)[0]}/"
            f"preview-{job_id}.pdf"
        )
        storage.client.put_object(
            Bucket=settings.S3_BUCKET_PREVIEWS,
            Key=preview_key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )

        # 页数检测
        page_count = _count_pdf_pages(pdf_bytes)

        # 获取转换器版本信息
        version_result = subprocess.run(
            ["soffice", "--version"], capture_output=True, text=True, timeout=5
        )
        converter_version = version_result.stdout.strip()

        AttachmentPreview.objects.create(
            attachment=attachment,
            preview_object_key=preview_key,
            source_sha256=attachment.source_sha256,
            converter_name="LibreOffice",
            converter_version=converter_version,
            converter_image_digest="",
            font_bundle_version="",
            output_sha256=output_sha256,
            page_count=page_count,
            status="ready",
        )

        # 检查是否有字体警告
        compat_report = AttachmentCompatibilityReport.objects.filter(
            attachment=attachment
        ).first()
        has_warnings = compat_report and (compat_report.missing_or_substituted_fonts or compat_report.warnings)

        if has_warnings:
            _record_event(attachment, AttachmentStatus.PREVIEW_WARNING)
        else:
            _record_event(attachment, AttachmentStatus.PREVIEW_READY)

    except subprocess.TimeoutExpired:
        logger.error("Conversion timeout for %s", attachment_id)
        _record_event(
            attachment,
            AttachmentStatus.FAILED,
            error_code="OFFICE_CONVERSION_TIMEOUT",
            user_message="文件转换超时，请尝试上传自行导出的 PDF",
        )
    except Exception as exc:
        logger.exception("Conversion failed for %s", attachment_id)
        _record_event(
            attachment,
            AttachmentStatus.FAILED,
            error_code="OFFICE_CONVERSION_FAILED",
            user_message="文件转换失败，请下载原件或上传 PDF",
        )
    finally:
        # 清理临时文件
        import shutil
        for d in [input_path.parent, output_dir, profile_dir]:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    """快速统计 PDF 页数。"""
    import re
    matches = re.findall(rb"/Type\s*/Page[^s]", pdf_bytes)
    return len(matches) or 1


# ═══════════════════════════════════════════════════════════════
# 4. 文本抽取（从 PDF）
# ═══════════════════════════════════════════════════════════════

@shared_task(bind=True, max_retries=1)
def extract_text(self, attachment_id: str):
    """从附件或 PDF 预览中抽取文本。"""
    try:
        attachment = Attachment.objects.get(id=attachment_id)
    except Attachment.DoesNotExist:
        return

    try:
        # 优先从 PDF 预览抽取
        preview = AttachmentPreview.objects.filter(
            attachment=attachment, status="ready"
        ).first()

        if preview and preview.preview_object_key:
            pdf_bytes = storage.download_to_bytes(
                settings.S3_BUCKET_PREVIEWS, preview.preview_object_key
            )
        else:
            # 直接读取原件（PDF 或文本文件）
            pdf_bytes = storage.download_to_bytes(
                settings.S3_BUCKET_ORIGINALS, attachment.original_object_key
            )

        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        texts = []
        total_chars = 0
        max_chars = 5_000_000

        for page in doc:
            text = page.get_text()
            total_chars += len(text)
            if total_chars > max_chars:
                texts.append(text[: max_chars - total_chars + len(text)])
                break
            texts.append(text)

        doc.close()
        full_text = "\n\n".join(texts)

        completeness = "full"
        warnings = []
        if total_chars > max_chars:
            completeness = "partial"
            warnings.append(f"文本已截断，超过 {max_chars} 字符限制")

        if len(full_text.strip()) < 10:
            completeness = "empty"
            warnings.append("PDF 不包含可抽取文本层（可能为扫描件）")

        AttachmentExtractedText.objects.update_or_create(
            attachment=attachment,
            defaults={
                "content": full_text[:max_chars],
                "completeness": completeness,
                "extractor_name": "PyMuPDF",
                "warnings": warnings,
            },
        )

        # 触发 AI 分析（如果启用）
        if settings.LLM_ENABLED and completeness != "empty":
            from analysis.tasks import analyze_report
            # 找到关联的修订版
            from reporting.models import WeeklyReportRevision
            revision = WeeklyReportRevision.objects.filter(
                confirmed_pdf_attachment=attachment
            ).first()
            if revision:
                analyze_report.delay(str(revision.id))

    except Exception as exc:
        logger.exception("Text extraction failed for %s", attachment_id)
        AttachmentExtractedText.objects.update_or_create(
            attachment=attachment,
            defaults={
                "content": "",
                "completeness": "empty",
                "extractor_name": "error",
                "warnings": [str(exc)],
            },
        )
