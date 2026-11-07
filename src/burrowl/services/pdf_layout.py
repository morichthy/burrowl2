"""PDF 按位置分段（设计稿 02 D-03、D-04）：用 pdfium 的字符位置把一页的文字排成带位置的块。

纯函数，不读写账本，不加新依赖（只用 pypdfium2）。步骤：
1. 取字符：每个字符的位置、字号；pdfium 生成的换行把字符切成"片段"（一段连续的同行文字）；
2. 成行：纵向重叠、横向相邻的片段并成一行；字号明显更小、与某行纵向重叠的片段（上下标）并入那一行，
   不再单独成段；
3. 分栏：左右两栏都有足够多的行时，按"跨栏的行切开的横带内，先左栏后右栏"排阅读顺序；
4. 成块：行距明显变大、字号变化、首行缩进、上一行明显短于栏宽时断开；字号明显大于正文的短块标为标题；
5. 页眉页脚：在多页同一位置重复出现的行、页边上只有数字的行标为 furniture（不进索引，显示上仍在原件里）；
6. 公式（设计稿 03 D-15）：数学字体（CMMI、CMSY、Cambria Math…）或数学符号占多数的行是公式行，相邻的公式行
   （分式的分子分母、多行对齐）与右侧的公式编号合成一个 formula 块；夹着行内公式的段落标 math。

块的位置 box = [x, y, 宽, 高]，取值是占整页（裁切框）宽高的比例，原点在左上角，已按页面旋转换算，
与 PPTX 块的 box 同一格式，前端在原样显示的页面上据此画框。
"""
import re
from dataclasses import dataclass, field

_CJK = re.compile(r"[　-鿿＀-￯]")
_DIGITS = re.compile(r"\d+")
SOFT_HYPHEN = "￾"  # pdfium 用它标出行尾被断开的单词


@dataclass
class Run:
    """一个片段：pdfium 一次连续输出的同行文字。坐标是 PDF 页面坐标（原点左下）。"""
    text: str
    x0: float
    b: float
    r: float
    t: float
    size: float
    bold: bool = False
    math: int = 0  # 数学字体或数学符号的字符数
    chars: int = 0  # 可见字符数

    @property
    def h(self) -> float:
        return max(self.t - self.b, 0.1)

    @property
    def cy(self) -> float:
        return (self.t + self.b) / 2


@dataclass
class Line:
    runs: list[Run] = field(default_factory=list)
    furniture: bool = False

    @property
    def x0(self) -> float:
        return min(r.x0 for r in self.runs)

    @property
    def r(self) -> float:
        return max(r.r for r in self.runs)

    @property
    def b(self) -> float:
        return min(r.b for r in self.main_runs)

    @property
    def t(self) -> float:
        return max(r.t for r in self.main_runs)

    @property
    def main_runs(self) -> list[Run]:
        big = max(r.size for r in self.runs)
        return [r for r in self.runs if r.size >= 0.8 * big] or self.runs

    @property
    def size(self) -> float:
        return max(r.size for r in self.runs)

    @property
    def bold(self) -> bool:
        main = self.main_runs
        return sum(len(r.text.strip()) for r in main if r.bold) * 2 > sum(len(r.text.strip()) for r in main)

    @property
    def math_ratio(self) -> float:
        n = sum(r.chars for r in self.runs)
        return sum(r.math for r in self.runs) / n if n else 0.0

    @property
    def text(self) -> str:
        out = ""
        prev = None
        for run in sorted(self.runs, key=lambda r: r.x0):
            piece = run.text
            if prev is not None and out and not out.endswith(" ") and not piece.startswith(" "):
                gap = run.x0 - prev.r
                if gap > 0.2 * min(run.size, prev.size) and not (_CJK.match(out[-1]) and _CJK.match(piece[:1] or "a")):
                    out += " "
            out += piece
            prev = run
        return re.sub(r"[ \t]+", " ", out).strip()

    def full_box(self) -> tuple[float, float, float, float]:
        return (min(r.x0 for r in self.runs), min(r.b for r in self.runs),
                max(r.r for r in self.runs), max(r.t for r in self.runs))


_BOLD_NAME = re.compile(rb"bold|black|heavy|semibold|demi|medi|-bd|\.b$", re.I)


