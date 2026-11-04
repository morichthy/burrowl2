"""按自然边界分段：标题、段落、表格、代码块（草图 §12.1；Memory Tax：按自然边界最好，固定窗口最差）。

每段带定位 `seg:<序号>` 与行号范围，供读取记录引用。原件本身不拆。
SEGMENTER_VERSION 变化时，索引整体重建。
"""
import re
from dataclasses import dataclass

SEGMENTER_VERSION = 1
MAX_CHARS = 1500  # 超长段落按句子边界再切，避免一段淹没检索

_SENTENCE_END = re.compile(r"(?<=[。！？!?；;.])\s*")


@dataclass
class Segment:
    ordinal: int
    locator: str
    text: str
    line_start: int
    line_end: int


def segment_text(text: str) -> list[Segment]:
    blocks: list[tuple[int, int, str]] = []
    lines = text.splitlines()
    start, buffer, in_code = None, [], False

    def flush(end: int):
        nonlocal start, buffer
        if buffer and any(s.strip() for s in buffer):
            blocks.append((start, end, "\n".join(buffer).strip()))
        start, buffer = None, []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                buffer.append(line)
                flush(i)
                in_code = False
                continue
            flush(i - 1)
            in_code, start = True, i
            buffer.append(line)
            continue
        if in_code:
            buffer.append(line)
            continue
        is_heading = stripped.startswith("#")
        is_table = stripped.startswith("|")
        prev_table = bool(buffer) and buffer[-1].strip().startswith("|")
        if not stripped or is_heading or (buffer and is_table != prev_table):
            flush(i - 1)
            if not stripped:
                continue
        if start is None:
            start = i
        buffer.append(line)
        if is_heading:  # 标题自成一段，并作为下一段的前缀上下文
            flush(i)
    flush(len(lines))

    segments: list[Segment] = []
    for line_start, line_end, block in blocks:
        for piece in _split_long(block):
            segments.append(Segment(len(segments), f"seg:{len(segments)}", piece, line_start, line_end))
    return segments


def _split_long(block: str) -> list[str]:
    if len(block) <= MAX_CHARS:
        return [block]
    pieces, current = [], ""
    for sentence in _SENTENCE_END.split(block):
        if current and len(current) + len(sentence) > MAX_CHARS:
            pieces.append(current)
            current = ""
        current += sentence
    if current:
        pieces.append(current)
    return pieces
