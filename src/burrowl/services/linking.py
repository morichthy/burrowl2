"""F7 术语连接（草图 §12.3）与对象归一化（草图 §13 第 2 条）。

三档：
- 确定：标识精确对上，或别名表中已登记 → 直接建机械关系边，不需要复核；
- AI 较有把握：只有一个合理候选、影响范围小 → 建 AI 推断边（未复核，可用于综合），进待复核列表；
- 拿不准：多个候选、没有候选，或影响范围大 → 不建边，进待决策列表，附候选和原文片段。
"拿不准"只按可检查的结构条件判断，不看 AI 自报的置信度。人的决定写回判断层并加入别名表。
"""
import re
import unicodedata

from ..core.actor import Actor
from ..core.errors import BurrowlError

IDENTIFIER = re.compile(r"^(?=.*\d)[\w.\-/:]+$")  # 含数字的编号类叫法，如 P-102、10.1000/xyz、ERR_42


def normalize(term: str) -> str:
    """别名比较用的规范形式：NFKC（全角转半角）、去首尾空白、合并空白、转小写。"""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", term)).strip().lower()


class LinkingService:
    def __init__(self, ws):
        self.ws = ws

    # ---------- 对象归一化 ----------
    def resolve_certain(self, term: str) -> str | None:
        """只在"确定"档时返回实体 ID：别名表唯一命中，或实体名精确且唯一。"""
        if term.startswith("ent_") and self.ws.framework.entity(term):
            return term
        key = normalize(term)
        targets = self.ws.framework.alias_targets(key)
        if len(targets) == 1:
            return targets[0]
        if targets:
            return None
        matches = [e["id"] for e in self.ws.framework.entities() if normalize(e["name"]) == key]
        return matches[0] if len(matches) == 1 else None

    def normalize_objects(self, objects: list[str]) -> list[str]:
        """能确定对应实体的换成实体 ID；对不上的保留规范化后的原叫法，不猜（草图 §13 第 2 条）。"""
        out = []
        for obj in objects:
            if not obj or not str(obj).strip():
                continue
            out.append(self.resolve_certain(obj) or normalize(obj))
        return list(dict.fromkeys(out))

    # ---------- 机械连接 ----------
    def link_mentions(self, artifact_id: str) -> list[str]:
        """导入时把原件中出现的实体名和已登记别名连到实体上（机械关系，草图 §12.2 第 1 条）。"""
        try:
            text = "\n".join(s["text"] for s in self.ws.artifacts.segments(artifact_id))
        except BurrowlError:
            return []
        haystack = normalize(text)
        linked = []
        names: dict[str, set[str]] = {}
        for e in self.ws.framework.entities():
            names.setdefault(normalize(e["name"]), set()).add(e["id"])
        for r in self.ws.framework.conn.execute("SELECT alias, entity_id FROM aliases"):
            names.setdefault(r[0], set()).add(r[1])
        for name, ids in names.items():
            if len(name) >= 2 and len(ids) == 1 and name in haystack:
                entity_id = next(iter(ids))
                self.ws.framework.add_edge(rel="mentions", src_id=artifact_id, dst_id=entity_id, origin="mechanical",
                                           review="rule", data={"term": name}, inputs=[artifact_id])
                linked.append(entity_id)
        return linked

    # ---------- 三档连接 ----------
    def link_term(self, actor: Actor, *, term: str, source_id: str | None = None, excerpt: str | None = None,
                  proposed_entity_id: str | None = None) -> dict:
        fw = self.ws.framework
        certain = self.resolve_certain(term)
        if certain and (proposed_entity_id in (None, certain)):
            edge = self._edge(source_id, certain, "mechanical", "rule", term)
            return {"tier": "certain", "entity_id": certain, "edge": edge}

        key = normalize(term)
        candidates = []
        for e in fw.entities():
            names = [normalize(e["name"]), *(a for a in fw.entity(e["id"])["aliases"])]
            if any(len(n) >= 2 and (key in n or n in key) for n in names):
                candidates.append(e["id"])
        if proposed_entity_id:
            if not fw.entity(proposed_entity_id):
                raise BurrowlError("NOT_FOUND", "proposed_entity_id 不存在", {"id": proposed_entity_id})
            if proposed_entity_id not in candidates:
                candidates.append(proposed_entity_id)
        impact = sum(len(fw.edges_of(c)) for c in candidates)
        threshold = self.ws.config["linking"]["impact_threshold"]

        if len(candidates) == 1 and impact < threshold:
            edge = self._edge(source_id, candidates[0], "ai_inferred", "ai_generated", term)
            fw.add_decision("review", edge["id"] if edge else candidates[0], 0,
                            {"what": "术语连接（AI 较有把握）", "term": term, "entity_id": candidates[0],
                             "source_id": source_id, "excerpt": excerpt, "proposed_by": actor.id})
            return {"tier": "confident", "entity_id": candidates[0], "edge": edge}

        reason = "没有候选" if not candidates else ("多个候选" if len(candidates) > 1 else "影响范围大")
        decision = fw.add_decision("term_link", source_id, impact, {
            "term": term, "candidates": [fw.entity(c) for c in candidates], "source_id": source_id,
            "excerpt": excerpt, "reason": reason, "proposed_by": actor.id,
        })
        return {"tier": "uncertain", "decision": decision}

    def decide(self, actor: Actor, *, decision_id: str, entity_id: str | None = None,
               new_entity: dict | None = None, note: str = "") -> dict:
        """人对术语连接的决定：写回判断层，同时加入别名表，下次同一叫法直接落入"确定"档。"""
        actor.require_human("决定术语连接")
        fw = self.ws.framework
        decision = fw.decision(decision_id)
        if not decision or decision["kind"] != "term_link" or decision["status"] != "open":
            raise BurrowlError("NOT_FOUND", "没有这个待处理的术语连接", {"decision_id": decision_id})
        if (entity_id is None) == (new_entity is None):
            raise BurrowlError("INVALID_ARGUMENT", "entity_id 与 new_entity 必须且只能给一个")
        if new_entity:
            entity = fw.entity_by_name(new_entity["kind"], new_entity["name"]) or \
                fw.add_entity(new_entity["kind"], new_entity["name"], user_marked=True)
            entity_id = entity["id"]
        elif not fw.entity(entity_id):
            raise BurrowlError("NOT_FOUND", "实体不存在", {"entity_id": entity_id})
        entity = fw.entity(entity_id)
        term, source_id = decision["data"]["term"], decision["data"].get("source_id")
        cites = [source_id] if source_id and source_id.split("_")[0] in ("art", "rec", "rd", "evt", "jdg") else []
        judgment = self.ws.judgments.write(
            actor, kind="review", text=f"术语「{term}」指的是{entity['kind']}「{entity['name']}」。{note}".strip(),
            cites=cites, objects=[entity_id])
        fw.add_alias(normalize(term), entity_id, judgment["id"])
        edge = self._edge(source_id, entity_id, "projection", "human_reviewed", term, inputs=[judgment["id"]])
        fw.close_decision(decision_id, "resolved", {"entity_id": entity_id, "judgment_id": judgment["id"]})
        return {"entity_id": entity_id, "judgment_id": judgment["id"], "edge": edge}

    def _edge(self, source_id: str | None, entity_id: str, origin: str, review: str, term: str,
              inputs: list[str] | None = None) -> dict | None:
        if not source_id:
            return None
        return self.ws.framework.add_edge(rel="mentions", src_id=source_id, dst_id=entity_id, origin=origin,
                                          review=review, data={"term": term}, inputs=inputs or [source_id])
