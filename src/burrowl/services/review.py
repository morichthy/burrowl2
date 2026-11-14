"""复核（设计稿 04）：人的复核、AI 复核、请人复核，以及由复核历史折算出的当前状态。

- 复核是被复核条目某一版的变更历史，不是新条目（D-18）：记在账本表 reviews（只追加，带 target_version），
  不进检索、不能被引用。框架页与边的复核状态缓存在框架库的 review 列；判断的复核状态每次从当前版的历史算出，
  复核确认时补充的依据参与依据来源的推出（D-19，services/coordinates.py）。
- 人的复核（submit）只能由人做（I5）。确认两端都是判断的可能矛盾、可能替代边时，直接写一条
  opposes / supersedes 关系，写的人是复核的人，关系的限定里记下复核记录 ID（D-20）。
- AI 复核（ai_submit）是另一种操作：结果记为方式 AI，只能把事情移出人的队列或往前排，不产生
  "人已复核""被驳回"，不写回判断层（D-12 至 D-14）。依据只能来自原件层和判断层，先读后复核（D-13）。
- 请人复核（request）只是加入待决策列表，AI 也可以调用（D-17）。
"""
import hashlib
from datetime import datetime

from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.ids import new_id
from ..core.sql import transaction

# 确认后写回判断层的边（两端都是判断时）；只能由人复核（D-08、D-20）
WRITEBACK_REL = {"may_contradict": "opposes", "may_supersede": "supersedes"}
HUMAN_VERDICTS = ("confirm", "reject")
AI_VERDICTS = ("confirm", "reject", "unsure")
AI_MODES = ("off", "framework", "all")
# 一页 AI 页面成为这么多个其他页面的输入时，才开复核待决策项（D-05）
CONSUMER_THRESHOLD = 2
KIND_OF_PREFIX = {"pg": "page", "edg": "edge", "jdg": "judgment", "art": "artifact"}
VERDICT_LABEL = {"confirm": "确认", "reject": "驳回", "unsure": "拿不准", "request": "请人复核"}


def target_kind(item_id: str) -> str:
    kind = KIND_OF_PREFIX.get(item_id.split("_", 1)[0])
    if kind is None:
        raise BurrowlError("INVALID_ARGUMENT",
                           "复核对象只能是框架页（pg_…）、边（edg_…）、判断（jdg_…）或原件（art_…）",
                           {"item_id": item_id})
    return kind


def writes_back(edge: dict) -> bool:
    return edge["rel"] in WRITEBACK_REL and edge["src_id"].startswith("jdg_") and edge["dst_id"].startswith("jdg_")


