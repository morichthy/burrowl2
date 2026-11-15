"""F5 框架层：实体、实体页、概念页、综合页、非文本原件的描述、AI 推断的边（草图 §11、§12.2）。

- 框架回答"现在该信什么、该怎么理解"，全部可以再生，永远不能作为依据。
- 每个框架条目生成时记下输入清单；时效与复核状态单独维护。
- AI 写的条目一律是"AI 生成、未复核"，但不再逐条进待复核列表（设计稿 04 D-01、D-02）：页面成为两个以上
  页面的输入、有人请人复核、AI 复核认为有问题时才进（D-05）；两端都是判断的可能矛盾、可能替代照旧进。
- 复核在 services/review.py；复核结论是被复核条目的变更历史，不再写成判断（D-18）。
- 新建实体页、概念页要过门槛，不建空壳页（草图 §12.2 第 3 条）。
"""
from datetime import UTC, datetime, timedelta

from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.hashing import sha256_text
from ..core.ids import make_ref, parse_ref, split_version, ulid
from ..core.model import PAGE_TYPES
from ..core.refs import extract_refs, strip_markers
from ..index.tokenize import tokens
from ..index.units import build_units, markdown_segments

AI_EDGE_RELS = ("may_contradict", "may_supersede", "may_support", "similar", "analogy", "related", "refines")
# 要点的关联（设计稿 17 D-06）：一致、矛盾、细化、相关（相似、类比照旧可用）
POINT_LINK_RELS = ("may_support", "may_contradict", "refines", "related", "similar", "analogy")
POINT_SUBKINDS = ("digest", "lesson")  # 摘要 / 经验（D-02）
POINT_SUBKIND_LABEL = {"digest": "摘要", "lesson": "经验"}
SIMILAR_LIST = 0.3   # 字面重合度不低于这个值列进 similar
SIMILAR_HINT = 0.55  # 不低于这个值给 SIMILAR_POINT 提示（巡检的重复要点同用）


def point_tokens(text: str) -> set[str]:
    return set(tokens(strip_markers(text or "")))


