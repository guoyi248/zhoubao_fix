"""Identify Word story parts containing Office Math and the previews rendered from them."""

import io
import re
from zipfile import ZipFile

from django.conf import settings
from lxml import etree


EQUATION_VERSION = "+equations-v1"
MAX_WORD_XML_BYTES = 32 * 1024 * 1024
STORY_PART = re.compile(r"word/(?:document|header\d*|footer\d*|footnotes|endnotes)\.xml")
MATH_TAGS = (
    "{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath",
    "{http://purl.oclc.org/ooxml/officeDocument/math}oMath",
)


def validate_word_archive(archive: ZipFile) -> None:
    members = archive.infolist()
    if sum(part.file_size for part in members) > max(settings.MAX_UPLOAD_BYTES, 512 * 1024 * 1024):
        raise ValueError("Word 文件解压后过大，无法生成公式预览。")
    xml_bytes = sum(
        part.file_size for part in members
        if part.filename == "[Content_Types].xml"
        or (part.filename.startswith("word/") and part.filename.endswith((".xml", ".rels")))
    )
    if xml_bytes > MAX_WORD_XML_BYTES:
        raise ValueError("Word 文件的排版数据过大，无法生成公式预览。")


def has_omml(data: bytes) -> bool:
    with ZipFile(io.BytesIO(data)) as archive:
        validate_word_archive(archive)
        for name in archive.namelist():
            if not STORY_PART.fullmatch(name):
                continue
            with archive.open(name) as xml:
                for _, element in etree.iterparse(xml, events=("end",), resolve_entities=False, no_network=True):
                    if element.tag in MATH_TAGS:
                        return True
                    element.clear()
    return False
