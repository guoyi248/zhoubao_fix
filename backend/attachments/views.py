"""
附件视图：
- 上传附件到周报
- 查询附件状态（单个 + 批量轮询）
- 预览文件流式返回
- 原件下载（鉴权后）
- 成员预览确认
- 重试失败任务
"""

from contextlib import closing

from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.http import FileResponse, HttpResponse
from django.utils.cache import get_conditional_response, patch_vary_headers
from django.utils.http import quote_etag

from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from common.storage import storage
from audit.events import record_report
from audit.models import AuditEvent
from common.exceptions import AttachmentLockedError, MalwareDetectedError, PermissionDeniedError, ScanUnavailableError
from reporting.models import WeeklyReport, ReportStatus

from .models import (
    Attachment,
    AttachmentStatus,
    AttachmentPreview,
)
from .serializers import (
    AttachmentDetailSerializer,
    AttachmentStatusSerializer,
    ConfirmPreviewSerializer,
    BatchStatusSerializer,
)
from .mime_utils import is_pdf
from .services import prepare_preview, store_report_file, retire_attachments
from .scanning import scan_stream


# ═══════════════════════════════════════════════════════════════
# 上传
# ═══════════════════════════════════════════════════════════════

@api_view(["GET", "POST"])
@parser_classes([MultiPartParser])
@transaction.atomic
def upload_attachment(request, report_id):
    """成员查看草稿附件或上传新文件。"""
    reports = WeeklyReport.objects
    if request.method == "POST":
        reports = reports.select_for_update()
    report = get_object_or_404(reports, id=report_id, owner=request.user)
    if request.method == "GET":
        attachments = report.attachments.filter(is_current=True).prefetch_related(Prefetch(
            "previews", queryset=AttachmentPreview.objects.filter(status="ready").order_by("-created_at", "-id"),
            to_attr="ready_previews",
        )).order_by("-created_at", "id")
        return Response(AttachmentStatusSerializer(attachments, many=True).data)
    if report.status not in {ReportStatus.DRAFT, ReportStatus.RESUBMITTED}:
        return Response({"code": "REPORT_NOT_EDITABLE", "message": "当前状态不允许上传"}, status=409)
    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return Response({"code": "NO_FILE", "message": "请选择文件"}, status=400)
    attachment = store_report_file(report, uploaded_file, request.user)
    record_report(request, AuditEvent.EventType.ATTACHMENT_UPLOADED, report, f"上传 {uploaded_file.name}")
    return Response(AttachmentDetailSerializer(attachment).data, status=status.HTTP_201_CREATED)


# ═══════════════════════════════════════════════════════════════
# 状态查询（轮询）
# ═══════════════════════════════════════════════════════════════

@api_view(["GET"])
def get_attachment_status(request, attachment_id):
    """
    GET /api/v1/attachments/{id}/status
    轮询单个附件处理状态。
    """
    attachment = _get_authorized_attachment(request, attachment_id)
    return Response({
        "id": str(attachment.id),
        "status": attachment.status,
        "message": _status_message(attachment.status),
        "updated_at": attachment.updated_at.isoformat(),
    })


@api_view(["POST"])
def batch_status(request):
    """
    POST /api/v1/attachments/batch-status
    批量查询附件状态（避免 N+1 轮询）。
    """
    serializer = BatchStatusSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    ids = serializer.validated_data["attachment_ids"]

    attachments = _readable_attachments(request.user).filter(id__in=ids).values("id", "status", "updated_at")
    status_map = {
        str(a["id"]): {
            "status": a["status"],
            "updated_at": a["updated_at"].isoformat(),
        }
        for a in attachments
    }
    return Response({"statuses": status_map})


def _status_message(status: str) -> str:
    messages = {
        AttachmentStatus.UPLOADING: "上传中",
        AttachmentStatus.QUARANTINED: "已接收，等待扫描",
        AttachmentStatus.SCANNING: "安全扫描中",
        AttachmentStatus.STORED: "已安全存储",
        AttachmentStatus.COMPATIBILITY_CHECK: "兼容性检测中",
        AttachmentStatus.CONVERTING: "正在转换为 PDF",
        AttachmentStatus.PREVIEW_READY: "预览已生成，请确认",
        AttachmentStatus.PREVIEW_WARNING: "预览已生成（存在兼容性警告），请确认",
        AttachmentStatus.USER_CONFIRMED: "已确认",
        AttachmentStatus.EXTRACTING: "文本抽取中",
        AttachmentStatus.ANALYZING: "AI 分析中",
        AttachmentStatus.READY: "就绪",
        AttachmentStatus.READY_WITH_WARNING: "就绪（有警告）",
        AttachmentStatus.FAILED: "处理失败",
        AttachmentStatus.REJECTED: "已拒绝",
        AttachmentStatus.PASSWORD_PROTECTED: "文件有密码保护",
        AttachmentStatus.UNSUPPORTED: "不支持的文件格式",
    }
    return messages.get(status, status)


