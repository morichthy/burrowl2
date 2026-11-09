"""本地模型的适配器（设计稿 05 D-02）：把各工具的 HTTP 接口与输出统一成 burrowl 的格式。只用标准库。

统一的版面结果：
    {"tool": "mineru", "version": "4.1.7",
     "pages": [{"page": 1, "blocks": [{"type", "box": [x, y, 宽, 高], "text", "latex"?, "level"?, "rows"?,
                                       "inline"?: [{"t": "text"|"math", "v": …}]}]}]}
box 与内置抽取相同：占页面的比例，左上为原点。

MinerU（4.x，`mineru-api` 的 V1 任务接口，2026-11-08 按 4.1.7 实测）：
    POST /v1/tasks {tier, output_formats, files: [{file_name, bytes, sha256sum}]} → task_id、上传地址
    PUT  上传地址（application/octet-stream）→ GET /v1/tasks/{id} 轮询到 completed → GET result_url 得到 ZIP，
    ZIP 里的 middle_json.json 是 docvortex.middle 2.0：pages[].page_idx（从 0 开始）、blocks[]：
    type（text / paragraph_title / equation / table / header / page_number …）、bbox [x0, y0, x1, y1]（0–1）、
    content（行间公式是 LaTeX 字符串，段落是 [{type: text | equation_inline, content}]）。
"""
import base64
import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from html.parser import HTMLParser

from ..core.errors import BurrowlError

TIMEOUT = 30
FURNITURE = {"header", "footer", "page_number", "page_header", "page_footer", "page_footnote", "aside_text"}
HEADINGS = {"title", "paragraph_title", "doc_title"}


def _http(method: str, url: str, body: bytes | dict | None = None, *, ctype: str = "application/json",
          headers: dict | None = None, timeout: float = TIMEOUT) -> bytes:
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    hdrs = {**({"Content-Type": ctype} if data is not None else {}), **(headers or {})}
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 地址来自人填写的设置
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:500].decode("utf-8", "replace")
        raise BurrowlError("MODEL_ERROR", f"模型服务返回 {exc.code}：{detail}", {"url": url}) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise BurrowlError("MODEL_UNREACHABLE", f"连不上模型服务：{exc}", {"url": url}) from exc


def _json(raw: bytes) -> dict:
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise BurrowlError("MODEL_ERROR", "模型服务返回的不是 JSON") from exc


# ---------- MinerU ----------
class MinerU:
    name = "mineru"

    def health(self, url: str) -> dict:
        h = _json(_http("GET", f"{url}/v1/health"))
        tiers = [t.get("id") for t in _json(_http("GET", f"{url}/v1/tiers")).get("data", [])]
        return {"ok": h.get("status") == "ok", "tool": "mineru", "version": h.get("version"), "tiers": tiers,
                "detail": f"MinerU {h.get('version')}，可用档位：{'、'.join(tiers) or '无'}"}

    def run(self, url: str, data: bytes, file_name: str, *, tier: str | None = None, timeout: float = 3600) -> tuple:
        """跑一个解析任务，返回 (middle_json, 版本)。"""
        body = {"output_formats": ["default"],
                "files": [{"file_name": file_name, "bytes": len(data), "sha256sum": hashlib.sha256(data).hexdigest()}]}
        if tier and tier != "auto":
            body["tier"] = tier
        created = _json(_http("POST", f"{url}/v1/tasks", body))
        task, f = created["task_id"], created["files"][0]
        up = f.get("upload") or {}
        _http(up.get("method", "PUT"), up.get("url") or f"{url}/v1/tasks/{task}/uploads/{f['file_id']}", data,
              ctype="application/octet-stream", timeout=300)
        end = time.monotonic() + timeout
        while True:
            d = _json(_http("GET", f"{url}/v1/tasks/{task}"))
            if d["status"] in ("completed", "partial", "failed", "canceled"):
                break
            if time.monotonic() > end:
                raise BurrowlError("MODEL_TIMEOUT", "MinerU 解析超时", {"task_id": task})
            time.sleep(2)
        fd = d["files"][0]
        if fd.get("status") != "completed" or not fd.get("result_url"):
            err = (fd.get("error") or d.get("error") or {})
            raise BurrowlError("MODEL_ERROR", f"MinerU 解析失败：{err.get('message') or err or d['status']}")
        raw = _http("GET", fd["result_url"], timeout=300)
        try:
            middle = json.loads(zipfile.ZipFile(io.BytesIO(raw)).read("middle_json.json"))
        except (zipfile.BadZipFile, KeyError, ValueError) as exc:
            raise BurrowlError("MODEL_ERROR", "MinerU 的结果包里没有 middle_json.json") from exc
        version = (fd.get("parse") or {}).get("parser_version") \
            or middle.get("metadata", {}).get("producer", {}).get("version")
        return middle, version

    def parse(self, url: str, data: bytes, file_name: str, *, tier: str | None = None) -> dict:
        middle, version = self.run(url, data, file_name, tier=tier)
        return normalize_mineru(middle, version)

    def formula(self, url: str, png: bytes, *, tier: str | None = None) -> tuple[str, str | None]:
        """单个公式的裁切图 → LaTeX（公式槽位"跟随版面引擎"时用 MinerU 识别图片）。"""
        result = self.parse(url, png, "formula.png", tier=tier)
        blocks = [b for p in result["pages"] for b in p["blocks"]]
        latex = next((b["latex"] for b in blocks if b.get("latex")), None)
        if latex is None:  # 小图有时被当成段落：取其中的行内公式
            parts = [r["v"] for b in blocks for r in b.get("inline") or [] if r["t"] == "math"]
            latex = " ".join(parts) or None
        if not latex:
            raise BurrowlError("MODEL_ERROR", "MinerU 没有在这张图里认出公式")
        return latex, result.get("version")


