"""坐标（设计稿 10 D-12 至 D-16）：读取时从事实与关系推出，不落盘。

四组，显示顺序"地位 → 类型 → 现状 → 说明"：
- 地位：layer（综合程度）× sources（依据来源记号）。sources 只看本条目这一版自己的 cites（以及人勾的本地实证、
  人复核时补充的依据），不因别人后来的佐证或反驳改变（D-13）；
- 类型：kind；
- 现状：state = {validity, review, marks}；
- 说明：notes = {author, quoted, marks}。

每个标记是 {mark, via: [{rel, end, detail}]}：via 指向造成它的那条关系与另一端（D-14），由条目自身事实或人的处置
推出的标记 via 为空或指向那次处置。坐标字段的来源见设计稿 10"坐标字段"表的最后一列。

推出规则只读内存图（services/graph.py，G 组 D-31）：条目、关系、处置、复核、替换、抽取状态都从图上取，不查 SQL。
图有变化（本进程或别的进程写了账本、框架库）时代数加一，这里记住的结果全部作废，下一次读时重算（D-32）。
版本处置、有效性（含"依据全部失效"）、复核状态、原件替换、待复核、识别状态在这里按图重新表述，
与 versions / review / purge / judgments / extraction 里查 SQL 的同名逻辑一致：由对比测试保证（D-36，
tests/reference_coordinates.py 是 2.2.0 之前的 SQL 实现）。改其中一边时两边一起改。
"""
from ..core.ids import make_ref, parse_ref
from ..core.vocab import REVIEW, SOURCE_LABELS, sort_sources, source_of, standing_label, status_note
from .extraction import anchor_of
from .graph import LedgerGraph, author_of, kind_of_actor

_PAGE_REVIEW = {"ai_reviewed": "ai_confirmed", "human_reviewed": "human_confirmed", "rejected": "human_rejected"}
_REVIEW_STATE = {"human_reviewed": "human_confirmed", "rejected": "human_rejected", "ai_reviewed": "ai_confirmed"}
_RECOGNITION = {"unchecked": "未核对", "ai_confirmed": "AI 核对一致", "ai_flagged": "AI 认为有问题",
                "ai_unsure": "AI 拿不准"}
LOW_FIDELITY = ("ocr", "ai")
_FLAG = {"withdraw": "withdrawn", "defect": "defective", "retire": "retired"}
_UNDO = {"unwithdraw": "withdraw", "undefect": "defect", "restore": "retire"}
_AI_VERDICTS = ("confirm", "reject", "unsure")
_LEDGER_PREFIXES = ("art_", "evt_", "rec_", "rd_", "jdg_")

# 推出规则读图上的哪些字段（D-37）。测试核对它与 graph.NODE_FIELDS / DATA_FIELDS 完全一致：
# 规则要读新字段，先在这里和图上同时声明；图上的节点只暴露声明过的字段，漏了会直接报错
READS: dict[str, set[str]] = {
    "artifact": {"id", "version", "created_at", "source_class", "storage", "sha256", "data", "session_id",
                 "format", "ref", "head_version", "entry_kind", "author", "artifact_id", "event_id"},
    "event": {"id", "version", "created_at", "session_id", "data", "ref", "head_version", "entry_kind", "author",
              "artifact_id", "event_id"},
    "record": {"id", "version", "created_at", "event_id", "artifact_id", "boundary", "data", "ref",
               "head_version", "entry_kind", "author", "session_id"},
    "read": {"id", "version", "created_at", "artifact_id", "artifact_version", "session_id", "data", "ref",
             "head_version", "entry_kind", "author", "event_id"},
    "judgment": {"id", "version", "created_at", "kind", "author_kind", "session_id", "data", "ref", "head_version",
                 "entry_kind", "author", "artifact_id", "event_id"},
    "relation": {"id", "predicate", "subject_id", "subject_version", "object_id", "object_version",
                 "object_anchor", "asserted_by", "session_id", "created_at", "qualifiers", "subject", "object"},
    "version_state": {"id", "entry_id", "version", "action", "created_at", "actor_id", "data"},
    "review": {"id", "target_id", "target_version", "method", "verdict", "created_at", "data"},
    "replacement": {"id", "old_id", "new_id", "created_at"},
    "extraction": {"id", "artifact_id", "artifact_sha256", "kind", "unit", "created_at"},
    "page": {"id", "type", "head_version", "freshness", "review"},
    "page_version": {"page_id", "version", "author_id"},
    "edge": {"id", "rel", "src_id", "dst_id", "origin", "review", "freshness"},
    "entity": {"id", "kind", "name", "user_marked"},
}
DATA_READS: dict[str, set[str]] = {
    "artifact": {"external_tier", "path"},
    "event": {"source_class"},
    "record": set(),
    "read": {"anchors", "segment_sha256"},
    "judgment": {"external_author", "conditions", "scope_unclear", "local_observation", "text"},
    "version_state": {"reason", "replaced_by"},
    "review": {"revokes", "revoked_rel_id", "version", "cites", "local_observation", "anchor", "part",
               "extraction_id"},
}


