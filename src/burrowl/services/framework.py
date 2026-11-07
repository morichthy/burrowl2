"""F5 框架层：实体、实体页、概念页、综合页、非文本原件的描述、AI 推断的边（草图 §11、§12.2）。

- 框架回答"现在该信什么、该怎么理解"，全部可以再生，永远不能作为依据。
- 每个框架条目生成时记下输入清单；时效与复核状态单独维护。
- AI 写的条目一律是"AI 生成、未复核"，并进入待复核列表；人的复核结论写回判断层（草图 §4）。
- 新建实体页、概念页要过门槛，不建空壳页（草图 §12.2 第 3 条）。
"""
from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.hashing import sha256_text
from ..core.ids import split_version
from ..core.model import PAGE_TYPES
from ..core.refs import extract_refs

AI_EDGE_RELS = ("may_contradict", "may_supersede", "similar", "analogy", "related")
# 复核确认后写回判断层时使用的关系；相似与类比只留在框架里
WRITEBACK_REL = {"may_contradict": "opposes", "may_supersede": "supersedes"}


class FrameworkService:
    def __init__(self, ws):
        self.ws = ws

    # ---------- 实体 ----------
    def entity_upsert(self, actor: Actor, *, kind: str, name: str, description: str | None = None) -> dict:
        fw = self.ws.framework
        existing = fw.entity_by_name(kind, name)
        if existing:
            if actor.kind == "human" and not existing["user_marked"]:
                fw.mark_entity(existing["id"])
            return fw.entity(existing["id"])
        return fw.add_entity(kind, name, {"description": description, "created_by": actor.id},
                             user_marked=actor.kind == "human")

    # ---------- 页面 ----------
    def page_write(self, actor: Actor, *, type: str, title: str, body: str, inputs: list[str] | None = None,
                   slug: str | None = None, summary: str | None = None, subject_id: str | None = None) -> dict:
        if type not in PAGE_TYPES:
            raise BurrowlError("INVALID_ARGUMENT", f"type 必须是 {', '.join(PAGE_TYPES)} 之一", {"type": type})
        fw = self.ws.framework
        slug = slug or _slugify(title)
        current = fw.page_by_slug(slug)
        inputs = list(dict.fromkeys([*(inputs or []), *extract_refs(body)]))
        for ref in inputs:
            self._check_input(ref)
        if type in ("entity", "concept", "description") and not subject_id:
            raise BurrowlError("INVALID_ARGUMENT", "实体页、概念页和描述页必须给出 subject_id")
        if current is None and type in ("entity", "concept"):
            self._check_threshold(actor, subject_id)
        if type == "description" and not (subject_id or "").startswith("art_"):
            raise BurrowlError("INVALID_ARGUMENT", "描述页只能挂在原件上（subject_id 为 art_…）")
        review = "human_reviewed" if actor.kind == "human" else "ai_generated"
        page = fw.write_page(
            page_id=current["id"] if current else None, type_=type, slug=slug, title=title, subject_id=subject_id,
            author_id=actor.id, review=review, inputs=inputs,
            version_data={"body": body, "summary": summary, "author_kind": actor.kind},
            page_data={"summary": summary, "ai_written": actor.kind == "ai"},
        )
        self.index_page(page["id"])
        rederive = fw.open_decision_for("rederive", page["id"])
        if rederive:
            fw.close_decision(rederive["id"], "resolved", {"version": page["head_version"]})
        if actor.kind == "ai" and not fw.open_decision_for("review", page["id"]):
            fw.add_decision("review", page["id"], 0, {"what": f"{type} 页面", "title": title, "proposed_by": actor.id})
        self.ws.capture.log(actor, "framework.page_write", input={"page_id": page["id"],
                                                                  "version": page["head_version"]})
        return {**page, "ref": f"{page['id']}@{page['head_version']}"}

    def page_get(self, page_ref: str) -> dict:
        page_id, version = split_version(page_ref)
        fw = self.ws.framework
        page = fw.page(page_id)
        if page is None:
            raise BurrowlError("NOT_FOUND", "页面不存在", {"page": page_ref})
        version = version or page["head_version"]
        ver = fw.page_version(page_id, version)
        if ver is None:
            raise BurrowlError("NOT_FOUND", "页面版本不存在", {"page": page_ref})
        inputs = fw.inputs_of("page", page_id, version)
        changed = []
        for ref in inputs:
            base = ref.split("#", 1)[0].split("@", 1)[0]
            if base.startswith("jdg_") and self.ws.judgments.status(base)["superseded"]:
                changed.append(ref)
        return {"page": page, "version": version, "body": ver["data"]["body"], "summary": ver["data"].get("summary"),
                "author_id": ver["author_id"], "inputs": inputs, "superseded_inputs": changed,
                "versions": fw.page_versions(page_id)}

    # ---------- AI 推断的边 ----------
    def edge_add(self, actor: Actor, *, rel: str, src_id: str, dst_id: str, reason: str,
                 inputs: list[str] | None = None) -> dict:
        if rel not in AI_EDGE_RELS:
            raise BurrowlError("INVALID_ARGUMENT", f"rel 必须是 {', '.join(AI_EDGE_RELS)} 之一", {"rel": rel})
        for ref in (src_id, dst_id):
            if self.ws.get(ref) is None:
                raise BurrowlError("NOT_FOUND", "边的端点不存在", {"ref": ref})
        origin = "ai_inferred" if actor.kind == "ai" else "candidate"
        edge = self.ws.framework.add_edge(rel=rel, src_id=src_id, dst_id=dst_id, origin=origin,
                                          review="ai_generated", data={"reason": reason, "by": actor.id},
                                          inputs=[src_id, dst_id, *(inputs or [])])
        if not self.ws.framework.open_decision_for("review", edge["id"]):
            self.ws.framework.add_decision("review", edge["id"], 1 if rel in WRITEBACK_REL else 0,
                                           {"what": f"AI 推断的关系 {rel}", "src_id": src_id, "dst_id": dst_id,
                                            "reason": reason})
        return edge

    # ---------- 复核（人） ----------
    def review(self, actor: Actor, *, item_id: str, verdict: str, reason: str, cites: list[str] | None = None) -> dict:
        """人复核框架条目：确认或驳回。复核结论写成一条新判断，否则框架重建时会丢失（草图 §4）。"""
        actor.require_human("复核框架条目")
        if verdict not in ("confirm", "reject"):
            raise BurrowlError("INVALID_ARGUMENT", "verdict 必须是 confirm 或 reject")
        fw = self.ws.framework
        kind = "page" if item_id.startswith("pg_") else "edge" if item_id.startswith("edg_") else None
        item = fw.page(item_id) if kind == "page" else fw.edge(item_id) if kind == "edge" else None
        if item is None:
            raise BurrowlError("NOT_FOUND", "框架条目不存在", {"item_id": item_id})
        relations = []
        if kind == "edge" and verdict == "confirm" and item["rel"] in WRITEBACK_REL \
                and item["src_id"].startswith("jdg_") and item["dst_id"].startswith("jdg_"):
            # 确认后转为判断层关系：src 的主张替代或反对 dst（草图 §11.2：复核确认后写回判断层）
            relations.append({"rel": WRITEBACK_REL[item["rel"]], "target": item["dst_id"],
                              "successor": item["src_id"]})
        subject = item.get("subject_id") if kind == "page" else None
        label = item["title"] if kind == "page" else f"{item['src_id']} {item['rel']} {item['dst_id']}"
        text = f"复核{'确认' if verdict == 'confirm' else '驳回'}「{label}」：{reason}"
        judgment = self.ws.judgments.write(actor, kind="review", text=text, cites=cites, relations=relations,
                                           objects=[subject] if subject else [])
        state = "human_reviewed" if verdict == "confirm" else "rejected"
        fw.set_state(kind, item_id, review=state)
        if kind == "edge" and relations:
            fw.set_state("edge", item_id, origin="projection")
            fw.add_inputs("edge", item_id, 1, [judgment["id"]])
        for d in fw.decisions(kind="review"):
            if d["subject_id"] == item_id:
                fw.close_decision(d["id"], "resolved", {"verdict": verdict, "judgment_id": judgment["id"]})
        return {"item_id": item_id, "review": state, "judgment_id": judgment["id"]}

    def index_page(self, page_id: str) -> None:
        page = self.ws.framework.page(page_id)
        ver = self.ws.framework.page_version(page_id, page["head_version"])
        text = f"{page['title']}\n{ver['data'].get('summary') or ''}\n{ver['data']['body']}"
        self.ws.index.replace(page_id, page["head_version"], "framework", [(0, page["type"], sha256_text(text), text)])

    # ---------- 内部 ----------
    def _check_input(self, ref: str) -> None:
        base, version = split_version(ref.split("#", 1)[0])
        entry = self.ws.get(base)
        if entry is None:
            raise BurrowlError("NOT_FOUND", "输入条目不存在", {"ref": ref})
        if base.startswith("pg_") and version and self.ws.framework.page_version(base, version) is None:
            raise BurrowlError("NOT_FOUND", "输入页面的版本不存在", {"ref": ref})

    def _check_threshold(self, actor: Actor, subject_id: str) -> None:
        """新建实体页或概念页的门槛（D-16）：用户标记过；或该对象出现在两条以上的条目中。

        条目包括提及它的原件，以及对象列表中有它的原件、事实记录、判断（结论、过程、规定都算）；
        过程日志和读取记录不算（读取记录是自动日志，设计稿 01 D-06）。
        目的只是不建空壳页，所以用可以直接数出来的条件，不判断"是否正在研究"。
        """
        fw = self.ws.framework
        entity = fw.entity(subject_id)
        if entity is None:
            raise BurrowlError("NOT_FOUND", "subject_id 指向的实体不存在", {"subject_id": subject_id})
        if actor.kind == "human" or entity["user_marked"]:
            return
        mentions = {e["src_id"] for e in fw.edges_of(subject_id) if e["rel"] == "mentions"
                    and e["src_id"].startswith("art_") and e["review"] != "rejected"}
        tagged = {r["entry_id"] for r in self.ws.ledger.query(
            "SELECT entry_id FROM entry_objects WHERE object = ? AND entry_id NOT LIKE 'evt_%' "
            "AND entry_id NOT LIKE 'rd_%'", (subject_id,))}
        entries = mentions | tagged
        if len(entries) >= 2:
            return
        raise BurrowlError("PAGE_THRESHOLD",
                           "这个实体只出现在不到两条条目中，先不建页面（只保留图节点和提及边）",
                           {"subject_id": subject_id, "appears_in": sorted(entries)})


def _slugify(title: str) -> str:
    slug = "-".join(title.strip().lower().split())
    return slug[:80] or "page"
