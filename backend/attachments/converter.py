"""从上传原件生成用于阅读和投影的 PDF。"""

import hashlib
import io
import logging
import os
import zipfile
from pathlib import Path

import fpdf
import fitz
import requests
from django.conf import settings
from fpdf import FPDF
from .mime_utils import is_office_file
from .office_renderer import convert_with_libreoffice
from .word_equations import prepare_word_equations
from .word_preview_versions import EQUATION_VERSION

logger = logging.getLogger(__name__)


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
        if line.strip():
            pdf.multi_cell(0, 8, line, new_x="LMARGIN")
        else:
            pdf.ln(4)
    return bytes(pdf.output())


WORD_EXTENSIONS = {".doc", ".docx", ".docm"}
WORD_MIME = {"application/msword", "application/vnd.ms-word.document.macroenabled.12",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def is_word_document(mime, filename):
    return mime in WORD_MIME or Path(filename).suffix.lower() in WORD_EXTENSIONS


def valid_word_source(data, extension):
    # Writer 可以将伪装成 DOCX 的纯文本也导出为 PDF。拒绝这种错误预览。
    if extension == ".doc":
        return data.startswith(bytes.fromhex("d0cf11e0a1b11ae1")) or data.lstrip().startswith(b"{\\rtf")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            return "word/document.xml" in package.namelist()
    except zipfile.BadZipFile:
        return False


def _setup_font(pdf: FPDF):
    """设置中文字体"""
    if CHINESE_FONT:
        try:
            pdf.add_font("zh", "", CHINESE_FONT)
            pdf.set_font("zh", size=12)
            return
        except Exception:
            pass
    # 回退
    pdf.set_font("Helvetica", size=12)


def convert_via_gotenberg(file_bytes: bytes, filename: str) -> bytes | None:
    url = os.environ.get("GOTENBERG_URL", "").rstrip("/")
    if not url:
        return None
    try:
        response = requests.post(
            f"{url}/forms/libreoffice/convert",
            files={"files": (filename, file_bytes)},
            timeout=settings.PREVIEW_TIMEOUT_SECONDS,
        )
        if response.ok and response.content.startswith(b"%PDF-"):
            return response.content
        logger.warning("Gotenberg conversion failed (HTTP %s)", response.status_code)
    except requests.RequestException as exc:
        logger.warning("Gotenberg unavailable: %s", exc)
    return None


def _local_pdf(file_bytes: bytes, mime_type: str, filename: str) -> bytes | None:
    # 文本文件直接 Python 处理
    if mime_type in ("text/plain", "text/markdown", "text/csv"):
        content = file_bytes.decode("utf-8", errors="replace")
        return convert_txt_to_pdf(content)

    if "spreadsheetml" in mime_type or "ms-excel" in mime_type or filename.endswith((".xlsx", ".xls")):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True)
            lines = []
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]; lines.append(f"[{sheet_name}]")
                for row in ws.iter_rows(values_only=True):
                    lines.append(" | ".join(str(c) if c is not None else "" for c in row))
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


def convert_and_store(attachment, *, require_office_layout=False):
    """保存排版后的 PDF 并返回预览元数据；无法生成预览时返回 None。"""
    from common.storage import storage

    file_bytes = storage.download_to_bytes(
        settings.S3_BUCKET_ORIGINALS, attachment.original_object_key
    )

    if len(attachment.source_sha256) == 64 and hashlib.sha256(file_bytes).hexdigest() != attachment.source_sha256:
        logger.warning("Source hash mismatch for attachment %s", attachment.pk)
        return None

    name = attachment.original_filename
    mime = attachment.detected_mime
    extension = Path(name).suffix.lower()
    word = is_word_document(mime, name)
    if word and not valid_word_source(file_bytes, extension):
        return None
    pdf_bytes = None
    try:
        formulas_prepared = False
        if word and extension in {".docx", ".docm"}:
            prepared = prepare_word_equations(file_bytes)
            if prepared is not None:
                file_bytes = prepared
                formulas_prepared = True
        if is_office_file(mime) or word:
            converter, version = "Gotenberg", "8"
            pdf_bytes = convert_via_gotenberg(file_bytes, "source" + extension)
            if not pdf_bytes:
                converter, version = "LibreOffice", ""
                pdf_bytes = convert_with_libreoffice(file_bytes, extension)
        if not pdf_bytes and not (word or require_office_layout):
            converter, version = "fpdf2", fpdf.__version__
            pdf_bytes = _local_pdf(file_bytes, mime, name.lower())
        if not pdf_bytes:
            return None
        with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
            if not pdf.is_pdf or pdf.needs_pass or not len(pdf):
                return None
            page_count = len(pdf)
            if converter == "LibreOffice":
                version = (pdf.metadata.get("producer") or "")[:100]
            if formulas_prepared:
                version = version[:100 - len(EQUATION_VERSION)] + EQUATION_VERSION
    except Exception:
        logger.warning("Cannot render attachment %s", attachment.pk, exc_info=True)
        return None

    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    preview_key = f"previews/{attachment.original_object_key.rsplit('/', 1)[0]}/{pdf_sha256}.pdf"

    storage.client.put_object(
        Bucket=settings.S3_BUCKET_PREVIEWS,
        Key=preview_key,
        Body=pdf_bytes,
        ContentType="application/pdf",
    )

    return {"sha256": pdf_sha256, "object_key": preview_key, "page_count": page_count,
            "converter_name": converter, "converter_version": version}
