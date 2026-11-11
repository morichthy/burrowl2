"""各格式的抽取器（设计稿 01 D-11、D-16、D-17）：输入原件字节，输出单元清单、每个单元的文本与版式块。

纯函数，不读写账本。单元（unit）是抽取与引用的基本单位：
    doc        文本文件、DOCX 的正文（单一文档流）
    p<N>       PDF 的第 N 页、PPTX 的第 N 页（从 1 开始）
    img        独立的图片原件
    img<K>     PPTX / DOCX 里嵌入的第 K 张图片（默认不抽取）
    av         音视频原件（转写按时间戳分块）
版式块（block）保存"哪句在哪"：标题、段落、列表、表格、图片、媒体、备注、字幕块。
PPTX 与 PDF 的块带 box = [x, y, 宽, 高]，取值是占整页宽高的比例（0–1），原点在左上角：
PPTX 用于没有页面快照时按位置重建，PDF 用于在原样显示的页面上画段落标记（设计稿 02 D-03）。
"""
import io
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..core.errors import BurrowlError
from ..core.hashing import sha256_bytes
from . import omml

# 抽取器的版本：改变抽取结果的修改都要加 1，重建时据此判断"方法变了"
# 2：PDF 按位置分段、块带 box、页眉页脚标为 furniture（设计稿 02 D-04）；3：公式块（设计稿 03 D-15）；
# 4：Excel 工作表（设计稿 03 D-11；只新增格式，已有的 PDF / PPT / Word 抽取不变，补抽只重建 xlsx）；
# 5：Word / PPT 的 Office 公式（OMML）转 LaTeX、PPT 里带公式的形状、Word 的修订插入与内容控件（设计稿 03 D-20）
EXTRACTOR_VERSION = 5
# 各格式的抽取器最后一次改变结果时的版本：补抽只重建这个版本之前抽取的原件，其他格式不必重抽
FORMAT_VERSION_SINCE = {"pdf": 3, "pptx": 5, "docx": 5, "xlsx": 4}

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".log", ".py", ".yaml", ".yml",
                 ".xml", ".html", ".htm", ".ini", ".cfg", ".toml", ".sql", ".rst", ".tex"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
AV_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v", ".mp3", ".wav", ".m4a", ".ogg", ".flac"}
FORMAT_OF_SUFFIX = {**{s: "text" for s in TEXT_SUFFIXES}, **{s: "image" for s in IMAGE_SUFFIXES},
                    **{s: "av" for s in AV_SUFFIXES}, ".pdf": "pdf", ".pptx": "pptx", ".docx": "docx",
                    ".xlsx": "xlsx", ".xlsm": "xlsx"}

MEDIA_TYPES = {
    ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp", ".tif": "image/tiff", ".tiff": "image/tiff",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo", ".m4v": "video/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".ogg": "audio/ogg", ".flac": "audio/flac",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".json": "application/json", ".html": "text/html", ".htm": "text/html", ".csv": "text/csv",
    ".md": "text/markdown", ".markdown": "text/markdown", ".xml": "text/xml",
}


def format_of(artifact: dict) -> str:
    """text / pdf / pptx / docx / image / av / binary。直接以文本登记的原件（没有文件名）按文本处理。"""
    suffix = artifact["data"].get("suffix")
    if suffix is None:
        return "text" if artifact["data"].get("media_type", "text/plain").startswith("text/") else "binary"
    return FORMAT_OF_SUFFIX.get(suffix, "binary")


def media_type_of(artifact: dict) -> str:
    suffix = artifact["data"].get("suffix")
    if suffix is None:
        return artifact["data"].get("media_type") or "text/plain"
    if suffix in TEXT_SUFFIXES and suffix not in MEDIA_TYPES:
        return "text/plain"
    return MEDIA_TYPES.get(suffix, "application/octet-stream")


@dataclass
class Content:
    """一个单元的抽取结果。status：text 有文本 / image 图片页，待抽取 / empty 空白 / not_extracted 未抽取。"""
    unit: str
    status: str
    text: str = ""
    blocks: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


