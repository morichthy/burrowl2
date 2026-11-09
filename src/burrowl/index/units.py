"""检索单元（设计稿 06 D-01 至 D-05）：在引用段落之上，把相邻段落顺序合并成召回与排序用的单位。

- 引用段落（`seg-N`、`p3-2`）不变：判断引用它、记它的指纹。检索单元只是索引里的派生物，随时可重建。
- 长度按 token 估计（D-02）：目标 TARGET、上限 MAX。链条里最短的是重排模型（512 token，含查询与上下文），
  单元不超过 MAX 就不会被截断。单段超过上限时按句末标点切成几块，几块都指向这一段。
- 遇到标题就断开，标题作为下一单元的第一行；`break_units=True` 时单元（幻灯片、图片）之间也断开（D-03）。
- 机械上下文（D-04）：标题 › 各级小节标题，由规则生成，不用 AI 摘要。
- TARGET、MAX、CONTEXT_CHARS 是默认值；数据目录可以在设置里改（`index.units_*`，设计稿 06 D-22），
  改了要重建索引（`Workspace.index_version` 带上非默认的取值）。
"""
import re
from dataclasses import dataclass, field

from .tokenize import estimate_tokens

UNITS_VERSION = 1
TARGET = 300
MAX = 400
CONTEXT_CHARS = 160
_SENTENCE_END = re.compile(r"(?<=[。！？!?；;.])\s+|(?<=[。！？；])")


@dataclass
class Unit:
    ordinal: int
    anchors: list[str]
    text: str
    context: str
    tokens: int = 0
    units: list[str] = field(default_factory=list)  # 覆盖的抽取单元（页、幻灯片），供 read_as 用


def build_units(segments: list[dict], *, title: str = "", break_units: bool = False, target: int = TARGET,
                max_tokens: int = MAX, context_chars: int = CONTEXT_CHARS) -> list[Unit]:
    """segments：按顺序的段落，每项至少有 anchor、text；可选 unit、heading（标题级别，1 起）。
    target / max_tokens：单元的目标与上限长度（token 估计）；context_chars：机械上下文最多几个字。"""
    out: list[Unit] = []
    stack: list[tuple[int, str]] = []
    cur: dict = {"anchors": [], "texts": [], "tokens": 0, "units": [], "context": _context(title, stack, context_chars)}

    def flush():
        if cur["texts"]:
            out.append(Unit(len(out), list(dict.fromkeys(cur["anchors"])), "\n".join(cur["texts"]),
                            cur["context"], cur["tokens"], list(dict.fromkeys(cur["units"]))))
        cur.update(anchors=[], texts=[], tokens=0, units=[], context=_context(title, stack, context_chars))

    last_unit = None
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        unit = seg.get("unit")
        if break_units and last_unit is not None and unit != last_unit:
            flush()
        last_unit = unit
        level = seg.get("heading")
        if level:
            flush()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text[:80]))
            cur["context"] = _context(title, stack[:-1], context_chars)
        size = estimate_tokens(text)
        if size > max_tokens:
            flush()
            for piece in split_long(text, max_tokens):
                cur.update(anchors=[seg["anchor"]], texts=[piece], tokens=estimate_tokens(piece),
                           units=[unit] if unit else [])
                flush()
            continue
        if cur["texts"] and (cur["tokens"] + size > max_tokens or cur["tokens"] >= target):
            flush()
        cur["anchors"].append(seg["anchor"])
        cur["texts"].append(text)
        cur["tokens"] += size
        if unit:
            cur["units"].append(unit)
    flush()
    return out


def split_long(text: str, limit: int = MAX) -> list[str]:
    """超长段落按句末标点切开；单句仍超长时按字数切（文字全部保留，只是分到几个单元里）。"""
    pieces, current = [], ""
    for sentence in (s for s in _SENTENCE_END.split(text) if s):
        while estimate_tokens(sentence) > limit:
            cut = _cut_at(sentence, limit)
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut])
            sentence = sentence[cut:]
        if current and estimate_tokens(current + sentence) > limit:
            pieces.append(current)
            current = ""
        current += sentence if not current else (" " + sentence if sentence[:1].isascii() else sentence)
    if current:
        pieces.append(current)
    return [p.strip() for p in pieces if p.strip()]


def _cut_at(text: str, limit: int) -> int:
    lo, hi = 1, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if estimate_tokens(text[:mid]) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _context(title: str, stack: list[tuple[int, str]], limit: int = CONTEXT_CHARS) -> str:
    parts = [p for p in [title.strip(), *(t for _, t in stack)] if p]
    text = " › ".join(parts)
    if limit <= 0:
        return ""
    return text if len(text) <= limit else text[:limit - 1] + "…"


def markdown_segments(text: str) -> list[dict]:
    """框架页、文本：按自然边界分段（复用 segment.segment_text），`#` 开头的段标为标题。"""
    from .segment import segment_text  # noqa: PLC0415
    out = []
    for s in segment_text(text):
        m = re.match(r"^(#{1,6})\s", s.text)
        out.append({"anchor": s.locator.replace("seg:", "seg-", 1), "text": s.text,
                    "heading": len(m.group(1)) if m else None})
    return out