# 数学字体（TeX 的 CM / AMS 字体、Word 的 Cambria Math、STIX、Latin Modern Math、Symbol 等）
_MATH_FONT = re.compile(rb"CMMI|CMSY|CMEX|CMBSY|MSAM|MSBM|EUFM|EUSM|EUEX|RSFS|LMMath|"
                        rb"Math|STIX|Symbol|MTSY|MTMI|MTEX|txsy|txmi|txex|pxsy|pxmi|esint|wasy|stmary", re.I)


def is_math_char(ch: str) -> bool:
    """数学符号：希腊字母、运算符、箭头、数学字母数字（𝑥 𝛼 …）、上下标数字。"""
    if not ch:
        return False
    o = ord(ch)
    return (0x0391 <= o <= 0x03C9 or 0x2190 <= o <= 0x22FF or 0x27C0 <= o <= 0x27EF or 0x2980 <= o <= 0x2AFF
            or 0x1D400 <= o <= 0x1D7FF or 0x2070 <= o <= 0x209F or ch in "√∞∂∇±×÷·′″‖")


def _font(raw, textpage, i: int) -> tuple[bool, bool]:
    """(是否粗体, 是否数学字体)。"""
    import ctypes  # noqa: PLC0415

    buf = ctypes.create_string_buffer(128)
    flags = ctypes.c_int()
    raw.FPDFText_GetFontInfo(textpage.raw, i, buf, 128, ctypes.byref(flags))
    bold = (raw.FPDFText_GetFontWeight(textpage.raw, i) >= 600 or bool(_BOLD_NAME.search(buf.value))
            or bool(flags.value & (1 << 18)))  # ForceBold
    return bold, bool(_MATH_FONT.search(buf.value))


_NUMBERED = re.compile(r"^(\d+(?:\.\d+){0,3}|[A-Z]|[IVX]+|第[一二三四五六七八九十\d]+[章节部分])[.、\s]\s*\S")


def heading_level(text: str, lines: int, size: float, body: float, bold: bool) -> int | None:
    """标题判断：字号明显大于正文；或与正文同号、单独一行的粗体 / 全大写 / 带编号的短行。"""
    if lines <= 3 and size >= 1.15 * body and len(text) <= 200:
        return 1 if size >= 1.5 * body else 2
    if (lines > (2 if bold else 1) or len(text) > 80 * lines or len(text.split()) > 12 * lines
            or text.endswith((".", "。", ",", "，", ";", "；"))):
        return None
    letters = [c for c in text if c.isalpha() and c.isascii()]
    upper = len(letters) >= 4 and all(c.isupper() for c in letters)
    numbered = bool(_NUMBERED.match(text)) and len(text) <= 60 and not re.search(r"\s\d+$", text)  # 目录行以页码结尾
    if bold or upper or numbered:
        m = re.match(r"^(\d+(?:\.\d+)*)", text)
        return 2 + min(m.group(1).count("."), 2) if m else 3
    return None


