import io
from zipfile import ZipFile

import fitz
import pytest
from docx import Document
from lxml import etree

from attachments.office_renderer import convert_with_libreoffice, libreoffice_binary
from attachments.word_equations import prepare_word_equations
from attachments.word_preview_versions import has_omml


MATH = "http://schemas.openxmlformats.org/officeDocument/2006/math"
UNION = (
    '<m:nary><m:naryPr><m:chr m:val="∪"/></m:naryPr>'
    '<m:sub><m:r><m:t>i=1</m:t></m:r></m:sub><m:sup><m:r><m:t>n</m:t></m:r></m:sup>'
    '<m:e><m:r><m:t>F</m:t></m:r></m:e></m:nary>'
)
FRACTION = '<m:f><m:num><m:r><m:t>x</m:t></m:r></m:num><m:den><m:r><m:t>y</m:t></m:r></m:den></m:f>'


def equation_document(body=UNION):
    doc = Document()
    for paragraph, code in ((doc.add_paragraph(), body), (doc.sections[0].header.paragraphs[0], FRACTION)):
        paragraph._p.append(etree.fromstring(f'<m:oMathPara xmlns:m="{MATH}"><m:oMath>{code}</m:oMath></m:oMathPara>'.encode()))
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


@pytest.mark.parametrize("strict", [False, True])
def test_equations_in_document_and_header_become_vectors(strict):
    raw = equation_document()
    if strict:
        # Only the parts under test need strict Word, Math and Drawing namespaces.
        out = io.BytesIO()
        with ZipFile(io.BytesIO(raw)) as src, ZipFile(out, "w") as dst:
            for name in src.namelist():
                part = src.read(name)
                if name in {"word/document.xml", "word/header1.xml"}:
                    for family in (b"officeDocument", b"drawingml", b"wordprocessingml"):
                        part = part.replace(b"http://schemas.openxmlformats.org/" + family + b"/2006/",
                                            b"http://purl.oclc.org/ooxml/" + family + b"/")
                dst.writestr(name, part)
        raw = out.getvalue()
    updated = prepare_word_equations(raw)
    assert has_omml(raw) and not has_omml(updated)
    assert prepare_word_equations(updated) is None
    with ZipFile(io.BytesIO(raw)) as old, ZipFile(io.BytesIO(updated)) as new:
        assert old.read("word/styles.xml") == new.read("word/styles.xml")
        names = [n for n in new.namelist() if n.endswith(".svg")]
        assert len(names) == 2
        for n in names:
            tree = etree.fromstring(new.read(n))
            assert len(tree.findall(".//{*}path")) >= 2
            assert tree.find(".//{*}use") is None
        root = etree.fromstring(new.read("word/document.xml"))
        drawing = root.find(".//{*}docPr")
        assert r"\bigcup" in drawing.get("descr") and r"\int" not in drawing.get("descr")
        assert ("purl.oclc.org" in drawing.tag) == strict


def test_unsupported_large_operator_cannot_be_mistaken_for_an_integral():
    with pytest.raises(ValueError, match="n-ary"):
        prepare_word_equations(equation_document(UNION.replace("∪", "☂")))


def test_oversized_xml_rejected_before_parsing(monkeypatch):
    from attachments import word_preview_versions

    raw = equation_document()
    monkeypatch.setattr(word_preview_versions, "MAX_WORD_XML_BYTES", 128)
    for read in (prepare_word_equations, has_omml):
        with pytest.raises(ValueError, match="排版数据"):
            read(raw)


def test_formula_preview_has_real_glyphs_after_lo_export():
    if not libreoffice_binary():
        pytest.skip("LibreOffice is needed for the PDF rendering check")
    source = equation_document()
    ready = prepare_word_equations(source)
    result = convert_with_libreoffice(ready, ".docx")
    with fitz.open(stream=result, filetype="pdf") as pdf:
        assert len(pdf) == 1
        ink = [shape for shape in pdf[0].get_drawings() if shape["rect"].get_area() > 0]
        top = [shape for shape in ink if shape["rect"].y1 < 72]  # header
        body = [shape for shape in ink if shape["rect"].y0 >= 72]
        assert len(top) >= 3  # numerator, denominator, fraction bar
        assert len(body) >= 5  # union, both limits, operand
