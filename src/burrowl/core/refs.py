"""正文中的引用写成 `[[ID]]` 或 `[[ID|显示文字]]`，与 Obsidian 维基链接兼容（DESIGN §0）。"""
import re

REF_RE = re.compile(r"\[\[([a-z]+_[0-9A-HJKMNP-TV-Z]{26}(?:@\d+|#[\w-]+)?)(?:\|[^\]]*)?\]\]")


def extract_refs(text: str) -> list[str]:
    seen: list[str] = []
    for ref in REF_RE.findall(text or ""):
        if ref not in seen:
            seen.append(ref)
    return seen
