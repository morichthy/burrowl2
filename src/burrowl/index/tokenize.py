"""词法检索的切词（设计稿 06 D-06）：中文双字滑窗，英文保留完整标识符并拆开蛇形 / 驼峰。

不是语义分词模型。双字让"温漂""停机"这类两个字的词能命中，长句也有部分重叠；
完整标识符可以精确查函数名、型号。索引与查询必须用同一版本（TOKENIZER_VERSION 变了就整库重建）。
沿用旧版 burrowl 的 `index/tokenize.py`（bigram-cjk-v1）。
"""
import re

TOKENIZER_VERSION = "bigram-cjk-v1"
_TERMS = re.compile(r"[㐀-鿿豈-﫿]+|[A-Za-z0-9_]+")
_CJK = re.compile(r"[㐀-鿿豈-﫿]+")
_PARTS = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|[0-9]+")
_CJK_CHAR = re.compile(r"[㐀-鿿豈-﫿　-〿＀-￯]")


def tokens(text: str) -> list[str]:
    out: list[str] = []
    for term in _TERMS.findall(text or ""):
        if _CJK.fullmatch(term):
            out.extend([term] if len(term) == 1 else [term[i:i + 2] for i in range(len(term) - 1)])
        else:
            out.append(term.casefold())
            parts = [p.casefold() for p in _PARTS.findall(term)]
            if len(parts) > 1:
                out.extend(parts)
    return out


def fts_document(text: str) -> str:
    return " ".join(tokens(text))


def fts_query(text: str, *, max_terms: int = 64) -> str | None:
    """"任一词命中"的 FTS5 表达式；每个词加引号，避免被当作运算符。"""
    unique = list(dict.fromkeys(tokens(text)))[:max_terms]
    if not unique:
        return None
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in unique)


def estimate_tokens(text: str) -> int:
    """模型 token 数的保守估计（设计稿 06 D-02）：中日韩字符按 0.9，其他字符按 0.25。"""
    cjk = len(_CJK_CHAR.findall(text))
    return int(cjk * 0.9 + (len(text) - cjk) * 0.25) + 1
