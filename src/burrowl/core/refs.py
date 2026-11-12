"""正文中的引用写成 `[[ID]]` 或 `[[ID|显示文字]]`，与 Obsidian 维基链接兼容（DESIGN §0）。"""
import re

REF_RE = re.compile(r"\[\[([a-z]+_[0-9A-HJKMNP-TV-Z]{26}(?:@\d+|#[\w-]+)?)(?:\|[^\]]*)?\]\]")


# 判断正文里的行内引用标记 [^1]（设计稿 11 D-05）：编号对应这一版某条关系的 marker
MARKER_RE = re.compile(r"\[\^(\d{1,3})\]")


def extract_markers(text: str) -> list[str]:
    return list(dict.fromkeys(MARKER_RE.findall(text or "")))


def strip_markers(text: str) -> str:
    """去掉 [^n]（索引、检索结果、预览不带标记，设计稿 11 D-09）。"""
    return MARKER_RE.sub("", text or "")


def extract_refs(text: str) -> list[str]:
    seen: list[str] = []
    for ref in REF_RE.findall(text or ""):
        if ref not in seen:
            seen.append(ref)
    return seen