@dataclass
class Extraction:
    manifest: dict
    contents: list[Content]
    images: dict[str, bytes] = field(default_factory=dict)  # 嵌入图片：sha256 → 字节，写入 blobs
    method: str = ""


# ---------- 块与文本 ----------
def block_text(block: dict) -> str:
    t = block.get("type")
    if t == "table":
        return "\n".join(" | ".join(c.strip() for c in row) for row in block.get("rows", []))
    if t in ("title", "text"):
        return "\n".join(p["text"] for p in block.get("paragraphs", []) if p["text"].strip())
    if t == "notes":
        return f"备注：{block.get('text', '')}" if block.get("text", "").strip() else ""
    if t in ("image", "media"):
        return block.get("alt") or ""
    if t == "cue":
        return block.get("text", "")
    if t == "furniture":
        return ""  # 页眉、页脚、页码、页边竖排编号：不进索引、不分段（设计稿 02 D-04）
    return block.get("text", "")


def text_of(blocks: list[dict]) -> str:
    return "\n\n".join(t for t in (block_text(b) for b in blocks) if t.strip())


def paragraphs_to_blocks(text: str) -> list[dict]:
    """提交的纯文本（AI 识别、人工转写）按空行分成段落块；以 # 开头的行作为标题。"""
    blocks = []
    for part in re.split(r"\n\s*\n", text.strip()):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", part)
        if m and "\n" not in part:
            blocks.append({"type": "heading", "level": len(m.group(1)), "text": m.group(2)})
        else:
            blocks.append({"type": "paragraph", "text": part})
    return blocks


_CUE = re.compile(r"^\[?(?:(\d+):)?(\d{1,2}):(\d{2})(?:\.\d+)?\]?\s*(.*)$")


def cues_from_text(text: str) -> list[dict]:
    """视频转写："[00:01:23] 文字" 或 "01:23 文字" 一行一块；没有时间戳的行接到上一块。"""
    blocks: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _CUE.match(line)
        if m:
            h, mnt, sec, rest = m.groups()
            t = int(h or 0) * 3600 + int(mnt) * 60 + int(sec)
            blocks.append({"type": "cue", "t": t, "text": rest})
        elif blocks:
            blocks[-1]["text"] = (blocks[-1]["text"] + " " + line).strip()
        else:
            blocks.append({"type": "cue", "t": 0, "text": line})
    return blocks


# ---------- PDF ----------
def extract_pdf(data: bytes) -> Extraction:
    """PDF 按位置分段（设计稿 02 D-03、D-04，见 pdf_layout）：每页一个单元，块带 box；没有文字层的页标为图片页。"""
    import pypdfium2 as pdfium  # noqa: PLC0415 - 只在抽取 PDF 时加载
    import pypdfium2.raw as raw  # noqa: PLC0415

    from .pdf_layout import layout_pages  # noqa: PLC0415

    try:
        doc = pdfium.PdfDocument(data)
    except Exception as exc:  # noqa: BLE001 - 损坏或加密的 PDF
        raise BurrowlError("UNREADABLE", f"PDF 打不开：{exc}") from exc
    units, contents = [], []
    try:
        layout = layout_pages(doc)
        for i in range(len(doc)):
            page = doc[i]
            n = i + 1
            width, height = page.get_size()
            units.append({"unit": f"p{n}", "label": f"第 {n} 页", "kind": "page", "page": n})
            meta = {"page": n, "size": [round(width, 1), round(height, 1)], "rotation": page.get_rotation()}
            blocks = layout[i]["blocks"]
            text = text_of(blocks)
            if len(text.strip()) < 20:  # 几乎没有文字层：图片页（扫描件）或空白页
                has_image = any(True for _ in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE], max_depth=2))
                contents.append(Content(f"p{n}", "image" if has_image else "empty", meta=meta))
                continue
            contents.append(Content(f"p{n}", "text", text, blocks, meta))
    finally:
        doc.close()
    return Extraction({"format": "pdf", "units": units, "pages": len(units)}, contents,
                      method=f"pypdfium2 {pdfium.version.PYPDFIUM_INFO}（按位置分段）")