def _box(bbox) -> list[float] | None:
    if not bbox or len(bbox) != 4:
        return None
    x0, y0, x1, y1 = (float(v) for v in bbox)
    if max(x0, y0, x1, y1) > 1.5:  # 万一是 0–1000 的旧坐标
        x0, y0, x1, y1 = (v / 1000 for v in (x0, y0, x1, y1))
    return [round(x0, 4), round(y0, 4), round(max(x1 - x0, 0), 4), round(max(y1 - y0, 0), 4)]


def _strip_math(s: str) -> str:
    s = s.strip()
    for a, b in (("$$", "$$"), ("\\[", "\\]"), ("$", "$")):
        if s.startswith(a) and s.endswith(b) and len(s) > len(a) + len(b):
            return s[len(a):-len(b)].strip()
    return s


def _runs(content) -> list[dict]:
    """段落内容 → [{t: text | math, v}]；嵌套的子块（如算法正文）展开。"""
    if isinstance(content, str):
        return [{"t": "text", "v": content}]
    out = []
    for c in content or []:
        if not isinstance(c, dict):
            continue
        t, v = c.get("type"), c.get("content")
        if t == "equation_inline" and isinstance(v, str):
            out.append({"t": "math", "v": _strip_math(v)})
        elif isinstance(v, str):
            out.append({"t": "text", "v": v})
        elif isinstance(v, list):
            out += _runs(v)
    return out


