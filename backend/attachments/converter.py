"""纯 Python Word/Text → PDF 转换器。不依赖 LibreOffice。"""

import io
import hashlib
import logging
from pathlib import Path

from fpdf import FPDF
from docx import Document

logger = logging.getLogger(__name__)

# 内置中文字体路径（用 fpdf2 的 Unicode 字体支持）
# fpdf2 默认支持 UTF-8，需要注册中文字体
# 这里用 Noto Sans CJK 的路径，Windows 上可能不存在
# 回退方案：用内置的 Helvetica（不支持中文，但不会崩）

FONT_DIRS = [
    "C:/Windows/Fonts/",
    "/usr/share/fonts/opentype/noto/",
    "/usr/share/fonts/truetype/noto/",
]


def _find_chinese_font() -> str | None:
    """查找可用的中文字体"""
    candidates = [
        "C:/Windows/Fonts/simsun.ttc",  # Windows: 宋体
        "C:/Windows/Fonts/msyh.ttc",     # Windows: 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",   # Windows: 黑体
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return None


CHINESE_FONT = _find_chinese_font()


def convert_txt_to_pdf(content: str) -> bytes:
    """将纯文本内容转为 PDF。"""
    pdf = FPDF()
    pdf.add_page()
    _setup_font(pdf)
    pdf.set_font_size(12)
    # 分行写入
    for line in content.replace("\r\n", "\n").split("\n"):
        safe_line = line.encode("utf-8", errors="replace").decode("utf-8")[:120]
        if safe_line.strip():
            pdf.multi_cell(0, 8, safe_line)
        else:
            pdf.ln(4)
    return pdf.output()


def convert_docx_to_pdf(file_bytes: bytes) -> bytes:
    """将 DOCX 文件转为 PDF。"""
    doc = Document(io.BytesIO(file_bytes))
    content_parts = []

    # 标题
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        if para.style.name.startswith("Heading"):
            content_parts.append(("heading", text))
        else:
            content_parts.append(("body", text))

    # 表格
    for table in doc.tables:
        rows = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows.append(" | ".join(cells))
        content_parts.append(("table", "\n".join(rows)))

    pdf = FPDF()
    pdf.add_page()
    _setup_font(pdf)

    for kind, text in content_parts:
        if kind == "heading":
            pdf.set_font_size(16)
            pdf.multi_cell(0, 10, text)
            pdf.ln(4)
        elif kind == "table":
            pdf.set_font_size(10)
            for line in text.split("\n"):
                pdf.multi_cell(0, 7, line)
            pdf.ln(4)
        else:
            pdf.set_font_size(12)
            for line in text.split("\n"):
                safe_line = line[:150]
                if safe_line.strip():
                    pdf.multi_cell(0, 8, safe_line)

    return pdf.output()


def _setup_font(pdf: FPDF):
    """设置中文字体"""
    if CHINESE_FONT:
        try:
            pdf.add_font("zh", "", CHINESE_FONT, uni=True)
            pdf.set_font("zh", size=12)
            return
        except Exception:
            pass
    # 回退
    pdf.set_font("Helvetica", size=12)


def convert_via_gotenberg(file_bytes: bytes, filename: str) -> bytes | None:
    """
    通过 Gotenberg HTTP API 转换 Office 文件为 PDF。
    Gotenberg: docker run -p 3000:3000 gotenberg/gotenberg:8
    API docs: https://gotenberg.dev/docs/routes#convert-office-documents
    """
    import requests
    gotenberg_url = "http://localhost:3000/forms/libreoffice/convert"
    try:
        resp = requests.post(
            gotenberg_url,
            files={"files": (filename, file_bytes)},
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.content
        logger.warning("Gotenberg returned %d", resp.status_code)
    except Exception as e:
        logger.warning("Gotenberg not available: %s", e)
    return None


def convert_via_api(file_bytes: bytes, filename: str) -> bytes | None:
    """
    通过外部 API 转换（兜底）。
    配置 GOTENBERG_URL 环境变量指向 Gotenberg 服务即可启用。
    如未配置则跳过。
    """
    import os
    url = os.environ.get("GOTENBERG_URL", "")
    if url:
        import requests
        try:
            resp = requests.post(
                f"{url}/forms/libreoffice/convert",
                files={"files": (filename, file_bytes)},
                timeout=120,
            )
            if resp.status_code == 200:
                return resp.content
        except Exception:
            pass
    return None


def office_to_pdf(file_bytes: bytes, mime_type: str, filename: str) -> bytes:
    """
    统一入口：1) Gotenberg API（首选）→ 2) 纯 Python（兜底）→ 3) 失败
    """
    # 文本文件直接 Python 处理
    if mime_type in ("text/plain", "text/markdown", "text/csv"):
        content = file_bytes.decode("utf-8", errors="replace")
        return convert_txt_to_pdf(content)

    # Office 文件：优先 Gotenberg
    result = convert_via_api(file_bytes, filename)
    if result and len(result) > 100:
        return result

    # Python 兜底
    logger.info("Gotenberg not available, using Python fallback for %s", filename)
    if "wordprocessingml" in mime_type or "msword" in mime_type or filename.endswith((".docx", ".doc")):
        return convert_docx_to_pdf(file_bytes)
    if "spreadsheetml" in mime_type or "ms-excel" in mime_type or filename.endswith((".xlsx", ".xls")):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True)
            lines = []
            for sheet_name in wb.sheetnames[:3]:
                ws = wb[sheet_name]; lines.append(f"[{sheet_name}]")
                for row in ws.iter_rows(values_only=True):
                    lines.append(" | ".join(str(c) if c else "" for c in row))
                lines.append("")
            wb.close()
            return convert_txt_to_pdf("\n".join(lines))
        except Exception:
            return None
    if "presentation" in mime_type or filename.endswith((".pptx", ".ppt")):
        try:
            from pptx import Presentation
            prs = Presentation(io.BytesIO(file_bytes))
            lines = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if shape.has_text_frame: lines.append(shape.text_frame.text)
            return convert_txt_to_pdf("\n\n".join(lines))
        except Exception:
            return None
    return None


def convert_and_store(attachment):
    """
    转换附件为 PDF 并存储到 MinIO。
    返回 (pdf_sha256, page_count) 或 None。
    """
    from common.storage import storage
    from django.conf import settings

    file_bytes = storage.download_to_bytes(
        settings.S3_BUCKET_ORIGINALS, attachment.original_object_key
    )

    pdf_bytes = office_to_pdf(file_bytes, attachment.detected_mime, attachment.original_filename)
    if not pdf_bytes:
        return None

    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    preview_key = f"previews/{attachment.original_object_key.rsplit('/', 1)[0]}/preview.pdf"

    storage.client.put_object(
        Bucket=settings.S3_BUCKET_PREVIEWS,
        Key=preview_key,
        Body=pdf_bytes,
        ContentType="application/pdf",
    )

    import re
    page_count = len(re.findall(rb"/Type\s*/Page[^s]", pdf_bytes)) or 1

    return {"sha256": pdf_sha256, "object_key": preview_key, "page_count": page_count}