def pdf_page_count(data: bytes) -> int:
    import pypdfium2 as pdfium  # noqa: PLC0415
    doc = pdfium.PdfDocument(data)
    try:
        return len(doc)
    finally:
        doc.close()


def render_pdf_page(data: bytes, page: int, scale: float = 1.5,
                    clip: tuple[float, float, float, float] | None = None) -> bytes:
    """把 PDF 第 page 页（从 1 开始）渲染成 PNG。scale 1 ≈ 72 dpi。

    clip = (x, y, 宽, 高)：只要页面上的这一块（占页面的比例，左上原点，与块的 box 同一格式；
    设计稿 03 D-16 公式裁切图），四周各留一点边。"""
    import pypdfium2 as pdfium  # noqa: PLC0415
    doc = pdfium.PdfDocument(data)
    try:
        if not 1 <= page <= len(doc):
            raise BurrowlError("NOT_FOUND", "页码超出范围", {"page": page, "pages": len(doc)})
        image = doc[page - 1].render(scale=scale).to_pil()
        if clip:
            x, y, w, h = clip
            pad = 0.006
            width, height = image.size
            box = (max(0, int((x - pad) * width)), max(0, int((y - pad) * height)),
                   min(width, int((x + w + pad) * width) + 1), min(height, int((y + h + pad) * height) + 1))
            if box[2] <= box[0] or box[3] <= box[1]:
                raise BurrowlError("INVALID_ARGUMENT", "裁切范围为空", {"clip": list(clip)})
            image = image.crop(box)
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    finally:
        doc.close()


def downscale_image(data: bytes, max_side: int = 1600) -> tuple[bytes, str]:
    """给 AI 看图时缩小过大的图片；返回 (字节, 格式)。打不开的图片原样返回。"""
    from PIL import Image  # noqa: PLC0415
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:  # noqa: BLE001
        return data, "png"
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side))
    if image.mode not in ("RGB", "L", "RGBA"):
        image = image.convert("RGBA")
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), "png"


# ---------- PPTX ----------
def _image_mime(ext: str) -> str:
    return MEDIA_TYPES.get("." + ext.lower().lstrip("."), "image/png")


