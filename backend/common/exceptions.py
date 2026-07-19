"""
统一 API 异常处理。
错误返回稳定 code + 中文 message + request_id，前端不解析英文异常文本。
"""

import uuid
import logging

from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.exceptions import APIException
from django.http import JsonResponse

logger = logging.getLogger(__name__)


class WeeklyReportError(APIException):
    """业务异常基类，所有业务错误继承此类。"""

    status_code = 400
    default_code = "BUSINESS_ERROR"
    default_detail = "业务处理失败"


# ── 账号相关 ──────────────────────────────────────────────


class AccountDisabledError(WeeklyReportError):
    status_code = 403
    default_code = "ACCOUNT_DISABLED"
    default_detail = "账号已被禁用，请联系管理员"


class InvalidCredentialsError(WeeklyReportError):
    status_code = 401
    default_code = "INVALID_CREDENTIALS"
    default_detail = "账号或密码错误"


# ── 权限相关 ──────────────────────────────────────────────


class PermissionDeniedError(WeeklyReportError):
    status_code = 403
    default_code = "PERMISSION_DENIED"
    default_detail = "没有权限执行此操作"


class ObjectNotFound(WeeklyReportError):
    """越权访问时也返回 404，不暴露对象是否存在。"""

    status_code = 404
    default_code = "NOT_FOUND"
    default_detail = "未找到请求的资源"


# ── 文件相关 ──────────────────────────────────────────────


class FileTooLargeError(WeeklyReportError):
    status_code = 413
    default_code = "FILE_TOO_LARGE"
    default_detail = "文件大小超出限制"


class FileTypeMismatchError(WeeklyReportError):
    status_code = 400
    default_code = "FILE_TYPE_MISMATCH"
    default_detail = "文件类型与扩展名不匹配"


class MalwareDetectedError(WeeklyReportError):
    status_code = 400
    default_code = "MALWARE_DETECTED"
    default_detail = "文件安全扫描未通过"


class PreviewFailedError(WeeklyReportError):
    status_code = 422
    default_code = "ATTACHMENT_PREVIEW_FAILED"
    default_detail = "附件无法生成在线预览，请下载原件或上传 PDF"


# ── 版本冲突 ──────────────────────────────────────────────


class VersionConflictError(WeeklyReportError):
    status_code = 409
    default_code = "REPORT_VERSION_CONFLICT"
    default_detail = "文档已被其他标签页修改，请刷新后重试"


# ── 统一异常处理 ─────────────────────────────────────────


def api_exception_handler(exc, context):
    """
    将所有异常统一为 JSON 格式：
    {
      "code": "ERROR_CODE",
      "message": "中文错误消息",
      "request_id": "uuid",
      "details": { ... }
    }
    """
    request = context.get("request")
    request_id = getattr(request, "request_id", str(uuid.uuid4()))

    response = drf_exception_handler(exc, context)

    if response is None:
        # 非 DRF 异常
        logger.exception("Unhandled exception: %s", exc, extra={"request_id": request_id})
        return JsonResponse(
            {
                "code": "INTERNAL_ERROR",
                "message": "服务器内部错误，请联系管理员",
                "request_id": request_id,
            },
            status=500,
        )

    if isinstance(exc, WeeklyReportError):
        response.data = {
            "code": exc.default_code,
            "message": str(exc.detail),
            "request_id": request_id,
        }
        if hasattr(exc, "details"):
            response.data["details"] = exc.details

    return response
