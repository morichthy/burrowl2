"""抽取层（设计稿 01 D-10 至 D-17）：原件的可读文本属于原件本身，按单元组织，随时可重建。

- 原件字节始终原样；抽取写在 extractions 表（只追加），当前抽取层 = 每个单元最新的一条 content。
- 文本类原件的抽取就是原样复制，是确定的，不写抽取记录（虚拟抽取层，与 2.0.0a9 的分段完全一致）。
- 检索索引、工作台显示、读取、引用都来自当前抽取层，所以"看到的"和"搜到的"一致。
- 可信度档（D-12）：copy 原样复制 > parsed 解析文字层 > manual 人工转写 > ocr > ai 模型识别；
  任何一档都可以被人确认（verification）。引用 ocr / ai 档且未确认的段落会得到提示。
- 重建（D-13）：单元文本指纹不变的，引用照常；变化或消失的，引用它的判断进入待复核，并沿框架传播"输入已变化"。

段落定位（D-14）：文本文件与 DOCX 正文写 `seg-N`（N 从 0 开始，与旧版一致）；
其余单元写 `<单元>-<K>`（K 从 1 开始），如 `p3-2` 第 3 页第 2 段、`img-1`、`img2-1`、`av-4`。
补抽其他单元不改变已有编号。
"""
import json
import re

from ..core.actor import SYSTEM, Actor
from ..core.errors import BurrowlError
from ..core.hashing import sha256_bytes, sha256_text
from ..index.segment import _split_long, segment_text
from . import extractors as ex

FIDELITY_ORDER = ("copy", "parsed", "manual", "ocr", "ai")
LOW_FIDELITY = ("ocr", "ai")
FIDELITY_LABEL = {"copy": "原样复制", "parsed": "解析文字层", "manual": "人工转写", "ocr": "OCR 识别",
                  "ai": "AI 识别"}
SUBMIT_METHODS = {"manual": "manual", "ocr": "ocr", "ai": "ai"}
AUTO_FORMATS = ("pdf", "pptx", "docx", "xlsx")  # 本地即可可靠抽取的格式；图片与音视频默认不抽取
SNAPSHOT_FORMATS = ("pptx", "docx", "xlsx")
LATEX_MAX = 4000  # 一条公式 LaTeX 的长度上限
_ANCHOR = re.compile(r"^(?:seg-(\d+)|([a-z]+\d*)-(\d+))$")
EXTRACTOR = Actor("system:extractor", "system", "ses_system")


def anchor_of(locator: str) -> str:
    return locator.replace("seg:", "seg-", 1) if locator.startswith("seg:") else locator