def extract_pptx(data: bytes) -> Extraction:
    from pptx import Presentation  # noqa: PLC0415
    from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER  # noqa: PLC0415
    from pptx.oxml.shapes.groupshape import CT_GroupShape  # noqa: PLC0415
    from pptx.shapes.shapetree import SlideShapeFactory  # noqa: PLC0415

    SHAPE_TAGS = set(CT_GroupShape._shape_tags)

    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise BurrowlError("UNREADABLE", f"PPTX 打不开：{exc}") from exc
    width, height = prs.slide_width or 1, prs.slide_height or 1
    units, contents, images = [], [], {}
    image_no = 0

    def box(shape) -> list[float] | None:
        if None in (shape.left, shape.top, shape.width, shape.height):
            return None
        return [round(shape.left / width, 4), round(shape.top / height, 4),
                round(shape.width / width, 4), round(shape.height / height, 4)]

    def walk(container, parent):
        """形状树里的形状，按文档顺序。带公式的形状被 PowerPoint 包在 mc:AlternateContent 里，
        python-pptx 不认，这里取 Choice 里的形状（设计稿 03 D-20）。"""
        for elm in container:
            tag = elm.tag if isinstance(elm.tag, str) else ""
            if tag == f"{{{MC_NS}}}AlternateContent":
                yield from walk(_choice(elm), parent)
            elif tag in SHAPE_TAGS:
                shape = SlideShapeFactory(elm, parent)
                if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                    yield from walk(elm.iterchildren(), parent)
                else:
                    yield shape

    for n, slide in enumerate(prs.slides, 1):
        unit = f"p{n}"
        units.append({"unit": unit, "label": f"第 {n} 页", "kind": "slide", "page": n})
        blocks: list[dict] = []
        for shape in walk(slide.shapes._spTree.iterchildren(), slide.shapes):
            b = box(shape)
            kind = None
            if shape.is_placeholder:
                try:
                    kind = shape.placeholder_format.type
                except ValueError:
                    kind = None
            if getattr(shape, "has_table", False) and shape.has_table:
                rows = [[_pptx_cell_text(cell) for cell in row.cells] for row in shape.table.rows]
                blocks.append({"type": "table", "rows": rows, "box": b})
            elif getattr(shape, "has_chart", False) and shape.has_chart:
                chart = shape.chart
                title = chart.chart_title.text_frame.text if chart.has_title else ""
                blocks.append({"type": "chart", "text": f"图表：{title}" if title else "图表", "box": b})
            elif shape.shape_type == MSO_SHAPE_TYPE.MEDIA:
                blocks.append({"type": "media", "alt": shape.name, "box": b,
                               "note": "嵌入的音视频，请打开原件播放"})
            elif _has_image(shape):
                image_no += 1
                blob, ext = shape.image.blob, shape.image.ext
                sha = sha256_bytes(blob)
                images[sha] = blob
                sub = f"img{image_no}"
                units.append({"unit": sub, "label": f"第 {n} 页的图片 {image_no}", "kind": "image", "parent": unit})
                blocks.append({"type": "image", "sha256": sha, "mime": _image_mime(ext), "unit": sub, "box": b,
                               "alt": (shape.name if not shape.name.lower().startswith(("picture", "图片")) else "")})
            elif shape.has_text_frame:
                is_title = kind in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE)
                blocks.extend(_pptx_text_blocks(shape.text_frame, "title" if is_title else "text", b))
        # 阅读顺序：标题在前，其余按从上到下、从左到右
        blocks.sort(key=lambda blk: (blk["type"] != "title", *(blk["box"][1::-1] if blk.get("box") else (9, 9))))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text if slide.notes_slide.notes_text_frame else ""
            if notes.strip():
                blocks.append({"type": "notes", "text": notes})
        text = text_of(blocks)
        contents.append(Content(unit, "text" if text.strip() else "empty", text, blocks, {"page": n}))
    import pptx  # noqa: PLC0415
    manifest = {"format": "pptx", "units": units, "pages": len(prs.slides),
                "aspect": round(width / height, 4)}
    return Extraction(manifest, contents, images, method=f"python-pptx {pptx.__version__}")


def _has_image(shape) -> bool:
    try:
        return shape.image is not None
    except (AttributeError, ValueError, KeyError):
        return False


# ---------- Office 公式（设计稿 03 D-20） ----------
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
A14_M = "{http://schemas.microsoft.com/office/drawing/2010/main}m"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# 段落里这些容器的内容照常显示（修订插入、内容控件、智能标记、简单域、超链接）；删除的修订不算
_W_CONTAINERS = {f"{_W}{t}" for t in ("hyperlink", "ins", "moveTo", "smartTag", "fldSimple", "customXml", "dir",
                                      "bdo")}


def _choice(el):
    """mc:AlternateContent 取第一个 Choice（Office 把带公式的形状这样包起来，Fallback 是同一内容的图片）。"""
    choice = el.find(f"{{{MC_NS}}}Choice")
    return list(choice) if choice is not None else []


def _math_piece(el) -> tuple | None:
    """m:oMath → ("math", LaTeX, 纯文字)；m:oMathPara → ("display", [(LaTeX, 纯文字)…])；其他返回 None。"""
    if omml.is_math(el, "oMath"):
        return ("math", omml.to_latex(el), omml.plain_text(el))
    if omml.is_math(el, "oMathPara"):
        return ("display", omml.display_parts(el))
    return None


