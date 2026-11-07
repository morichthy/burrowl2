"""各格式的抽取器（设计稿 01 D-11、D-16、D-17）：输入原件字节，输出单元清单、每个单元的文本与版式块。

纯函数，不读写账本。单元（unit）是抽取与引用的基本单位：
    doc        文本文件、DOCX 的正文（单一文档流）
    p<N>       PDF 的第 N 页、PPTX 的第 N 页（从 1 开始）
    img        独立的图片原件
    img<K>     PPTX / DOCX 里嵌入的第 K 张图片（默认不抽取）
    av         音视频原件（转写按时间戳分块）
版式块（block）保存"哪句在哪"：标题、段落、列表、表格、图片、媒体、备注、字幕块。
PPTX 的块带 box = [x, y, 宽, 高]，取值是占整页宽高的比例（0–1），用于没有页面快照时按位置重建。
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

# 抽取器的版本：改变抽取结果的修改都要加 1，重建时据此判断"方法变了"
EXTRACTOR_VERSION = 1

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".log", ".py", ".yaml", ".yml",
                 ".xml", ".html", ".htm", ".ini", ".cfg", ".toml", ".sql", ".rst", ".tex"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
AV_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v", ".mp3", ".wav", ".m4a", ".ogg", ".flac"}
FORMAT_OF_SUFFIX = {**{s: "text" for s in TEXT_SUFFIXES}, **{s: "image" for s in IMAGE_SUFFIXES},
                    **{s: "av" for s in AV_SUFFIXES}, ".pdf": "pdf", ".pptx": "pptx", ".docx": "docx"}

MEDIA_TYPES = {
    ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp", ".tif": "image/tiff", ".tiff": "image/tiff",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo", ".m4v": "video/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".ogg": "audio/ogg", ".flac": "audio/flac",
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
_CJK = re.compile(r"[　-鿿＀-￯]")


def _join_lines(lines: list[str]) -> str:
    out = ""
    for line in lines:
        if not out:
            out = line
        elif out.endswith("-") and line[:1].islower():
            out = out[:-1] + line  # 行尾连字符断开的英文单词
        elif _CJK.match(out[-1]) and _CJK.match(line[0]):
            out += line
        else:
            out += " " + line
    return out


def pdf_paragraphs(raw: str) -> list[str]:
    """把 PDF 文字层的逐行文本合成段落：空行或明显短于常见行宽的行视为段落结束。

    pdfium 用 U+FFFE 标出行尾的软连字符（单词被断到下一行），去掉即可接上。
    """
    raw = raw.replace("￾", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in raw.split("\n")]
    lengths = sorted(len(line) for line in lines if line)
    typical = lengths[int(len(lengths) * 0.75)] if lengths else 0
    paras, current = [], []
    for line in lines:
        if not line:
            if current:
                paras.append(_join_lines(current))
                current = []
            continue
        current.append(line)
        if len(line) < 0.7 * typical:
            paras.append(_join_lines(current))
            current = []
    if current:
        paras.append(_join_lines(current))
    return [p for p in paras if p.strip()]


def extract_pdf(data: bytes) -> Extraction:
    import pypdfium2 as pdfium  # noqa: PLC0415 - 只在抽取 PDF 时加载
    import pypdfium2.raw as raw  # noqa: PLC0415

    try:
        doc = pdfium.PdfDocument(data)
    except Exception as exc:  # noqa: BLE001 - 损坏或加密的 PDF
        raise BurrowlError("UNREADABLE", f"PDF 打不开：{exc}") from exc
    units, contents = [], []
    try:
        for i in range(len(doc)):
            page = doc[i]
            n = i + 1
            width, height = page.get_size()
            units.append({"unit": f"p{n}", "label": f"第 {n} 页", "kind": "page", "page": n})
            text = page.get_textpage().get_text_range()
            meta = {"page": n, "size": [round(width, 1), round(height, 1)]}
            if len(text.strip()) < 20:  # 几乎没有文字层：图片页（扫描件）或空白页
                has_image = any(True for _ in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE], max_depth=2))
                contents.append(Content(f"p{n}", "image" if has_image else "empty", meta=meta))
                continue
            blocks = [{"type": "paragraph", "text": p} for p in pdf_paragraphs(text)]
            contents.append(Content(f"p{n}", "text", text_of(blocks), blocks, meta))
    finally:
        doc.close()
    return Extraction({"format": "pdf", "units": units, "pages": len(units)}, contents,
                      method=f"pypdfium2 {pdfium.version.PYPDFIUM_INFO}")


def pdf_page_count(data: bytes) -> int:
    import pypdfium2 as pdfium  # noqa: PLC0415
    doc = pdfium.PdfDocument(data)
    try:
        return len(doc)
    finally:
        doc.close()


def render_pdf_page(data: bytes, page: int, scale: float = 1.5) -> bytes:
    """把 PDF 第 page 页（从 1 开始）渲染成 PNG。scale 1 ≈ 72 dpi。"""
    import pypdfium2 as pdfium  # noqa: PLC0415
    doc = pdfium.PdfDocument(data)
    try:
        if not 1 <= page <= len(doc):
            raise BurrowlError("NOT_FOUND", "页码超出范围", {"page": page, "pages": len(doc)})
        image = doc[page - 1].render(scale=scale).to_pil()
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

    def walk(shapes):
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                yield from walk(shape.shapes)
            else:
                yield shape

    for n, slide in enumerate(prs.slides, 1):
        unit = f"p{n}"
        units.append({"unit": unit, "label": f"第 {n} 页", "kind": "slide", "page": n})
        blocks: list[dict] = []
        for shape in walk(slide.shapes):
            b = box(shape)
            kind = None
            if shape.is_placeholder:
                try:
                    kind = shape.placeholder_format.type
                except ValueError:
                    kind = None
            if getattr(shape, "has_table", False) and shape.has_table:
                rows = [[cell.text for cell in row.cells] for row in shape.table.rows]
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
            elif shape.has_text_frame and shape.text_frame.text.strip():
                paragraphs = [{"text": p.text, "level": p.level} for p in shape.text_frame.paragraphs if p.text.strip()]
                is_title = kind in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE)
                blocks.append({"type": "title" if is_title else "text", "paragraphs": paragraphs, "box": b})
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
            text = p.text
            ppr = child.find(qn("w:pPr"))
            num = ppr.find(qn("w:numPr")) if ppr is not None else None
            if text.strip():
                heading = re.match(r"^(?:Heading|标题)\s*(\d)$", style)
                if heading or style == "Title":
                    blocks.append({"type": "heading", "level": int(heading.group(1)) if heading else 1, "text": text})
                elif num is not None or style.startswith("List"):
                    ilvl = num.find(qn("w:ilvl")) if num is not None else None
                    level = int(ilvl.get(qn("w:val"))) if ilvl is not None else 0
                    blocks.append({"type": "list", "level": level, "text": text,
                                   "ordered": "Number" in style})
                else:
                    runs = [r for r in p.runs if r.text.strip()]
                    blk = {"type": "paragraph", "text": text}
                    if runs and all(r.bold for r in runs):
                        blk["bold"] = True
                    if runs and all(r.italic for r in runs):
                        blk["italic"] = True
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
            rows = [[cell.text for cell in row.cells] for row in table.rows]
            blocks.append({"type": "table", "rows": rows})
    text = text_of(blocks)
    return Extraction({"format": "docx", "units": units}, [Content("doc", "text" if text.strip() else "empty",
                                                                   text, blocks)],
                      images, method=f"python-docx {getattr(docx, '__version__', '')}".strip())


EXTRACTORS = {"pdf": extract_pdf, "pptx": extract_pptx, "docx": extract_docx}


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
    """app：PowerPoint 或 Word。按 COM 登记判断，不启动 Office。"""
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
            "libreoffice": libreoffice_path()}


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
    app = {".pptx": "PowerPoint", ".docx": "Word"}.get(suffix)
    if app is None:
        raise BurrowlError("INVALID_ARGUMENT", "只有 PPTX 和 DOCX 需要页面快照", {"suffix": suffix})
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
                    script = _PS_POWERPOINT if app == "PowerPoint" else _PS_WORD
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