# ═══════════════════════════════════════════════════════════════
# 预览 + 下载
# ═══════════════════════════════════════════════════════════════

@api_view(["GET"])
def get_attachment_detail(request, attachment_id):
    """GET /api/v1/attachments/{id}"""
    attachment = _get_authorized_attachment(request, attachment_id)
    return Response(AttachmentDetailSerializer(attachment).data)


@api_view(["GET"])
def download_original(request, attachment_id):
    """
    GET /api/v1/attachments/{id}/download
    下载原件（鉴权后流式返回）。
    """
    attachment = _get_authorized_attachment(request, attachment_id)

    if attachment.status in {AttachmentStatus.UPLOADING, AttachmentStatus.QUARANTINED,
                              AttachmentStatus.SCANNING, AttachmentStatus.REJECTED}:
        return Response({"code": "FILE_UNAVAILABLE", "message": "此附件尚未通过安全扫描"}, status=409)
    return FileResponse(
        storage.generate_download_stream(settings.S3_BUCKET_ORIGINALS, attachment.original_object_key),
        as_attachment=True, filename=attachment.original_filename, content_type="application/octet-stream",
    )


@api_view(["GET"])
def get_preview_content(request, attachment_id):
    """
    GET /api/v1/attachments/{id}/preview-content
    流式返回 PDF 预览内容。
    """
    attachment = _get_authorized_attachment(request, attachment_id)
    source = attachment.pdf_source
    if not source:
        return Response(
            {"code": "NO_PREVIEW", "message": "预览尚未生成"},
            status=status.HTTP_404_NOT_FOUND,
        )

    response = FileResponse(storage.generate_download_stream(*source), content_type="application/pdf")
    response["Content-Disposition"] = "inline"
    response["Cache-Control"] = "private, no-cache"
    patch_vary_headers(response, ["Cookie"])
    return response


@api_view(["GET"])
def presentation_page(request, attachment_id, page):
    """按需渲染组会投影页，在内嵌浏览器和手机上保留 PDF 原排版。"""
    import fitz
    from hashlib import sha256

    attachment = _get_authorized_attachment(request, attachment_id)
    source = attachment.pdf_source
    if not source:
        return Response({"message": "这份附件没有可展示的预览"}, status=404)
    pdf_digest = attachment.source_sha256 if is_pdf(attachment.detected_mime) else attachment.ready_preview.output_sha256
    fingerprint = f"present-v2:{source}:{pdf_digest}:{page}"
    etag = quote_etag(sha256(fingerprint.encode()).hexdigest())
    response = get_conditional_response(request, etag=etag)
    if response is None:
        try:
            with fitz.open(stream=storage.download_to_bytes(*source), filetype="pdf") as document:
                if document.needs_pass:
                    return Response({"message": "PDF 需要密码，请打开原文件查看"}, status=422)
                if not 1 <= page <= document.page_count:
                    return Response({"message": "页码不存在"}, status=404)
                sheet = document[page - 1]
                scale = min(1800 / max(sheet.rect.width, 1), 2400 / max(sheet.rect.height, 1))
                pixmap = sheet.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
                response = HttpResponse(pixmap.tobytes("png"), content_type="image/png")
                response["X-Page-Count"] = document.page_count
                response["X-Page-Width"] = pixmap.width
                response["X-Page-Height"] = pixmap.height
        except FileNotFoundError:
            return Response({"message": "未找到周报附件"}, status=404)
        except (fitz.FileDataError, RuntimeError, ValueError):
            return Response({"message": "该 PDF 无法渲染，请打开原文件查看"}, status=422)
    response["ETag"] = etag
    response["Cache-Control"] = "private, no-cache"
    patch_vary_headers(response, ["Cookie"])
    return response


@api_view(["GET"])
def get_compatibility(request, attachment_id):
    """GET /api/v1/attachments/{id}/compatibility"""
    from .models import AttachmentCompatibilityReport
    attachment = _get_authorized_attachment(request, attachment_id)
    report = AttachmentCompatibilityReport.objects.filter(attachment=attachment).first()
    if not report:
        return Response({"detail": "暂无兼容性报告"}, status=status.HTTP_404_NOT_FOUND)
    return Response({
        "detected_mime": report.detected_mime,
        "format_family": report.format_family,
        "legacy_format": report.legacy_format,
        "macro_enabled": report.macro_enabled,
        "declared_fonts": report.declared_fonts,
        "font_matches": report.font_matches,
        "missing_fonts": report.missing_or_substituted_fonts,
        "preview_level": report.preview_level,
        "warnings": report.warnings,
    })