class _Table(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _find_html(content) -> str | None:
    if isinstance(content, str):
        return content if "<table" in content else None
    for c in content or []:
        if isinstance(c, dict):
            for key in ("html", "content"):
                v = c.get(key)
                found = _find_html(v) if isinstance(v, (str, list)) else None
                if found:
                    return found
    return None


def normalize_mineru(middle: dict, version: str | None) -> dict:
    pages = []
    for p in middle.get("pages", []):
        blocks = []
        for b in p.get("blocks", []):
            t, box = b.get("type"), _box(b.get("bbox"))
            if t == "equation":
                latex = _strip_math(b["content"]) if isinstance(b.get("content"), str) else None
                if not latex:
                    latex = " ".join(r["v"] for r in _runs(b.get("content")) if r["t"] == "math") or None
                blocks.append({"type": "formula", "box": box, "latex": latex, "text": latex or ""})
                continue
            if t == "table":
                html = _find_html(b.get("content"))
                rows = []
                if html:
                    parser = _Table()
                    parser.feed(html)
                    rows = parser.rows
                blocks.append({"type": "table", "box": box, "rows": rows, "html": html})
                continue
            if t in ("image", "figure", "chart"):
                blocks.append({"type": "image", "box": box})
                continue
            runs = _runs(b.get("content"))
            text = "".join(r["v"] if r["t"] == "text" else f"${r['v']}$" for r in runs).strip()
            kind = "furniture" if t in FURNITURE else "heading" if t in HEADINGS else "paragraph"
            item = {"type": kind, "box": box, "text": text}
            if kind == "heading":
                item["level"] = b.get("level") or 2
            if any(r["t"] == "math" for r in runs):
                item["inline"] = runs
            blocks.append(item)
        pages.append({"page": int(p.get("page_idx", 0)) + 1, "blocks": blocks})
    info = (middle.get("extensions") or {}).get("mineru") or {}
    # parse_mode：txt 表示正文取自 PDF 文字层，ocr 表示整页识别（扫描件），设计稿 05 D-17
    return {"tool": "mineru", "version": version, "parse_mode": info.get("parse_mode"), "pages": pages}


def to_block(b: dict, source: dict) -> dict | None:
    """统一格式的块 → 内置抽取的块（整份替换时用，设计稿 05 D-07）。"""
    if b["type"] == "formula":
        return {"type": "formula", "text": b.get("latex") or "", "box": b.get("box"), "latex": b.get("latex"),
                "latex_source": source} if b.get("latex") else None
    if b["type"] == "table":
        return {"type": "table", "rows": b.get("rows") or [], "box": b.get("box")} if b.get("rows") else None
    if b["type"] == "image" or not b.get("text"):
        return None
    out = {"type": b["type"], "text": b["text"], "box": b.get("box")}
    if b["type"] == "heading":
        out["level"] = b.get("level", 2)
    if b.get("inline"):
        out["inline_math"] = {"runs": b["inline"], "source": source["method"]}
    return out


ADAPTERS = {"mineru": MinerU()}


# ---------- LLM（OpenAI 兼容接口；只在人显式点击时调用，设计稿 05 §2） ----------
FORMULA_PROMPT = ("把图中的数学公式转写为 LaTeX。只输出 LaTeX 本身：不要解释，不要加 $ 或代码块；"
                  "有编号时写成 \\tag{n}。")


CHECK_PROMPT = {
    "text": "下面是从图中识别出的文字。对照图片判断它是否与图中的文字一致（忽略换行、空格和全角半角差别）。",
    "latex": ("下面是从图中识别出的数学公式（LaTeX）。对照图片判断它是否与图中的公式一致"
              "（写法不同但数学含义相同算一致）。"),
}
CHECK_FORMAT = ("只输出一个 JSON 对象，不要其他内容："
                '{"verdict": "confirm（一致）| reject（有错）| unsure（看不清或拿不准）", '
                '"reason": "一句话说明", "suggestion": "有错时给出改正后的完整内容，否则留空"}')


def llm_check(url: str, key: str, model: str, png: bytes, part: str, content: str) -> dict:
    """识别结果的 AI 核对（设计稿 04 D-23）：给大模型原件裁切图与识别结果，要它判断是否一致。"""
    if not model:
        raise BurrowlError("INVALID_ARGUMENT", "还没有填写大模型的模型名")
    image = "data:image/png;base64," + base64.b64encode(png).decode()
    prompt = f"{CHECK_PROMPT[part]}\n\n识别结果：\n{content}\n\n{CHECK_FORMAT}"
    body = {"model": model, "temperature": 0, "messages": [{"role": "user", "content": [
        {"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image}}]}]}
    data = _json(_http("POST", f"{url}/chat/completions", body, headers=_llm_headers(key), timeout=180))
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise BurrowlError("MODEL_ERROR", "大模型的回答格式不对") from exc
    found = re.search(r"\{.*\}", text or "", re.S)
    try:
        out = json.loads(found.group(0)) if found else {}
    except ValueError:
        out = {}
    verdict = str(out.get("verdict", "")).strip().lower()
    verdict = next((v for v in ("confirm", "reject", "unsure") if verdict.startswith(v)), "unsure")
    suggestion = out.get("suggestion") or None
    if isinstance(suggestion, str):
        suggestion = _strip_math(suggestion) if part == "latex" else suggestion.strip()
    return {"verdict": verdict, "reason": str(out.get("reason") or (text or "")[:300]),
            **({"suggestion": suggestion} if suggestion and verdict == "reject" else {})}


def _llm_headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"} if key else {}


def llm_health(url: str, key: str, model: str) -> dict:
    data = _json(_http("GET", f"{url}/models", headers=_llm_headers(key)))
    ids = [m.get("id") for m in data.get("data", [])]
    ok = not model or model in ids or not ids
    return {"ok": ok, "tool": "llm", "version": None, "models": ids[:20],
            "detail": f"可用模型：{'、'.join(ids[:8]) or '未列出'}" + ("" if ok else f"；没有 {model}")}


def llm_formula(url: str, key: str, model: str, png: bytes) -> str:
    if not model:
        raise BurrowlError("INVALID_ARGUMENT", "还没有填写大模型的模型名")
    image = "data:image/png;base64," + base64.b64encode(png).decode()
    body = {"model": model, "temperature": 0, "messages": [{"role": "user", "content": [
        {"type": "text", "text": FORMULA_PROMPT}, {"type": "image_url", "image_url": {"url": image}}]}]}
    data = _json(_http("POST", f"{url}/chat/completions", body, headers=_llm_headers(key), timeout=180))
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise BurrowlError("MODEL_ERROR", "大模型的回答格式不对") from exc
    text = re.sub(r"^```(?:latex|tex)?\s*|\s*```$", "", text.strip())
    return _strip_math(text)
