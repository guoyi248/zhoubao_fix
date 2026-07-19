"""
附件视图：
- 上传附件到周报
- 查询附件状态（单个 + 批量轮询）
- 预览文件流式返回
- 原件下载（鉴权后）
- 成员预览确认
- 重试失败任务
"""

import os
import uuid
from datetime import datetime

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.http import StreamingHttpResponse, HttpResponse
from django.utils import timezone

from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from common.storage import storage
from common.exceptions import (
    PermissionDeniedError,
    FileTooLargeError,
    FileTypeMismatchError,
    ObjectNotFound,
)
from reporting.models import WeeklyReport, ReportStatus

from .models import (
    Attachment,
    AttachmentStatus,
    AttachmentPreview,
)
from .serializers import (
    AttachmentStatusSerializer,
    AttachmentDetailSerializer,
    ConfirmPreviewSerializer,
    BatchStatusSerializer,
)
from .mime_utils import detect_mime, get_level, check_extension, is_office_file, is_pdf
from .tasks import scan_file


# ═══════════════════════════════════════════════════════════════
# 上传
# ═══════════════════════════════════════════════════════════════

@api_view(["POST"])
@parser_classes([MultiPartParser])
def upload_attachment(request, report_id):
    """
    POST /api/v1/me/reports/{report_id}/attachments
    流式上传附件到周报草稿。
    """
    report = get_object_or_404(WeeklyReport, id=report_id, owner=request.user)
    if report.status not in {ReportStatus.DRAFT, ReportStatus.RESUBMITTED}:
        return Response(
            {"code": "REPORT_NOT_EDITABLE", "message": "当前状态不允许上传"},
            status=status.HTTP_409_CONFLICT,
        )

    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return Response(
            {"code": "NO_FILE", "message": "请选择文件"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ── 统一命名：hubu_W{iso_week}_{username}_{date}.{ext} ──
    _, ext = os.path.splitext(uploaded_file.name)
    from django.utils import timezone as tz
    today = tz.now().date()
    iso_week = report.reporting_period.iso_week
    safe_name = f"hubu_W{iso_week:02d}_{request.user.username}_{today.strftime('%Y%m%d')}{ext}"
    uploaded_file.name = safe_name

    # 检查附件数量
    current_count = Attachment.objects.filter(report=report).count()
    if current_count >= settings.MAX_ATTACHMENTS_PER_REPORT:
        return Response(
            {"code": "ATTACHMENT_LIMIT", "message": f"每份周报最多 {settings.MAX_ATTACHMENTS_PER_REPORT} 个附件"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 检查扩展名
    _, ext = os.path.splitext(uploaded_file.name)
    if not check_extension(ext):
        return Response(
            {"code": "FILE_TYPE_NOT_ALLOWED", "message": f"不支持的文件类型: {ext}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 流式上传到对象存储隔离区
    attachment_uuid = uuid.uuid4()
    now = timezone.now()
    quarantine_key = (
        f"quarantine/{attachment_uuid}/{uploaded_file.name}"
    )

    result = storage.upload_stream(
        bucket=settings.S3_BUCKET_ORIGINALS,
        object_key=f"_quarantine/{attachment_uuid}/source",
        file_obj=uploaded_file,
    )

    # 大小检查
    if result["size"] > settings.MAX_UPLOAD_BYTES:
        storage.delete_object(settings.S3_BUCKET_ORIGINALS, f"_quarantine/{attachment_uuid}/source")
        raise FileTooLargeError()

    # MIME 检测（取文件前 4KB + 文件名回退）
    uploaded_file.seek(0)
    mime_type = detect_mime(uploaded_file.read(4096), uploaded_file.name)
    level = get_level(mime_type)

    # 创建附件记录（状态：quarantined）
    attachment = Attachment.objects.create(
        report=report,
        uploaded_by=request.user,
        original_filename=uploaded_file.name,
        safe_filename=f"{attachment_uuid}{ext}",
        detected_mime=mime_type,
        source_sha256=result["sha256"],
        file_size_bytes=result["size"],
        original_object_key=f"originals/{attachment_uuid}/source",
        status=AttachmentStatus.QUARANTINED,
    )

    # 移动文件到正式位置
    storage.copy_object(
        settings.S3_BUCKET_ORIGINALS,
        f"_quarantine/{attachment_uuid}/source",
        settings.S3_BUCKET_ORIGINALS,
        attachment.original_object_key,
    )
    storage.delete_object(
        settings.S3_BUCKET_ORIGINALS,
        f"_quarantine/{attachment_uuid}/source",
    )

    # 开发模式：直接同步处理
    if level == "C":
        attachment.status = AttachmentStatus.READY
        attachment.save(update_fields=["status"])
    elif level == "A" and attachment.detected_mime == "application/pdf":
        # PDF 直传：直接可用为预览
        attachment.status = AttachmentStatus.PREVIEW_READY
        attachment.save(update_fields=["status"])
    else:
        # Office 文件：标记为已存储，需 Worker 进一步处理
        attachment.status = AttachmentStatus.STORED
        attachment.save(update_fields=["status"])

    return Response(
        AttachmentDetailSerializer(attachment).data,
        status=status.HTTP_201_CREATED,
    )


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

    attachments = Attachment.objects.filter(id__in=ids[:50]).values("id", "status", "updated_at")
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

    file_stream = storage.generate_download_stream(
        settings.S3_BUCKET_ORIGINALS, attachment.original_object_key
    )

    response = StreamingHttpResponse(
        file_stream,
        content_type="application/octet-stream",
    )
    # RFC 5987 UTF-8 filename
    from urllib.parse import quote
    response["Content-Disposition"] = (
        f"attachment; filename*=UTF-8''{quote(attachment.original_filename)}"
    )
    response["Content-Length"] = attachment.file_size_bytes
    return response


@api_view(["GET"])
def get_preview_content(request, attachment_id):
    """
    GET /api/v1/attachments/{id}/preview-content
    流式返回 PDF 预览内容。
    """
    attachment = _get_authorized_attachment(request, attachment_id)
    preview = AttachmentPreview.objects.filter(attachment=attachment).first()
    if not preview:
        return Response(
            {"code": "NO_PREVIEW", "message": "预览尚未生成"},
            status=status.HTTP_404_NOT_FOUND,
        )

    file_stream = storage.generate_download_stream(
        settings.S3_BUCKET_PREVIEWS, preview.preview_object_key
    )

    response = StreamingHttpResponse(file_stream, content_type="application/pdf")
    response["Content-Disposition"] = "inline"
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
def confirm_preview(request, attachment_id):
    """
    POST /api/v1/attachments/{id}/confirm
    成员确认 PDF 预览无误（或拒绝、要求重新转换）。
    """
    attachment = _get_authorized_attachment(request, attachment_id, owner_only=True)

    if attachment.status not in {
        AttachmentStatus.PREVIEW_READY,
        AttachmentStatus.PREVIEW_WARNING,
    }:
        return Response(
            {"code": "NOT_READY_FOR_CONFIRM", "message": "预览尚未就绪"},
            status=status.HTTP_409_CONFLICT,
        )

    serializer = ConfirmPreviewSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    if serializer.validated_data["confirmed"]:
        attachment.status = AttachmentStatus.USER_CONFIRMED
        attachment.save(update_fields=["status", "updated_at"])

        # 触发文本抽取和 AI 分析
        from .tasks import extract_text
        extract_text.delay(str(attachment.id))

        return Response({"status": "user_confirmed", "detail": "预览已确认"})
    else:
        # 成员拒绝：重置状态，要求重新上传
        attachment.status = AttachmentStatus.FAILED
        attachment.save(update_fields=["status", "updated_at"])
        return Response({"status": "failed", "detail": "请重新上传文件或上传自行导出的 PDF"})


@api_view(["POST"])
def link_author_pdf(request, attachment_id):
    """
    POST /api/v1/attachments/{id}/link-author-pdf
    将另一个上传的 PDF 关联为"作者 PDF"。
    """
    attachment = _get_authorized_attachment(request, attachment_id, owner_only=True)

    author_pdf_id = request.data.get("author_pdf_id")
    if not author_pdf_id:
        return Response({"code": "MISSING_ID", "message": "请提供作者 PDF 附件 ID"}, status=status.HTTP_400_BAD_REQUEST)

    author_pdf = get_object_or_404(Attachment, id=author_pdf_id, report=attachment.report)
    if not is_pdf(author_pdf.detected_mime):
        return Response({"code": "NOT_PDF", "message": "作者上传的必须是 PDF"}, status=status.HTTP_400_BAD_REQUEST)

    attachment.author_pdf_for = author_pdf
    attachment.save(update_fields=["author_pdf_for", "updated_at"])
    return Response({"detail": "已关联作者 PDF"})


@api_view(["POST"])
def retry_processing(request, attachment_id):
    """POST /api/v1/attachments/{id}/retry —— 重试失败的处理任务。"""
    attachment = _get_authorized_attachment(request, attachment_id, owner_only=True)

    if attachment.status not in {AttachmentStatus.FAILED, AttachmentStatus.READY_WITH_WARNING}:
        return Response(
            {"code": "NOT_RETRYABLE", "message": "当前状态不支持重试"},
            status=status.HTTP_409_CONFLICT,
        )

    attachment.retry_count += 1
    attachment.status = AttachmentStatus.QUARANTINED
    attachment.save(update_fields=["status", "retry_count", "updated_at"])

    scan_file.delay(str(attachment.id))
    return Response({"detail": "已重新开始处理"})


@api_view(["DELETE"])
def delete_attachment(request, attachment_id):
    """DELETE /api/v1/me/attachments/{id} —— 删除草稿中的附件。"""
    attachment = _get_authorized_attachment(request, attachment_id, owner_only=True)

    if attachment.status in {AttachmentStatus.UPLOADING, AttachmentStatus.QUARANTINED,
                              AttachmentStatus.SCANNING}:
        return Response(
            {"code": "PROCESSING", "message": "附件正在处理中，无法删除"},
            status=status.HTTP_409_CONFLICT,
        )

    # 检查周报状态
    if attachment.report and attachment.report.status not in {ReportStatus.DRAFT, ReportStatus.RESUBMITTED}:
        return Response(
            {"code": "REPORT_LOCKED", "message": "周报已提交，无法删除附件"},
            status=status.HTTP_409_CONFLICT,
        )

    attachment.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@parser_classes([MultiPartParser])
def replace_attachment(request, attachment_id):
    """
    POST /api/v1/attachments/{id}/replace
    用新文件替换旧附件——删除旧的，上传新的。需用户确认。
    """
    old_attachment = _get_authorized_attachment(request, attachment_id, owner_only=True)

    if old_attachment.report and old_attachment.report.status not in {ReportStatus.DRAFT, ReportStatus.RESUBMITTED}:
        return Response(
            {"code": "REPORT_LOCKED", "message": "周报已提交，无法替换附件"},
            status=status.HTTP_409_CONFLICT,
        )

    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return Response({"code": "NO_FILE", "message": "请选择文件"}, status=status.HTTP_400_BAD_REQUEST)

    report = old_attachment.report

    # 统一命名
    _, ext = os.path.splitext(uploaded_file.name)
    from django.utils import timezone as tz
    today = tz.now().date()
    iso_week = report.reporting_period.iso_week if report else 0
    safe_name = f"hubu_W{iso_week:02d}_{request.user.username}_{today.strftime('%Y%m%d')}{ext}"
    uploaded_file.name = safe_name

    # 上传新文件
    attachment_uuid = uuid.uuid4()
    result = storage.upload_stream(
        bucket=settings.S3_BUCKET_ORIGINALS,
        object_key=f"originals/{attachment_uuid}/source",
        file_obj=uploaded_file,
    )

    # MIME 检测
    uploaded_file.seek(0)
    mime_type = detect_mime(uploaded_file.read(4096), uploaded_file.name)
    level = get_level(mime_type)

    # 创建新附件
    new_attachment = Attachment.objects.create(
        report=report,
        uploaded_by=request.user,
        original_filename=safe_name,
        safe_filename=f"{attachment_uuid}{ext}",
        detected_mime=mime_type,
        source_sha256=result["sha256"],
        file_size_bytes=result["size"],
        original_object_key=f"originals/{attachment_uuid}/source",
        status=AttachmentStatus.QUARANTINED,
    )

    # 删旧
    old_attachment.delete()

    # 处理新附件
    if level == "C":
        new_attachment.status = AttachmentStatus.READY
        new_attachment.save(update_fields=["status"])
    elif is_pdf(mime_type):
        new_attachment.status = AttachmentStatus.PREVIEW_READY
        new_attachment.save(update_fields=["status"])
    else:
        new_attachment.status = AttachmentStatus.STORED
        new_attachment.save(update_fields=["status"])

    return Response(AttachmentDetailSerializer(new_attachment).data, status=status.HTTP_201_CREATED)


# ═══════════════════════════════════════════════════════════════
# 权限辅助
# ═══════════════════════════════════════════════════════════════

def _get_authorized_attachment(request, attachment_id, owner_only=False):
    """
    权限检查：附件所属者 or 管理员（查看已提交周报附件）。
    owner_only=True 时管理员也不能操作（删除、确认）。
    """
    attachment = get_object_or_404(Attachment, id=attachment_id)

    if attachment.uploaded_by == request.user:
        return attachment

    if not owner_only and request.user.is_admin:
        # 管理员可查看已提交周报的附件
        if attachment.report and attachment.report.status in {
            ReportStatus.SUBMITTED,
            ReportStatus.RESUBMITTED,
            ReportStatus.ARCHIVED,
        }:
            return attachment

    # 个人计划附件仅本人
    if attachment.private_plan and attachment.private_plan.owner_id == request.user.id:
        return attachment

    raise PermissionDeniedError()
