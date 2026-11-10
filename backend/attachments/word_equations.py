"""Render native Word equations as inert vector pictures in the preview copy only."""

import io
import re
import shutil
from pathlib import PurePosixPath
from uuid import uuid4
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from docx.oxml.shape import CT_Inline
from lxml import etree
from omml2latex import convert_omml
from ziamath import Latex, config as math_config

from .word_preview_versions import MATH_TAGS, STORY_PART, validate_word_archive

PACKAGE = "http://schemas.openxmlformats.org/package/2006"
OFFICE = "http://schemas.openxmlformats.org/officeDocument/2006"
STRICT_WORD = "http://purl.oclc.org/ooxml/wordprocessingml/main"
STRICT_PREFIX = "http://purl.oclc.org/ooxml/"
NARY_ALIASES = str.maketrans("∪∩∨∧⊕⊗⊙⊎", "⋃⋂⋁⋀⨁⨂⨀⨄")
NARY_OPERATORS = "∫∬∭∮∯∰∑∏∐⋃⋂⋁⋀⨁⨂⨀⨄"
LITERAL_TEXT = str.maketrans({"\\": r"\backslash ", "_": r"\_", "{": r"\{", "}": r"\}",
                              "$": r"\$", "&": r"\&", "#": r"\#"})
# Emit glyph outlines directly; some Office SVG filters misplace SVG2 <use> references.
math_config.svg2 = False


def _parse(xml):
    return etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))


def _xml(node):
    return etree.tostring(node, xml_declaration=True, encoding="UTF-8", standalone=True)


def _math_picture(equation, word, picture_id, relationship_id, filename, default_size):
    math = "{" + etree.QName(equation).namespace + "}"
    if sum(1 for _ in equation.iter()) > 4096 or sum(map(len, equation.itertext())) > 65536:
        raise ValueError("Word equation exceeds the rendering limit")
    # OMML run contents are literal characters, even when they look like TeX commands.
    for text in equation.iter(math + "t"):
        text.text = (text.text or "").translate(LITERAL_TEXT)
    for tag in ("chr", "begChr", "endChr", "sepChr"):
        if any(len(char.get(math + "val", "")) > 1 for char in equation.iter(math + tag)):
            raise ValueError("Invalid Word equation delimiter")
    for char in equation.iterfind(".//" + math + "naryPr/" + math + "chr"):
        value = char.get(math + "val", "∫").translate(NARY_ALIASES)
        if value not in NARY_OPERATORS or len(value) != 1:
            # omml2latex otherwise silently substitutes an integral for unknown operators.
            raise ValueError("Unsupported n-ary operator in Word equation")
        char.set(math + "val", value)
    latex = convert_omml(equation)[1:-1].strip()
    if not latex:
        raise ValueError("Word equation contained no renderable content")
    size = equation.find(".//" + word + "sz")
    points = float(size.get(word + "val", default_size)) / 2 if size is not None else default_size / 2
    if not 0.5 <= points <= 819:
        raise ValueError("Invalid Word equation font size")
    color = equation.find(".//" + word + "color")
    rgb = color.get(word + "val", "") if color is not None else ""
    formula = Latex(latex, size=points, color="#" + rgb if re.fullmatch(r"[a-fA-F0-9]{6}", rgb) else "black",
                    margin=0.4)
    svg = formula.svgxml()
    width, height = float(svg.attrib["width"]), float(svg.attrib["height"])
    picture = ElementTree.tostring(svg, encoding="utf-8")
    inline = CT_Inline.new_pic_inline(picture_id, relationship_id, filename,
                                     round(width * 12700), round(height * 12700))
    inline.docPr.set("descr", latex)
    run = etree.Element(word + "r")
    props = etree.SubElement(run, word + "rPr")
    position = round(2 * (formula.getyofst() - 0.4))
    etree.SubElement(props, word + "position").set(word + "val", str(position))
    etree.SubElement(run, word + "drawing").append(inline)
    if word == "{" + STRICT_WORD + "}":
        # The python-docx picture template uses Transitional namespace names.
        picture_run = etree.tostring(run, encoding="unicode")
        for family in ("officeDocument", "drawingml"):
            picture_run = picture_run.replace(f"http://schemas.openxmlformats.org/{family}/2006/",
                                              STRICT_PREFIX + family + "/")
        run = _parse(picture_run.encode())
    return run, picture