def _docx_pieces(children) -> list[tuple]:
    """Word 段落的内容（传入段落的子元素），按文档顺序：("text", 文字) / ("math", …) / ("display", …)。
    w:r 的文字沿用 python-docx 的 `CT_R.text`，没有公式和修订的段落与原来的抽取逐字一致。"""
    out: list[tuple] = []
    for child in children:
        tag = child.tag if isinstance(child.tag, str) else ""
        if tag == f"{_W}r":
            out.append(("text", child.text))
        elif tag in _W_CONTAINERS:
            out.extend(_docx_pieces(child.iterchildren()))
        elif tag == f"{_W}sdt":
            content = child.find(f"{_W}sdtContent")
            if content is not None:
                out.extend(_docx_pieces(content.iterchildren()))
        elif tag == f"{{{MC_NS}}}AlternateContent":
            out.extend(_docx_pieces(_choice(child)))
        else:
            piece = _math_piece(child)
            if piece:
                out.append(piece)
    return out


def _pieces_text(pieces: list[tuple]) -> str:
    return "".join(p[1] if p[0] == "text" else p[2] if p[0] == "math" else
                   " ".join(t for _, t in p[1]) for p in pieces)


def _inline_math(pieces: list[tuple]) -> dict | None:
    """夹着行内公式的段落：记下文字与公式的序列（LaTeX），显示时用 KaTeX；段落文字仍是抽取文字（设计稿 05 D-12）。"""
    if not any(p[0] == "math" for p in pieces):
        return None
    runs: list[dict] = []
    for p in pieces:
        if p[0] == "text" and p[1]:
            if runs and runs[-1]["t"] == "text":
                runs[-1]["v"] += p[1]
            else:
                runs.append({"t": "text", "v": p[1]})
        elif p[0] == "math":
            runs.append({"t": "math", "v": p[1]} if p[1] else {"t": "text", "v": p[2]})
    return {"runs": runs, "source": omml.OMML_METHOD}


def _split_display(pieces: list[tuple]) -> list[tuple[str, list]]:
    """按行间公式把段落切开：[("para", pieces) | ("formula", parts)]，行间公式自成一块。"""
    out: list[tuple[str, list]] = []
    current: list[tuple] = []
    for p in pieces:
        if p[0] == "display":
            if _pieces_text(current).strip():
                out.append(("para", current))
            current = []
            out.append(("formula", p[1]))
        else:
            current.append(p)
    if _pieces_text(current).strip():
        out.append(("para", current))
    return out


_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_A_CONTENT = {f"{_A}r", f"{_A}br", f"{_A}fld"}  # 与 python-pptx 的段落文字一致（a:br 记为 \v）


def _pptx_pieces(children) -> list[tuple]:
    """PPT 段落（a:p）的内容：文字沿用 python-pptx 的写法；a14:m 里是 Office 公式。"""
    out: list[tuple] = []
    for child in children:
        tag = child.tag if isinstance(child.tag, str) else ""
        if tag in _A_CONTENT:
            out.append(("text", child.text))
        elif tag == A14_M:
            for m in child.iterchildren():
                piece = _math_piece(m)
                if piece:
                    out.append(piece)
        elif tag == f"{{{MC_NS}}}AlternateContent":
            out.extend(_pptx_pieces(_choice(child)))
    return out


def _pptx_text_blocks(frame, kind: str, box) -> list[dict]:
    """一个文本框的块：普通段落合成一个 text / title 块（与原来一致）；只有行间公式的段落自成 formula 块。"""
    blocks: list[dict] = []
    paragraphs: list[dict] = []

    def flush():
        if paragraphs:
            blocks.append({"type": kind, "paragraphs": list(paragraphs), "box": box})
            paragraphs.clear()

    for p in frame.paragraphs:
        for part_kind, part in _split_display(_pptx_pieces(p._p.iterchildren())):
            if part_kind == "formula":
                flush()
                blocks.append(omml.formula_block(part, box=box))
                continue
            para = {"text": _pieces_text(part), "level": p.level}
            inline = _inline_math(part)
            if inline:
                para["inline_math"] = inline
            paragraphs.append(para)
    flush()
    return blocks


def _pptx_cell_text(cell) -> str:
    """PPT 表格单元格：有公式时把公式的纯文字放回原处，没有时与 python-pptx 的 cell.text 一致。"""
    if next(cell._tc.iter(A14_M), None) is None:
        return cell.text
    return "\n".join(_pieces_text(_pptx_pieces(p._p.iterchildren())) for p in cell.text_frame.paragraphs)


