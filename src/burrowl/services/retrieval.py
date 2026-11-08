"""F8 检索与展开、约束生效（草图 §7、§12.4；DESIGN §0 约束如何强制生效）。

检索结果的每一条都带"地位坐标"：两个轴、复核状态、时效、是否被替代。
排序逐级比较，不打分：先排除被驳回的；被替代的仍返回，但排在最后并带标注。
与查询对象相关的有效约束总是单独列在最前。
"""
from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.ids import kind_of
from ..core.model import HISTORY_KINDS, LAYER_OF_KIND, rank_key

INTERNAL_OPS = ("artifact.", "judgment.", "framework.", "linking.", "constraints.", "agent.", "record.")
# 对象页不显示的自动日志：写判断、写框架页、检查约束这类系统操作的流水（设计稿 01 D-08）
AUTO_LOG_OPS = ("judgment.write", "framework.page_write", "constraints.check", "artifact.register", "artifact.read")
SOURCE_FIELDS = ("title", "filename", "suffix", "size", "media_type", "path", "external_tier")


class RetrievalService:
    def __init__(self, ws):
        self.ws = ws

    # ---------- 地位坐标 ----------
    def coordinates(self, entry_id: str) -> dict:
        base = entry_id.split("#", 1)[0].split("@", 1)[0]
        kind = kind_of(base)
        if kind is None:
            raise BurrowlError("INVALID_REFERENCE", "不是合法的条目 ID", {"id": entry_id})
        layer = LAYER_OF_KIND.get(kind, "framework")
        if layer == "history":  # 复核记录、退役记录：变更历史，不是条目
            return {"layer": "history", "kind": kind, "source_classes": [], "external_tiers": []}
        if layer == "original":
            basis = self.ws.judgments.basis_of(base)
            out = {"layer": layer, "kind": kind, "source_classes": basis["source_classes"],
                   "external_tiers": basis["external_tiers"], "complete": basis["complete"],
                   "defective": bool(self.ws.ledger.links_to(base, ("defect_of",)))}
            if kind == "artifact":
                out["retired"] = self.ws.judgments.retirement_of(base)  # 退役记录 ID 或 None（设计稿 02 D-12）
            return out
        if kind == "judgment":
            j = self.ws.ledger.get(base)
            written, status = j["data"]["credibility"], self.ws.judgments.status(base)
            if j["kind"] in HISTORY_KINDS:  # 旧版写成判断的复核、退役记录
                return {"layer": layer, "kind": kind, "judgment_kind": j["kind"], "author_kind": j["author_kind"],
                        "history": True, "source_classes": [], "external_tiers": []}
            # 当前地位 = 写入时的依据 + 复核补充的依据（设计稿 04 D-19）；写入时可信度另给 written_credibility
            review = self.ws.reviews.state(base)
            cred = self.ws.reviews.current_credibility(j, review)
            return {"layer": layer, "kind": kind, "judgment_kind": j["kind"], "author_kind": j["author_kind"],
                    "source_classes": cred["source_classes"], "external_tiers": cred["external_tiers"],
                    "all_local": cred["all_local"], "mixed": cred["mixed"], "process": j["kind"] == "process",
                    "reopen_condition": j["data"].get("reopen_condition"),
                    "normative": cred.get("normative", False),
                    "complete": cred["basis_complete"], "superseded": status["superseded"],
                    "opposed": bool(status["opposed_by"]), "independent_support": status["independent_support"],
                    "review": review["review"], "ai_flag": review["ai_flag"],
                    **({"written_credibility": written} if cred is not written else {})}
        item = self.ws.get(base) or {}
        out = {"layer": "framework", "kind": kind, "source_classes": [], "external_tiers": [],
               "review": item.get("review"), "freshness": item.get("freshness")}
        if kind in ("page", "edge"):
            out["ai_flag"] = self.ws.reviews.state(base)["ai_flag"]
        return out

    # ---------- 检索 ----------
    def search(self, query: str, *, layers: list[str] | None = None, objects: list[str] | None = None,
               mode: str = "reuse", include_log: bool = False, include_process: bool | None = None,
               include_retired: bool = False, limit: int = 20) -> dict:
        """mode=reuse：三列都返回；mode=explore：不返回框架内容，避免框架锚定（草图 §11.3 风险）。

        include_process：是否返回过程内容（提问、尝试、停下的路线）。省略时复用模式返回、探索模式不返回：
        "这条路试过了"最容易让探索变窄（1.8），但也能避免重复踩坑，所以只是默认隐藏（D-15）。
        include_retired：是否返回已退役的原件；返回时排在最后（设计稿 02 D-12）。
        """
        if mode not in ("reuse", "explore"):
            raise BurrowlError("INVALID_ARGUMENT", "mode 必须是 reuse 或 explore")
        if include_process is None:
            include_process = mode == "reuse"
        if mode == "explore":
            layers = [x for x in (layers or ["original", "judgment"]) if x != "framework"]
        objects = self.ws.linking.normalize_objects(objects or [])
        best: dict[str, dict] = {}
        for hit in self.ws.index.search(query, layers=layers, limit=limit * 5):
            if hit.layer == "framework":  # 旧版本的索引行不返回（草图 §12.1）
                page = self.ws.framework.page(hit.entry_id)
                if page is None or page["head_version"] != hit.version or page["review"] == "rejected":
                    continue
            if hit.entry_id in best and best[hit.entry_id]["score"] <= hit.score:
                continue
            best[hit.entry_id] = {"id": hit.entry_id, "layer": hit.layer, "locator": hit.locator,
                                  "ordinal": hit.ordinal, "text": hit.text[:600], "score": hit.score}
            if hit.entry_id.startswith("art_") and hit.locator != "title":
                best[hit.entry_id]["anchor"] = hit.locator.replace("seg:", "seg-", 1)
        exact = self.ws.linking.resolve_certain(query.strip())
        if exact:
            for entry_id in self.ws.ledger.entries_with_objects([exact]):
                if entry_id.startswith("evt_") and not include_log:  # 过程日志不进入默认检索（草图 §2）
                    continue
                best.setdefault(entry_id, {"id": entry_id, "layer": LAYER_OF_KIND[kind_of(entry_id)],
                                           "locator": "", "ordinal": 0, "text": self.preview(entry_id),
                                           "score": -1e9, "exact": True})
        if include_log:
            for ev in self.ws.ledger.query("SELECT id FROM events WHERE data LIKE ? ORDER BY created_at DESC LIMIT ?",
                                           (f"%{query}%", limit)):
                best.setdefault(ev["id"], {"id": ev["id"], "layer": "original", "locator": "log", "ordinal": 0,
                                           "text": self.preview(ev["id"]), "score": 0.0})
        hits = []
        for hit in best.values():
            hit.update(self.coordinates(hit["id"]))
            if hit.get("anchor"):  # 原件段落：带上单元与可信度档（D-12），识别文本提示对照原件
                art = self.ws.ledger.get(hit["id"])
                seg = self.ws.extraction.find(art, hit["anchor"]) if art else None
                if seg:
                    hit.update(unit=seg["unit"], unit_label=seg["unit_label"], fidelity=seg["fidelity"],
                               verified=seg["verified"], cite_as=f"{hit['id']}#{seg['anchor']}")
            if objects and not set(objects) & set(self._objects(hit["id"])):
                continue
            if hit.get("process") and not include_process:
                continue
            if hit.get("retired") and not include_retired:
                continue
            if hit.get("history") or hit["layer"] == "history":
                continue
            hits.append(hit)
        current = sorted((h for h in hits if not h.get("superseded") and not h.get("retired")), key=rank_key)
        superseded = sorted((h for h in hits if h.get("superseded") and not h.get("retired")), key=rank_key)
        superseded += sorted((h for h in hits if h.get("retired")), key=rank_key)
        related = set(objects)
        for h in current[:limit]:
            related.update(self._objects(h["id"]))
        return {"query": query, "mode": mode, "constraints": self.active_constraints(sorted(related)),
                "hits": (current + superseded)[:limit], "total": len(hits)}

    # ---------- 展开 ----------
    def expand(self, entry_ref: str, *, mode: str = "reuse") -> dict:
        """一条原件一列条目的背景（设计稿 01 D-08、D-09）：
        来源（原件）或条件（过程日志、事实记录）→ 同一来源的前后内容 → 涉及的对象 → 引用了它的判断（解读）。"""
        base, _, anchor = entry_ref.partition("#")
        entry = self.ws.get(base)
        if entry is None:
            raise BurrowlError("NOT_FOUND", "条目不存在", {"id": entry_ref})
        out: dict = {"entry": entry, "coordinates": self.coordinates(base)}
        kind = kind_of(base)
        if kind == "record":
            out["conditions"] = {"conditions": entry["data"].get("conditions") or {},
                                 "method": entry["data"].get("method"), "boundary": entry["boundary"],
                                 "gaps": entry["data"].get("gaps") or [], "locator": entry["data"].get("locator"),
                                 "from": entry["event_id"] or entry["artifact_id"]}
        elif kind == "event":
            out["conditions"] = {"conditions": entry["data"].get("conditions") or {},
                                 "input": entry["data"].get("input") or {},
                                 "source_class": entry["data"].get("source_class", "local")}
            out["neighbors"] = self.ws.ledger.query(
                "SELECT * FROM events WHERE session_id = ? AND seq BETWEEN ? AND ? AND id != ? ORDER BY seq",
                (entry["session_id"], entry["seq"] - 2, entry["seq"] + 2, base))
            promoted = self.ws.ledger.query("SELECT id FROM records WHERE event_id = ?", (base,))
            out["promoted_to"] = [r["id"] for r in promoted]
        elif kind == "artifact":
            out["source"] = self.source_of(entry)
            if anchor:
                segs = self.ws.extraction.segments(entry)
                at = next((i for i, x in enumerate(segs) if x["anchor"] == anchor.replace("seg:", "seg-", 1)), None)
                if at is not None:
                    out["neighbors"] = [x for x in segs[max(0, at - 1):at + 2] if x["unit"] == segs[at]["unit"]]
        elif kind == "read":
            out["read_of"] = {"artifact_id": entry["artifact_id"],
                              "anchors": entry["data"].get("anchors")
                              or [f"seg-{n}" for n in entry["data"].get("segments", [])]}
        out["objects"] = self.object_tags(self._objects(base))
        if mode != "explore":
            out["interpretations"] = self.interpretations(base)
        out["framework"] = [e for e in self.ws.framework.edges_of(base) if e["review"] != "rejected"]
        return out

    def source_of(self, art: dict) -> dict:
        """原件的"来源"（D-09）：登记时能核对的信息，按键值对给出；元数据原样附上。"""
        d = art["data"]
        fields = {k: d.get(k) for k in SOURCE_FIELDS if d.get(k) is not None}
        return {"kind": art["kind"], "source_class": art["source_class"], "storage": art["storage"],
                "uri": art["uri"], "sha256": art["sha256"], "captured_by": art["captured_by"],
                "session_id": art["session_id"], "created_at": art["created_at"], "version_of": art["version_of"],
                "newer_versions": [r["id"] for r in self.ws.ledger.query(
                    "SELECT id FROM artifacts WHERE version_of = ?", (art["id"],))],
                **fields, "metadata": d.get("metadata") or {}}

    def interpretations(self, base: str) -> list[dict]:
        """引用了它的判断：直接引用、引用它的某个段落（art_…#段落）、经由它的读取记录引用。"""
        links = self.ws.ledger.query("SELECT * FROM links WHERE dst_id = ? OR dst_id LIKE ? ORDER BY created_at",
                                     (base, f"{base}#%"))
        if base.startswith("art_"):
            links += self.ws.ledger.query(
                "SELECT l.* FROM links l JOIN reads r ON r.id = l.dst_id WHERE r.artifact_id = ? ORDER BY l.created_at",
                (base,))
        out, seen = [], set()
        for link in links:
            key = (link["src_id"], link["rel"], link["dst_id"])
            if key in seen or not link["src_id"].startswith("jdg_"):
                continue
            seen.add(key)
            j = self.ws.ledger.get(link["src_id"])
            out.append({"judgment_id": link["src_id"], "rel": link["rel"], "via": link["dst_id"],
                        "judgment_kind": j["kind"] if j else None, "preview": self.preview(link["src_id"]),
                        "note": "这是解读，不是原件内容"})
        return out

    def object_tags(self, objects: list[str]) -> list[dict]:
        """对象标签（D-08）：实体显示名称与类别；每个标签带"关于它的条目"数（不含自动日志）。"""
        out = []
        for obj in objects:
            entity = self.ws.framework.entity(obj) if obj.startswith("ent_") else None
            count = len([i for i in self.ws.ledger.entries_with_objects([obj]) if not i.startswith(("evt_", "rd_"))])
            out.append({"id": obj, "name": entity["name"] if entity else obj,
                        "kind": entity["kind"] if entity else None, "entity": entity is not None, "count": count})
        return out

    def segment_stats(self, artifact_id: str) -> dict:
        """每个段落被读过几次、被哪些判断引用（按结论 / 过程 / 规定分组，D-01、T-06）。"""
        art = self.ws.ledger.get(artifact_id)
        if art is None or art["entry_kind"] != "artifact":
            raise BurrowlError("NOT_FOUND", "原件不存在", {"artifact_id": artifact_id})
        stats: dict[str, dict] = {}

        def slot(anchor: str) -> dict:
            return stats.setdefault(anchor, {"reads": [], "citations": {}})

        reads = self.ws.ledger.query("SELECT * FROM reads WHERE artifact_id = ? ORDER BY created_at", (artifact_id,))
        read_anchors = {}
        for r in reads:
            anchors = r["data"].get("anchors") or [f"seg-{n}" for n in r["data"].get("segments", [])]
            read_anchors[r["id"]] = anchors
            for a in anchors:
                slot(a)["reads"].append({"id": r["id"], "actor_id": r["actor_id"], "created_at": r["created_at"]})
        whole = []
        for item in self.interpretations(artifact_id):
            if item["rel"] != "used":
                continue
            via = item["via"]
            if via == artifact_id:
                whole.append(item)
                continue
            anchors = [via.split("#", 1)[1].replace("seg:", "seg-", 1)] if "#" in via else read_anchors.get(via, [])
            for a in anchors:
                group = slot(a)["citations"].setdefault(item["judgment_kind"] or "other", [])
                if item["judgment_id"] not in [g["judgment_id"] for g in group]:
                    group.append({"judgment_id": item["judgment_id"], "via": via, "preview": item["preview"]})
        return {"artifact_id": artifact_id, "segments": stats, "whole_artifact": whole, "reads": len(reads)}

    def object_view(self, obj: str) -> dict:
        """对象页（D-08）：关于这个对象的全部条目。有效约束在前，其次有争议的结论，其余按类型、时间。
        不显示自动日志（写判断、写框架页等）；已升级为事实记录的过程日志只显示事实记录。"""
        key = (self.ws.linking.normalize_objects([obj]) or [obj])[0]
        entity = self.ws.framework.entity(key) if key.startswith("ent_") else None
        ids = self.ws.ledger.entries_with_objects([key])
        promoted = {r["event_id"] for r in self.ws.ledger.query(
            "SELECT event_id FROM records WHERE event_id IS NOT NULL")}
        groups: dict[str, list[dict]] = {"constraints": [], "disputed": [], "conclusion": [], "process": [],
                                         "record": [], "artifact": [], "event": [], "system": []}
        for entry_id in ids:
            entry = self.ws.get(entry_id)
            if entry is None or entry_id.startswith("rd_"):
                continue
            if entry_id.startswith("evt_") and (entry["op"] in AUTO_LOG_OPS or entry_id in promoted):
                continue
            if entry_id.startswith("jdg_") and entry["kind"] in HISTORY_KINDS:
                continue
            item = {"id": entry_id, "created_at": entry["created_at"], "preview": self.preview(entry_id),
                    **self.coordinates(entry_id)}
            if entry_id.startswith("jdg_"):
                status = self.ws.judgments.status(entry_id)
                item["superseded"] = status["superseded"]
                if entry["kind"] == "normative":
                    group = "constraints"
                elif entry["kind"] == "conclusion" and status["opposed_by"] and not status["superseded"]:
                    group = "disputed"
                elif entry["kind"] in ("conclusion", "process"):
                    group = entry["kind"]
                else:
                    group = "system"
            else:
                group = {"record": "record", "artifact": "artifact", "event": "event"}[entry["entry_kind"]]
            groups[group].append(item)
        for items in groups.values():
            items.sort(key=lambda i: i["created_at"], reverse=True)  # 新的在前
            items.sort(key=lambda i: bool(i.get("superseded")))  # 被替代的排到最后（稳定排序，组内仍按时间）
        pages = [dict(p) for p in self.ws.framework.conn.execute(
            "SELECT id, type, title, freshness, review FROM pages WHERE subject_id = ?", (key,))]
        return {"id": key, "name": entity["name"] if entity else key, "entity": entity,
                "groups": groups, "total": sum(len(v) for v in groups.values()), "pages": pages}

    def timeline(self, obj: str) -> list[dict]:
        """按对象和时间精确过滤（历史类查询）。"""
        key = self.ws.linking.normalize_objects([obj])
        ids = self.ws.ledger.entries_with_objects(key)
        items = [self.ws.get(i) for i in ids]
        items.sort(key=lambda e: e["created_at"])
        return [{"id": e["id"], "created_at": e["created_at"], "preview": self.preview(e["id"]),
                 **self.coordinates(e["id"])} for e in items]

    # ---------- 约束 ----------
    def active_constraints(self, objects: list[str]) -> list[dict]:
        if not objects:
            return []
        rows = self.ws.ledger.query(
            "SELECT DISTINCT j.id FROM judgments j JOIN entry_objects o ON o.entry_id = j.id "
            f"WHERE j.kind = 'normative' AND o.object IN ({','.join('?' * len(objects))})",
            objects)
        out = []
        for r in rows:
            if self.ws.judgments.status(r["id"])["superseded"]:
                continue
            j = self.ws.ledger.get(r["id"])
            out.append({"id": j["id"], "kind": j["kind"], "text": j["data"]["text"], "author_kind": j["author_kind"],
                        "author_id": j["author_id"], "objects": j["objects"], "created_at": j["created_at"]})
        return out

    def check_constraints(self, actor: Actor, objects: list[str]) -> dict:
        """agent 对某对象动手前必须调用（Skill 规定）；调用本身记入过程日志，作为"已检查"的凭据。"""
        objects = self.ws.linking.normalize_objects(objects)
        found = self.active_constraints(objects)
        self.ws.capture.log(actor, "constraints.check", input={"constraints": [c["id"] for c in found]},
                            objects=objects)
        return {"objects": objects, "constraints": found}

    def flag_unchecked_constraints(self, actor: Actor, event: dict) -> None:
        """对某对象的操作发生在对它的约束检查之前，就生成一条待决策项（DESIGN §0）。"""
        if event["op"].startswith(INTERNAL_OPS):
            return
        found = self.active_constraints(event["objects"])
        if not found:
            return
        checked = set()
        for ev in self.ws.ledger.query("SELECT objects FROM events WHERE session_id = ? AND op = 'constraints.check' "
                                       "AND seq < ?", (event["session_id"], event["seq"])):
            checked.update(ev["objects"])
        missing = [c for c in found if not set(c["objects"]) & checked]
        if missing:
            self.ws.framework.add_decision("constraint_unchecked", event["id"], len(missing), {
                "op": event["op"], "actor_id": actor.id, "constraints": missing,
                "note": "操作前没有检查相关约束"})

    # ---------- 内部 ----------
    def _objects(self, entry_id: str) -> list[str]:
        if entry_id.startswith("pg_"):
            page = self.ws.framework.page(entry_id)
            return [page["subject_id"]] if page and page["subject_id"] else []
        entry = self.ws.ledger.get(entry_id)
        return entry["objects"] if entry else []

    def preview(self, entry_id: str) -> str:
        e = self.ws.get(entry_id) or {}
        d = e.get("data") or {}
        return str(d.get("text") or d.get("result") or d.get("excerpt") or d.get("title") or d.get("output")
                   or e.get("title") or e.get("op") or "")[:300]
