"""F5 框架层：实体、实体页、概念页、综合页、非文本原件的描述、AI 推断的边（草图 §11、§12.2）。

- 框架回答"现在该信什么、该怎么理解"，全部可以再生，永远不能作为依据。
- 每个框架条目生成时记下输入清单；时效与复核状态单独维护。
- AI 写的条目一律是"AI 生成、未复核"，但不再逐条进待复核列表（设计稿 04 D-01、D-02）：页面成为两个以上
  页面的输入、有人请人复核、AI 复核认为有问题时才进（D-05）；两端都是判断的可能矛盾、可能替代照旧进。
- 复核在 services/review.py；复核结论是被复核条目的变更历史，不再写成判断（D-18）。
- 新建实体页、概念页要过门槛，不建空壳页（草图 §12.2 第 3 条）。
"""
from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.hashing import sha256_text
from ..core.ids import split_version
from ..core.model import PAGE_TYPES
from ..core.refs import extract_refs
from ..index.units import build_units, markdown_segments

AI_EDGE_RELS = ("may_contradict", "may_supersede", "similar", "analogy", "related")


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
        review = "human_reviewed" if actor.kind == "human" else "ai_generated"  # AI 改写后回到未复核（D-14）
        page = fw.write_page(
            page_id=current["id"] if current else None, type_=type, slug=slug, title=title, subject_id=subject_id,
            author_id=actor.id, review=review, inputs=inputs,
            version_data={"body": body, "title": title, "summary": summary, "author_kind": actor.kind,
                          "session_id": actor.session_id},
            page_data={"summary": summary, "ai_written": actor.kind == "ai"},
        )
        self.index_page(page["id"])
        rederive = fw.open_decision_for("rederive", page["id"])
        if rederive:
            fw.close_decision(rederive["id"], "resolved", {"version": page["head_version"]})
        self.ws.reviews.on_page_inputs(inputs)  # 按需复核：用到的 AI 页面成为两个以上页面的输入时（D-05）
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
        input_statuses = {}
        for ref in inputs:
            status = self.ws.coordinates.ref_status(ref)
            input_statuses[ref] = status
            if status.get("missing") or status.get("validity", "current") != "current" or status.get("current_ref"):
                changed.append(ref)
        decision = fw.open_decision_for("rederive", page_id) if version == page["head_version"] else None
        return {"page": page, "version": version, "body": ver["data"]["body"], "summary": ver["data"].get("summary"),
                "author_id": ver["author_id"], "inputs": inputs, "superseded_inputs": changed,
                "input_statuses": input_statuses,
                "basis_mix": self.ws.retrieval.basis_mix(inputs),  # 设计稿 09 D-12
                "change_reason": decision["data"].get("reason") if decision else None,
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
                                          review="ai_generated",
                                          data={"reason": reason, "by": actor.id, "session_id": actor.session_id},
                                          inputs=[src_id, dst_id, *(inputs or [])])
        # 只有确认后会写回判断层的边（两端都是判断的可能矛盾、可能替代）进待复核；关联边只打标签（D-02、D-08）
        if self.ws.reviews.is_writeback(edge) and not self.ws.framework.open_decision_for("review", edge["id"]):
            self.ws.framework.add_decision("review", edge["id"], 1,
                                           {"what": f"AI 推断的关系 {rel}", "src_id": src_id, "dst_id": dst_id,
                                            "reason": reason})
        return edge

    # ---------- 复核（人） ----------
    def review(self, actor: Actor, *, item_id: str, verdict: str, reason: str, cites: list[str] | None = None) -> dict:
        """旧的入口：转给 services/review.py 的 submit（设计稿 04 D-10）。"""
        return self.ws.reviews.submit(actor, item_id=item_id, verdict=verdict, reason=reason, cites=cites)

    def index_page(self, page_id: str) -> None:
        page = self.ws.framework.page(page_id)
        ver = self.ws.framework.page_version(page_id, page["head_version"])
        text = f"{page['title']}\n{ver['data'].get('summary') or ''}\n{ver['data']['body']}"
        # 框架页按 Markdown 标题切成检索单元（设计稿 06 D-05），长页面也能定位到节
        summary = ver["data"].get("summary") or ""
        segs = ([{"anchor": "summary", "text": summary}] if summary else []) + markdown_segments(ver["data"]["body"])
        self.ws.index.replace(page_id, page["head_version"], "framework", [(0, page["type"], sha256_text(text), text)],
                              build_units(segs, title=page["title"], **self.ws.unit_options()))

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
        # 已退役的原件、依据全部失效而隐藏的条目不计入（设计稿 02 D-12、07 D-02）
        entries = (mentions | tagged) - self.ws.purge.excluded_ids()
        if len(entries) >= 2:
            return
        raise BurrowlError("PAGE_THRESHOLD",
                           "这个实体只出现在不到两条条目中，先不建页面（只保留图节点和提及边）",
                           {"subject_id": subject_id, "appears_in": sorted(entries)})


def _slugify(title: str) -> str:
    slug = "-".join(title.strip().lower().split())
    return slug[:80] or "page"
