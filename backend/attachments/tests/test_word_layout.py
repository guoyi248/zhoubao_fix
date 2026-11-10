"""Word 排版回归；安装 LibreOffice 后，同时运行真实排版检查。"""

import io
from pathlib import Path

import fitz
import pytest
from docx import Document
from docx.shared import Inches, RGBColor

from attachments.converter import valid_word_source
from attachments.office_renderer import convert_with_libreoffice, libreoffice_binary


def test_named_word_file_requires_a_word_document():
    source = Path(__file__).resolve().parents[3] / "tests/office-samples/sample_report.docx"
    assert valid_word_source(source.read_bytes(), ".docx")
    assert not valid_word_source(b"plain text renamed to .docx", ".docx")
    assert not valid_word_source(b"plain text renamed to .doc", ".doc")


def test_word_failure_preserves_original_without_text_only_preview(local_files, monkeypatch, settings):
    import hashlib
    from types import SimpleNamespace

    from attachments.converter import convert_and_store

    data = (Path(__file__).resolve().parents[3] / "tests/office-samples/sample_report.docx").read_bytes()
    source = SimpleNamespace(pk="example", original_filename="test.docx", original_object_key="originals/test/source",
                             detected_mime="text/plain", source_sha256=hashlib.sha256(data).hexdigest())
    local_files.upload_stream(settings.S3_BUCKET_ORIGINALS, source.original_object_key, io.BytesIO(data))
    monkeypatch.setattr("attachments.office_renderer.libreoffice_binary", lambda: None)
    assert convert_and_store(source) is None
    assert local_files.download_to_bytes(settings.S3_BUCKET_ORIGINALS, source.original_object_key) == data


def test_word_image_color_table_and_pagination_survive_real_export():
    if not libreoffice_binary():
        pytest.skip("安装 LibreOffice 后运行真实文档排版检查")
    document = Document()
    document.sections[0].header.paragraphs[0].text = "Group weekly report"
    paragraph = document.add_paragraph()
    paragraph.add_run("Survey results").font.color.rgb = RGBColor(255, 0, 0)
    with fitz.open() as sample:
        chart = sample.new_page(width=80, height=40)
        chart.draw_rect(fitz.Rect(10, 10, 50, 25), fill=(0, .7, .2))
        document.add_picture(io.BytesIO(chart.get_pixmap().tobytes("png")), width=Inches(1.8))
    row = document.add_table(rows=1, cols=2).rows[0]
    row.cells[0].text, row.cells[1].text = "Sample A", "Sample B"
    document.add_page_break()
    document.add_paragraph("Follow-up")
    source = io.BytesIO()
    document.save(source)
    output = convert_with_libreoffice(source.getvalue(), ".docx")
    assert output
    with fitz.open(stream=output, filetype="pdf") as pdf:
        assert len(pdf) == 2
        first, second = pdf[0], pdf[1]
        assert first.get_image_info() and not second.get_image_info()
        left, right = first.search_for("Sample A")[0], first.search_for("Sample B")[0]
        assert left.x1 < right.x0 and abs(left.y0 - right.y0) < 1
        spans = [span for block in first.get_text("dict")["blocks"] for line in block.get("lines", [])
                 for span in line["spans"]]
        assert any(s["color"] == 0xff0000 and "Survey results" in s["text"] for s in spans)
        assert "Follow-up" in second.get_text() and "Group weekly report" in second.get_text()
