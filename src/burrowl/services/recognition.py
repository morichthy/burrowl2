"""识别结果的 AI 核对（设计稿 04 D-22 至 D-25）：OCR / AI 识别的文字与公式 LaTeX，由人点击后交给大模型看图核对。

- 对象：未经人确认、可信度档为 OCR / AI 识别的段落块（part=text），以及未经人确认、来源为 OCR / AI 识别的
  公式 LaTeX（part=latex）。每次从抽取层算出，不写待决策表。
- 由工作台在后台任务里直接调用设置里的大模型（人显式点击，符合设计稿 05 §2）；框架页、边、判断仍交给 AI 客户端。
- 结果记在账本表 reviews（target_kind=artifact，method=ai），数据记 anchor、extraction_id、part、model、reason、
  suggestion。只在这条抽取（extraction_id）不变时有效；不等于人已确认，可信度档不变（D-24）。
"""
from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.ids import new_id
from . import extractors as ex
from . import model_adapters as ma
from .extraction import LOW_FIDELITY, crop_box

LLM_ACTOR = Actor("system:llm", "system", "ses_system")
MAX_ITEMS = 300  # 一次任务最多核对这么多块


class RecognitionReview:
    def __init__(self, ws):
        self.ws = ws

    # ---------- 读取 ----------
    def checks(self, artifact_id: str) -> dict[tuple[str, str, str], dict]:
        """(anchor, part, extraction_id) → 最近一次 AI 核对。"""
        out = {}
        for r in self.ws.reviews.rows(artifact_id):
            d = r["data"]
            if r["method"] != "ai" or not d.get("anchor") or not d.get("part"):
                continue
            out[(d["anchor"], d["part"], d.get("extraction_id") or "")] = {
                "review_id": r["id"], "verdict": r["verdict"], "reason": d.get("reason", ""),
                "suggestion": d.get("suggestion"), "model": d.get("model"), "created_at": r["created_at"]}
        return out

    def items(self, artifact_id: str) -> list[dict]:
        """一份原件里待确认的识别：每块一项，带当前文字或 LaTeX 与最近一次 AI 核对。"""
        ext = self.ws.extraction
        art = self.ws.artifacts._artifact(artifact_id)
        if ext.format(art) == "text":
            return []
        current = ext.current(artifact_id)
        checks = self.checks(artifact_id)
        out = []
        for seg in ext._safe_segments(art):
            if seg["verified"] or seg.get("block") is None:
                continue
            row = current.get(seg["unit"])
            blocks = (row or {}).get("data", {}).get("blocks") or []
            block = blocks[seg["block"]] if seg["block"] < len(blocks) else {}
            if block.get("type") == "formula":
                src = block.get("latex_source") or {}
                if not block.get("latex") or src.get("fidelity") not in LOW_FIDELITY:
                    continue
                part, text = "latex", block["latex"]
            elif seg["fidelity"] in LOW_FIDELITY:
                part, text = "text", seg["text"]
            else:
                continue
            item = {"anchor": seg["anchor"], "unit": seg["unit"], "part": part, "text": text,
                    "extraction_id": seg.get("extraction_id"), "fidelity": seg["fidelity"]}
            ai = checks.get((seg["anchor"], part, seg.get("extraction_id") or ""))
            if ai:
                item["ai"] = ai
            out.append(item)
        return out

    def summary(self) -> list[dict]:
        """待决策页"待确认的识别"：每份原件一行；被判断引用过的排在前面（D-25）。"""
        ext = self.ws.extraction
        retired = self.ws.judgments.retired_ids()
        rows = []
        for r in self.ws.ledger.query("SELECT DISTINCT artifact_id FROM extractions WHERE kind = 'content'"):
            aid = r["artifact_id"]
            if aid in retired:
                continue
            try:
                items = self.items(aid)
            except BurrowlError:
                continue
            if not items:
                continue
            art = self.ws.ledger.get(aid)
            verdicts = [i["ai"]["verdict"] for i in items if i.get("ai")]
            rows.append({"artifact_id": aid, "title": art["data"].get("title"), "format": ext.format(art),
                         "text": sum(1 for i in items if i["part"] == "text"),
                         "latex": sum(1 for i in items if i["part"] == "latex"),
                         "ai_confirmed": verdicts.count("confirm"), "ai_rejected": verdicts.count("reject"),
                         "ai_unsure": verdicts.count("unsure"),
                         "unchecked": sum(1 for i in items if not i.get("ai")),
                         "cited": ext.is_cited(aid)})
        rows.sort(key=lambda x: (not x["cited"], -x["ai_rejected"], -(x["text"] + x["latex"])))
        return rows

    def allowed(self) -> str | None:
        if self.ws.config.get("review", {}).get("ai", "framework") == "off":
            return "这个数据目录关闭了 AI 复核（设置 → 复核）"
        if not self.ws.models.configured("llm"):
            return "还没有配置大模型（设置 → 模型与引擎）"
        return None

    # ---------- 交给 AI ----------
    def enqueue(self, actor: Actor, artifact_ids: list[str], *, anchors: list[str] | None = None,
                repeat: bool = False) -> list[dict]:
        actor.require_human("调用大模型核对识别结果")
        reason = self.allowed()
        if reason:
            raise BurrowlError("REVIEW_DISABLED", reason)
        jobs = []
        for aid in dict.fromkeys(artifact_ids):
            self.ws.artifacts._artifact(aid)
            jobs.append(self.ws.models.enqueue("ai_check", aid, by=actor.id,
                                               params={"anchors": list(anchors or []), "repeat": repeat}))
        return jobs

    def run(self, job: dict) -> dict:
        """后台任务：逐块看图核对。调用模型期间不持有数据目录的锁。"""
        ws = self.ws
        with ws.lock:
            aid = job["artifact_id"]
            wanted = set(job["params"].get("anchors") or [])
            repeat = job["params"].get("repeat", False)
            todo = [i for i in self.items(aid) if (not wanted or i["anchor"] in wanted)
                    and (wanted or bool(i.get("ai")) == repeat)][:MAX_ITEMS]
            crops = [(i, self._image(aid, i)) for i in todo]
            cfg = dict(ws.models.cfg)
            url = ws.models.url("llm")
            agent, answer = ws.models.llm_agent()
        model = agent or cfg.get("llm_model") or ""
        results = []
        for item, png in crops:
            if png is None:
                results.append((item, {"verdict": "unsure", "reason": "这一块没有可裁切的原件图像"}))
                continue
            try:
                if answer:
                    result = ma.parse_check(answer(ma.check_prompt(item["part"], item["text"]), png), item["part"])
                else:
                    result = ma.llm_check(url, cfg.get("llm_key") or "", model, png, item["part"], item["text"])
                results.append((item, result))
            except BurrowlError as exc:
                results.append((item, {"verdict": "unsure", "reason": f"调用大模型失败：{exc.message}"}))
        counts = {"confirm": 0, "reject": 0, "unsure": 0}
        with ws.lock:
            for item, r in results:
                verdict = r.get("verdict") if r.get("verdict") in counts else "unsure"
                counts[verdict] += 1
                ws.ledger.insert("reviews", "rev", {
                    "id": new_id("rev"), "target_id": aid, "target_kind": "artifact", "verdict": verdict,
                    "method": "ai", "actor_id": LLM_ACTOR.id, "session_id": LLM_ACTOR.session_id,
                    "data": {"anchor": item["anchor"], "part": item["part"], "extraction_id": item["extraction_id"],
                             "model": model, "reason": (r.get("reason") or "")[:1000],
                             "requested_by": job["by"],
                             **({"suggestion": r["suggestion"][:4000]} if r.get("suggestion") else {})}})
        return {"artifact_id": aid, "checked": len(results), **counts}

    def _image(self, artifact_id: str, item: dict) -> bytes | None:
        ext = self.ws.extraction
        art = self.ws.artifacts._artifact(artifact_id)
        fmt = ext.format(art)
        unit = next((u for u in ext.units(art) if u["unit"] == item["unit"]), None)
        if unit is None:
            return None
        seg = ext.find(art, item["anchor"])
        blocks = unit.get("blocks") or []
        block = blocks[seg["block"]] if seg and seg.get("block") is not None and seg["block"] < len(blocks) else {}
        if unit.get("page") and fmt in ("pdf", "pptx", "docx", "xlsx"):
            try:
                if block.get("box"):
                    return ext.page_image(artifact_id, unit["page"], source="auto", scale=3.0, clip=crop_box(block))
                return ext.page_image(artifact_id, unit["page"], scale=2.0)
            except BurrowlError:
                return None
        if fmt == "image":
            return ex.downscale_image(self.ws.artifacts.content(art))[0]
        return None