def _docx_cell_text(cell) -> str:
    """表格单元格的文字：有公式时把公式的纯文字放回原处，没有时与 python-docx 的 cell.text 一致。"""
    if next(cell._tc.iter(omml._m("oMath")), None) is None:
        return cell.text
    return "\n".join(_pieces_text(_docx_pieces(p._p.iterchildren())) for p in cell.paragraphs)


# ---------- DOCX ----------
def extract_docx(data: bytes) -> Extraction:
    import docx  # noqa: PLC0415
    from docx.oxml.ns import qn  # noqa: PLC0415
    from docx.table import Table  # noqa: PLC0415
    from docx.text.paragraph import Paragraph  # noqa: PLC0415

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise BurrowlError("UNREADABLE", f"DOCX 打不开：{exc}") from exc
    blocks: list[dict] = []
    units = [{"unit": "doc", "label": "正文", "kind": "document"}]
    images: dict[str, bytes] = {}
    image_no = 0
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, document)
            style = (p.style.name if p.style is not None else "") or ""
            ppr = child.find(qn("w:pPr"))
            num = ppr.find(qn("w:numPr")) if ppr is not None else None
            # 行间公式（m:oMathPara）自成 formula 块；行内公式（m:oMath）的纯文字留在段落里，LaTeX 记在 inline_math
            for kind, part in _split_display(_docx_pieces(child.iterchildren())):
                if kind == "formula":
                    blocks.append(omml.formula_block(part))
                    continue
                text = _pieces_text(part)
                heading = re.match(r"^(?:Heading|标题)\s*(\d)$", style)
                if heading or style == "Title":
                    blk = {"type": "heading", "level": int(heading.group(1)) if heading else 1, "text": text}
                elif num is not None or style.startswith("List"):
                    ilvl = num.find(qn("w:ilvl")) if num is not None else None
                    level = int(ilvl.get(qn("w:val"))) if ilvl is not None else 0
                    blk = {"type": "list", "level": level, "text": text, "ordered": "Number" in style}
                else:
                    runs = [r for r in p.runs if r.text.strip()]
                    blk = {"type": "paragraph", "text": text}
                    if runs and all(r.bold for r in runs):
                        blk["bold"] = True
                    if runs and all(r.italic for r in runs):
                        blk["italic"] = True
                inline = _inline_math(part)
                if inline:
                    blk.update(math=True, inline_math=inline)
                blocks.append(blk)
            for blip in child.iter(qn("a:blip")):
                rid = blip.get(qn("r:embed"))
                part = document.part.related_parts.get(rid) if rid else None
                if part is None:
                    continue
                image_no += 1
                sha = sha256_bytes(part.blob)
                images[sha] = part.blob
                sub = f"img{image_no}"
                ext = Path(str(part.partname)).suffix
                units.append({"unit": sub, "label": f"图片 {image_no}", "kind": "image", "parent": "doc"})
                blocks.append({"type": "image", "sha256": sha, "mime": _image_mime(ext), "unit": sub})
        elif tag == "tbl":
            table = Table(child, document)
            rows = [[_docx_cell_text(cell) for cell in row.cells] for row in table.rows]
            blocks.append({"type": "table", "rows": rows})
    text = text_of(blocks)
    return Extraction({"format": "docx", "units": units}, [Content("doc", "text" if text.strip() else "empty",
                                                                   text, blocks)],
                      images, method=f"python-docx {getattr(docx, '__version__', '')}".strip())


# ---------- Excel（设计稿 03 D-11）：每个工作表一个单元，按空行分开的表格区域是块 ----------
XLSX_BLOCK_ROWS = 50  # 一个块最多的行数：大表按行切开，引用能落到具体的几十行
XLSX_MAX_CELLS = 200_000  # 一个工作表最多抽取的单元格数（超出的行不抽取，单元的 meta 记下截断）


