"""坐标（设计稿 10 D-12 至 D-16）：读取时从事实与关系推出，不落盘。

四组，显示顺序"地位 → 类型 → 现状 → 说明"：
- 地位：layer（综合程度）× sources（依据来源记号）。sources 只看本条目这一版自己的 cites（以及人勾的本地实证、
  人复核时补充的依据），不因别人后来的佐证或反驳改变（D-13）；
- 类型：kind；
- 现状：state = {validity, review, marks}；
- 说明：notes = {author, quoted, marks}。

每个标记是 {mark, via: [{rel, end, detail}]}：via 指向造成它的那条关系与另一端（D-14），由条目自身事实或人的处置
推出的标记 via 为空或指向那次处置。坐标字段的来源见设计稿 10"坐标字段"表的最后一列。
"""
from ..core.ids import make_ref, parse_ref
from ..core.vocab import REVIEW, SOURCE_LABELS, sort_sources, source_of, standing_label, status_note

_PAGE_REVIEW = {"ai_reviewed": "ai_confirmed", "human_reviewed": "human_confirmed", "rejected": "human_rejected"}
_REVIEW_STATE = {"human_reviewed": "human_confirmed", "rejected": "human_rejected", "ai_reviewed": "ai_confirmed"}
_RECOGNITION = {"unchecked": "未核对", "ai_confirmed": "AI 核对一致", "ai_flagged": "AI 认为有问题",
                "ai_unsure": "AI 拿不准"}
LOW_FIDELITY = ("ocr", "ai")