def overlap(a: set[str], b: set[str]) -> float:
    """重合度：交集 / 较小的一边（短的一条被长的一条包含时也算相似）。"""
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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

    # ---------- 要点（设计稿 15 C 组；设计稿 17：轻判断） ----------
    def point_write(self, actor: Actor, *, title: str | None = None, text: str | None = None,
                    cites: list | None = None, conditions: str | None = None, external_author: str | None = None,
                    objects: list[str] | None = None, revises: str | None = None, reason: str | None = None,
                    scope_unclear: bool | None = None, subkind: str | None = None, links: list[dict] | None = None,
                    add_cites: list | None = None) -> dict:
        """写一条要点：为经验复用、快速导航与联想而写的轻判断，框架层的独立条目，不能作为依据（设计稿 17 D-01）。
        - subkind：digest 摘要（一份材料说了什么，默认）/ lesson 经验（从几处来源归纳出的可复用规律或做法）；
        - cites：原件段落、原件、事实记录、判断或别的要点，可以跨多份材料，至少一项（D-03）；正文用 [^n] 时
          每个编号对应 cites 的一项 {ref, marker, role, why}（设计稿 11 的对应规则）；
        - links：[{rel, target, why}]，写入时一并建框架边（一致 may_support、矛盾 may_contradict、细化 refines、
          相关 related……，D-06、D-07）；
        - revises：写那条要点的新版本；没给的字段沿用上一版。add_cites 在沿用的依据上追加——把新来源并进已有要点
          （先查后写，D-09）。AI 可以改写 AI 写的、人还没复核过的要点（D-10）。"""
        from .judgments import clean_title
        fw = self.ws.framework
        page, last = None, {}
        if revises:
            page = fw.page(parse_ref(revises)[0])
            if page is None or page["type"] != "point":
                raise BurrowlError("NOT_FOUND", "要改写的要点不存在", {"revises": revises})
            if not (reason or "").strip():
                raise BurrowlError("INVALID_ARGUMENT", "改写要点要说明原因（reason）")
            last = fw.page_version(page["id"], page["head_version"])["data"]
            if actor.kind != "human" and (page["review"] == "human_reviewed" or last.get("author_kind") == "human"):
                raise BurrowlError("FORBIDDEN", "人写的或人复核过的要点只有人能改；有异议请另写一条要点并用 links 连上"
                                   "（may_contradict），或请人处理", {"revises": revises})
        title = clean_title(title if title is not None else last.get("title")) or ""
        text = text if (text or "").strip() else last.get("body") or ""
        if not title or not text.strip():
            raise BurrowlError("INVALID_ARGUMENT", "要点要有 title（一句话，写出对象）和 text（论断本身）")
        subkind = subkind or last.get("subkind") or "digest"
        if subkind not in POINT_SUBKINDS:
            raise BurrowlError("INVALID_ARGUMENT", "要点的 subkind 是 digest（摘要）或 lesson（经验）",
                               {"subkind": subkind})
        if cites is None and last:
            cites = [{"ref": c["ref"], **{k: c[k] for k in ("marker", "role", "why") if c.get(k)}}
                     for c in last.get("cites") or []]
        cites = [*(cites or []), *(add_cites or [])]
        refs, cited, _, notes = self.ws.claims.prepare(actor, "conclusion", text, cites, None, layer="framework")
        if not refs:
            raise BurrowlError("INVALID_ARGUMENT",
                               "要点至少引用一处来源（原件段落、事实记录、判断或要点）：出处要可回溯")
        if page and any(parse_ref(r)[0] == page["id"] for r in refs):
            raise BurrowlError("INVALID_ARGUMENT", "要点不能引用它自己")
        pin = {r: self._pin(r) for r in refs}
        refs = list(dict.fromkeys(pin.values()))
        notes = {pin[k]: v for k, v in notes.items()}
        cited = {pin.get(k, k): v for k, v in cited.items()}
        items = [{"ref": r, **notes.get(r, {}), **({"sha256": cited[r]["sha256"]} if r in cited else {})}
                 for r in refs]
        arts = list(dict.fromkeys(parse_ref(r)[0] for r in refs if r.startswith("art_")))
        links = self._check_links(links, page["id"] if page else None)

        def keep(key: str, value):
            return value if value is not None else last.get(key)
        conditions = keep("conditions", (conditions.strip() or None) if conditions is not None else None)
        external_author = keep("external_author", (external_author.strip() or None)
                               if external_author is not None else None)
        objs = self.ws.linking.normalize_objects(objects) if objects is not None else last.get("objects") or []
        scope_unclear = keep("scope_unclear", (bool(scope_unclear) or None) if scope_unclear is not None else None)
        review = "human_reviewed" if actor.kind == "human" else "ai_generated"
        result = fw.write_page(
            page_id=page["id"] if page else None, type_="point",
            slug=page["slug"] if page else f"point-{ulid().lower()}",
            title=title, subject_id=None, author_id=actor.id, review=review, inputs=[*refs, *arts],
            version_data={"body": text, "title": title, "summary": None, "author_kind": actor.kind,
                          "session_id": actor.session_id, "subkind": subkind, "conditions": conditions,
                          "external_author": external_author, "objects": objs, "cites": items,
                          "scope_unclear": scope_unclear, **({"reason": reason} if revises else {})},
            page_data={**((page or {}).get("data") or {}), "summary": None, "ai_written": actor.kind == "ai"})
        pid = result["id"]
        self.index_page(pid)
        for link in links:
            self.edge_add(actor, rel=link["rel"], src_id=pid, dst_id=link["target"],
                          reason=link["why"] or "要点关联", inputs=[f"{pid}@{result['head_version']}"])
        if revises:
            self.ws.propagation.propagate([pid, f"{pid}@{result['head_version'] - 1}"], reason=f"要点 {pid} 改写")
        self.ws.capture.log(actor, "framework.point_write", input={"page_id": pid, "version": result["head_version"]},
                            objects=objs)
        warnings, codes = self.ws.claims.notice_warnings(self.ws.claims.notices(refs, cited, []))
        for code, message in self.ws.claims.lint(  # 只提示（D-04）：条件只对摘要提示
                text=text, title=title, conditions=conditions, scope_unclear=bool(scope_unclear), notes=notes,
                needs_conditions=subkind == "digest", quoted=True):
            codes.add(code)
            warnings.append(message)
        sources = {parse_ref(r)[0] for r in refs}
        if subkind == "lesson" and len(sources) < 2:
            codes.add("LESSON_SINGLE_SOURCE")
            warnings.append("LESSON_SINGLE_SOURCE：经验只引用了一处来源；经验是从几处材料或几条判断归纳出的，"
                            "只来自一份材料的请写成摘要（subkind=digest），或补上别的来源")
        similar = self.similar_points(f"{title}\n{strip_markers(text)}", exclude={pid})
        if similar and similar[0]["score"] >= SIMILAR_HINT and not revises:
            codes.add("SIMILAR_POINT")
            warnings.append(f"SIMILAR_POINT：已有相似的要点 {similar[0]['id']}（{similar[0]['title']}）。说的是同一件事"
                            "时，请把新来源并进那一条（point_write 的 revises + add_cites），"
                            "再用 point_archive 归档这条（merged_into 写那一条）；不是同一件事就用 links 连上")
        return {**self.point_view(pid), "similar": similar, "warnings": warnings, "warning_codes": sorted(codes)}

    def _check_links(self, links: list[dict] | None, self_id: str | None) -> list[dict]:
        out = []
        for link in links or []:
            rel, target = (link or {}).get("rel"), (link or {}).get("target")
            if rel not in POINT_LINK_RELS:
                raise BurrowlError("INVALID_ARGUMENT", f"links 的 rel 是 {', '.join(POINT_LINK_RELS)} 之一",
                                   {"rel": rel})
            if not target or self.ws.get(parse_ref(target)[0]) is None:
                raise BurrowlError("NOT_FOUND", "links 的 target 不存在", {"target": target})
            if self_id and parse_ref(target)[0] == self_id:
                raise BurrowlError("INVALID_ARGUMENT", "要点不能连到它自己")
            out.append({"rel": rel, "target": parse_ref(target)[0], "why": (link.get("why") or "").strip()})
        return out

    def _pin(self, ref: str) -> str:
        base, version, anchor = parse_ref(ref)
        if base.startswith("pg_"):
            return make_ref(base, version or self.ws.framework.page(base)["head_version"], anchor)
        return make_ref(base, version or self.ws.ledger.head_version(base), anchor)

    # ---------- 要点：相似、活跃度、归档（D-09、D-11、D-12） ----------
    def live_points(self) -> list[dict]:
        """当前没有归档的要点（页面行）。"""
        return [p for p in self.ws.framework.pages(type_="point") if not (p.get("data") or {}).get("archived")]

    def archived_points(self) -> set[str]:
        return {p["id"] for p in self.ws.framework.pages(type_="point") if (p.get("data") or {}).get("archived")}

    def point_text(self, page_id: str) -> str:
        page = self.ws.framework.page(page_id)
        data = (self.ws.framework.page_version(page_id, page["head_version"]) or {}).get("data") or {}
        return f"{data.get('title') or page['title']}\n{strip_markers(data.get('body') or '')}"

    def similar_points(self, text: str, *, exclude: set[str] | frozenset = frozenset(), limit: int = 3) -> list[dict]:
        """按字面（双字切词的重合度）找相似的要点，不调用模型；给"先查后写"和巡检的重复要点用。"""
        mine = point_tokens(text)
        if not mine:
            return []
        out = []
        for p in self.live_points():
            if p["id"] in exclude:
                continue
            score = overlap(mine, point_tokens(self.point_text(p["id"])))
            if score >= SIMILAR_LIST:
                out.append({"id": p["id"], "title": p["title"], "score": round(score, 2)})
        return sorted(out, key=lambda x: -x["score"])[:limit]

    def point_use(self, page_id: str, *, window_days: float | None = None) -> dict:
        """活跃度（读取时算，不存）：窗口内被检索返回的次数、作为综合页输入的次数、框架边数、来源数。"""
        fw = self.ws.framework
        days = float(window_days or self.ws.inspection.settings().get("window_days") or 90)
        since = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        hits = 0
        for ev in self.ws.ledger.query("SELECT data FROM events WHERE op = 'search' AND created_at >= ?", (since,)):
            hits += sum(1 for h in ((ev["data"] or {}).get("input") or {}).get("hits") or [] if h.get("id") == page_id)
        pages = [pid for kind, pid in fw.dependents([page_id]) if kind == "page"
                 and (fw.page(pid) or {}).get("type") != "point"]
        edges = [e for e in fw.edges_of(page_id) if e["review"] != "rejected"]
        page = fw.page(page_id)
        data = (fw.page_version(page_id, page["head_version"]) or {}).get("data") or {}
        sources = {parse_ref(c["ref"])[0] for c in data.get("cites") or []}
        return {"hits": hits, "pages": len(pages), "links": len(edges), "sources": len(sources), "window_days": days}

    def point_archive(self, actor: Actor, ref: str, *, reason: str, merged_into: str | None = None) -> dict:
        """归档一条要点：默认不出现在检索、关系图、列表与计数里，版本都在，可以恢复（D-11）。
        AI 只能在合并时归档 AI 写的、人没复核过的要点（merged_into 是并入的那条）；其余由人做。"""
        fw = self.ws.framework
        page = fw.page(parse_ref(ref)[0])
        if page is None or page["type"] != "point":
            raise BurrowlError("NOT_FOUND", "要点不存在", {"ref": ref})
        if not (reason or "").strip():
            raise BurrowlError("INVALID_ARGUMENT", "归档要写原因（reason）")
        if merged_into:
            target = fw.page(parse_ref(merged_into)[0])
            if target is None or target["type"] != "point" or target["id"] == page["id"]:
                raise BurrowlError("INVALID_ARGUMENT", "merged_into 要是另一条要点", {"merged_into": merged_into})
        if actor.kind != "human":
            last = fw.page_version(page["id"], page["head_version"])["data"]
            if not merged_into or page["review"] == "human_reviewed" or last.get("author_kind") == "human":
                raise BurrowlError("FORBIDDEN", "AI 只能在合并时归档 AI 写的、人没复核过的要点（给出 merged_into）；"
                                   "其余请交巡检发现，由人决定", {"ref": ref})
        archived = {"at": now_iso(), "by": actor.id, "reason": reason.strip(),
                    **({"merged_into": parse_ref(merged_into)[0]} if merged_into else {})}
        fw.set_page_data(page["id"], {"archived": archived})
        self.ws.capture.log(actor, "framework.point_archive", input={"page_id": page["id"], **archived})
        return {"id": page["id"], "archived": archived}

    def point_restore(self, actor: Actor, ref: str, *, reason: str) -> dict:
        """恢复归档的要点（人）。"""
        actor.require_human("恢复归档的要点")
        fw = self.ws.framework
        page = fw.page(parse_ref(ref)[0])
        if page is None or page["type"] != "point" or not (page.get("data") or {}).get("archived"):
            raise BurrowlError("NOT_FOUND", "没有这条归档的要点", {"ref": ref})
        fw.set_page_data(page["id"], {"archived": None})
        self.ws.capture.log(actor, "framework.point_restore", input={"page_id": page["id"], "reason": reason})
        return {"id": page["id"], "archived": None}

    def point_view(self, ref: str) -> dict:
        """要点的完整内容（设计稿 15 D-11、17 D-17）：标签、正文、条件、原作者、对象、每项来源（段落带原文片段）、
        关联（框架边）、被哪些综合页用到、活跃度、说明、来源是否已变化；读的是旧版时带回当前版。"""
        fw = self.ws.framework
        page_id, version = split_version(ref)
        page = fw.page(page_id)
        if page is None or page["type"] != "point":
            raise BurrowlError("NOT_FOUND", "要点不存在", {"ref": ref})
        version = version or page["head_version"]
        data = (fw.page_version(page_id, version) or {}).get("data") or {}
        cites, changed = [], []
        for c in data.get("cites") or []:
            base = parse_ref(c["ref"])[0]
            if base.startswith("pg_"):
                other = fw.page(base)
                status = {} if other else {"missing": True}
                text = (other or {}).get("title") or ""
            else:
                status = self.ws.coordinates.ref_status(c["ref"])
                text = self.ws.retrieval.segment_text(c["ref"]) if "#" in c["ref"] \
                    else self.ws.retrieval.preview(c["ref"])
            cites.append({"cite_as": c["ref"], **{k: c[k] for k in ("role", "why", "marker") if c.get(k)},
                          "text": (text or "")[:300]})
            if status.get("missing") or status.get("validity", "current") != "current" or status.get("current_ref") \
                    or status.get("anchor_missing"):
                changed.append({"ref": c["ref"], **({"current_ref": status["current_ref"]}
                                                    if status.get("current_ref") else {}),
                                "detail": status.get("status_note") or "来源已删除"})
        subkind = data.get("subkind") or "digest"
        archived = (page.get("data") or {}).get("archived")
        note = [f"框架 · 要点（{POINT_SUBKIND_LABEL[subkind]}）"]
        if archived:
            note.append("已归档" + (f"，并入 {archived['merged_into']}" if archived.get("merged_into") else ""))
        if data.get("external_author"):
            note.append(f"转述 · 原作者 {data['external_author']}")
        if data.get("scope_unclear"):
            note.append("适用范围未明")
        elif not data.get("conditions") and subkind == "digest":
            note.append("没写条件")
        if changed:
            note.append("来源已变化")
        if page["freshness"] == "inputs_changed" and version == page["head_version"]:
            note.append("输入已变化")
        note.append("不能作为依据，要依据请读 cites 里的来源")
        links = []
        for e in fw.edges_of(page_id):
            if e["review"] == "rejected":
                continue
            out = e["src_id"] == page_id
            links.append({"id": e["id"], "rel": e["rel"], "direction": "out" if out else "in",
                          "other": e["dst_id"] if out else e["src_id"], "why": (e.get("data") or {}).get("reason")})
        used_by = [pid for kind, pid in fw.dependents([page_id]) if kind == "page"
                   and (fw.page(pid) or {}).get("type") != "point"]
        out = {"id": page_id, "ref": make_ref(page_id, version), "kind": "point", "subkind": subkind,
               "title": data.get("title"), "text": data.get("body"), "conditions": data.get("conditions"),
               "external_author": data.get("external_author"), "objects": data.get("objects") or [],
               "cites": cites, "links": links, "used_by": used_by, "use": self.point_use(page_id),
               "review": page["review"], "status_note": "；".join(note),
               **({"scope_unclear": True} if data.get("scope_unclear") else {}),
               **({"archived": archived} if archived else {})}
        if changed:
            out["source_changed"] = changed
        if version < page["head_version"]:
            out["current_ref"] = make_ref(page_id, page["head_version"])
        return out

    def points_citing(self, artifact_id: str) -> list[str]:
        """引用了这份原件（段落）的要点（当前版）：按引用算出，不是挂载关系（D-08、D-16）。"""
        return [pid for kind, pid in self.ws.framework.dependents([artifact_id])
                if kind == "page" and (self.ws.framework.page(pid) or {}).get("type") == "point"]

    # ---------- 页面 ----------
    def page_write(self, actor: Actor, *, type: str, title: str, body: str, inputs: list[str] | None = None,
                   slug: str | None = None, summary: str | None = None, subject_id: str | None = None) -> dict:
        if type not in PAGE_TYPES:
            raise BurrowlError("INVALID_ARGUMENT", f"type 必须是 {', '.join(PAGE_TYPES)} 之一", {"type": type})
        if type == "point":
            raise BurrowlError("INVALID_ARGUMENT", "要点用 point_write 写（带条件、原作者与段落依据）")
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
        extra = {"point": self.point_view(f"{page_id}@{version}")} if page["type"] == "point" else {}
        return {**extra, "page": page, "version": version, "body": ver["data"]["body"],
                "summary": ver["data"].get("summary"),
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
        if page["type"] == "point":  # 要点：标题、正文、条件、对象都进索引（设计稿 15 D-13）
            d = ver["data"]
            body = strip_markers(d["body"]) + (f"\n条件：{d['conditions']}" if d.get("conditions") else "") \
                + (f"\n对象：{'、'.join(d['objects'])}" if d.get("objects") else "")
            text = f"{page['title']}\n{body}"
            self.ws.index.replace(page_id, page["head_version"], "framework", [(0, "point", sha256_text(text), text)],
                                  build_units([{"anchor": "point", "text": body}], title=page["title"],
                                              **self.ws.unit_options()))
            return
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