# ═══════════════════════════════════════════════════════════════
# 成员确认预览 → user_confirmed
# ═══════════════════════════════════════════════════════════════

@api_view(["POST"])
@transaction.atomic
def confirm_preview(request, attachment_id):
    """
    POST /api/v1/attachments/{id}/confirm
    成员确认 PDF 预览无误（或拒绝、要求重新转换）。
    """
    attachment = _get_authorized_attachment(request, attachment_id, owner_only=True)
    serializer = ConfirmPreviewSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    confirmed = serializer.validated_data["confirmed"]
    attachment = _lock_for_processing(attachment, allow_published=confirmed)
    if confirmed and attachment.status == AttachmentStatus.USER_CONFIRMED:
        return Response({"status": "user_confirmed", "detail": "预览已确认"})

    if attachment.status not in {
        AttachmentStatus.PREVIEW_READY,
        AttachmentStatus.PREVIEW_WARNING,
    }:
        return Response(
            {"code": "NOT_READY_FOR_CONFIRM", "message": "预览尚未就绪"},
            status=status.HTTP_409_CONFLICT,
        )

    if not attachment.pdf_source:
        return Response({"code": "NO_PREVIEW", "message": "此附件没有可确认的 PDF 预览"}, status=409)
    if confirmed:
        attachment.status = AttachmentStatus.USER_CONFIRMED
        attachment.save(update_fields=["status", "updated_at"])

        # 触发文本抽取和 AI 分析
        from .tasks import extract_text
        transaction.on_commit(lambda: extract_text.delay(str(attachment.id)), robust=True)

        return Response({"status": "user_confirmed", "detail": "预览已确认"})
    else:
        # 成员拒绝：重置状态，要求重新上传
        attachment.status = AttachmentStatus.FAILED
        attachment.save(update_fields=["status", "updated_at"])
        return Response({"status": "failed", "detail": "请重新上传文件或上传自行导出的 PDF"})


@api_view(["POST"])
@transaction.atomic
def link_author_pdf(request, attachment_id):
    """
    POST /api/v1/attachments/{id}/link-author-pdf
    将另一个上传的 PDF 关联为"作者 PDF"。
    """
    attachment = _get_authorized_attachment(request, attachment_id, owner_only=True)

    author_pdf_id = request.data.get("author_pdf_id")
    if not author_pdf_id:
        return Response({"code": "MISSING_ID", "message": "请提供作者 PDF 附件 ID"}, status=status.HTTP_400_BAD_REQUEST)

    attachment = _lock_for_processing(attachment)
    author_pdf = get_object_or_404(Attachment, id=author_pdf_id, report_id=attachment.report_id,
                                  private_plan_id=attachment.private_plan_id, uploaded_by=request.user, is_current=True)
    if not is_pdf(author_pdf.detected_mime):
        return Response({"code": "NOT_PDF", "message": "作者上传的必须是 PDF"}, status=status.HTTP_400_BAD_REQUEST)

    attachment.author_pdf_for = author_pdf
    attachment.save(update_fields=["author_pdf_for", "updated_at"])
    return Response({"detail": "已关联作者 PDF"})


@api_view(["POST"])
@transaction.atomic
def retry_processing(request, attachment_id):
    """POST /api/v1/attachments/{id}/retry —— 重试失败的处理任务。"""
    attachment = _get_authorized_attachment(request, attachment_id, owner_only=True)
    attachment = _lock_for_processing(attachment)

    if attachment.status not in {AttachmentStatus.FAILED, AttachmentStatus.READY_WITH_WARNING,
                                  AttachmentStatus.STORED, AttachmentStatus.QUARANTINED}:
        return Response(
            {"code": "NOT_RETRYABLE", "message": "当前状态不支持重试"},
            status=status.HTTP_409_CONFLICT,
        )

    attachment.retry_count += 1
    attachment.save(update_fields=["retry_count"])
    with closing(storage.generate_download_stream(settings.S3_BUCKET_ORIGINALS, attachment.original_object_key)) as stream:
        if settings.CLAMAV_SCAN_UPLOADS or attachment.status == AttachmentStatus.QUARANTINED:
            try:
                scan_stream(stream)
            except (MalwareDetectedError, ScanUnavailableError) as exc:
                attachment.status = (AttachmentStatus.REJECTED if isinstance(exc, MalwareDetectedError)
                                     else AttachmentStatus.QUARANTINED)
                attachment.save(update_fields=["status", "updated_at"])
                return Response({"code": exc.default_code, "message": str(exc.detail)}, status=exc.status_code)
    prepare_preview(attachment)
    if not attachment.pdf_source:
        return Response({"code": "NO_PREVIEW", "message": "无法生成预览，请上传自行导出的 PDF"}, status=422)
    return Response({"detail": "预览已生成", "status": attachment.status})


