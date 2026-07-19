"""
MIME 类型检测与文件格式分类。
使用 libmagic 进行真实类型检测，不信任扩展名。
"""

import os
import mimetypes

try:
    import magic
    _has_libmagic = True
except ImportError:
    _has_libmagic = False

# 文件支持等级
SUPPORTED_MIME_LEVEL_A = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
    "text/markdown",
    "text/csv",
    "image/png",
    "image/jpeg",
    "image/webp",
}

SUPPORTED_MIME_LEVEL_B = {
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
    "application/rtf",
    "application/vnd.ms-word.document.macroenabled.12",
    "application/vnd.ms-excel.sheet.macroenabled.12",
    "application/vnd.ms-powerpoint.presentation.macroenabled.12",
}

EXTENSION_WHITELIST = {
    ".pdf", ".docx", ".xlsx", ".pptx",
    ".doc", ".xls", ".ppt",
    ".odt", ".ods", ".odp", ".rtf",
    ".docm", ".xlsm", ".pptm",
    ".txt", ".md", ".csv",
    ".png", ".jpg", ".jpeg", ".webp", ".tiff",
    ".zip", ".7z",
}

FORBIDDEN_EXTENSIONS = {
    ".exe", ".dll", ".so", ".sh", ".bat", ".cmd", ".ps1",
    ".vbs", ".js", ".jar", ".py", ".rb", ".pl",
    ".scr", ".msi", ".com",
}

def detect_mime(file_bytes: bytes) -> str:
    """使用 libmagic 检测文件真实 MIME 类型。"""
    return magic.from_buffer(file_bytes[:4096], mime=True)


def get_level(mime_type: str) -> str:
    """返回文件支持等级：A / B / C。"""
    if mime_type in SUPPORTED_MIME_LEVEL_A:
        return "A"
    if mime_type in SUPPORTED_MIME_LEVEL_B:
        return "B"
    return "C"


def check_extension(ext: str) -> bool:
    """检查扩展名是否在白名单中。"""
    ext_lower = ext.lower()
    if ext_lower in FORBIDDEN_EXTENSIONS:
        return False
    return ext_lower in EXTENSION_WHITELIST


def is_office_file(mime_type: str) -> bool:
    """判断是否为 Office 文件（需 LibreOffice 转换）。"""
    return any(
        mime_type.startswith(prefix)
        for prefix in [
            "application/vnd.openxmlformats-officedocument",
            "application/vnd.ms-",
            "application/msword",
            "application/vnd.oasis.opendocument",
            "application/rtf",
        ]
    )


def is_pdf(mime_type: str) -> bool:
    return mime_type == "application/pdf"


def is_image(mime_type: str) -> bool:
    return mime_type.startswith("image/")


def is_text(mime_type: str) -> bool:
    return mime_type in {"text/plain", "text/markdown", "text/csv"}


def is_macro_enabled(mime_type: str) -> bool:
    """检测是否为启用宏的 Office 格式。"""
    return mime_type in {
        "application/vnd.ms-word.document.macroenabled.12",
        "application/vnd.ms-excel.sheet.macroenabled.12",
        "application/vnd.ms-powerpoint.presentation.macroenabled.12",
    }