def _copy(value):
    """记住的结果在请求之间共享：交出去的是副本，调用方改了也不影响别人。"""
    if isinstance(value, dict):
        return {k: _copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy(v) for v in value]
    return value


class CoordinateService:
    def __init__(self, ws):
        self.ws = ws
        self.graph = LedgerGraph(ws)
        self._gen: int | None = None
        self._memo: dict = {}
        self._lapse: dict | None = None

    def _sync(self) -> LedgerGraph:
        gen = self.graph.sync()
        if gen != self._gen:
            self._gen, self._memo, self._lapse = gen, {}, None
        return self.graph

    # ---------- 入口 ----------
    def of(self, ref: str, *, memo: dict | None = None) -> dict | None:
        """一个条目某一版（不带 @n 指当前版）的完整坐标；条目不存在时为 None。memo 参数保留兼容，不再需要。"""
        with self.graph.lock:
            self._sync()
            return _copy(self._of(ref))

    def sources(self, ref: str, memo: dict | None = None) -> list[str]:
        """某一版的依据来源记号（D-13）。"""
        with self.graph.lock:
            self._sync()
            return list(self._sources(ref))

    def recompute_all(self) -> int:
        """全量推一遍全部条目当前版的坐标（测耗时、预热用），返回条目数。"""
        with self.graph.lock:
            g = self._sync()
            ids = list(g.versions) + list(getattr(g, "pages", {})) + list(getattr(g, "edges", {}))
            for entry_id in ids:
                self._of(entry_id)
            return len(ids)

    # ---------- 给关系图用（设计稿 10 D-38 至 D-40；调用方持有 graph.lock） ----------
    def sync(self) -> LedgerGraph:
        """把新写入合进图并返回它。调用方要在 `with coords.graph.lock:` 里用，读完之前图不会变。"""
        return self._sync()

    def excluded_ids(self) -> set[str]:
        """默认不画、不列的条目：已退役的原件、依据全部失效的条目、当前版已撤回或已退役的条目
        （与 PurgeService.excluded_ids 一致，对比测试核对）。"""
        with self.graph.lock:
            self._sync()
            key = ("excluded",)
            if key not in self._memo:
                g = self.graph
                hidden = set()
                for entry_id in g.state_entries():
                    head = g.head_version(entry_id)
                    if any(s["version"] == head for s in g.states[entry_id]):
                        st = self._state(entry_id, head)
                        if st["withdrawn"] or st["retired"]:
                            hidden.add(entry_id)
                self._memo[key] = self._retired_ids() | set(self._lapse_map()["hidden"]) | hidden
            return set(self._memo[key])

    def review_extra_cites(self, judgment_id: str) -> list[str]:
        """人或 AI 复核确认时补充的依据（判断当前版，设计稿 04 D-19）。"""
        with self.graph.lock:
            self._sync()
            return list(self._review_state(judgment_id).get("extra_cites") or [])

    def replacement_info(self, artifact_id: str) -> dict | None:
        """原件的替代：最近一条替换记录，否则当前退役处置里写的替代原件（与 JudgmentService.replacement_info 一致）。"""
        with self.graph.lock:
            self._sync()
            return _copy(self._replacement_info(artifact_id))

    def _of(self, ref: str) -> dict | None:
        g = self.graph
        base, version, _ = parse_ref(ref)
        prefix = base.split("_", 1)[0]
        if prefix in ("pg", "edg", "ent"):
            key = ("framework", base, version)
            if key not in self._memo:
                self._memo[key] = self._framework(base, version)
            return self._memo[key]
        entry = g.entry(base, version)
        if entry is None or entry["entry_kind"] not in ("artifact", "event", "record", "read", "judgment"):
            return None
        key = ("coords", entry["ref"])
        if key in self._memo:
            return self._memo[key]
        self._memo[key] = None  # 环：先占位
        self._memo[key] = self._judgment(entry) if entry["entry_kind"] == "judgment" else self._original(entry)
        return self._memo[key]

    def note(self, coords: dict) -> str:
        return status_note(coords)

    def ref_status(self, ref: str) -> dict:
        """一个引用（带版本与段落）现在的状况：有效性、一行说明；所引不是当前版时给出当前版的引用。
        段落还在不在照旧现查抽取层（外部文本原件可能被改而账本不变，D-35）。"""
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
    def _sources(self, ref: str) -> list[str]:
        key = ("sources", ref)
        if key in self._memo:
            return self._memo[key]
        self._memo[key] = []  # 环：先占位
        base, version, _ = parse_ref(ref)
        entry = self.graph.entry(base, version)
        out: list[str] = []
        if entry is None:
            out = []
        elif entry["entry_kind"] == "artifact":
            out = [source_of(entry["source_class"], entry["data"].get("external_tier"))]
        elif entry["entry_kind"] == "event":
            out = [entry["data"].get("source_class", "local")]
        elif entry["entry_kind"] == "record":
            origin = entry.get("event_id") or entry.get("artifact_id")
            out = self._sources(origin) if origin else []
        elif entry["entry_kind"] == "read":
            out = self._sources(make_ref(entry["artifact_id"], entry.get("artifact_version")))
        elif entry["entry_kind"] == "judgment":
            out = self._judgment_sources(entry)
        self._memo[key] = sort_sources(out)
        return self._memo[key]

    def _judgment_sources(self, j) -> list[str]:
        cites = self._basis_refs(j)
        local = bool(j["data"].get("local_observation"))
        review = self._review_state(j["id"])
        local = local or bool(review.get("local"))
        if not cites:
            if j["kind"] == "normative" and not local:
                return []
            return ["local"] if local else ["inferred"]
        out = set()
        for ref in cites:
            out.update(self._sources(ref.split("#", 1)[0]))
        if local:
            out.add("local")
        return sorted(out)

    def _basis_refs(self, j) -> list[str]:
        """这一版的依据：出边 cites，加上人或 AI 复核确认时补充的依据（设计稿 04 D-19）。"""
        refs = [r["object"] for r in self.graph.relations_from(j["id"], "cites", version=j["version"])]
        if j["version"] == j["head_version"]:
            refs += self._review_state(j["id"]).get("extra_cites") or []
        return list(dict.fromkeys(refs))

    # ---------- 判断 ----------
    def _judgment(self, j) -> dict:
        ref = j["ref"]
        cites = self.graph.relations_from(j["id"], "cites", version=j["version"])
        state_marks = []
        corroborated = self._incoming(j["id"], "supports")
        if corroborated:
            state_marks.append({"mark": "corroborated", "via": corroborated})
        opposed = self._incoming(j["id"], "opposes")
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
        if j["data"].get("scope_unclear"):
            notes_marks.append({"mark": "scope_unclear", "via": []})
        incomplete = self._incomplete(cites)
        if incomplete:
            notes_marks.append({"mark": "basis_incomplete", "via": incomplete})
        if j["kind"] == "conclusion" and not cites and not j["data"].get("local_observation"):
            notes_marks.append({"mark": "no_basis", "via": []})
        if j["data"].get("local_observation"):
            notes_marks.append({"mark": "local_observation", "via": []})
        roots = self._local_roots(cites)
        if len(roots) >= 2:
            notes_marks.append({"mark": "local_roots", "via": roots, "count": len(roots)})
        return {"ref": ref, "layer": "judgment", "sources": self._sources(ref), "kind": j["kind"],
                "state": {"validity": self._validity(ref), "review": self._review(j["id"]),
                          "marks": state_marks},
                "notes": {"author": j["author_kind"], "quoted": quoted, "marks": notes_marks}}

    def _incoming(self, entry_id: str, predicate: str) -> list[dict]:
        """被佐证、被反驳：入边的主语仍有效时才算；出处带对方的依据来源。"""
        out = []
        for r in self.graph.relations_to(entry_id, predicate):
            if self._validity(parse_ref(r["subject"])[0]) in ("withdrawn", "retired"):
                continue
            src = self._sources(r["subject"])
            detail = " + ".join(SOURCE_LABELS.get(s, s) for s in src) if src else ""
            out.append({"rel": r["id"], "end": r["subject"], "detail": detail})
        return out

    def _basis_state(self, j, cites: list) -> tuple[list[dict], list[dict]]:
        """依据有变化（所引版本不是当前版、被撤回、段落已变）与依据已失效（原件退役、删除）。"""
        g = self.graph
        changed, lapsed = [], []
        recheck = self._recheck_refs(j["id"]) if j["version"] == j["head_version"] else {}
        changed_segments = {ref for refs in recheck.values() for ref in refs} | set(recheck)
        for r in cites:
            obj_id, obj_version = r["object_id"], r["object_version"]
            head = g.head_version(obj_id)
            behind = self._artifact_behind(r["object"])
            gone = head is None or bool(behind and self._state(behind)["retired"])
            if gone:  # 已删除或已退役：有替代原件时算"依据有变化"，否则算失效（设计稿 07 D-01、D-03）
                info = self._replacement_info(behind or obj_id)
                replaced = info["new_id"] if info else None
                if replaced:
                    changed.append({"rel": r["id"], "end": r["object"], "current": replaced,
                                    "detail": f"原件已由 {replaced} 替代"})
                else:
                    lapsed.append({"rel": r["id"], "end": r["object"],
                                   "detail": "已删除" if head is None else "原件已退役"})
                continue
            if obj_version and obj_version < head:
                changed.append({"rel": r["id"], "end": r["object"], "detail": f"当前为第 {head} 版",
                                "current": make_ref(obj_id, head, r.get("object_anchor") or "")})
                continue
            st = self._state(obj_id, obj_version)
            if st["withdrawn"]:
                changed.append({"rel": r["id"], "end": r["object"], "detail": "所引版本已撤回"})
            elif st["defective"]:
                changed.append({"rel": r["id"], "end": r["object"], "detail": "所引版本有缺陷"})
            elif r["object"] in changed_segments or make_ref(obj_id, None, r.get("object_anchor") or "") \
                    in changed_segments:
                changed.append({"rel": r["id"], "end": r["object"], "detail": "所引段落已变化，尚未复核"})
            elif obj_id.startswith("jdg_") and self._validity(obj_id) == "replaced":
                changed.append({"rel": r["id"], "end": r["object"], "detail": "所引判断已被替代"})
        return changed, lapsed

    def _recognition(self, cites: list) -> list[dict]:
        """依据含未经人确认的 OCR / AI 识别（含公式 LaTeX）：按当前抽取层与复核状态推出，人确认后自动消失。
        人自己写的依据关系不标（人引用时看过原件，设计稿 04 D-26）。"""
        out = []
        for r in cites:
            if not r["object_id"].startswith("art_") or not r.get("object_anchor") \
                    or r["asserted_by"].startswith("human"):
                continue
            state = self._unverified_state(r["object_id"], r["object_anchor"])
            if state:
                out.append({"rel": r["id"], "end": r["object"], "detail": _RECOGNITION.get(state, state),
                            "state": state})
        return out

    def _incomplete(self, cites: list) -> list[dict]:
        out = []
        for r in cites:
            e = self.graph.entry(r["object_id"], r["object_version"])
            if e is None:
                continue
            if e["entry_kind"] == "record" and e["boundary"] != "complete":
                out.append({"rel": r["id"], "end": r["object"], "detail": f"事实记录边界：{e['boundary']}"})
            elif e["entry_kind"] == "judgment":
                sub = self._of(e["ref"])
                if sub and any(m["mark"] == "basis_incomplete" for m in sub["notes"]["marks"]):
                    out.append({"rel": r["id"], "end": r["object"], "detail": "所引判断依据不完整"})
        return out

    def _local_roots(self, cites: list) -> list[dict]:
        """本地依据的独立来源：本地实证依据中原件互不相同、会话也互不相同的，各算一次。"""
        seen_roots, seen_sessions, out = set(), set(), []
        for r in cites:
            if "local" not in self._sources(r["object"].split("#", 1)[0]):
                continue
            e = self.graph.entry(r["object_id"], r["object_version"])
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
        st = self._review_state(item_id)
        review = _REVIEW_STATE.get(st.get("review") or "", "none")
        if st.get("ai_flag") and review in ("none", "ai_confirmed"):
            review = "ai_flagged"
        elif review == "none" and st.get("ai_unsure"):
            review = "ai_unsure"
        return review

    # ---------- 原件一列 ----------
    def _original(self, e) -> dict:
        g = self.graph
        ref = e["ref"]
        st = self._state(e["id"], e["version"])
        state_marks = []
        if st["defective"]:
            state_marks.append({"mark": "defective", "via": [{"rel": st["defective"], "end": ref,
                                                              "detail": _reason(st, "defect")}]})
        behind = e.get("artifact_id") if e["entry_kind"] in ("record", "read") else None
        if behind:
            if g.head_version(behind) is None:
                state_marks.append({"mark": "basis_lapsed", "via": [{"rel": None, "end": behind,
                                                                     "detail": "原件已删除"}]})
            elif self._state(behind)["retired"]:
                state_marks.append({"mark": "basis_lapsed", "via": [{"rel": None, "end": behind,
                                                                     "detail": "原件已退役"}]})
        notes_marks = []
        if e["entry_kind"] == "record" and e["boundary"] != "complete":
            notes_marks.append({"mark": "basis_incomplete", "via": [{"rel": None, "end": ref,
                                                                     "detail": f"边界：{e['boundary']}"}]})
        review = self._review(e["id"]) if e["entry_kind"] == "artifact" else "none"
        return {"ref": ref, "layer": "original", "sources": self._sources(ref), "kind": e["entry_kind"],
                "state": {"validity": self._validity(ref), "review": review, "marks": state_marks},
                "notes": {"author": e["author"], "quoted": None, "marks": notes_marks}}

    # ---------- 框架一列（框架层整层在图上，D-34） ----------
    def _framework(self, base: str, version: int | None) -> dict | None:
        g = self.graph
        if base.startswith("pg_"):
            page = g.pages.get(base)
            if page is None:
                return None
            version = version or page["head_version"]
            pv = g.page_versions.get((base, version)) or {}
            validity = "replaced" if version < page["head_version"] or page["freshness"] == "superseded" \
                else "current"
            marks = []
            if page["freshness"] in ("inputs_changed", "unchecked") and version == page["head_version"]:
                marks.append({"mark": page["freshness"], "via": []})
            review = _PAGE_REVIEW.get(page["review"], "none")
            if review in ("none", "ai_confirmed") and self._review_state(base).get("ai_flag"):
                review = "ai_flagged"
            who = pv.get("author_id") or ""
            return {"ref": make_ref(base, version), "layer": "framework", "sources": [], "kind": page["type"],
                    "state": {"validity": validity, "review": review, "marks": marks},
                    "notes": {"author": kind_of_actor(who), "quoted": None, "marks": []}}
        if base.startswith("edg_"):
            edge = g.edges.get(base)
            if edge is None:
                return None
            marks = [{"mark": edge["freshness"], "via": []}] if edge["freshness"] in ("inputs_changed",
                                                                                     "unchecked") else []
            review = _PAGE_REVIEW.get(edge["review"], "none")
            if review in ("none", "ai_confirmed") and self._review_state(base).get("ai_flag"):
                review = "ai_flagged"
            return {"ref": base, "layer": "framework", "sources": [], "kind": "edge",
                    "state": {"validity": "replaced" if edge["freshness"] == "superseded" else "current",
                              "review": review, "marks": marks},
                    "notes": {"author": "ai" if edge["origin"] in ("ai_inferred", "candidate") else "system",
                              "quoted": None, "marks": []}}
        ent = g.entities.get(base)
        if ent is None:
            return None
        return {"ref": base, "layer": "framework", "sources": [], "kind": "entity",
                "state": {"validity": "current", "review": "none", "marks": []},
                "notes": {"author": "human" if ent.get("user_marked") else "system", "quoted": None, "marks": []}}

    # ---------- 版本处置与有效性（与 services/versions.py 一致） ----------
    def _state(self, entry_id: str, version: int | None = None) -> dict:
        g = self.graph
        version = version or g.head_version(entry_id)
        key = ("state", entry_id, version)
        if key in self._memo:
            return self._memo[key]
        flags: dict[str, str | None] = {"withdrawn": None, "defective": None, "retired": None}
        replaced_by = None
        changes = []
        rows = g.version_states(entry_id, version) if version is not None else g.states.get(entry_id, [])
        for r in rows:
            changes.append({"id": r["id"], "created_at": r["created_at"], "actor_id": r["actor_id"],
                            "action": r["action"], "reason": r["data"].get("reason", ""),
                            **({"replaced_by": r["data"]["replaced_by"]} if r["data"].get("replaced_by") else {})})
            if r["action"] in _FLAG:
                flags[_FLAG[r["action"]]] = r["id"]
                if r["action"] == "retire":
                    replaced_by = r["data"].get("replaced_by")
            else:
                flags[_FLAG[_UNDO[r["action"]]]] = None
                if r["action"] == "restore":
                    replaced_by = None
        self._memo[key] = {**flags, "replaced_by": replaced_by, "changes": changes}
        return self._memo[key]

    def _validity(self, ref: str) -> str:
        """retired / withdrawn（本版的处置）> replaced（有更新的版本，或被人确认的 supersedes 替代）
        > lapsed（依据全部失效）> current。"""
        g = self.graph
        entry_id, version, _ = parse_ref(ref)
        head = g.head_version(entry_id)
        if head is None:
            return "lapsed" if entry_id.startswith(_LEDGER_PREFIXES) else "current"
        version = version or head
        st = self._state(entry_id, version)
        if st["retired"]:
            return "retired"
        if st["withdrawn"]:
            return "withdrawn"
        if version < head or g.relations_to(entry_id, "supersedes"):
            return "replaced"
        if entry_id in self._lapse_map()["hidden"]:
            return "lapsed"
        return "current"

    def _retirement_of(self, artifact_id: str) -> str | None:
        if not artifact_id.startswith("art_") or self.graph.head_version(artifact_id) is None:
            return None
        return self._state(artifact_id)["retired"]

    def _retired_ids(self) -> set[str]:
        g = self.graph
        out = set()
        for entry_id in g.state_entries():
            head = g.head_version(entry_id)
            if any(s["action"] == "retire" and s["version"] == head for s in g.states[entry_id]) \
                    and self._state(entry_id)["retired"]:
                out.add(entry_id)
        return out

    def _replacement_info(self, artifact_id: str) -> dict | None:
        """最近一条替换记录，否则当前退役处置里写的 replaced_by（与 JudgmentService.replacement_info 一致）。"""
        g = self.graph
        row = g.last_replacement(artifact_id)
        if row is not None:
            return {"new_id": row["new_id"], "at": row["created_at"], "record": row["id"]}
        current = self._retirement_of(artifact_id)
        if current:
            r = next((s for s in g.states.get(artifact_id, ()) if s["id"] == current), None)
            new_id = r["data"].get("replaced_by") if r else None
            if new_id:
                return {"new_id": new_id, "at": r["created_at"], "record": current}
        return None

    def _artifact_behind(self, ref: str) -> str | None:
        base = parse_ref(ref)[0]
        if base.startswith("art_"):
            return base
        if base.startswith(("rd_", "rec_")):
            e = self.graph.entry(base)
            return e.get("artifact_id") if e else None
        return None

    def _lapse_map(self) -> dict:
        """依据全部失效的条目（与 PurgeService._compute 无假设时一致）：每一代算一次。"""
        if self._lapse is not None:
            return self._lapse
        g = self.graph
        retired = self._retired_ids()
        links: dict[str, list[str]] = {}
        for r in g.all_relations("cites"):
            if r["subject_id"].startswith("jdg_") and r["subject_version"] == g.head_version(r["subject_id"]):
                links.setdefault(r["subject_id"], []).append(r["object_id"])
        records = g.ids("rec")
        for rec_id in records:
            rec = g.entry(rec_id)
            source = rec.get("artifact_id") or rec.get("event_id")
            if source:
                links.setdefault(rec_id, []).append(source)

        def present(entry_id: str) -> bool:
            return g.head_version(entry_id) is not None

        def replaced(artifact_id: str) -> bool:
            info = self._replacement_info(artifact_id)
            return bool(info and present(info["new_id"]))

        memo: dict[str, list[dict] | None] = {}

        def reason_of(ref: str, stack: frozenset) -> str | None:
            base = ref.split("@", 1)[0].split("#", 1)[0]
            prefix = base.split("_", 1)[0]
            if prefix == "art":
                if not present(base):
                    return None if replaced(base) else "deleted"
                return "retired" if base in retired and not replaced(base) else None
            if not present(base):
                return "deleted"
            if prefix == "rd":
                return reason_of(g.entry(base)["artifact_id"], stack)
            if prefix in ("rec", "jdg"):
                return "hidden" if hidden(base, stack) is not None else None
            return None

        def hidden(entry_id: str, stack: frozenset = frozenset()) -> list[dict] | None:
            if entry_id in memo:
                return memo[entry_id]
            if entry_id in stack:
                return None
            refs = links.get(entry_id, [])
            lapsed = [{"ref": r, "reason": reason} for r in refs if (reason := reason_of(r, stack | {entry_id}))]
            memo[entry_id] = lapsed if refs and len(lapsed) == len(refs) else None
            return memo[entry_id]

        for entry_id in records + [j for j in links if j.startswith("jdg_")]:
            hidden(entry_id)
        self._lapse = {"hidden": {k: v for k, v in memo.items() if v is not None}}
        return self._lapse

    # ---------- 复核状态（与 ReviewService.state 一致） ----------
    def _review_state(self, item_id: str) -> dict:
        key = ("review", item_id)
        if key in self._memo:
            return self._memo[key]
        g = self.graph
        prefix = item_id.split("_", 1)[0]
        all_rows = g.review_rows(item_id)
        revoked = {r["data"]["revokes"] for r in all_rows if r["data"].get("revokes")}
        rows = [r for r in all_rows if r["id"] not in revoked and not r["data"].get("revokes")
                and r["verdict"] in _AI_VERDICTS]
        if prefix == "pg":
            page = g.pages.get(item_id) or {}
            rows = [r for r in rows if r["data"].get("version") == page.get("head_version")]
        if prefix == "jdg":
            head = g.head_version(item_id)
            rows = [r for r in rows if r.get("target_version") in (None, head)]
        human = [r for r in rows if r["method"] == "human"]
        ai_all = [r for r in rows if r["method"] == "ai"]
        ai = [r for r in ai_all if r["verdict"] != "unsure"]
        last_h = human[-1]["created_at"] if human else ""
        ai_flag = bool(ai and ai[-1]["verdict"] == "reject" and ai[-1]["created_at"] > last_h)
        if prefix in ("pg", "edg"):
            item = (g.pages if prefix == "pg" else g.edges).get(item_id) or {}
            out = {"review": item.get("review"), "ai_flag": ai_flag}
        elif prefix == "art":
            out = {"review": None, "ai_flag": False}
        else:
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
            out = {"review": review, "ai_flag": ai_flag, "ai_unsure": ai_unsure,
                   "extra_cites": list(dict.fromkeys(extra)), "local": local}
        self._memo[key] = out
        return out

    # ---------- 待复核与识别状态（与 ExtractionService.recheck_entry、unverified_state 一致） ----------
    def _cited_hashes(self, judgment) -> list[dict]:
        out = []
        for r in self.graph.relations_from(judgment["id"], "cites", version=judgment["version"]):
            ref = r["object"]
            if r["object_id"].startswith("art_") and r.get("object_anchor") and r["qualifiers"].get("sha256"):
                out.append({"ref": f"{r['object_id']}#{r['object_anchor']}", "pinned": ref, "rel": r["id"],
                            "artifact_id": r["object_id"], "artifact_version": r["object_version"],
                            "anchor": r["object_anchor"], "sha256": r["qualifiers"]["sha256"],
                            "unit": r["qualifiers"].get("unit")})
            elif r["object_id"].startswith("rd_"):
                rd = self.graph.entry(r["object_id"], r["object_version"])
                if rd:
                    anchors = rd["data"].get("anchors") or []
                    for i, sha in enumerate(rd["data"].get("segment_sha256", [])):
                        out.append({"ref": ref, "rel": r["id"], "artifact_id": rd["artifact_id"],
                                    "artifact_version": rd.get("artifact_version"),
                                    "anchor": anchors[i] if i < len(anchors) else None, "sha256": sha,
                                    "via_read": True})
        return out

    def _recheck_refs(self, judgment_id: str) -> dict[str, list[str]]:
        key = ("recheck", judgment_id)
        if key in self._memo:
            return self._memo[key]
        refs: dict[str, list[str]] = {}
        item = self._recheck_item(judgment_id)
        for part in item["changed"] if item else []:
            source = part["ref"]
            anchor = part.get("anchor")
            ref = f"{part['artifact_id']}#{anchor}" if anchor else source
            changed = refs.setdefault(source, [])
            if ref not in changed:
                changed.append(ref)
        self._memo[key] = refs
        return refs

    def _recheck_item(self, judgment_id: str) -> dict | None:
        key = ("recheck_item", judgment_id)
        if key not in self._memo:
            self._memo[key] = self._compute_recheck(judgment_id)
        return self._memo[key]

    def _compute_recheck(self, judgment_id: str) -> dict | None:
        g = self.graph
        judgment = g.entry(judgment_id.split("@", 1)[0])
        if judgment is None or judgment["entry_kind"] != "judgment":
            return None
        changed = []
        for c in self._cited_hashes(judgment):
            art = g.entry(c["artifact_id"])
            replaced = None
            if art is None or self._retirement_of(art["id"]):
                replaced = self._replacement_info(c["artifact_id"])
                if replaced:
                    art = g.entry(replaced["new_id"])
            if art is None or (art["format"] == "text" and not replaced):
                continue
            if not replaced and c.get("artifact_version") and c["artifact_version"] != art["version"]:
                continue
            current = g.segment_info(art["id"])[0]
            if c["sha256"] not in current:
                at = replaced["at"] if replaced else self._unit_changed_at(art, c.get("unit"))
                changed.append({**c, "changed_at": at, **({"replaced_by": art["id"]} if replaced else {})})
        if not changed:
            return None
        since = max((x["changed_at"] or "" for x in changed), default="")
        if judgment["created_at"] > since and judgment["version"] > 1 and judgment["author_kind"] == "human":
            return None  # 人在依据变化之后写了新版本
        handled = [r for r in g.relations_to(judgment["id"], "supersedes") if r["created_at"] > since]
        withdrawn = self._state(judgment["id"], judgment["version"])["withdrawn"]
        if withdrawn:
            w = next((s for s in g.states.get(judgment["id"], ()) if s["id"] == withdrawn), None)
            if w is not None and w["created_at"] > since:
                handled.append(w)
        all_rows = g.review_rows(judgment["id"])
        revoked = {r["data"]["revokes"] for r in all_rows if r["data"].get("revokes")}
        reviews = [r for r in all_rows if r["id"] not in revoked and not r["data"].get("revokes")
                   and r["created_at"] > since]
        if handled or any(r["method"] == "human" and r["verdict"] in ("confirm", "reject") for r in reviews):
            return None
        ai = [r for r in reviews if r["method"] == "ai" and r["verdict"] in ("confirm", "reject")]
        return {"judgment_id": judgment["id"], "ref": judgment["ref"], "kind": judgment["kind"],
                "text": judgment["data"]["text"][:200], "changed": changed,
                **({"ai_checked": ai[-1]["id"]} if ai and ai[-1]["verdict"] == "confirm" else {})}

    # ---------- 状态检查用（与 ExtractionService 的 SQL 版一致，由对比测试保证） ----------
    def recheck_entry(self, judgment_id: str) -> dict | None:
        """一条判断是否待复核（依据段落已变化、还没有人处理）：与 ExtractionService.recheck_entry 相同的结果。"""
        with self.graph.lock:
            self._sync()
            return _copy(self._recheck_item(judgment_id))

    def pending_recheck(self, judgment_id: str) -> bool:
        item = self.recheck_entry(judgment_id)
        return bool(item and not item.get("ai_checked"))

    def needs_recheck(self) -> list[dict]:
        """全部待复核的判断（与 ExtractionService.needs_recheck 一致）。"""
        with self.graph.lock:
            g = self._sync()
            ids = []
            for r in g.all_relations("cites"):
                if r["subject_id"].startswith("jdg_") and (r["object_anchor"] or r["object_id"].startswith("rd_")):
                    ids.append(r["subject_id"])
            return [_copy(item) for jid in dict.fromkeys(ids) if (item := self._recheck_item(jid))]

    def unverified_state(self, artifact_id: str, anchor: str) -> str | None:
        """所引段落来自未经人确认的识别时的复核状态（与 ExtractionService.unverified_state 一致）。"""
        with self.graph.lock:
            self._sync()
            return self._unverified_state(artifact_id, anchor)

    def _unit_changed_at(self, art, unit: str | None) -> str | None:
        rows = self.graph.extraction_rows(art["id"], "content", art["sha256"], unit)
        return rows[-1]["created_at"] if rows else None

    def _unverified_state(self, artifact_id: str, anchor: str) -> str | None:
        info = self.graph.segment_info(artifact_id)
        if info is None:
            return None
        _, by_anchor, low_latex = info
        seg = by_anchor.get(anchor_of(anchor))
        if seg is None or seg["verified"]:
            return None
        ai_latex = seg.get("block") is not None and (seg["unit"], seg["block"]) in low_latex
        if seg["fidelity"] in LOW_FIDELITY:
            return self._recognition_state(artifact_id, seg, "latex" if ai_latex else "text")
        if ai_latex:
            return self._recognition_state(artifact_id, seg, "latex")
        return None

    def _recognition_state(self, artifact_id: str, seg: dict, part: str) -> str:
        """与 RecognitionReview.checks 一致：同一块同一部分取最近一次 AI 核对（撤销的也算）。"""
        verdict = ""
        for r in self.graph.review_rows(artifact_id):
            d = r["data"]
            if r["method"] != "ai" or not d.get("anchor") or not d.get("part"):
                continue
            if (d["anchor"], d["part"], d.get("extraction_id") or "") == (seg["anchor"], part,
                                                                        seg.get("extraction_id") or ""):
                verdict = r["verdict"]
        return {"confirm": "ai_confirmed", "reject": "ai_flagged", "unsure": "ai_unsure"}.get(verdict, "unchecked")

    # ---------- 给界面与 AI 的组合 ----------
    def label(self, coords: dict) -> str:
        return standing_label(coords["layer"], coords["sources"])

    def review_label(self, coords: dict) -> str:
        return REVIEW.get(coords["state"]["review"], "")


author_kind = author_of  # 旧名，别处可能引用


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