def _cell_text(value) -> str:
    import datetime  # noqa: PLC0415

    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return f"{value:.15g}"
    if isinstance(value, datetime.datetime):
        return value.isoformat(sep=" ", timespec="seconds").removesuffix(" 00:00:00")
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    return str(value).replace("\r\n", "\n").strip()


def col_name(n: int) -> str:
    """1 → A，27 → AA。"""
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def sheet_blocks(rows: list[tuple[int, list[str]]]) -> list[dict]:
    """(行号, 单元格文字) → 表格块：整行空白处分开区域，区域按 XLSX_BLOCK_ROWS 行切开；range 如 A1:F20。"""
    regions: list[list[tuple[int, list[str]]]] = []
    for r_idx, cells in rows:
        if regions and r_idx == regions[-1][-1][0] + 1:
            regions[-1].append((r_idx, cells))
        else:
            regions.append([(r_idx, cells)])
    blocks: list[dict] = []
    for region in regions:
        cols = [i for _, cells in region for i, c in enumerate(cells) if c]
        c0, c1 = min(cols), max(cols)
        for k in range(0, len(region), XLSX_BLOCK_ROWS):
            part = region[k:k + XLSX_BLOCK_ROWS]
            blocks.append({"type": "table", "rows": [cells[c0:c1 + 1] for _, cells in part],
                           "range": f"{col_name(c0 + 1)}{part[0][0]}:{col_name(c1 + 1)}{part[-1][0]}"})
    return blocks


def extract_xlsx(data: bytes) -> Extraction:
    """Excel 工作簿：每个工作表一个单元（s1、s2…），按整行空白分开的区域是表格块，大区域按行切开。
    块的 range 是单元格范围（如 A1:F20），前端表格阅读器据此标出被引用的区域。公式取文件里保存的计算结果。"""
    import openpyxl  # noqa: PLC0415 - 只在抽取 Excel 时加载

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=False)
    except Exception as exc:  # noqa: BLE001 - 损坏、加密或不是 xlsx
        raise BurrowlError("UNREADABLE", f"Excel 打不开：{exc}") from exc
    units, contents = [], []
    for n, ws in enumerate(wb.worksheets, 1):
        unit = f"s{n}"
        hidden = ws.sheet_state != "visible"
        units.append({"unit": unit, "label": f"工作表 {ws.title}" + ("（隐藏）" if hidden else ""), "kind": "sheet",
                      "sheet": ws.title})
        max_row, max_col = ws.max_row or 0, ws.max_column or 0
        limit = max(1, XLSX_MAX_CELLS // max(max_col, 1))
        truncated = max_row > limit
        rows: list[tuple[int, list[str]]] = []
        for r_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=min(max_row, limit), values_only=True), 1):
            cells = [_cell_text(v) for v in row]
            if any(cells):
                rows.append((r_idx, cells))
        blocks = sheet_blocks(rows)
        meta = {"rows": max_row, "cols": max_col, "merged": [str(m) for m in ws.merged_cells.ranges][:500],
                **({"truncated_at_row": limit} if truncated else {})}
        text = text_of(blocks)
        contents.append(Content(unit, "text" if text.strip() else "empty", text, blocks, meta))
    import openpyxl as _o  # noqa: PLC0415
    return Extraction({"format": "xlsx", "units": units}, contents, method=f"openpyxl {_o.__version__}")


EXTRACTORS = {"pdf": extract_pdf, "pptx": extract_pptx, "docx": extract_docx, "xlsx": extract_xlsx}


def media_manifest(fmt: str) -> dict:
    """图片与音视频默认不抽取，只登记单元（D-11）。"""
    if fmt == "image":
        return {"format": "image", "units": [{"unit": "img", "label": "图片", "kind": "image"}]}
    return {"format": "av", "units": [{"unit": "av", "label": "音视频", "kind": "media"}]}


# ---------- 页面快照（D-17）：用本机的 Office 或 LibreOffice 把 PPTX / DOCX 转成 PDF ----------
def libreoffice_path() -> str | None:
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base and (Path(base) / "LibreOffice/program/soffice.exe").exists():
            return str(Path(base) / "LibreOffice/program/soffice.exe")
    return None


