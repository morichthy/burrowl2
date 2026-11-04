"""F8 检索与展开、约束生效（草图 §7、§12.4；DESIGN §0 约束如何强制生效）。

检索结果的每一条都带"地位坐标"：两个轴、复核状态、时效、是否被替代。
排序逐级比较，不打分：先排除被驳回的；被替代的仍返回，但排在最后并带标注。
与查询对象相关的有效约束总是单独列在最前。
"""
from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.ids import kind_of
from ..core.model import LAYER_OF_KIND, rank_key

INTERNAL_OPS = ("artifact.", "judgment.", "framework.", "linking.", "constraints.", "agent.", "record.")


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
        if layer == "original":
            basis = self.ws.judgments.basis_of(base)
            return {"layer": layer, "kind": kind, "source_classes": basis["source_classes"],
                    "external_tiers": basis["external_tiers"], "complete": basis["complete"],
                    "defective": bool(self.ws.ledger.links_to(base, ("defect_of",)))}
        if kind == "judgment":
            j = self.ws.ledger.get(base)
            cred, status = j["data"]["credibility"], self.ws.judgments.status(base)
            return {"layer": layer, "kind": kind, "judgment_kind": j["kind"], "author_kind": j["author_kind"],
                    "source_classes": cred["source_classes"], "external_tiers": cred["external_tiers"],
                    "verified_by_us": cred["verified_by_us"], "mixed": cred["mixed"],
                    "normative": cred.get("normative", False),
                    "complete": cred["basis_complete"], "superseded": status["superseded"],
                    "opposed": bool(status["opposed_by"]), "independent_support": status["independent_support"]}
        item = self.ws.get(base) or {}
        return {"layer": "framework", "kind": kind, "source_classes": [], "external_tiers": [],
                "review": item.get("review"), "freshness": item.get("freshness")}

    # ---------- 检索 ----------
    def search(self, query: str, *, layers: list[str] | None = None, objects: list[str] | None = None,
               mode: str = "reuse", include_log: bool = False, limit: int = 20) -> dict:
        """mode=reuse：三列都返回；mode=explore：不返回框架内容，避免框架锚定（草图 §11.3 风险）。"""
        if mode not in ("reuse", "explore"):
            raise BurrowlError("INVALID_ARGUMENT", "mode 必须是 reuse 或 explore")
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
            if objects and not set(objects) & set(self._objects(hit["id"])):
                continue
            hits.append(hit)
        current = sorted((h for h in hits if not h.get("superseded")), key=rank_key)
        superseded = sorted((h for h in hits if h.get("superseded")), key=rank_key)
        related = set(objects)
        for h in current[:limit]:
            related.update(self._objects(h["id"]))
        return {"query": query, "mode": mode, "constraints": self.active_constraints(sorted(related)),
                "hits": (current + superseded)[:limit], "total": len(hits)}

    # ---------- 展开 ----------
    def expand(self, entry_ref: str, *, mode: str = "reuse") -> dict:
        """一条原件记录的背景，按顺序：自带条件 → 同一来源的前后内容 → 同一对象的其他记录 → 引用了它的判断（解读）。"""
        base, _, anchor = entry_ref.partition("#")
        entry = self.ws.get(base)
        if entry is None:
            raise BurrowlError("NOT_FOUND", "条目不存在", {"id": entry_ref})
        out: dict = {"entry": entry, "coordinates": self.coordinates(base)}
        kind = kind_of(base)
        if kind == "record":
            out["conditions"] = {"conditions": entry["data"].get("conditions"), "method": entry["data"].get("method"),
                                 "boundary": entry["boundary"], "gaps": entry["data"].get("gaps")}
        elif kind == "event":
            out["conditions"] = entry["data"].get("conditions")
            out["neighbors"] = self.ws.ledger.query(
                "SELECT * FROM events WHERE session_id = ? AND seq BETWEEN ? AND ? AND id != ? ORDER BY seq",
                (entry["session_id"], entry["seq"] - 2, entry["seq"] + 2, base))
        elif kind == "artifact":
            out["conditions"] = {"metadata": entry["data"].get("metadata"), "storage": entry["storage"],
                                 "uri": entry["uri"], "version_of": entry["version_of"]}
            if anchor.startswith("seg-") or anchor.startswith("seg:"):
                n = int(anchor[4:])
                segs = self.ws.artifacts.segments(base)
                out["neighbors"] = [s for s in segs if abs(s["ordinal"] - n) <= 1]
        objects = self._objects(base)
        others = [i for i in self.ws.ledger.entries_with_objects(objects) if i != base][:20]
        out["same_objects"] = [{"id": i, "preview": self.preview(i), **self.coordinates(i)} for i in others]
        if mode != "explore":
            out["interpretations"] = [{"judgment_id": link["src_id"], "rel": link["rel"],
                                       "preview": self.preview(link["src_id"]),
                                       "note": "这是解读，不是原件内容"}
                                      for link in self.ws.ledger.links_to(base)]
        out["framework"] = [e for e in self.ws.framework.edges_of(base) if e["review"] != "rejected"]
        return out

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
            f"WHERE j.kind IN ('constraint','decision','instruction') AND o.object IN ({','.join('?' * len(objects))})",
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