class ReviewService:
    is_writeback = staticmethod(writes_back)

    def __init__(self, ws):
        self.ws = ws

    # ---------- 读取 ----------
    def rows(self, target_id: str) -> list[dict]:
        return self.ws.ledger.query("SELECT * FROM reviews WHERE target_id = ? ORDER BY created_at, rowid",
                                    (target_id,))

    def revoked_ids(self, item_id: str) -> set[str]:
        rows = self.ws.ledger.query("SELECT json_extract(data, '$.revokes') AS id FROM reviews "
                                    "WHERE target_id = ? AND json_extract(data, '$.revokes') IS NOT NULL", (item_id,))
        return {r["id"] for r in rows}

    def active_rows(self, item_id: str) -> list[dict]:
        rows = self.rows(item_id)
        revoked = {r["data"]["revokes"] for r in rows if r["data"].get("revokes")}
        return [r for r in rows if r["id"] not in revoked and not r["data"].get("revokes")]

    def history(self, item_id: str) -> dict:
        """一个条目的"复核与变更"：复核、请人复核、AI 复核（含旧版写成判断的复核）；原件另含抽取确认与退役。"""
        if self.ws.inspection.is_finding(item_id):  # 巡检发现：复核员意见与人的处理记在这一项待决策上
            return self.ws.inspection.finding_view(item_id)
        kind = target_kind(item_id)
        page = self.ws.framework.page(item_id) if kind == "page" else None
        revoked = self.revoked_ids(item_id)
        items = []
        for r in self.rows(item_id):
            d = r["data"]
            items.append({"id": r["id"], "created_at": r["created_at"],
                          "type": "review_revoked" if d.get("revokes") else "review", "verdict": r["verdict"],
                          "method": r["method"], "actor_id": r["actor_id"], "session_id": r["session_id"],
                          "reason": d.get("reason") or d.get("note") or "", "cites": d.get("cites") or [],
                          "local_observation": d.get("local_observation", False), "model": d.get("model"),
                          "rel_id": d.get("rel_id"), "version": d.get("version"),
                          "cleared_freshness": d.get("cleared_freshness", False),
                          "target_version": r.get("target_version"),
                          "unit": d.get("unit"), "revokes": d.get("revokes"), "revoked": r["id"] in revoked,
                          "can_revoke": r["method"] == "human" and r["verdict"] in HUMAN_VERDICTS
                          and r["id"] not in revoked and (not page or d.get("version") == page["head_version"]),
                          **({"anchor": d["anchor"], "part": d.get("part"), "suggestion": d.get("suggestion")}
                             if d.get("anchor") else {})})
        if kind == "artifact":
            active = self.ws.extraction.active_verification_ids(item_id)
            current = {r["id"] for r in self.ws.extraction.current(item_id).values()}
            for v in self.ws.ledger.query("SELECT * FROM extractions WHERE artifact_id = ? AND kind = 'verification' "
                                          "ORDER BY created_at", (item_id,)):
                items.append({"id": v["id"], "created_at": v["created_at"], "type": "verification",
                              "verdict": "confirm", "method": "human", "actor_id": v["actor_id"],
                              "unit": v["unit"], "reason": v["data"].get("note") or "",
                              "revoked": v["id"] in revoked,
                              "can_revoke": v["id"] in active and v["data"]["extraction_id"] in current})
            for h in self.ws.judgments.retirement_history(item_id):
                items.append({**h, "type": h["action"], "verdict": h["action"], "method": "human"})
        items.sort(key=lambda x: x["created_at"])
        state = self.state(item_id)
        view = self.ws.frameworks.page_get(item_id) if page and page["freshness"] == "inputs_changed" else None
        stale = ({"freshness": page["freshness"], "inputs": view["inputs"] if view else [],
                  "changed_inputs": view["superseded_inputs"] if view else []} if page else {})
        return {"item_id": item_id, "kind": kind, "items": items, **state, **stale,
                **({"head_version": page["head_version"]} if page else {}),
                "ai_allowed": self.ai_allowed(item_id),
                "open_decision": self.ws.framework.open_decision_for("review", item_id)}

    def state(self, item_id: str) -> dict:
        """当前复核状态。判断：human_reviewed / rejected / ai_reviewed / None，以及复核补充的依据（D-19）；
        框架页与边：review 列。ai_flag：AI 复核认为有问题、人还没有处理（D-14）；ai_unsure：最近一次 AI 复核拿不准。
        判断只看当前版的复核（设计稿 10 D-04）。"""
        kind = target_kind(item_id)
        rows = [r for r in self.active_rows(item_id) if r["verdict"] in AI_VERDICTS]
        if kind == "page":
            page = self.ws.get(item_id) or {}
            rows = [r for r in rows if r["data"].get("version") == page.get("head_version")]
        if kind == "judgment":
            head = self.ws.ledger.head_version(item_id)
            rows = [r for r in rows if r.get("target_version") in (None, head)]
        human = [r for r in rows if r["method"] == "human"]
        ai_all = [r for r in rows if r["method"] == "ai"]
        ai = [r for r in ai_all if r["verdict"] != "unsure"]
        last_h = human[-1]["created_at"] if human else ""
        ai_flag = bool(ai and ai[-1]["verdict"] == "reject" and ai[-1]["created_at"] > last_h)
        if kind in ("page", "edge"):
            item = self.ws.get(item_id) or {}
            return {"review": item.get("review"), "ai_flag": ai_flag}
        if kind == "artifact":
            return {"review": None, "ai_flag": False}
        review = None
        if human:
            review = "human_reviewed" if human[-1]["verdict"] == "confirm" else "rejected"
        elif ai and ai[-1]["verdict"] == "confirm":
            review = "ai_reviewed"
        extra, local = [], False
        for r in rows:
            if r["verdict"] == "confirm":
                extra += r["data"].get("cites") or []
                local = local or (r["method"] == "human" and r["data"].get("local_observation", False))
        ai_unsure = bool(ai_all and ai_all[-1]["verdict"] == "unsure" and not human)
        return {"review": review, "ai_flag": ai_flag, "ai_unsure": ai_unsure,
                "extra_cites": list(dict.fromkeys(extra)), "local": local}

    # ---------- 人的复核（D-10） ----------
    def submit(self, actor: Actor, *, item_id: str, verdict: str, reason: str, cites: list[str] | None = None,
               local_observation: bool = False) -> dict:
        actor.require_human("复核")
        kind = target_kind(item_id)
        if kind == "artifact":
            raise BurrowlError("INVALID_ARGUMENT", "原件的复核就是确认抽取：用 artifact.verify_extraction",
                               {"item_id": item_id})
        if verdict not in HUMAN_VERDICTS:
            raise BurrowlError("INVALID_ARGUMENT", "verdict 必须是 confirm 或 reject")
        if not reason.strip():
            raise BurrowlError("INVALID_ARGUMENT", "请写明复核的理由")
        if local_observation and kind != "judgment":
            raise BurrowlError("INVALID_ARGUMENT", "本地实证只能在复核判断时勾选")
        item = self._item(kind, item_id)
        cites = self._check_cites(cites or [], item_id)
        fw = self.ws.framework
        review_id = new_id("rev")
        data = {"reason": reason, "cites": cites, "local_observation": local_observation,
                **({"version": item["head_version"]} if kind == "page" else {})}
        # 人在输入变化之后确认页面，就是核对过变化的输入、认为页面仍然成立：同时让时效回到有效（D-103）。
        # 只清除"输入已变化"；"未核查"（传播超限、没人看过）与"被替代"不靠一次确认清除
        clears = kind == "page" and verdict == "confirm" and item["freshness"] == "inputs_changed"
        if clears:
            data["cleared_freshness"] = True
            view = self.ws.frameworks.page_get(item_id)
            data["inputs"], data["changed_inputs"] = view["inputs"], view["superseded_inputs"]
        touched = []
        if kind == "edge" and verdict == "confirm" and writes_back(item):
            data["prior_origin"] = item["origin"]
            rel = self.ws.ledger.relate(WRITEBACK_REL[item["rel"]], item["src_id"], item["dst_id"], actor.id,
                                        session_id=actor.session_id,
                                        qualifiers={"review_id": review_id, "edge_id": item_id, "reason": reason})
            data["rel_id"] = rel["id"]
            touched = [item["src_id"], item["dst_id"]]
        self._insert(review_id, actor, item_id, kind, verdict, "human", data)
        state = None
        if kind in ("page", "edge"):
            state = "human_reviewed" if verdict == "confirm" else "rejected"
            fw.set_state(kind, item_id, review=state)
            if clears:
                fw.set_state("page", item_id, freshness="valid")
                rederive = fw.open_decision_for("rederive", item_id)
                if rederive:
                    fw.close_decision(rederive["id"], "resolved", {"review_id": review_id, "by": actor.id,
                                                                    "cleared": "inputs_changed"})
            if data.get("rel_id"):
                fw.set_state("edge", item_id, origin="projection")
                fw.add_inputs("edge", item_id, 1, [data["rel_id"]])
        else:
            touched = [item_id]  # 复核改变判断的现状与依据来源：用到它的框架页标为输入已变化（I6）
            state = self.state(item_id)["review"]
        marked = self.ws.propagation.propagate(touched, reason=f"复核 {review_id}") if touched else []
        for d in fw.decisions(kind="review"):
            if d["subject_id"] == item_id:
                fw.close_decision(d["id"], "resolved", {"verdict": verdict, "review_id": review_id, "by": actor.id})
        self.ws.capture.log(actor, "review.submit", input={"item_id": item_id, "verdict": verdict,
                                                           "review_id": review_id})
        return {"review_id": review_id, "item_id": item_id, "verdict": verdict, "review": state,
                "rel_id": data.get("rel_id"), "marked": marked}

    def revoke(self, actor: Actor, *, item_id: str, record_ids: list[str], reason: str) -> dict:
        """撤销选中的人工记录。账本只追加；框架缓存按剩余有效记录重算。"""
        actor.require_human("撤销复核")
        kind = target_kind(item_id)
        item = self._item(kind, item_id)
        if not reason.strip() or not record_ids:
            raise BurrowlError("INVALID_ARGUMENT", "请选择要撤销的记录并填写理由")
        history = {r["id"]: r for r in self.history(item_id)["items"]}
        selected = []
        for rid in dict.fromkeys(record_ids):
            row = history.get(rid)
            if row and row.get("revoked"):
                continue  # 网络重试不会再写一次撤销
            if not row or not row.get("can_revoke"):
                raise BurrowlError("REVIEW_NOT_ALLOWED", "该记录不能撤销，或当前版本已变化", {"record_id": rid})
            selected.append(row)
        if not selected:
            return {"item_id": item_id, "revoked": []}
        revoked = [r["id"] for r in selected]
        with transaction(self.ws.ledger.conn):
            for row in selected:
                # 沿用兼容旧账本的 verdict 取值，用独立数据字段区分撤销与请人复核。
                self._insert(new_id("rev"), actor, item_id, kind, "request", "human",
                             {"revokes": row["id"], "reason": reason.strip(), "unit": row.get("unit"),
                              "revoked_rel_id": row.get("rel_id"), "version": row.get("version")})
        touched = [item_id]
        active = [r for r in self.active_rows(item_id) if r["verdict"] in AI_VERDICTS]
        fw = self.ws.framework
        if kind == "page":
            active = [r for r in active if r["data"].get("version") == item["head_version"]]
        human = [r for r in active if r["method"] == "human"]
        if kind in ("page", "edge"):
            human_authored = kind == "page" and not item["data"].get("ai_written", True)
            state = "human_reviewed" if human_authored else "ai_generated"
            if any(r["verdict"] == "confirm" and r["method"] == "ai" for r in active):
                state = "ai_reviewed"
            if human:
                state = "human_reviewed" if human[-1]["verdict"] == "confirm" else "rejected"
            fields = {"review": state}
            links = [r["rel_id"] for r in selected if r.get("rel_id")]
            if kind == "edge" and links:
                fw.remove_edge_inputs(item_id, links)
                if not any(r["data"].get("rel_id") for r in human):
                    first = next(r for r in self.rows(item_id) if r["data"].get("rel_id"))
                    original = first["data"].get("prior_origin")
                    fields["origin"] = original or ("ai_inferred" if str(item["data"].get("by", "")).startswith("ai:")
                                                    else "candidate")
                touched += [item["src_id"], item["dst_id"]]
            fw.set_state(kind, item_id, **fields)
            if kind == "page":  # 撤销了清除"输入已变化"的那次确认：时效恢复，重新综合重新列入待决策（D-103）
                raw = {r["id"]: r for r in self.rows(item_id)}
                undone = any(raw[rid]["data"].get("cleared_freshness") for rid in revoked if rid in raw)
                still = any(r["data"].get("cleared_freshness") for r in human if r["verdict"] == "confirm")
                if undone and not still and fw.page(item_id)["freshness"] == "valid":
                    fw.set_state("page", item_id, freshness="inputs_changed")
                    if not fw.open_decision_for("rederive", item_id):
                        why = f"撤销复核：{reason.strip()}；输入已变化，需要重新综合"
                        fw.add_decision("rederive", item_id, 1, {"reason": why, "title": item["title"]})
        if kind != "artifact" and not human:
            relevant = {h["id"] for h in history.values() if (h["id"] in revoked or h.get("revoked"))
                        and (kind != "page" or h.get("version") == item["head_version"])}
            closed = next((d for d in fw.decisions("resolved", "review") if d["subject_id"] == item_id
                           and d["data"].get("resolution", {}).get("review_id") in relevant), None)
            if closed:
                self._open_decision(item_id, kind, impact=closed["impact"],
                                    requested=bool(closed["data"].get("requested")),
                                    note={"by": actor.id, "note": f"撤销复核：{reason.strip()}"})
        self.ws.propagation.propagate(touched, reason=f"撤销复核或抽取确认：{reason.strip()}")
        self.ws.capture.log(actor, "review.revoke", input={"item_id": item_id, "record_ids": revoked})
        return {"item_id": item_id, "revoked": revoked}

    # ---------- 请人复核（D-17） ----------
    def request(self, actor: Actor, *, item_id: str, note: str) -> dict:
        kind = target_kind(item_id)
        self._item(kind, item_id)
        if not note.strip():
            raise BurrowlError("INVALID_ARGUMENT", "请写一句要看什么")
        review_id = new_id("rev")
        self._insert(review_id, actor, item_id, kind, "request", "human" if actor.kind == "human" else "ai",
                     {"note": note})
        decision = self._open_decision(item_id, kind, impact=1, requested=True,
                                       note={"review_id": review_id, "by": actor.id, "note": note})
        return {"review_id": review_id, "decision_id": decision["id"]}

    # ---------- AI 复核（D-12 至 D-15） ----------
    def ai_allowed(self, item_id: str) -> str | None:
        """这个条目现在能否交给 AI 复核；不能时返回原因，能时返回 None。"""
        try:
            self._ai_target(item_id)
        except BurrowlError as e:
            return e.message
        return None

    def _ai_target(self, item_id: str) -> tuple[str, dict]:
        mode = self.ws.config.get("review", {}).get("ai", "framework")
        if mode == "off":
            raise BurrowlError("REVIEW_DISABLED", "这个数据目录关闭了 AI 复核（设置 review.ai）")
        kind = target_kind(item_id)
        if kind == "artifact":
            raise BurrowlError("REVIEW_NOT_ALLOWED", "原件的确认抽取只能由人做")
        if kind == "judgment" and mode != "all":
            raise BurrowlError("REVIEW_DISABLED", "这个数据目录只允许 AI 复核框架页与关联边（设置 review.ai）")
        item = self._item(kind, item_id)
        if kind in ("page", "edge") and item["review"] not in ("ai_generated", "ai_reviewed"):
            raise BurrowlError("REVIEW_NOT_ALLOWED", "只有 AI 生成且尚未由人处理的框架条目可以由 AI 复核",
                               {"review": item["review"]})
        if kind == "edge" and writes_back(item):
            raise BurrowlError("REVIEW_NOT_ALLOWED",
                               "两端都是判断的可能矛盾、可能替代，确认后会写回判断层，只能由人复核")
        if kind == "judgment" and not (self.ws.extraction.recheck_entry(item_id)
                                       or self.ws.framework.open_decision_for("review", item_id)):
            rows = [r for r in self.active_rows(item_id) if r["verdict"] in AI_VERDICTS]
            if not rows or any(r["method"] == "human" for r in rows):
                raise BurrowlError("REVIEW_NOT_ALLOWED", "判断须处于待复核，或已有 AI 复核且尚未由人处理")
        return kind, item

    def ai_submit(self, actor: Actor, *, item_id: str, verdict: str, reason: str, model: str,
                  cites: list[str] | None = None, proposed_change: str = "", proposed_kind: str = "",
                  proposed_conditions: str = "", proposed_reopen_condition: str = "") -> dict:
        if self.ws.inspection.is_finding(item_id):  # 巡检发现（一项待决策）的二次检查（设计稿 08 D-20、§9）
            return self.ws.inspection.ai_review(actor, decision_id=item_id, verdict=verdict, reason=reason,
                                                model=model, cites=cites, proposed_change=proposed_change,
                                                proposed_kind=proposed_kind, proposed_conditions=proposed_conditions,
                                                proposed_reopen_condition=proposed_reopen_condition)
        if proposed_change.strip() or proposed_kind or proposed_conditions or proposed_reopen_condition:
            raise BurrowlError("INVALID_ARGUMENT", "修改意见只用于巡检发现的复核")
        if actor.kind != "ai":
            raise BurrowlError("FORBIDDEN", "AI 复核只给 AI 用；人请用 review.submit")
        if verdict not in AI_VERDICTS:
            raise BurrowlError("INVALID_ARGUMENT", "verdict 必须是 confirm / reject / unsure")
        if not reason.strip():
            raise BurrowlError("INVALID_ARGUMENT", "请写明理由")
        if not (model or "").strip():
            raise BurrowlError("INVALID_ARGUMENT", "请在 model 里写明模型（如 claude-opus-5-5）")
        kind, item = self._ai_target(item_id)
        if self._session_of(kind, item) == actor.session_id:
            raise BurrowlError("SAME_SESSION", "不能复核本会话自己写的条目；请换一个会话复核")
        cites = self._check_cites(cites or [], item_id)
        if verdict != "unsure":
            if not cites:
                raise BurrowlError("INVALID_ARGUMENT", "确认或驳回至少要一条依据（原件段落、事实记录、判断）；"
                                   "拿不准时交 unsure")
            self._check_relevant(kind, item, cites)
            low = self._check_read(actor, cites)
            if verdict == "confirm" and low and len(low) == len(cites):
                raise BurrowlError("LOW_FIDELITY_REVIEW",
                                   "依据只有未经人确认的 OCR / AI 识别段落，不能确认；请交 unsure", {"refs": low})
        review_id = new_id("rev")
        self._insert(review_id, actor, item_id, kind, verdict, "ai",
                     {"reason": reason, "cites": cites, "model": model,
                      **({"version": item["head_version"]} if kind == "page" else {})})
        fw = self.ws.framework
        entry = {"review_id": review_id, "verdict": verdict, "reason": reason, "model": model, "by": actor.id}
        decision = None
        if verdict == "confirm":
            if kind in ("page", "edge"):
                fw.set_state(kind, item_id, review="ai_reviewed")
            open_d = fw.open_decision_for("review", item_id)
            if open_d and open_d["data"].get("requested"):  # 由"请人复核"开出的不关闭，只附上 AI 的结论
                decision = self._annotate(open_d, entry)
            elif open_d:
                decision = fw.close_decision(open_d["id"], "resolved", {**entry, "by_ai": True})
        else:
            decision = self._open_decision(item_id, kind, impact=1 if verdict == "unsure" else 2, note=entry,
                                           requested=verdict == "unsure")
            if verdict == "reject" and decision["impact"] < 2:
                fw.update_decision(decision["id"], impact=decision["impact"] + 1)
        self.ws.capture.log(actor, "review.ai_submit", input={"item_id": item_id, "verdict": verdict,
                                                              "review_id": review_id, "model": model})
        return {"review_id": review_id, "item_id": item_id, "verdict": verdict,
                "review": self.state(item_id)["review"], "decision_id": decision["id"] if decision else None}

    # ---------- 抽查（D-07） ----------
    def sample(self, size: int | None = None, *, at: datetime | None = None) -> dict:
        """本周抽查：从 AI 生成未复核的框架页里按周固定地挑几页（同一周每次结果相同）。"""
        size = size or int(self.ws.config.get("review", {}).get("sample_size", 5))
        year, week, _ = (at or datetime.now()).isocalendar()
        key = f"{year}-W{week:02d}"
        pages = self.ws.framework.pages()
        pool = [p for p in pages if p["review"] == "ai_generated"]
        pool.sort(key=lambda p: hashlib.sha256(f"{key}:{p['id']}".encode()).hexdigest())
        return {"week": key, "pool": len(pool),
                "pages": [{"id": p["id"], "title": p["title"], "type": p["type"], "freshness": p["freshness"],
                           "updated_at": p["updated_at"]} for p in pool[:size]]}

    # ---------- 按需复核的触发（D-05） ----------
    def page_consumers(self, page_id: str) -> list[str]:
        """以这一页（任一版本）为当前输入的其他框架页。"""
        rows = self.ws.framework.conn.execute(
            "SELECT DISTINCT di.derived_id FROM derivation_inputs di JOIN pages p ON p.id = di.derived_id "
            "WHERE di.derived_kind = 'page' AND di.derived_version = p.head_version AND di.derived_id != ? "
            "AND (di.input_id = ? OR di.input_id LIKE ?)", (page_id, page_id, f"{page_id}@%"))
        return [r[0] for r in rows]

    def on_page_inputs(self, inputs: list[str]) -> list[str]:
        """新页面写入后：它用到的 AI 页面若已成为两个以上页面的输入，开复核待决策项。"""
        opened = []
        for ref in inputs:
            base = ref.split("@", 1)[0].split("#", 1)[0]
            if not base.startswith("pg_"):
                continue
            page = self.ws.framework.page(base)
            if not page or page["review"] not in ("ai_generated", "ai_reviewed"):
                continue
            consumers = self.page_consumers(base)
            if len(consumers) >= CONSUMER_THRESHOLD and not self.ws.framework.open_decision_for("review", base):
                self.ws.framework.add_decision("review", base, len(consumers), {
                    "what": f"{page['type']} 页面", "title": page["title"], "trigger": "consumers",
                    "consumers": consumers, "note": f"已成为 {len(consumers)} 个页面的输入"})
                opened.append(base)
        return opened

    # ---------- 内部 ----------
    def _insert(self, review_id: str, actor: Actor, item_id: str, kind: str, verdict: str, method: str,
                data: dict) -> dict:
        version = self.ws.ledger.head_version(item_id) if kind in ("judgment", "artifact") else \
            data.get("version")
        return self.ws.ledger.insert("reviews", "rev", {
            "id": review_id, "target_id": item_id, "target_version": version, "target_kind": kind,
            "verdict": verdict, "method": method, "actor_id": actor.id, "session_id": actor.session_id,
            "data": data})

    def _item(self, kind: str, item_id: str) -> dict:
        item = self.ws.get(item_id)
        if item is None:
            raise BurrowlError("NOT_FOUND", "复核对象不存在", {"item_id": item_id})
        return item

    def _label(self, kind: str, item_id: str) -> dict:
        item = self.ws.get(item_id) or {}
        if kind == "page":
            return {"what": f"{item.get('type')} 页面", "title": item.get("title")}
        if kind == "edge":
            return {"what": f"关系 {item.get('rel')}", "src_id": item.get("src_id"), "dst_id": item.get("dst_id")}
        if kind == "judgment":
            return {"what": "判断", "title": (item.get("data") or {}).get("text", "")[:80]}
        return {"what": "原件", "title": (item.get("data") or {}).get("title")}

    def _open_decision(self, item_id: str, kind: str, *, impact: int, note: dict, requested: bool = False) -> dict:
        fw = self.ws.framework
        current = fw.open_decision_for("review", item_id)
        if current:
            if requested and not current["data"].get("requested"):
                fw.update_decision(current["id"], data={**current["data"], "requested": True})
                current = fw.decision(current["id"])
            if current["impact"] < impact:
                fw.update_decision(current["id"], impact=impact)
            return self._annotate(fw.decision(current["id"]), note)
        return fw.add_decision("review", item_id, impact, {**self._label(kind, item_id), "requested": requested,
                                                           "notes": [note]})

    def _annotate(self, decision: dict, note: dict) -> dict:
        data = {**decision["data"], "notes": [*decision["data"].get("notes", []), note]}
        self.ws.framework.update_decision(decision["id"], data=data)
        return self.ws.framework.decision(decision["id"])

    def _check_cites(self, cites: list[str], item_id: str) -> list[str]:
        """补充的依据只能来自原件层和判断层（I2）；不能是过程内容，也不能是被复核的条目本身（D-13 ②）。"""
        cites = list(dict.fromkeys(c.strip() for c in cites if c and c.strip()))
        for ref in cites:
            if ref.split("#", 1)[0].split("@", 1)[0] == item_id:
                raise BurrowlError("INVALID_ARGUMENT", "不能以被复核的条目本身为依据", {"ref": ref})
            target = self.ws.relations.target(ref)
            if target.get("kind") == "process":
                raise BurrowlError("PROCESS_NOT_EVIDENCE", "过程内容不能作为复核的依据", {"refs": [ref]})
            if ref.startswith("art_") and "#" in ref:
                self.ws.extraction.citation(Actor("system:review", "system", "ses_system"), ref)  # 段落必须存在
        return cites

    def _relevant_refs(self, kind: str, item: dict) -> set[str]:
        fw = self.ws.framework
        if kind == "page":
            refs = set(fw.inputs_of("page", item["id"], item["head_version"]))
        else:
            refs = set(fw.inputs_of("edge", item["id"], 1)) | {item["src_id"], item["dst_id"]}
        for ref in list(refs):
            base = ref.split("@", 1)[0].split("#", 1)[0]
            refs.add(base)
            if base.startswith("jdg_"):
                for r in self.ws.ledger.relations_from(base, "cites"):
                    refs.update({r["object"], r["object_id"], f"{r['object_id']}#{r['object_anchor']}"})
        return refs

    def _check_relevant(self, kind: str, item: dict, cites: list[str]) -> None:
        """依据要相关（D-13 ③）。"""
        if kind == "judgment":
            entry = self.ws.extraction.recheck_entry(item["id"])
            changed = {c["artifact_id"] for c in (entry or {}).get("changed", [])}
            if not changed:  # 被请人复核、依据没变：至少一条依据是它原来引用的条目
                changed = {r["object_id"] for r in self.ws.ledger.relations_from(item["id"], "cites",
                                                                                 version=item["version"])}
                if any(c.split("#", 1)[0].split("@", 1)[0] in changed for c in cites):
                    return
                raise BurrowlError("IRRELEVANT_EVIDENCE", "依据要包括这条判断原来引用的原件或条目")
            if any(c.startswith("art_") and "#" in c and c.split("#", 1)[0].split("@", 1)[0] in changed
                   for c in cites):
                return
            raise BurrowlError("IRRELEVANT_EVIDENCE", "复核依据已变化的判断，至少一条依据要是那份原件当前的段落",
                               {"artifacts": sorted(changed)})
        allowed = self._relevant_refs(kind, item)
        if not any(c in allowed or c.split("#", 1)[0].split("@", 1)[0] in allowed for c in cites):
            raise BurrowlError("IRRELEVANT_EVIDENCE", "至少一条依据要出现在被复核条目的输入清单里，"
                               "或是输入清单中判断所引用的条目", {"inputs": sorted(allowed)[:30]})

    def _check_read(self, actor: Actor, cites: list[str]) -> list[str]:
        """先读后复核（D-13 ④）：引用的原件段落本会话必须读过。返回其中未经确认的识别段落。"""
        low = []
        for ref in cites:
            if not ref.startswith("art_"):
                continue
            if "#" in ref:
                c = self.ws.extraction.citation(actor, ref, same_session=True)
                if "UNREAD_CITATION" in c["notices"]:
                    raise BurrowlError("UNREAD_REVIEW", "复核前要先用 artifact_read 读过引用的段落", {"ref": ref})
                if "LOW_FIDELITY_CITATION" in c["notices"]:
                    low.append(ref)
            elif not self.ws.ledger.query("SELECT id FROM reads WHERE artifact_id = ? AND actor_id = ? "
                                          "AND (session_id = ? OR session_id IS NULL) LIMIT 1",
                                          (ref, actor.id, actor.session_id)):
                raise BurrowlError("UNREAD_REVIEW", "复核前要先用 artifact_read 读过引用的原件", {"ref": ref})
        return low

    def _session_of(self, kind: str, item: dict) -> str | None:
        """写下这个条目的会话（D-13 ⑥；设计稿 04 §6 未决 5）。"""
        if kind == "judgment":
            return item.get("session_id")
        if kind == "edge":
            return (item.get("data") or {}).get("session_id")
        ver = self.ws.framework.page_version(item["id"], item["head_version"])
        if ver and ver["data"].get("session_id"):
            return ver["data"]["session_id"]
        for ev in self.ws.ledger.query("SELECT session_id, data FROM events WHERE op = 'framework.page_write' "
                                       "AND data LIKE ? ORDER BY created_at DESC", (f"%{item['id']}%",)):
            inp = (ev["data"] or {}).get("input") or {}
            if inp.get("page_id") == item["id"] and inp.get("version") == item["head_version"]:
                return ev["session_id"]
        return None