@api_view(["DELETE"])
@transaction.atomic
def delete_attachment(request, attachment_id):
    """DELETE /api/v1/me/attachments/{id} —— 删除草稿中的附件。"""
    attachment = _get_authorized_attachment(request, attachment_id, owner_only=True)

    if attachment.status in {AttachmentStatus.UPLOADING, AttachmentStatus.QUARANTINED,
                              AttachmentStatus.SCANNING}:
        return Response(
            {"code": "PROCESSING", "message": "附件正在处理中，无法删除"},
            status=status.HTTP_409_CONFLICT,
        )

    if attachment.report_id:
        report = get_object_or_404(WeeklyReport.objects.select_for_update(), pk=attachment.report_id)
        if report.status not in {ReportStatus.DRAFT, ReportStatus.RESUBMITTED}:
            return Response({"code": "REPORT_LOCKED", "message": "周报已提交，无法删除附件"}, status=409)
        current = get_object_or_404(report.attachments, pk=attachment.pk, is_current=True)
        retire_attachments(report.attachments.filter(pk=current.pk, is_current=True))
        record_report(request, AuditEvent.EventType.ATTACHMENT_REMOVED, report, f"移除 {current.original_filename}")
    else:
        attachment.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@parser_classes([MultiPartParser])
@transaction.atomic
def replace_attachment(request, attachment_id):
    """校验、存储并转换替换文件。已提交的附件继续用于历史修订。"""
    old = _get_authorized_attachment(request, attachment_id, owner_only=True)
    report = get_object_or_404(WeeklyReport.objects.select_for_update(), id=old.report_id, owner=request.user)
    if report.status not in {ReportStatus.DRAFT, ReportStatus.RESUBMITTED}:
        return Response({"code": "REPORT_LOCKED", "message": "周报已提交，无法替换附件"}, status=409)
    old = get_object_or_404(report.attachments, pk=attachment_id, is_current=True)
    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return Response({"code": "NO_FILE", "message": "请选择文件"}, status=400)
    had_preview = old.pdf_source is not None
    retire_attachments(report.attachments.filter(pk=old.pk))
    attachment = store_report_file(report, uploaded_file, request.user, require_preview=had_preview)
    record_report(request, AuditEvent.EventType.ATTACHMENT_REPLACED, report,
                  f"使用 {uploaded_file.name} 替换 {old.original_filename}")
    return Response(AttachmentDetailSerializer(attachment).data, status=201)


# ═══════════════════════════════════════════════════════════════
# 权限辅助
# ═══════════════════════════════════════════════════════════════

def _readable_attachments(user):
    allowed = Q(uploaded_by=user) | Q(private_plan__owner=user)
    if user.is_admin:
        published = Q(submitted_revisions__report__in=WeeklyReport.objects.visible_to(user))
        primary = Q(confirmed_for_revisions__report__in=WeeklyReport.objects.visible_to(user))
        allowed |= Q(private_plan__isnull=True) & (published | primary)
    return Attachment.objects.filter(allowed).distinct()


def _lock_for_processing(attachment, allow_published=False):
    if attachment.report_id:
        report = get_object_or_404(WeeklyReport.objects.select_for_update(), pk=attachment.report_id)
        if report.status not in {ReportStatus.DRAFT, ReportStatus.RESUBMITTED}:
            raise AttachmentLockedError()
    attachment = get_object_or_404(Attachment.objects.select_for_update(), pk=attachment.pk)
    if not attachment.is_current:
        raise AttachmentLockedError()
    if not allow_published and (attachment.submitted_revisions.exists() or attachment.confirmed_for_revisions.exists()):
        raise AttachmentLockedError()
    return attachment


def _get_authorized_attachment(request, attachment_id, owner_only=False):
    attachment = get_object_or_404(Attachment, id=attachment_id)
    if attachment.uploaded_by_id == request.user.pk or (
        attachment.private_plan_id and attachment.private_plan.owner_id == request.user.pk
    ):
        return attachment
    if not owner_only and _readable_attachments(request.user).filter(pk=attachment_id).exists():
        return attachment
    raise PermissionDeniedError()