def page_runs(page) -> tuple[list[Run], list[Run]]:
    """一页的全部片段：(横排片段, 旋转的片段)。跳过不可见的生成字符；生成的换行切开片段。

    旋转的文字（例如 arXiv 页边竖排的编号）不参与成行与分栏，单独作为 furniture。
    """
    import math  # noqa: PLC0415

    import pypdfium2.raw as raw  # noqa: PLC0415 - 只在抽取 PDF 时加载

    textpage = page.get_textpage()
    try:
        n = textpage.count_chars()
        runs: list[Run] = []
        rotated: list[Run] = []
        chars: list[tuple[str, tuple | None, float, bool, bool]] = []
        rot_chars: list[tuple[str, tuple | None, float, bool, bool]] = []

        def make(buf, into):
            if not buf:
                return
            # pdfium 按 UTF-16 码元给出字符，补充平面的字符（例如数学斜体字母）要把代理对拼回去
            text = "".join(c for c, *_ in buf).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
            boxes = [b for _, b, *_ in buf if b]
            if text.strip() and boxes:
                sizes = sorted(s for _, b, s, _, _ in buf if b)
                bolds = [w for _, b, _, w, _ in buf if b]
                visible = [(c, m) for c, b, _, _, m in buf if b]
                math = sum(1 for c, m in visible if m or is_math_char(c))
                into.append(Run(text, min(b[0] for b in boxes), min(b[1] for b in boxes),
                                max(b[2] for b in boxes), max(b[3] for b in boxes), sizes[len(sizes) // 2],
                                sum(bolds) * 2 > len(bolds), math, len(visible)))
            buf.clear()

        def flush():
            make(chars, runs)

        for i in range(n):
            code = raw.FPDFText_GetUnicode(textpage.raw, i)
            ch = chr(code) if code else ""
            generated = raw.FPDFText_IsGenerated(textpage.raw, i) == 1
            if ch in ("\r", "\n"):
                flush()
                continue
            if generated:  # pdfium 补上的空格：保留空格，不参与位置
                if ch == " " and chars:
                    chars.append((" ", None, 0.0, False, False))
                continue
            if not ch:
                continue
            if ch in ("\x02", "￾"):  # 行尾断词符
                ch = SOFT_HYPHEN
            elif ord(ch) < 0x20 and ch != "\t":
                ch = "�"  # 字体没有给出对应字符的字形（例如公式里的 ε），标成替换符而不是丢掉
            box = None
            if not ch.isspace():
                box = textpage.get_charbox(i, loose=False)
                if box[2] - box[0] <= 0 and box[3] - box[1] <= 0:
                    box = None
            size = raw.FPDFText_GetFontSize(textpage.raw, i) if box else 0.0
            bold, math_font = _font(raw, textpage, i) if box else (False, False)
            if box:
                angle = raw.FPDFText_GetCharAngle(textpage.raw, i)
                if angle > 0 and min(abs(angle), abs(angle - math.pi), abs(angle - 2 * math.pi)) > 0.1:
                    rot_chars.append((ch, box, size, bold, math_font))
                    continue
            if box and chars:
                last = next((b for _, b, *_ in reversed(chars) if b), None)
                # 同一个片段里纵向完全错开、或横向大幅回退：pdfium 没给换行，这里切开
                if last and (box[1] > last[3] or box[3] < last[1] or box[0] < last[0] - 2 * max(size, 1)):
                    flush()
            chars.append((ch, box, size or 0.0, bold, math_font))
        flush()
        make(rot_chars, rotated)
        return runs, rotated
    finally:
        textpage.close()


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _merge_adjacent(lines: list[Line]) -> list[Line]:
    """逐个片段归行与处理顺序有关：最后把纵向重叠、横向相邻的行两两合并，直到不再变化。"""
    changed = True
    while changed:
        changed = False
        for i, a in enumerate(lines):
            for b in lines[i + 1:]:
                ov = _overlap(a.b, a.t, b.b, b.t)
                gap = max(b.x0 - a.r, a.x0 - b.r)
                if ov >= 0.5 * min(a.t - a.b, b.t - b.b) and gap < 1.5 * max(a.size, b.size):
                    a.runs.extend(b.runs)
                    lines.remove(b)
                    changed = True
                    break
            if changed:
                break
    return lines


def build_lines(runs: list[Run]) -> list[Line]:
    """片段 → 行。先把正常字号、纵向重叠、横向相邻的片段并成行，再把小字号的上下标并入相邻的行。"""
    if not runs:
        return []
    sizes = sorted(r.size for r in runs)
    body = sizes[len(sizes) // 2] or 10.0
    small = [r for r in runs if r.size < 0.8 * body or len(r.text.strip()) <= 3]
    normal = [r for r in runs if r not in small] or small
    if normal is small:
        small = []
    lines: list[Line] = []
    for run in sorted(normal, key=lambda r: (-r.t, r.x0)):
        host = None
        for line in lines:
            ov = _overlap(run.b, run.t, line.b, line.t)
            if ov >= 0.5 * min(run.h, line.t - line.b or run.h):
                gap = max(run.x0 - line.r, line.x0 - run.r)
                if gap < 1.5 * max(run.size, line.size):
                    host = line
                    break
        if host:
            host.runs.append(run)
        else:
            lines.append(Line([run]))
    lines = _merge_adjacent(lines)
    for run in small:
        best, best_d = None, None
        for line in lines:
            lb, lt = line.b, line.t
            height = lt - lb or run.h
            if not (lb - 0.6 * height <= run.cy <= lt + 0.6 * height):
                continue
            gap = max(run.x0 - line.r, line.x0 - run.r, 0.0)
            if gap > 1.5 * line.size:
                continue
            d = abs(run.cy - (lb + lt) / 2) + gap
            if best_d is None or d < best_d:
                best, best_d = line, d
        if best is not None:
            best.runs.append(run)
        else:
            lines.append(Line([run]))
    return lines


def reading_order(lines: list[Line], width: float, x0: float) -> list[tuple[str, Line]]:
    """按阅读顺序排行，返回 (栏, 行)。栏：full 跨栏 / left / right / single 单栏。"""
    mid = x0 + width / 2
    left = [ln for ln in lines if ln.r < mid + 0.02 * width and ln.x0 < mid]
    right = [ln for ln in lines if ln.x0 > mid - 0.02 * width]
    two_col = len(left) >= 5 and len(right) >= 5
    by_top = sorted(lines, key=lambda ln: (-ln.t, ln.x0))
    if not two_col:
        return [("single", ln) for ln in by_top]
    out: list[tuple[str, Line]] = []
    band_l: list[Line] = []
    band_r: list[Line] = []

    def flush():
        out.extend(("left", ln) for ln in band_l)
        out.extend(("right", ln) for ln in band_r)
        band_l.clear()
        band_r.clear()

    for ln in by_top:
        if ln.x0 < mid - 0.02 * width and ln.r > mid + 0.02 * width:
            flush()
            out.append(("full", ln))
        elif ln.x0 >= mid - 0.02 * width:
            band_r.append(ln)
        else:
            band_l.append(ln)
    flush()
    return out


def _join(lines: list[str]) -> str:
    out = ""
    for line in lines:
        if not out:
            out = line
        elif out.endswith(SOFT_HYPHEN):
            out = out[:-1] + line
        elif out.endswith("-") and line[:1].islower():
            out = out[:-1] + line  # 行尾连字符断开的英文单词
        elif _CJK.match(out[-1]) and _CJK.match(line[0]):
            out += line
        else:
            out += " " + line
    return out.replace(SOFT_HYPHEN, "")


def furniture_key(line: Line, height: float, y0: float) -> str | None:
    """页眉页脚候选：落在页面上下 9% 以内的行，数字统一后作为跨页比较的键。"""
    rel = (line.b + line.t) / 2 - y0
    if 0.09 * height < rel < 0.91 * height:
        return None
    zone = "top" if rel >= 0.91 * height else "bottom"
    return f"{zone}:{_DIGITS.sub('#', line.text.lower())}"


def to_box(left: float, bottom: float, right: float, top: float, crop: tuple, rotation: int) -> list[float]:
    """PDF 坐标的矩形 → 占页面比例的 [x, y, 宽, 高]（左上原点，按页面顺时针旋转换算）。"""
    cx0, cy0, cx1, cy1 = crop
    w, h = (cx1 - cx0) or 1, (cy1 - cy0) or 1
    x, y, bw, bh = (left - cx0) / w, (cy1 - top) / h, (right - left) / w, (top - bottom) / h
    x, y = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
    bw, bh = min(bw, 1 - x), min(bh, 1 - y)
    rot = rotation % 360
    if rot == 90:
        x, y, bw, bh = 1 - y - bh, x, bh, bw
    elif rot == 180:
        x, y = 1 - x - bw, 1 - y - bh
    elif rot == 270:
        x, y, bw, bh = y, 1 - x - bw, bh, bw
    return [round(x, 4), round(y, 4), round(bw, 4), round(bh, 4)]


FORMULA_LINE = 0.45  # 一行里数学字符占这个比例以上算公式行
MATH_PARAGRAPH = 3  # 段落里有这么多数学字符就标 math（行内公式）
_EQ_NUMBER = re.compile(r"^\(\s*[\dA-Za-z]+(?:[.\-][\dA-Za-z]+)*\s*\)$")


def is_formula_line(ln: Line) -> bool:
    words = ln.text.split()
    if (len(ln.text) > 160 or sum(len(w) >= 6 and w.isalpha() and w.isascii() for w in words) >= 3
            or len(_CJK.findall(ln.text)) >= 4):
        return False  # 长句、带多个长单词或汉字的是正文（夹着行内公式）
    return ln.math_ratio >= FORMULA_LINE and sum(r.math for r in ln.runs) >= 2


def blocks_of(ordered: list[tuple[str, Line]], crop: tuple, rotation: int) -> list[dict]:
    """行 → 块。块：heading（带 level）/ paragraph / formula / furniture，都带 box。"""
    body_sizes = sorted(ln.size for _, ln in ordered if not ln.furniture) or [10.0]
    body = body_sizes[len(body_sizes) // 2]
    extents: dict[str, tuple[float, float]] = {}
    for col, ln in ordered:
        if not ln.furniture:
            l0, r0 = extents.get(col, (ln.x0, ln.r))
            extents[col] = (min(l0, ln.x0), max(r0, ln.r))

    def centered(ln: Line, col_l: float, col_r: float) -> bool:
        width = col_r - col_l
        return (width > 0 and ln.r - ln.x0 < 0.6 * width and ln.x0 > col_l + 0.12 * width
                and ln.r < col_r - 0.08 * width)

    groups: list[tuple[str, list[Line]]] = []
    for col, ln in ordered:
        if ln.furniture:
            groups.append(("furniture", [ln]))
            continue
        if _EQ_NUMBER.match(ln.text):
            groups.append((col, [ln]))  # 公式编号单独成组，之后并回同高的公式块
            continue
        if (is_formula_line(ln) and len(groups) >= 2 and _EQ_NUMBER.match(groups[-1][1][-1].text)
                and groups[-2][0] == col and is_formula_line(groups[-2][1][-1])):
            prev = groups[-2][1][-1]
            if -1.5 * (ln.t - ln.b) <= prev.b - ln.t <= 1.6 * max(prev.t - prev.b, ln.t - ln.b):
                groups[-2][1].append(ln)  # 编号夹在分式的分子与分母之间（按顶边排序时）
                continue
        if groups and groups[-1][0] == col:
            prev = groups[-1][1][-1]
            gap = prev.b - ln.t
            leading = max(prev.t - prev.b, ln.t - ln.b)
            col_l, col_r = extents.get(col, (prev.x0, prev.r))
            if is_formula_line(prev) and is_formula_line(ln) and -1.5 * leading <= gap <= 1.6 * leading:
                groups[-1][1].append(ln)  # 相邻的公式行（分式、多行对齐）并成一个公式块
                continue
            if centered(prev, col_l, col_r) and centered(ln, col_l, col_r) and -1.5 * leading <= gap <= 1.2 * leading:
                groups[-1][1].append(ln)  # 居中的窄行（行间公式、分式的分子分母）并成一块
                continue
            same_size = abs(ln.size - prev.size) <= 0.12 * body
            indented = ln.x0 - col_l > 0.8 * body and ln.x0 - prev.x0 > 0.8 * body
            block_r = max(x.r for x in groups[-1][1])  # 用块自己的行宽：缩进排版的摘要、引文比整栏窄
            short_prev = prev.r < block_r - 3 * body and prev.text[-1:] in ".:;!?。：；！？)"
            bold_change = prev.bold != ln.bold  # 粗体标题与下面的正文同号时，靠粗细分开
            if (same_size and -0.5 * leading <= gap <= 0.9 * leading and not indented and not short_prev
                    and not bold_change
                    and len(groups[-1][1]) < 80):
                groups[-1][1].append(ln)
                continue
        groups.append((col, [ln]))
    blocks: list[dict] = []
    for col, lns in groups:
        text = _join([ln.text for ln in lns])
        if not text.strip():
            continue
        box = to_box(min(x.full_box()[0] for x in lns), min(x.full_box()[1] for x in lns),
                     max(x.full_box()[2] for x in lns), max(x.full_box()[3] for x in lns), crop, rotation)
        if col == "furniture":
            blocks.append({"type": "furniture", "text": text, "box": box})
            continue
        if all(is_formula_line(x) for x in lns):
            blocks.append({"type": "formula", "text": text, "box": box})
            continue
        level = heading_level(text, len(lns), max(x.size for x in lns), body, all(x.bold for x in lns))
        if level:
            blocks.append({"type": "heading", "level": level, "text": text, "box": box})
        elif sum(r.math for x in lns for r in x.runs) >= MATH_PARAGRAPH:
            blocks.append({"type": "paragraph", "text": text, "box": box, "math": True})
        else:
            blocks.append({"type": "paragraph", "text": text, "box": box})
    return _attach_equation_numbers(blocks)


def _union(host: dict, b: dict) -> None:
    x0, y0 = min(host["box"][0], b["box"][0]), min(host["box"][1], b["box"][1])
    x1 = max(host["box"][0] + host["box"][2], b["box"][0] + b["box"][2])
    y1 = max(host["box"][1] + host["box"][3], b["box"][1] + b["box"][3])
    host["box"] = [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]
    host["text"] = f'{host["text"]} {b["text"]}'


def _attach_equation_numbers(blocks: list[dict]) -> list[dict]:
    """公式块的整理：位置上紧挨着的公式块（一条大公式被行距、分栏规则切开）并成一块；
    公式右侧的编号 (1)、(2.3) 单独成了一块时，并回与它同高的公式块。"""
    out: list[dict] = []
    for b in blocks:
        prev = out[-1] if out else None
        if prev and prev["type"] == "formula" and b["type"] == "formula":
            gap = b["box"][1] - (prev["box"][1] + prev["box"][3])
            h_gap = max(b["box"][0] - (prev["box"][0] + prev["box"][2]), prev["box"][0] - (b["box"][0] + b["box"][2]))
            numbered = re.search(r"\(\s*\d+(?:\.\d+)*\s*\)$", prev["text"])  # 上一条公式已有编号：是另一条公式
            if -0.02 <= gap <= 0.018 and h_gap <= 0.05 and not numbered:
                _union(prev, b)
                continue
        if b["type"] == "paragraph" and _EQ_NUMBER.match(b["text"]):
            cy = b["box"][1] + b["box"][3] / 2
            host = next((f for f in reversed(out[-3:]) if f["type"] == "formula"
                         and f["box"][1] - 0.005 <= cy <= f["box"][1] + f["box"][3] + 0.005
                         and f["box"][0] < b["box"][0]), None)
            if host:
                _union(host, b)
                continue
        out.append(b)
    return out


def layout_pages(doc) -> list[dict]:
    """整份 PDF：每页返回 {lines, crop, rotation, size}；跨页标出页眉页脚后再成块。"""
    pages = []
    for i in range(len(doc)):
        page = doc[i]
        crop = tuple(page.get_bbox())  # 实际生效的裁切框（get_cropbox 在页面继承页面树的框时会退回默认值）
        rotation = page.get_rotation()
        runs, rotated = page_runs(page)
        pages.append({"lines": build_lines(runs), "crop": crop, "rotation": rotation,
                      "rotated": [Line([r], furniture=True) for r in rotated]})
    # 页眉页脚：同一位置、去掉数字后相同的行出现在至少 3 页（或一半以上的页）；页边上只有数字的行
    counts: dict[str, int] = {}
    keys_of: list[list[str | None]] = []
    for p in pages:
        h = p["crop"][3] - p["crop"][1]
        keys = [furniture_key(ln, h, p["crop"][1]) for ln in p["lines"]]
        keys_of.append(keys)
        for k in set(k for k in keys if k):
            counts[k] = counts.get(k, 0) + 1
    need = max(3, len(pages) // 3) if len(pages) >= 3 else 99  # 奇偶页不同的页眉各占一半
    for p, keys in zip(pages, keys_of, strict=True):
        for ln, k in zip(p["lines"], keys, strict=True):
            if k and (counts.get(k, 0) >= need or re.fullmatch(r"(top|bottom):[#\s\-–—/ivxlc.page]*", k)):
                ln.furniture = True
    out = []
    for p in pages:
        crop = p["crop"]
        ordered = reading_order(p["lines"], crop[2] - crop[0], crop[0])
        ordered += [("furniture", ln) for ln in p["rotated"]]
        out.append({"blocks": blocks_of(ordered, crop, p["rotation"])})
    return out