class ExtractionService:
    def __init__(self, ws):
        self.ws = ws

    # ---------- 读当前抽取层 ----------
    def format(self, artifact: dict) -> str:
        return ex.format_of(artifact)

    def _rows(self, artifact_id: str, kind: str, unit: str | None = None) -> list[dict]:
        q, p = "SELECT * FROM extractions WHERE artifact_id = ? AND kind = ?", [artifact_id, kind]
        if unit is not None:
            q, p = q + " AND unit = ?", [*p, unit]
        return self.ws.ledger.query(q + " ORDER BY created_at, id", p)

    def manifest(self, artifact_id: str) -> dict | None:
        rows = self._rows(artifact_id, "manifest")
        return rows[-1] if rows else None

    def current(self, artifact_id: str) -> dict[str, dict]:
        """每个单元最新的一条 content。"""
        out: dict[str, dict] = {}
        for r in self._rows(artifact_id, "content"):
            out[r["unit"]] = r
        return out

    def verified(self, artifact_id: str) -> dict[str, dict]:
        """被确认过的 content ID → 确认记录。"""
        return {r["data"]["extraction_id"]: r for r in self._rows(artifact_id, "verification")}

    def snapshot_row(self, artifact_id: str) -> dict | None:
        rows = self._rows(artifact_id, "snapshot")
        return rows[-1] if rows else None

    def units(self, artifact: dict) -> list[dict]:
        """单元清单（按原件中的顺序），每项带当前抽取状态。"""
        fmt = self.format(artifact)
        if fmt == "text":
            return [{"unit": "doc", "label": "全文", "kind": "document", "status": "text", "fidelity": "copy",
                     "method": "原样复制", "verified": False, "virtual": True}]
        manifest = self.manifest(artifact["id"])
        if manifest is None:
            return []
        current, verified = self.current(artifact["id"]), self.verified(artifact["id"])
        out = []
        for u in manifest["data"]["units"]:
            row = current.get(u["unit"])
            item = {**u, "status": "not_extracted", "fidelity": None, "method": None, "verified": False}
            if row:
                d = row["data"]
                item.update(status=d["status"], fidelity=d.get("fidelity"), method=d.get("method"),
                            extraction_id=row["id"], extracted_by=row["actor_id"], extracted_at=row["created_at"],
                            verified=row["id"] in verified, text=d.get("text", ""), blocks=d.get("blocks", []),
                            meta=d.get("meta", {}))
            out.append(item)
        return out

    def layer(self, artifact_id: str) -> dict:
        """工作台原件页用：格式、单元清单（含文本与版式块）、覆盖情况、快照、可用的抽取方式。"""
        art = self.ws.artifacts._artifact(artifact_id)
        fmt = self.format(art)
        units = self.units(art)
        if fmt == "text":
            try:
                units[0]["text"] = self.ws.artifacts.text(art) or ""
            except BurrowlError as exc:
                units[0].update(status="unreadable", error=exc.message)
        manifest = self.manifest(artifact_id)
        snap = self.snapshot_row(artifact_id)
        counts: dict[str, int] = {}
        for u in units:
            counts[u["status"]] = counts.get(u["status"], 0) + 1
        return {
            "artifact_id": artifact_id, "format": fmt, "media_type": ex.media_type_of(art),
            "units": units, "counts": counts,
            "manifest": manifest["data"] if manifest else None,
            "manifest_error": (manifest or {}).get("data", {}).get("error"),
            "extracted": fmt == "text" or manifest is not None,
            "snapshot": ({"id": snap["id"], **snap["data"]} if snap else None),
            "snapshot_supported": fmt in SNAPSHOT_FORMATS,
            "auto_supported": fmt in AUTO_FORMATS,
            "derived_texts": self.derived_texts(art),
        }

    def derived_texts(self, art: dict) -> dict:
        """旧数据：登记成独立原件的派生文本（metadata.derived_from），只用于显示两者的联系。"""
        meta = art["data"].get("metadata") or {}
        out = {"from": meta.get("derived_from") if str(meta.get("derived_from", "")).startswith("art_") else None,
               "texts": []}
        sql = "SELECT id FROM artifacts WHERE json_extract(data, '$.metadata.derived_from') = ?"
        for r in self.ws.ledger.query(sql, (art["id"],)):
            out["texts"].append(r["id"])
        return out

    # ---------- 分段（检索、读取、引用的共同来源） ----------
    def segments(self, art: dict) -> list[dict]:
        fmt = self.format(art)
        if fmt == "text":
            text = self.ws.artifacts.text(art)
            if text is None:
                return []
            return [{"ordinal": s.ordinal, "locator": s.locator, "anchor": f"seg-{s.ordinal}", "unit": "doc",
                     "unit_label": "全文", "text": s.text, "lines": [s.line_start, s.line_end],
                     "sha256": sha256_text(s.text), "fidelity": "copy", "verified": False, "block": None}
                    for s in segment_text(text)]
        out: list[dict] = []
        for u in self.units(art):
            if u["status"] != "text":
                continue
            single_flow = u["unit"] == "doc"  # DOCX 正文：与文本文件一样写 seg-N
            k = 0
            for bi, block in enumerate(u.get("blocks") or []):
                text = ex.block_text(block)
                if not text.strip():
                    continue
                for piece in _split_long(text):
                    anchor = f"seg-{k}" if single_flow else f"{u['unit']}-{k + 1}"
                    out.append({"ordinal": len(out), "locator": anchor.replace("seg-", "seg:", 1) if single_flow
                                else anchor, "anchor": anchor, "unit": u["unit"], "unit_label": u["label"],
                                "text": piece, "sha256": sha256_text(piece), "fidelity": u["fidelity"],
                                "verified": u["verified"], "method": u["method"],
                                "extraction_id": u.get("extraction_id"), "block": bi,
                                **({"t": block["t"]} if "t" in block else {})})
                    k += 1
        return out

    def find(self, art: dict, anchor: str) -> dict | None:
        anchor = anchor_of(anchor)
        return next((s for s in self.segments(art) if s["anchor"] == anchor), None)

    def select(self, art: dict, locator: str | None) -> list[dict]:
        """读取范围：省略为全部；seg:N / seg:N-M（旧写法）；段落 p3-2 / seg-3；单元 p3；单元范围 p3:p5。"""
        segs = self.segments(art)
        if not segs:
            raise BurrowlError("UNREADABLE", self._unreadable_hint(art), {"artifact_id": art["id"]})
        if not locator:
            return segs
        if locator.startswith("seg:"):
            start, _, end = locator[4:].partition("-")
            try:
                a, b = int(start), int(end or start)
            except ValueError as exc:
                raise BurrowlError("INVALID_ARGUMENT", "locator 应为 seg:N 或 seg:N-M", {"locator": locator}) from exc
            chosen = [s for s in segs if s["anchor"].startswith("seg-") and a <= int(s["anchor"][4:]) <= b]
        elif ":" in locator:
            first, _, last = locator.partition(":")
            order = [u["unit"] for u in self.units(art)]
            if first not in order or last not in order:
                raise BurrowlError("INVALID_ARGUMENT", "单元不存在", {"locator": locator, "units": order[:50]})
            wanted = set(order[order.index(first):order.index(last) + 1])
            chosen = [s for s in segs if s["unit"] in wanted]
        else:
            chosen = [s for s in segs if s["anchor"] == locator] or [s for s in segs if s["unit"] == locator]
            if not chosen:
                unit = next((u for u in self.units(art) if u["unit"] == locator), None)
                if unit is not None:
                    raise BurrowlError("UNREADABLE", self._unit_hint(unit), {"unit": locator})
        if not chosen:
            raise BurrowlError("INVALID_ARGUMENT", "locator 超出范围", {"locator": locator, "segments": len(segs)})
        return chosen

    def _unit_hint(self, unit: dict) -> str:
        if unit["status"] == "image":
            return (f"{unit['label']}是图片页，还没有抽取文本：用 artifact_view 看页面图像，"
                    "识别后用 artifact_extract（method=ai）提交")
        if unit["status"] == "not_extracted":
            return f"{unit['label']}还没有抽取：用 artifact_view 查看，或用 artifact_extract 提交识别的文本"
        return f"{unit['label']}没有文字"

    def _unreadable_hint(self, art: dict) -> str:
        fmt = self.format(art)
        if fmt in ("image", "av"):
            return "这份原件是图片或音视频，默认不抽取；用 artifact_view 查看，再用 artifact_extract 提交识别的文本"
        if fmt in AUTO_FORMATS and self.manifest(art["id"]) is None:
            return "这份原件还没有抽取；用 artifact_extract（method=auto）抽取"
        if fmt == "binary":
            return "这类文件没有抽取器；可以用 artifact_extract（method=manual 或 ai）提交文本"
        return "这份原件还没有可读的文本；用 artifact_view 查看各单元"

    # ---------- 写入 ----------
    def on_register(self, actor: Actor, art: dict) -> dict | None:
        """登记后的默认抽取（D-11）：按设置自动抽取 PDF / PPTX / DOCX；图片与音视频只登记单元。"""
        fmt = self.format(art)
        policy = self.ws.config.get("extraction", {})
        if fmt in AUTO_FORMATS and policy.get(fmt, "auto") == "auto":
            return self.auto(actor, art["id"], reason="登记时自动抽取")
        if fmt in ("image", "av"):
            self._write(actor, art, "manifest", "", ex.media_manifest(fmt))
        return None

    def auto(self, actor: Actor, artifact_id: str, *, units: list[str] | None = None, reason: str = "") -> dict:
        """用内置抽取器（重新）抽取；units 省略时整份。文本相同的单元不写新记录。"""
        art = self.ws.artifacts._artifact(artifact_id)
        fmt = self.format(art)
        if fmt == "text":
            return {"artifact_id": artifact_id, "format": fmt, "written": [], "note": "文本原件按原样复制，不需要抽取"}
        if fmt not in AUTO_FORMATS:
            raise BurrowlError("INVALID_ARGUMENT", "这类原件没有内置抽取器，请用 method=ai / ocr / manual 提交文本",
                               {"format": fmt})
        data = self.ws.artifacts.content(art)
        try:
            result = ex.EXTRACTORS[fmt](data)
        except BurrowlError as exc:
            if self.manifest(artifact_id) is None:  # 记下失败，状态检查列出，不阻断登记
                self._write(actor, art, "manifest", "", {"format": fmt, "units": [], "error": exc.message})
            raise
        for sha, blob in result.images.items():
            self.ws.blobs.put(blob)
            assert sha == sha256_bytes(blob)
        manifest = {**result.manifest, "extractor_version": ex.EXTRACTOR_VERSION, "method": result.method}
        old = self.manifest(artifact_id)
        if (old is None or old["data"].get("units") != manifest["units"]
                or old["data"].get("extractor_version", 1) != ex.EXTRACTOR_VERSION):  # 抽取器升级后记下新版本号
            self._write(actor, art, "manifest", "", manifest)
        wanted = set(units) if units else None
        current = self.current(artifact_id)
        written = []
        for c in result.contents:
            if wanted is not None and c.unit not in wanted:
                continue
            submitted = (current.get(c.unit) or {}).get("data", {}).get("fidelity") in SUBMIT_METHODS.values()
            if submitted and (wanted is None or c.status != "text"):
                # 人工转写、OCR、AI 识别过的单元：整份重新抽取时保留；内置抽取器读不出文字时也不覆盖
                continue
            blocks = _carry_latex((current.get(c.unit) or {}).get("data", {}).get("blocks") or [], c.blocks)
            row = self._content(actor, art, c.unit, status=c.status, text=c.text, blocks=blocks, meta=c.meta,
                                method=result.method, fidelity="parsed" if c.status == "text" else None,
                                reason=reason)
            if row:
                written.append(c.unit)
        return self._after_write(actor, art, written)

    def submit(self, actor: Actor, artifact_id: str, *, method: str, content: list[dict], model: str | None = None,
               note: str = "") -> dict:
        """提交某些单元的文本：AI 识别（method=ai，填 model）、OCR 工具（ocr）、人工转写（manual，只有人）。

        content：[{unit, text, blocks?}]；视频的 text 可以写成 "[00:01:23] 文字" 一行一块。
        """
        if method not in SUBMIT_METHODS:
            raise BurrowlError("INVALID_ARGUMENT", "method 必须是 auto / ai / ocr / manual", {"method": method})
        if method == "manual":
            actor.require_human("提交人工转写（AI 识别请用 method=ai）")
        if method == "ai" and not model:
            raise BurrowlError("INVALID_ARGUMENT", "AI 识别请在 model 里写明模型（如 claude-opus-5-5）")
        art = self.ws.artifacts._artifact(artifact_id)
        fmt = self.format(art)
        if fmt == "text":
            raise BurrowlError("INVALID_ARGUMENT", "文本原件按原样复制，不接受另外提交的文本")
        if not content:
            raise BurrowlError("INVALID_ARGUMENT", "content 不能为空")
        if self.manifest(artifact_id) is None:
            base = ex.media_manifest(fmt) if fmt in ("image", "av") else \
                {"format": fmt, "units": [{"unit": "doc", "label": "全文", "kind": "document"}]}
            self._write(actor, art, "manifest", "", base)
        known = {u["unit"]: u for u in self.units(art)}
        label = f"{method}:{model}" if model else method
        written = []
        for item in content:
            unit, text = item.get("unit"), item.get("text") or ""
            if unit not in known:
                raise BurrowlError("INVALID_ARGUMENT", "单元不存在", {"unit": unit, "units": list(known)[:50]})
            blocks = item.get("blocks") or (ex.cues_from_text(text) if known[unit]["kind"] == "media"
                                            else ex.paragraphs_to_blocks(text))
            text = ex.text_of(blocks)
            if not text.strip():
                raise BurrowlError("INVALID_ARGUMENT", "提交的文本为空", {"unit": unit})
            row = self._content(actor, art, unit, status="text", text=text, blocks=blocks,
                                meta=known[unit].get("meta") or {}, method=label,
                                fidelity=SUBMIT_METHODS[method], reason=note)
            if row:
                written.append(unit)
        return self._after_write(actor, art, written)

    def submit_latex(self, actor: Actor, artifact_id: str, *, method: str, blocks: list[dict],
                     model: str | None = None, note: str = "") -> dict:
        """给公式块补充 LaTeX（设计稿 03 D-17）：[{anchor, latex}]，anchor 是公式块的段落锚点（如 p3-4）。

        写法：把那个单元当前的抽取复制一条，只在公式块上加 latex 与 latex_source（方法、可信度档、提交者）；
        块的文字、锚点、指纹都不变，所以引用它的判断不进待复核。人确认这个单元时一并确认 LaTeX。"""
        if method not in SUBMIT_METHODS:
            raise BurrowlError("INVALID_ARGUMENT", "method 必须是 ai / ocr / manual", {"method": method})
        if method == "manual":
            actor.require_human("人工填写公式（AI 识别请用 method=ai）")
        if method == "ai" and not model:
            raise BurrowlError("INVALID_ARGUMENT", "AI 识别请在 model 里写明模型（如 claude-opus-5-5）")
        if not blocks:
            raise BurrowlError("INVALID_ARGUMENT", "blocks 不能为空")
        art = self.ws.artifacts._artifact(artifact_id)
        segs = {s["anchor"]: s for s in self.segments(art)}
        current = self.current(artifact_id)
        label = f"{method}:{model}" if model else method
        changed: dict[str, list[dict]] = {}
        for item in blocks:
            anchor, latex = anchor_of(str(item.get("anchor") or "")), str(item.get("latex") or "").strip()
            seg = segs.get(anchor)
            if seg is None or seg.get("block") is None:
                raise BurrowlError("INVALID_ARGUMENT", "段落不存在", {"anchor": anchor})
            if not latex or len(latex) > LATEX_MAX:
                raise BurrowlError("INVALID_ARGUMENT", f"latex 不能为空，也不能超过 {LATEX_MAX} 个字符",
                                   {"anchor": anchor})
            unit = seg["unit"]
            target = changed.get(unit)
            if target is None:
                target = changed[unit] = json.loads(json.dumps(current[unit]["data"]["blocks"]))
            block = target[seg["block"]]
            if block.get("type") != "formula":
                raise BurrowlError("INVALID_ARGUMENT", "只有公式块（type=formula）可以补充 LaTeX；行内公式请看原件",
                                   {"anchor": anchor, "type": block.get("type")})
            block["latex"] = latex
            block["latex_source"] = {"method": label, "fidelity": SUBMIT_METHODS[method], "actor_id": actor.id,
                                     **({"note": note} if note else {})}
        written = []
        for unit, new_blocks in changed.items():
            d = current[unit]["data"]
            row = self._content(actor, art, unit, status=d["status"], text=d.get("text", ""), blocks=new_blocks,
                                meta=d.get("meta") or {}, method=d.get("method") or "", fidelity=d.get("fidelity"),
                                reason=note or f"补充公式 LaTeX（{label}）")
            if row:
                written.append(unit)
        return {"artifact_id": artifact_id, "written": written, "blocks": len(blocks),
                "note": "块的文字与锚点不变；这些单元需要人重新确认" if written else "与当前内容相同，没有写入"}

    def verify(self, actor: Actor, artifact_id: str, *, units: list[str] | None = None, note: str = "") -> dict:
        """人确认当前抽取与原件一致（逐单元或整份）。只确认当前那一条；以后重新抽取需要重新确认。"""
        actor.require_human("确认抽取结果")
        art = self.ws.artifacts._artifact(artifact_id)
        current, verified = self.current(artifact_id), self.verified(artifact_id)
        targets = units or [u for u, r in current.items() if r["data"]["status"] == "text"]
        done = []
        for unit in targets:
            row = current.get(unit)
            if row is None or row["data"]["status"] != "text":
                raise BurrowlError("INVALID_ARGUMENT", "这个单元还没有可确认的文本", {"unit": unit})
            if row["id"] in verified:
                continue
            self._write(actor, art, "verification", unit, {"extraction_id": row["id"], "note": note})
            done.append(unit)
        return {"artifact_id": artifact_id, "verified": done}

    def snapshot(self, actor: Actor, artifact_id: str, *, force: bool = False) -> dict:
        """PPTX / DOCX / Excel 的页面快照（D-17）：用本机 Office 或 LibreOffice 转成 PDF，只用于显示。"""
        art = self.ws.artifacts._artifact(artifact_id)
        fmt = self.format(art)
        if fmt not in SNAPSHOT_FORMATS:
            raise BurrowlError("INVALID_ARGUMENT", "只有 PPTX、DOCX 和 Excel 需要页面快照", {"format": fmt})
        existing = self.snapshot_row(artifact_id)
        if existing and not force:
            return {"id": existing["id"], **existing["data"], "existing": True}
        preference = self.ws.config.get("extraction", {}).get("snapshot", "auto")
        if preference == "none":
            raise BurrowlError("SNAPSHOT_UNAVAILABLE", "设置里关闭了页面快照")
        data = self.ws.artifacts.content(art)
        with self.ws.unlocked():  # 转换要 5–20 秒，期间不挡住其他请求
            pdf, converter = ex.convert_to_pdf(data, art["data"]["suffix"], preference)
        existing = self.snapshot_row(artifact_id)
        if existing and not force:  # 转换期间别的请求已经生成了
            return {"id": existing["id"], **existing["data"], "existing": True}
        sha = self.ws.blobs.put(pdf)
        row = self._write(actor, art, "snapshot", "", {"converter": converter, "pdf_sha256": sha,
                                                         "pages": ex.pdf_page_count(pdf)})
        return {"id": row["id"], **row["data"]}

    def outdated(self, art: dict) -> bool:
        """内置抽取器升级后，这份原件的抽取层是旧版抽取器做的（设计稿 02 D-07）。"""
        manifest = self.manifest(art["id"])
        fmt = self.format(art)
        return (fmt in AUTO_FORMATS and manifest is not None and not manifest["data"].get("error")
                and manifest["data"].get("extractor_version", 1)
                < ex.FORMAT_VERSION_SINCE.get(fmt, ex.EXTRACTOR_VERSION))

    def backfill(self, actor: Actor) -> dict:
        """补抽：还没有抽取层的 PDF / PPTX / DOCX、图片、音视频补上抽取；内置抽取器升级后，
        把旧版抽取器做的抽取层按新版重建（人工、OCR、AI 提交过的单元保留，设计稿 01 D-19、02 D-07）。"""
        done, rebuilt, failed = [], [], []
        for r in self.ws.ledger.query("SELECT id FROM artifacts ORDER BY created_at"):
            art = self.ws.ledger.get(r["id"])
            if self.format(art) in ("text", "binary"):
                continue
            try:
                if self.manifest(art["id"]) is None:
                    self.on_register(actor, art)
                    done.append(art["id"])
                elif self.outdated(art):
                    self.auto(actor, art["id"], reason=f"抽取器升级到第 {ex.EXTRACTOR_VERSION} 版")
                    rebuilt.append(art["id"])
            except BurrowlError as exc:
                failed.append({"artifact_id": art["id"], "error": exc.message})
        return {"extracted": done, "rebuilt": rebuilt, "failed": failed}

    def history(self, artifact_id: str, unit: str) -> list[dict]:
        verified = self.verified(artifact_id)
        return [{"id": r["id"], "created_at": r["created_at"], "actor_id": r["actor_id"],
                 "status": r["data"]["status"], "fidelity": r["data"].get("fidelity"),
                 "method": r["data"].get("method"), "text": r["data"].get("text", ""),
                 "reason": r["data"].get("reason"), "verified": r["id"] in verified}
                for r in reversed(self._rows(artifact_id, "content", unit))]

    # ---------- 看图（给 AI 识别、给工作台显示） ----------
    def page_image(self, artifact_id: str, page: int, *, source: str = "auto", scale: float = 1.5,
                   clip: tuple[float, float, float, float] | None = None) -> bytes:
        """PDF 原页，或 PPTX / DOCX 快照的第 page 页，渲染成 PNG（缓存在数据目录 cache/，可随时删除）。
        clip 为页面上的一块（块的 box），用于公式等的裁切图（设计稿 03 D-16）。"""
        art = self.ws.artifacts._artifact(artifact_id)
        fmt = self.format(art)
        if fmt == "pdf" and source in ("auto", "original"):
            pdf_sha = art["sha256"]
            loader = lambda: self.ws.artifacts.content(art)  # noqa: E731
        elif fmt in SNAPSHOT_FORMATS:
            snap = self.snapshot_row(artifact_id)
            if snap is None:
                raise BurrowlError("NOT_FOUND", "还没有页面快照，先生成快照")
            pdf_sha = snap["data"]["pdf_sha256"]
            loader = lambda: self.ws.blobs.get(pdf_sha)  # noqa: E731
        else:
            raise BurrowlError("INVALID_ARGUMENT", "这类原件没有页面图像", {"format": fmt})
        scale = min(max(scale, 0.5), 4.0)
        if clip is not None:
            if len(clip) != 4 or not all(0 <= v <= 1 for v in clip):
                raise BurrowlError("INVALID_ARGUMENT", "clip 是占页面比例的 x,y,宽,高（0–1）", {"clip": list(clip)})
            clip = tuple(round(v, 4) for v in clip)
        suffix = "" if clip is None else "-" + "_".join(f"{v:g}" for v in clip)
        cache = self.ws.root / "cache" / "pages" / pdf_sha / f"{page}@{scale:g}{suffix}.png"
        if cache.exists():
            return cache.read_bytes()
        png = ex.render_pdf_page(loader(), page, scale, clip)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(png)
        return png

    def snapshot_pdf(self, artifact_id: str) -> bytes:
        """PPTX / DOCX 页面快照的 PDF 字节，阅读模式用同一个 PDF 阅读器显示（设计稿 03 D-03）。"""
        snap = self.snapshot_row(artifact_id)
        if snap is None:
            raise BurrowlError("NOT_FOUND", "还没有页面快照，先生成快照")
        return self.ws.blobs.get(snap["data"]["pdf_sha256"])

    def view(self, artifact_id: str, unit: str, anchor: str | None = None) -> dict:
        """AI 识别用：返回单元的图像（PDF 页、PPT 页快照、图片、嵌入图片）与当前抽取状态。
        给 anchor（段落锚点）时只返回那一块在原件上的裁切图，用于识别公式（设计稿 03 D-17）。"""
        art = self.ws.artifacts._artifact(artifact_id)
        fmt = self.format(art)
        if anchor:
            return self._view_block(art, fmt, anchor)
        units = {u["unit"]: u for u in self.units(art)}
        u = units.get(unit)
        if u is None:
            raise BurrowlError("NOT_FOUND", "单元不存在", {"unit": unit, "units": list(units)[:50]})
        image, note = None, ""
        if u["kind"] in ("page", "slide"):
            if fmt == "pptx" and self.snapshot_row(artifact_id) is None:
                try:
                    self.snapshot(SYSTEM, artifact_id)
                except BurrowlError as exc:
                    note = f"没有页面快照（{exc.message}），只能给出抽取的文字"
            if not note:
                image = self.page_image(artifact_id, u["page"], scale=2.0)
        elif unit == "img":
            image, _ = ex.downscale_image(self.ws.artifacts.content(art))
        elif u["kind"] == "image":
            sha = self._embedded_sha(artifact_id, unit)
            if sha:
                image, _ = ex.downscale_image(self.ws.blobs.get(sha))
        elif u["kind"] == "media":
            note = "音视频不能以图像查看；请用外部工具转写后，用 artifact_extract 提交带时间戳的文本"
        out = {"artifact_id": artifact_id, "unit": unit, "label": u["label"], "status": u["status"],
               "fidelity": u.get("fidelity"), "text": u.get("text", ""), "note": note,
               "submit_hint": "识别后用 artifact_extract 提交：method=ai，model 写模型名，"
                              f"content=[{{unit: '{unit}', text: …}}]"}
        if image is not None:
            import base64  # noqa: PLC0415
            out["_image"] = {"mime": "image/png", "base64": base64.b64encode(image).decode()}
        return out

    def _view_block(self, art: dict, fmt: str, anchor: str) -> dict:
        seg = self.find(art, anchor)
        if seg is None:
            raise BurrowlError("NOT_FOUND", "段落不存在", {"anchor": anchor})
        unit = next(u for u in self.units(art) if u["unit"] == seg["unit"])
        block = (unit.get("blocks") or [])[seg["block"]] if seg.get("block") is not None else {}
        if not block.get("box") or not unit.get("page") or fmt not in ("pdf", "pptx"):
            raise BurrowlError("INVALID_ARGUMENT", "这一段没有页面位置，请用 unit 看整页", {"anchor": anchor})
        image = self.page_image(art["id"], unit["page"], source="original" if fmt == "pdf" else "snapshot",
                                scale=3.0, clip=tuple(block["box"]))
        import base64  # noqa: PLC0415
        return {"artifact_id": art["id"], "unit": unit["unit"], "anchor": seg["anchor"], "type": block.get("type"),
                "text": seg["text"], "latex": block.get("latex"),
                "submit_hint": "识别公式后用 artifact_extract 提交：method=ai，model 写模型名，"
                               f"blocks=[{{anchor: '{seg['anchor']}', latex: '…'}}]（只写 LaTeX，不加 $）",
                "_image": {"mime": "image/png", "base64": base64.b64encode(image).decode()}}

    def _embedded_sha(self, artifact_id: str, unit: str) -> str | None:
        for u in self.units(self.ws.artifacts._artifact(artifact_id)):
            for b in u.get("blocks") or []:
                if b.get("type") == "image" and b.get("unit") == unit:
                    return b.get("sha256")
        return None

    def owns_blob(self, artifact_id: str, sha: str) -> bool:
        """工作台取嵌入图片时核对：这个 blob 确实来自这份原件的抽取或快照。"""
        rows = self.ws.ledger.query("SELECT 1 FROM extractions WHERE artifact_id = ? AND data LIKE ? LIMIT 1",
                                    (artifact_id, f"%{sha}%"))
        return bool(rows) and re.fullmatch(r"[0-9a-f]{64}", sha) is not None

    # ---------- 引用与复核（D-02、D-05、D-12、D-13） ----------
    def citation(self, actor: Actor, ref: str) -> dict | None:
        """判断引用 art_…#段落 时：检查段落存在，返回段落指纹、可信度档、是否已确认和提示代码（notices）。"""
        base, _, anchor = ref.partition("#")
        if not base.startswith("art_") or not anchor:
            return None
        art = self.ws.artifacts._artifact(base)
        try:
            seg = self.find(art, anchor)
        except BurrowlError:
            seg = None
        if seg is None:
            raise BurrowlError("INVALID_REFERENCE",
                               "原件中没有这个段落；先用 artifact_segments 或 artifact_read 查看段落编号", {"ref": ref})
        notices = []
        if seg["fidelity"] in LOW_FIDELITY and not seg["verified"]:
            notices.append("LOW_FIDELITY_CITATION")
        if not self._was_read(actor, base, seg):
            notices.append("UNREAD_CITATION")
        return {"ref": ref, "artifact_id": base, "anchor": seg["anchor"], "sha256": seg["sha256"],
                "fidelity": seg["fidelity"], "verified": seg["verified"], "unit": seg["unit"],
                "extraction_id": seg.get("extraction_id"), "notices": notices}

    def _was_read(self, actor: Actor, artifact_id: str, seg: dict) -> bool:
        q, p = "SELECT data, session_id FROM reads WHERE artifact_id = ? AND actor_id = ?", [artifact_id, actor.id]
        for r in self.ws.ledger.query(q, p):
            if actor.session_id and r["session_id"] and r["session_id"] != actor.session_id:
                continue
            d = r["data"]
            if seg["anchor"] in d.get("anchors", []) or seg["sha256"] in d.get("segment_sha256", []):
                return True
        return False

    def cited_hashes(self, judgment: dict) -> list[dict]:
        """一条判断引用的原件段落及当时的指纹：新写的判断记在 cited_segments；旧判断从读取记录推出。"""
        out = list(judgment["data"].get("cited_segments") or [])
        seen = {c["ref"] for c in out}
        for link in self.ws.ledger.links_from(judgment["id"], "used"):
            ref = link["dst_id"]
            if ref in seen:
                continue
            if ref.startswith("art_") and "#" in ref:  # 2.0.0a10 以前写入的段落引用没有记指纹：按当前段落补出
                art = self.ws.ledger.get(ref.split("#", 1)[0])
                seg = self.find(art, ref.split("#", 1)[1]) if art else None
                if seg:
                    out.append({"ref": ref, "artifact_id": art["id"], "anchor": seg["anchor"], "sha256": seg["sha256"],
                                "unit": seg["unit"], "inferred": True})
            elif ref.startswith("rd_"):
                rd = self.ws.ledger.get(ref)
                if rd:
                    for i, sha in enumerate(rd["data"].get("segment_sha256", [])):
                        anchors = rd["data"].get("anchors") or [f"seg-{n}" for n in rd["data"].get("segments", [])]
                        out.append({"ref": ref, "artifact_id": rd["artifact_id"],
                                    "anchor": anchors[i] if i < len(anchors) else None, "sha256": sha,
                                    "via_read": True})
        return out

    def needs_recheck(self) -> list[dict]:
        """待复核（D-13）：判断引用的段落在当前抽取层里指纹已变或已消失，且之后没有人对这条判断表态。"""
        out = []
        for j in self.ws.ledger.query("SELECT * FROM judgments WHERE data LIKE '%cited_segments%' "
                                      "OR id IN (SELECT src_id FROM links WHERE rel='used' AND dst_id LIKE 'rd_%')"):
            judgment = self.ws.ledger.get(j["id"])
            changed = []
            for c in self.cited_hashes(judgment):
                art = self.ws.ledger.get(c["artifact_id"])
                if art is None or self.format(art) == "text":
                    continue  # 文本原件不会重新抽取；版本变化由 version_of 传播处理
                current = {s["sha256"]: s for s in self._safe_segments(art)}
                if c["sha256"] not in current:
                    changed.append({**c, "changed_at": self._unit_changed_at(art["id"], c.get("unit"))})
            if not changed:
                continue
            since = max((x["changed_at"] or "" for x in changed), default="")
            later = [lk for lk in self.ws.ledger.links_to(j["id"]) if lk["created_at"] > since]
            if later:
                continue
            out.append({"judgment_id": j["id"], "kind": j["kind"], "text": judgment["data"]["text"][:200],
                        "changed": changed})
        return out

    def _unit_changed_at(self, artifact_id: str, unit: str | None) -> str | None:
        rows = self._rows(artifact_id, "content", unit) if unit else self._rows(artifact_id, "content")
        return rows[-1]["created_at"] if rows else None

    def _safe_segments(self, art: dict) -> list[dict]:
        try:
            return self.segments(art)
        except BurrowlError:
            return []

    # ---------- 内部 ----------
    def _write(self, actor: Actor, art: dict, kind: str, unit: str, data: dict) -> dict:
        return self.ws.ledger.insert("extractions", "ex", {
            "artifact_id": art["id"], "artifact_sha256": art["sha256"], "kind": kind, "unit": unit,
            "actor_id": actor.id, "session_id": actor.session_id, "data": data})

    def _content(self, actor: Actor, art: dict, unit: str, *, status: str, text: str, blocks: list[dict],
                 meta: dict, method: str, fidelity: str | None, reason: str) -> dict | None:
        """写一条 content；与当前那条文本、版式和状态都相同时不写（重复提交不产生新记录）。"""
        blocks_sha = sha256_text(json.dumps(blocks, ensure_ascii=False, sort_keys=True))
        current = self.current(art["id"]).get(unit)
        if current and current["data"]["status"] == status and current["data"].get("blocks_sha256") == blocks_sha:
            return None
        return self._write(actor, art, "content", unit, {
            "status": status, "text": text, "text_sha256": sha256_text(text), "blocks": blocks,
            "blocks_sha256": blocks_sha, "meta": meta, "method": method, "fidelity": fidelity, "reason": reason})

    def _after_write(self, actor: Actor, art: dict, written: list[str]) -> dict:
        """抽取变化后：重建这份原件的索引，找出引用了已变化段落的判断并传播（D-13）。"""
        affected: list[str] = []
        marked: list[str] = []
        if written:
            self.ws.artifacts.index_artifact(art["id"])
            self.ws.linking.link_mentions(art["id"])
            current = {s["sha256"] for s in self._safe_segments(art)}
            ids = {r["id"] for r in self.ws.ledger.query("SELECT id FROM judgments WHERE data LIKE ?",
                                                          (f"%{art['id']}%",))}
            ids |= {r["src_id"] for r in self.ws.ledger.query(
                "SELECT src_id FROM links WHERE rel = 'used' "
                "AND dst_id IN (SELECT id FROM reads WHERE artifact_id = ?)", (art["id"],))}
            for jid in sorted(ids):
                judgment = self.ws.ledger.get(jid)
                if any(c["artifact_id"] == art["id"] and c["sha256"] not in current
                       for c in self.cited_hashes(judgment)):
                    affected.append(jid)
            if affected:
                marked = self.ws.propagation.propagate(affected, reason=f"原件 {art['id']} 的抽取已变化")
        return {"artifact_id": art["id"], "format": self.format(art), "written": written,
                "affected_judgments": affected, "marked": marked}

    # ---------- 状态检查（D-05、D-12、D-13） ----------
    def status_report(self) -> dict:
        """抽取与引用的状态：未抽取或抽取失败的原件、待抽取的图片页、未读先引、引用未确认识别文本、待复核的判断。"""
        unextracted, failed, pending, outdated = [], [], [], []
        for r in self.ws.ledger.query("SELECT id FROM artifacts ORDER BY created_at"):
            art = self.ws.ledger.get(r["id"])
            fmt = self.format(art)
            if fmt in ("text", "binary"):
                continue
            manifest = self.manifest(art["id"])
            title = art["data"].get("title")
            if manifest is None:
                unextracted.append({"artifact_id": art["id"], "title": title, "format": fmt})
                continue
            if manifest["data"].get("error"):
                failed.append({"artifact_id": art["id"], "title": title, "error": manifest["data"]["error"]})
            elif self.outdated(art):
                outdated.append({"artifact_id": art["id"], "title": title, "format": fmt,
                                 "extractor_version": manifest["data"].get("extractor_version", 1)})
            if fmt in AUTO_FORMATS:
                waiting = [u["unit"] for u in self.units(art) if u["status"] == "image"]
                if waiting:
                    pending.append({"artifact_id": art["id"], "title": title, "units": waiting})
        unread, low = [], []
        for j in self.ws.ledger.query("SELECT id, kind, data FROM judgments WHERE data LIKE '%citation_notices%' "
                                      "ORDER BY created_at DESC"):
            for n in j["data"].get("citation_notices", []):
                item = {"judgment_id": j["id"], "kind": j["kind"], "ref": n["ref"], "text": j["data"]["text"][:160]}
                if n["code"] == "UNREAD_CITATION":
                    unread.append(item)
                elif n["code"] == "LOW_FIDELITY_CITATION" and not self._now_verified(n["ref"]):
                    low.append(item)
        return {"unextracted": unextracted, "failed": failed, "image_pages": pending, "outdated": outdated,
                "retire_suggestions": self.retire_suggestions(), "unread_citations": unread,
                "low_fidelity_citations": low, "needs_recheck": self.needs_recheck()}

    def retire_suggestions(self) -> list[dict]:
        """建议退役（设计稿 02 D-15）：登记成独立原件的旧派生文本（metadata.derived_from），
        而它的源原件已经有自己的抽取层。只列出，由人确认后才写退役记录。"""
        retired = self.ws.judgments.retired_ids()
        out = []
        sql = ("SELECT id, json_extract(data, '$.metadata.derived_from') AS src FROM artifacts "
               "WHERE json_extract(data, '$.metadata.derived_from') LIKE 'art_%' ORDER BY created_at")
        for r in self.ws.ledger.query(sql):
            if r["id"] in retired or r["src"] in retired or self.manifest(r["src"]) is None:
                continue
            art, src = self.ws.ledger.get(r["id"]), self.ws.ledger.get(r["src"])
            if art is None or src is None:
                continue
            out.append({"artifact_id": r["id"], "title": art["data"].get("title"), "source_id": r["src"],
                        "source_title": src["data"].get("title"),
                        "reason": f"内容已由 {r['src']} 的抽取层取代"})
        return out

    def _now_verified(self, ref: str) -> bool:
        base, _, anchor = ref.partition("#")
        art = self.ws.ledger.get(base)
        seg = self.find(art, anchor) if art else None
        return bool(seg and seg["verified"])


def _carry_latex(old: list[dict], new: list[dict]) -> list[dict]:
    """重新抽取时，文字相同的公式块保留已提交的 LaTeX（设计稿 03 D-17）。"""
    kept = {b.get("text"): b for b in old if b.get("type") == "formula" and b.get("latex")}
    if not kept:
        return new
    out = []
    for b in new:
        prev = kept.get(b.get("text")) if b.get("type") == "formula" else None
        out.append({**b, "latex": prev["latex"], "latex_source": prev.get("latex_source")} if prev else b)
    return out