def _unwrap_math_paragraph(wrapper, math, word):
    parent = wrapper.getparent()
    # m:oMathPara accepts equations, not Word pictures. Move the runs back into
    # the Word paragraph, retaining the display equation's alignment.
    alignment = wrapper.find(math + "oMathParaPr/" + math + "jc")
    runs = list(wrapper.iterchildren(word + "r"))
    if parent.tag == word + "p":
        for run in runs:
            wrapper.addprevious(run)
    else:
        parent = etree.Element(word + "p")
        wrapper.addprevious(parent)
        parent.extend(runs)
    if alignment is not None or len(parent.findall(word + "r")) == len(runs):
        props = parent.find(word + "pPr")
        if props is None:
            props = etree.Element(word + "pPr")
            parent.insert(0, props)
        jc = props.find(word + "jc")
        if jc is None:
            jc = etree.SubElement(props, word + "jc")
            jc.set(word + "val", "center")
        if alignment is not None:
            value = alignment.get(math + "val")
            jc.set(word + "val", value if value in {"left", "right"} else "center")
    wrapper.getparent().remove(wrapper)


def prepare_word_equations(data):
    """Return a preview-only OOXML package, or None for a document without equations."""
    with ZipFile(io.BytesIO(data)) as source:
        validate_word_archive(source)
        replacements = {}
        picture_id = 0
        stories = []
        for part in source.namelist():
            if STORY_PART.fullmatch(part):
                story = _parse(source.read(part))
                for item in story.iter("{*}docPr"):
                    value = item.get("id", "")
                    if value.isascii() and value.isdigit():
                        picture_id = max(picture_id, int(value))
                equations = list(story.iter(*MATH_TAGS))
                if equations:
                    stories.append((part, story, equations))
        if not stories:
            return None
        if sum(len(equations) for _, _, equations in stories) > 4096:
            raise ValueError("Word document exceeds the equation rendering limit")

        default_size = 22  # OOXML run sizes are in half-points.
        if "word/styles.xml" in source.namelist():
            styles = _parse(source.read("word/styles.xml"))
            size = styles.find("{*}docDefaults/{*}rPrDefault/{*}rPr/{*}sz")
            if size is not None:
                default_size = int(size.get("{" + etree.QName(styles).namespace + "}val", "22"))
        relationships = "{" + PACKAGE + "/relationships}"
        types = _parse(source.read("[Content_Types].xml"))
        content_type = "{" + PACKAGE + "/content-types}"
        vector_bytes = 0
        for part, story, equations in stories:
            word = "{" + etree.QName(story).namespace + "}"
            image_type = (STRICT_PREFIX + "officeDocument" if word == "{" + STRICT_WORD + "}" else OFFICE) + "/relationships/image"
            rel_path = f"word/_rels/{PurePosixPath(part).name}.rels"
            rels = (_parse(source.read(rel_path)) if rel_path in source.namelist()
                    else etree.Element(relationships + "Relationships", nsmap={None: PACKAGE + "/relationships"}))
            for equation in equations:
                picture_id += 1
                unique = uuid4().hex
                rid, name = "img" + unique, "equation-" + unique + ".svg"
                run, picture = _math_picture(equation, word, picture_id, rid, name, default_size)
                vector_bytes += len(picture)
                if vector_bytes > 64 * 1024 * 1024:
                    raise ValueError("Word equations exceed the preview image budget")
                replacements["word/media/" + name] = picture
                etree.SubElement(rels, relationships + "Relationship", Id=rid, Type=image_type, Target="media/" + name)
                etree.SubElement(types, content_type + "Override", PartName="/word/media/" + name,
                                 ContentType="image/svg+xml")
                run.tail = equation.tail
                equation.getparent().replace(equation, run)
            for tag in MATH_TAGS:
                for wrapper in list(story.iter(tag + "Para")):
                    _unwrap_math_paragraph(wrapper, tag.rsplit("}", 1)[0] + "}", word)
            replacements[rel_path] = _xml(rels)
            replacements[part] = _xml(story)
        replacements["[Content_Types].xml"] = _xml(types)
        output = io.BytesIO()
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as target:
            for info in source.infolist():
                if info.filename not in replacements:
                    with source.open(info) as original, target.open(info, "w") as copy:
                        shutil.copyfileobj(original, copy)
            for name, part_data in replacements.items():
                target.writestr(name, part_data)
        return output.getvalue()