def office_available(app: str) -> bool:
    """app：PowerPoint、Word 或 Excel。按 COM 登记判断，不启动 Office。"""
    if os.name != "nt":
        return False
    import winreg  # noqa: PLC0415
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"{app}.Application"))
        return True
    except OSError:
        return False


def converters() -> dict:
    return {"office_powerpoint": office_available("PowerPoint"), "office_word": office_available("Word"),
            "office_excel": office_available("Excel"), "libreoffice": libreoffice_path()}


# 关掉 Office 前先看有没有用户自己打开的文档：New-Object 可能连到用户正在用的那个 PowerPoint，不能把它关掉
_PS_POWERPOINT = r"""
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject PowerPoint.Application
try {
  $p = $app.Presentations.Open($env:BURROWL_IN, -1, 0, 0)
  $p.SaveAs($env:BURROWL_OUT, 32)
  $p.Close()
} finally {
  if ($app.Presentations.Count -eq 0) { $app.Quit() }
}
"""
_PS_EXCEL = r"""
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject Excel.Application
$app.Visible = $false
$app.DisplayAlerts = $false
try {
  $w = $app.Workbooks.Open($env:BURROWL_IN, 0, $true)
  $w.ExportAsFixedFormat(0, $env:BURROWL_OUT)
  $w.Close($false)
} finally {
  if ($app.Workbooks.Count -eq 0) { $app.Quit() }
}
"""
_PS_WORD = r"""
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject Word.Application
$app.Visible = $false
$app.DisplayAlerts = 0
try {
  $d = $app.Documents.Open($env:BURROWL_IN, $false, $true, $false)
  $d.ExportAsFixedFormat($env:BURROWL_OUT, 17)
  $d.Close(0)
} finally {
  if ($app.Documents.Count -eq 0) { $app.Quit() }
}
"""


def convert_to_pdf(data: bytes, suffix: str, preference: str = "auto", timeout: int = 180) -> tuple[bytes, str]:
    """返回 (PDF 字节, 转换器名称)。preference：auto（Office 优先）/ office / libreoffice。"""
    app = {".pptx": "PowerPoint", ".docx": "Word", ".xlsx": "Excel", ".xlsm": "Excel"}.get(suffix)
    if app is None:
        raise BurrowlError("INVALID_ARGUMENT", "只有 PPTX、DOCX 和 Excel 需要页面快照", {"suffix": suffix})
    order = {"auto": ["office", "libreoffice"], "office": ["office"],
             "libreoffice": ["libreoffice"]}.get(preference, [])
    tried = []
    with tempfile.TemporaryDirectory(prefix="burrowl-snap-") as tmp:
        src = Path(tmp) / f"source{suffix}"
        src.write_bytes(data)
        out = Path(tmp) / "snapshot.pdf"
        for name in order:
            try:
                if name == "office" and office_available(app):
                    script = {"PowerPoint": _PS_POWERPOINT, "Word": _PS_WORD, "Excel": _PS_EXCEL}[app]
                    env = {**os.environ, "BURROWL_IN": str(src), "BURROWL_OUT": str(out)}
                    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env,
                                   check=True, capture_output=True, timeout=timeout,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    if out.exists():
                        return out.read_bytes(), f"Microsoft {app}"
                elif name == "libreoffice" and libreoffice_path():
                    subprocess.run([libreoffice_path(), "--headless", "--convert-to", "pdf", "--outdir", tmp, str(src)],
                                   check=True, capture_output=True, timeout=timeout,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    produced = Path(tmp) / "source.pdf"
                    if produced.exists():
                        return produced.read_bytes(), "LibreOffice"
                else:
                    tried.append(f"{name}：本机没有")
                    continue
                tried.append(f"{name}：没有生成 PDF")
            except subprocess.TimeoutExpired:
                tried.append(f"{name}：超过 {timeout} 秒")
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()
                tried.append(f"{name}：{detail[-1] if detail else exc.returncode}")
    raise BurrowlError("SNAPSHOT_UNAVAILABLE", "没有可用的转换器生成页面快照", {"tried": tried})