class CoordinateService:
    def __init__(self, ws):
        self.ws = ws

    # ---------- 入口 ----------
    def of(self, ref: str, *, memo: dict | None = None) -> dict | None:
        """一个条目某一版（不带 @n 指当前版）的完整坐标；条目不存在时为 None。"""
        memo = {} if memo is None else memo
        base, version, _ = parse_ref(ref)
        prefix = base.split("_", 1)[0]
        if prefix in ("pg", "edg", "ent"):
            return self._framework(base, version)
        entry = self.ws.ledger.get(make_ref(base, version))
        if entry is None or entry.get("entry_kind") not in ("artifact", "event", "record", "read", "judgment"):
            return None
        key = ("coords", entry["ref"])
        if key in memo:
            return memo[key]
        memo[key] = None  # 环：先占位
        memo[key] = self._judgment(entry, memo) if entry["entry_kind"] == "judgment" else self._original(entry, memo)
        return memo[key]

    def note(self, coords: dict) -> str:
        return status_note(coords)

    def ref_status(self, ref: str) -> dict:
        """一个引用（带版本与段落）现在的状况：有效性、一行说明；所引不是当前版时给出当前版的引用。"""
        base, version, anchor = parse_ref(ref)
        try:
            coords = self.of(make_ref(base, version))
        except Exception:  # noqa: BLE001 —— 引用格式不对或条目已删除：如实报缺失
            coords = None
        if coords is None:
            return {"missing": True}
        out = {"validity": coords["state"]["validity"], "status_note": status_note(coords)}
        head = parse_ref(self.of(base)["ref"])[1] if version else None
        if version and head and version < head:
            out["current_ref"] = make_ref(base, head, anchor)
        if anchor and base.startswith("art_"):
            art = self.ws.ledger.get(make_ref(base, version))
            try:
                found = self.ws.extraction.find(art, anchor) if art else None
            except Exception:  # noqa: BLE001
                found = None
            if found is None:
                out["anchor_missing"] = True
        return out

    def compact(self, coords: dict) -> dict:
        """返回给 AI 的坐标（D-21）：正常值省略，标记只给名字与处数。"""
        state = coords.get("state") or {}
        notes = coords.get("notes") or {}
        out = {"ref": coords["ref"], "layer": coords["layer"], "sources": coords["sources"], "kind": coords["kind"]}
        st = {}
        if state.get("validity", "current") != "current":
            st["validity"] = state["validity"]
        if state.get("review", "none") != "none":
            st["review"] = state["review"]
        if state.get("marks"):
            st["marks"] = [_count(m) for m in state["marks"]]
        if st:
            out["state"] = st
        nt = {"author": notes.get("author")}
        if notes.get("quoted"):
            nt["quoted"] = notes["quoted"]
        if notes.get("marks"):
            nt["marks"] = [_count(m) for m in notes["marks"]]
        out["notes"] = nt
        return out

    # ---------- 地位：依据来源 ----------
    def sources(self, ref: str, memo: dict | None = None) -> list[str]:
        """某一版的依据来源记号（D-13）。"""
        memo = {} if memo is None else memo
        key = ("sources", ref)
        if key in memo:
            return memo[key]
        memo[key] = []  # 环：先占位
        base, version, _ = parse_ref(ref)
        entry = self.ws.ledger.get(make_ref(base, version))
        out: list[str] = []
        if entry is None:
            out = []
        elif entry["entry_kind"] == "artifact":
            out = [source_of(entry["source_class"], entry["data"].get("external_tier"))]
        elif entry["entry_kind"] == "event":
            out = [entry["data"].get("source_class", "local")]
        elif entry["entry_kind"] == "record":
            origin = entry.get("event_id") or entry.get("artifact_id")
            out = self.sources(origin, memo) if origin else []
        elif entry["entry_kind"] == "read":
            out = self.sources(make_ref(entry["artifact_id"], entry.get("artifact_version")), memo)
        elif entry["entry_kind"] == "judgment":
            out = self._judgment_sources(entry, memo)
        memo[key] = sort_sources(out)
        return memo[key]

    def _judgment_sources(self, j: dict, memo: dict) -> list[str]:
        cites = self._basis_refs(j)
        local = bool(j["data"].get("local_observation"))
        review = self.ws.reviews.state(j["id"])
        local = local or bool(review.get("local"))
        if not cites:
            if j["kind"] == "normative" and not local:
                return []
            return ["local"] if local else ["inferred"]
        out = set()
        for ref in cites:
            out.update(self.sources(ref.split("#", 1)[0], memo))
        if local:
            out.add("local")
        return sorted(out)

    def _basis_refs(self, j: dict) -> list[str]:
        """这一版的依据：出边 cites，加上人或 AI 复核确认时补充的依据（设计稿 04 D-19）。"""
        refs = [r["object"] for r in self.ws.ledger.relations_from(j["id"], "cites", version=j["version"])]
        if j["version"] == j["head_version"]:
            refs += self.ws.reviews.state(j["id"]).get("extra_cites") or []
        return list(dict.fromkeys(refs))

    # ---------- 判断 ----------
    def _judgment(self, j: dict, memo: dict) -> dict:
        ref = j["ref"]
        cites = [r for r in self.ws.ledger.relations_from(j["id"], "cites", version=j["version"])]
        state_marks = []
        corroborated = self._incoming(j["id"], "supports", memo)
        if corroborated:
            state_marks.append({"mark": "corroborated", "via": corroborated})
        opposed = self._incoming(j["id"], "opposes", memo)
        if opposed:
            state_marks.append({"mark": "opposed", "via": opposed})
        changed, lapsed = self._basis_state(j, cites)
        if changed:
            state_marks.append({"mark": "basis_changed", "via": changed})
        if lapsed:
            state_marks.append({"mark": "basis_lapsed", "via": lapsed})
        notes_marks = []
        recog = self._recognition(cites)
        if recog:
            notes_marks.append({"mark": "recognition_unverified", "via": recog})
        quoted = j["data"].get("external_author")
        if quoted and j["kind"] == "conclusion" and not (j["data"].get("conditions") or "").strip():
            notes_marks.append({"mark": "conditions_unstated", "via": []})
        incomplete = self._incomplete(cites, memo)
        if incomplete:
            notes_marks.append({"mark": "basis_incomplete", "via": incomplete})
        if j["kind"] == "conclusion" and not cites and not j["data"].get("local_observation"):
            notes_marks.append({"mark": "no_basis", "via": []})
        if j["data"].get("local_observation"):
            notes_marks.append({"mark": "local_observation", "via": []})
        roots = self._local_roots(cites, memo)
        if len(roots) >= 2:
            notes_marks.append({"mark": "local_roots", "via": roots, "count": len(roots)})
        return {"ref": ref, "layer": "judgment", "sources": self.sources(ref, memo), "kind": j["kind"],
                "state": {"validity": self.ws.versions.validity(ref), "review": self._review(j["id"]),
                          "marks": state_marks},
                "notes": {"author": j["author_kind"], "quoted": quoted, "marks": notes_marks}}

    def _incoming(self, entry_id: str, predicate: str, memo: dict) -> list[dict]:
        """被佐证、被反驳：入边的主语仍有效时才算；出处带对方的依据来源。"""
        out = []
        for r in self.ws.ledger.relations_to(entry_id, predicate):
            if self.ws.versions.validity(parse_ref(r["subject"])[0]) in ("withdrawn", "retired"):
                continue
            src = self.sources(r["subject"], memo)
            detail = " + ".join(SOURCE_LABELS.get(s, s) for s in src) if src else ""
            out.append({"rel": r["id"], "end": r["subject"], "detail": detail})
        return out

    def _basis_state(self, j: dict, cites: list[dict]) -> tuple[list[dict], list[dict]]:
        """依据有变化（所引版本不是当前版、被撤回、段落已变）与依据已失效（原件退役、删除）。"""
        changed, lapsed = [], []
        recheck = self.ws.extraction.recheck_refs(j["id"]) if j["version"] == j["head_version"] else {}
        changed_segments = {ref for refs in recheck.values() for ref in refs} | set(recheck)
        for r in cites:
            obj_id, obj_version = r["object_id"], r["object_version"]
            head = self.ws.ledger.head_version(obj_id)
            if head is None:
                lapsed.append({"rel": r["id"], "end": r["object"], "detail": "已删除"})
                continue
            behind = self.ws.judgments._artifact_behind(r["object"])
            if behind and self.ws.versions.state(behind)["retired"]:
                lapsed.append({"rel": r["id"], "end": r["object"], "detail": "原件已退役"})
                continue
            if obj_version and obj_version < head:
                changed.append({"rel": r["id"], "end": r["object"], "detail": f"当前为第 {head} 版",
                                "current": make_ref(obj_id, head, r.get("object_anchor") or "")})
                continue
            st = self.ws.versions.state(make_ref(obj_id, obj_version))
            if st["withdrawn"]:
                changed.append({"rel": r["id"], "end": r["object"], "detail": "所引版本已撤回"})
            elif st["defective"]:
                changed.append({"rel": r["id"], "end": r["object"], "detail": "所引版本有缺陷"})
            elif r["object"] in changed_segments or make_ref(obj_id, None, r.get("object_anchor") or "") \
                    in changed_segments:
                changed.append({"rel": r["id"], "end": r["object"], "detail": "所引段落已变化，尚未复核"})
            elif obj_id.startswith("jdg_") and self.ws.versions.validity(obj_id) == "replaced":
                changed.append({"rel": r["id"], "end": r["object"], "detail": "所引判断已被替代"})
        return changed, lapsed

    def _recognition(self, cites: list[dict]) -> list[dict]:
        """依据含未经人确认的 OCR / AI 识别（含公式 LaTeX）：按当前抽取层与复核状态推出，人确认后自动消失。"""
        out = []
        for r in cites:
            if not r["object_id"].startswith("art_") or not r.get("object_anchor"):
                continue
            state = self.ws.extraction.unverified_state(r["object_id"], r["object_anchor"])
            if state:
                out.append({"rel": r["id"], "end": r["object"], "detail": _RECOGNITION.get(state, state),
                            "state": state})
        return out

    def _incomplete(self, cites: list[dict], memo: dict) -> list[dict]:
        out = []
        for r in cites:
            e = self.ws.ledger.get(make_ref(r["object_id"], r["object_version"]))
            if e is None:
                continue
            if e["entry_kind"] == "record" and e["boundary"] != "complete":
                out.append({"rel": r["id"], "end": r["object"], "detail": f"事实记录边界：{e['boundary']}"})
            elif e["entry_kind"] == "judgment":
                sub = self.of(e["ref"], memo=memo)
                if sub and any(m["mark"] == "basis_incomplete" for m in sub["notes"]["marks"]):
                    out.append({"rel": r["id"], "end": r["object"], "detail": "所引判断依据不完整"})
        return out

    def _local_roots(self, cites: list[dict], memo: dict) -> list[dict]:
        """本地依据的独立来源：本地实证依据中原件互不相同、会话也互不相同的，各算一次。"""
        seen_roots, seen_sessions, out = set(), set(), []
        for r in cites:
            if "local" not in self.sources(r["object"].split("#", 1)[0], memo):
                continue
            e = self.ws.ledger.get(make_ref(r["object_id"], r["object_version"]))
            if e is None:
                continue
            root = e.get("artifact_id") or e.get("event_id") or e["id"]
            session = e.get("session_id")
            if root in seen_roots or (session and session in seen_sessions):
                continue
            seen_roots.add(root)
            if session:
                seen_sessions.add(session)
            out.append({"rel": r["id"], "end": r["object"], "detail": ""})
        return out

    def _review(self, item_id: str) -> str:
        st = self.ws.reviews.state(item_id)
        review = _REVIEW_STATE.get(st.get("review") or "", "none")
        if st.get("ai_flag") and review in ("none", "ai_confirmed"):
            review = "ai_flagged"
        elif review == "none" and st.get("ai_unsure"):
            review = "ai_unsure"
        return review

    # ---------- 原件一列 ----------
    def _original(self, e: dict, memo: dict) -> dict:
        ref = e["ref"]
        st = self.ws.versions.state(ref)
        state_marks = []
        if st["defective"]:
            state_marks.append({"mark": "defective", "via": [{"rel": st["defective"], "end": ref,
                                                              "detail": _reason(st, "defect")}]})
        behind = e.get("artifact_id") if e["entry_kind"] in ("record", "read") else None
        if behind:
            if self.ws.ledger.head_version(behind) is None:
                state_marks.append({"mark": "basis_lapsed", "via": [{"rel": None, "end": behind,
                                                                     "detail": "原件已删除"}]})
            elif self.ws.versions.state(behind)["retired"]:
                state_marks.append({"mark": "basis_lapsed", "via": [{"rel": None, "end": behind,
                                                                     "detail": "原件已退役"}]})
        notes_marks = []
        if e["entry_kind"] == "record" and e["boundary"] != "complete":
            notes_marks.append({"mark": "basis_incomplete", "via": [{"rel": None, "end": ref,
                                                                     "detail": f"边界：{e['boundary']}"}]})
        review = self._review(e["id"]) if e["entry_kind"] == "artifact" else "none"
        return {"ref": ref, "layer": "original", "sources": self.sources(ref, memo), "kind": e["entry_kind"],
                "state": {"validity": self.ws.versions.validity(ref), "review": review, "marks": state_marks},
                "notes": {"author": author_kind(e), "quoted": None, "marks": notes_marks}}

    # ---------- 框架一列 ----------
    def _framework(self, base: str, version: int | None) -> dict | None:
        fw = self.ws.framework
        if base.startswith("pg_"):
            page = fw.page(base)
            if page is None:
                return None
            version = version or page["head_version"]
            pv = fw.page_version(base, version) or {}
            validity = "replaced" if version < page["head_version"] or page["freshness"] == "superseded" \
                else "current"
            marks = []
            if page["freshness"] in ("inputs_changed", "unchecked") and version == page["head_version"]:
                marks.append({"mark": page["freshness"], "via": []})
            review = _PAGE_REVIEW.get(page["review"], "none")
            if review in ("none", "ai_confirmed") and self.ws.reviews.state(base).get("ai_flag"):
                review = "ai_flagged"
            who = pv.get("author_id") or ""
            return {"ref": make_ref(base, version), "layer": "framework", "sources": [], "kind": page["type"],
                    "state": {"validity": validity, "review": review, "marks": marks},
                    "notes": {"author": _kind_of_actor(who), "quoted": None, "marks": []}}
        if base.startswith("edg_"):
            edge = fw.edge(base)
            if edge is None:
                return None
            marks = [{"mark": edge["freshness"], "via": []}] if edge["freshness"] in ("inputs_changed",
                                                                                     "unchecked") else []
            return {"ref": base, "layer": "framework", "sources": [], "kind": "edge",
                    "state": {"validity": "replaced" if edge["freshness"] == "superseded" else "current",
                              "review": _PAGE_REVIEW.get(edge["review"], "none"), "marks": marks},
                    "notes": {"author": "ai" if edge["origin"] in ("ai_inferred", "candidate") else "system",
                              "quoted": None, "marks": []}}
        ent = fw.entity(base)
        if ent is None:
            return None
        return {"ref": base, "layer": "framework", "sources": [], "kind": "entity",
                "state": {"validity": "current", "review": "none", "marks": []},
                "notes": {"author": "human" if ent.get("user_marked") else "system", "quoted": None, "marks": []}}

    # ---------- 给界面与 AI 的组合 ----------
    def label(self, coords: dict) -> str:
        return standing_label(coords["layer"], coords["sources"])

    def review_label(self, coords: dict) -> str:
        return REVIEW.get(coords["state"]["review"], "")


def author_kind(entry: dict) -> str:
    """一版条目的最终作者：人 / AI / 系统。"""
    if entry.get("author_kind") or entry.get("actor_kind"):
        return entry.get("author_kind") or entry.get("actor_kind")
    who = entry.get("captured_by") or entry.get("actor_id") or entry.get("promoted_by") or ""
    return _kind_of_actor(who)


def _kind_of_actor(who: str) -> str:
    if who.startswith("human"):
        return "human"
    if who.startswith("ai"):
        return "ai"
    return "system"


def _count(mark: dict) -> dict:
    out = {"mark": mark["mark"]}
    n = mark.get("count", len(mark.get("via") or []))
    if n:
        out["count"] = n
    return out


def _reason(state: dict, action: str) -> str:
    for c in reversed(state.get("changes") or []):
        if c["action"] == action:
            return c.get("reason", "")
    return ""
