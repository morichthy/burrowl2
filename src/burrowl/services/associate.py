"""联想模式（设计稿 06 D-17）：从检索命中（或给定条目）出发走 1–2 跳，把检索没有命中、但通过关系连着的条目找出来。

与检索结果里的一跳关系提示（D-12）不同：提示只注释已有命中；联想扩大召回，会带来噪声，所以单独一个操作，
每条结果都带经过的路径（via），并标为"联想，非检索命中"。不在服务端抽取实体图：只走已经存在的关系。

| 关系 | 复用模式 | 探索模式 |
|---|---|---|
| 判断之间的关系（支持、反对、回答、依赖、替代…） | 走 | 走 |
| 判断引用的依据（判断 → 原件段落、条目） | 走 | 走 |
| 引用了它的判断（原件 → 判断，即解读） | 走 | 不走 |
| 框架页的输入清单 | 走 | 不走 |
| 实体提及（经同一实体连到另一条）、AI 推断的边（相似、类比、可能矛盾，未被驳回） | 走 | 不走 |
| 共享对象（entry_objects） | 走 | 走 |
| 向量近邻 | 走 | 走 |
"""
from ..core.errors import BurrowlError

WEIGHT = {"link": 0.9, "cites": 0.8, "cited_by": 0.7, "input": 0.6, "used_in_page": 0.6, "mention": 0.5,
          "ai_edge": 0.5, "object": 0.4}
FANOUT = 20  # 每个节点每种关系最多展开几个：避免一个很泛的对象把全库都连进来
SEEDS = 5
VECTOR_MIN = 0.4  # 向量近邻的最低相似度：jina 上跨语言的同主题段落约 0.45，无关的约 0.1–0.3


class AssociateService:
    def __init__(self, ws):
        self.ws = ws

    def run(self, *, query: str | None = None, seeds: list[str] | None = None, hops: int = 1, mode: str = "reuse",
            include_process: bool | None = None, include_retired: bool = False, limit: int = 20,
            actor=None) -> dict:
        if mode not in ("reuse", "explore"):
            raise BurrowlError("INVALID_ARGUMENT", "mode 必须是 reuse 或 explore")
        if not query and not seeds:
            raise BurrowlError("INVALID_ARGUMENT", "query 与 seeds 至少给一个")
        hops = max(1, min(int(hops), 2))
        if include_process is None:
            include_process = mode == "reuse"
        ret = self.ws.retrieval
        start: dict[str, float] = {}
        anchors: dict[str, str] = {}
        if seeds:
            for i, ref in enumerate(seeds):
                base, _, anchor = ref.partition("#")
                base = base.split("@", 1)[0]
                if self.ws.get(base) is None:
                    raise BurrowlError("NOT_FOUND", "条目不存在", {"id": ref})
                start[base] = max(start.get(base, 0.0), 1.0 / (i + 1))
                if anchor:
                    anchors[base] = anchor
        else:
            res = ret.search(query, mode=mode, include_process=include_process, include_retired=include_retired,
                             limit=SEEDS, actor=actor)
            for i, h in enumerate(res["hits"]):
                start[h["id"]] = 1.0 / (i + 1)
                if h.get("anchor"):
                    anchors[h["id"]] = h["anchor"]

        found: dict[str, dict] = {}
        frontier = dict(start)
        paths: dict[str, list] = {k: [] for k in start}
        for hop in range(1, hops + 1):
            nxt: dict[str, float] = {}
            for node, score in frontier.items():
                if mode == "explore" and node.startswith(("pg_", "ent_", "edg_")):
                    continue  # 探索模式不经框架条目中转
                for other, kind, rel, via_node in self._neighbors(node, anchors.get(node), mode=mode):
                    if other in start or other == node:
                        continue
                    s = score * WEIGHT.get(kind, 0.5) * (0.5 ** (hop - 1)) if kind != "vector" else score * rel * 0.7
                    step = {"from": node, "rel": kind if kind != "vector" else "vector_neighbor",
                            "detail": rel if kind != "vector" else round(rel, 3), "to": other}
                    if via_node:
                        step["via"] = via_node
                    path = [*paths.get(node, []), step]
                    item = found.get(other)
                    if item is None or s > item["score"]:
                        found[other] = {"id": other, "score": s, "hop": hop, "via": path}
                    if s > nxt.get(other, 0.0):
                        nxt[other] = s
                        paths[other] = path
            frontier = nxt

        hits = []
        for item in sorted(found.values(), key=lambda x: -x["score"]):
            coords = ret._safe_coordinates(item["id"])
            if coords is None:
                continue
            if mode == "explore" and coords["layer"] == "framework":
                continue
            if (coords.get("process") and not include_process) or (coords.get("retired") and not include_retired):
                continue
            hits.append({**item, **coords, "score": round(item["score"], 4), "label": "联想，非检索命中",
                         "status_note": ret.status_note(coords), "text": ret.preview(item["id"])})
            if len(hits) >= limit:
                break
        return {"query": query, "seeds": list(start), "mode": mode, "hops": hops, "hits": hits, "total": len(found),
                "hints": ["联想结果是顺着关系找到的，不是检索命中；via 是经过的路径，相关与否要读原文判断",
                          "要用作依据，先用 artifact_read 读原件段落，或 entry_get 看判断"]}

    # ---------- 一个节点的邻居：(另一条目, 关系种类, 关系名或相似度, 经过的中间节点) ----------
    def _neighbors(self, node: str, anchor: str | None, *, mode: str):
        ws, out = self.ws, []
        reuse = mode != "explore"
        if node.startswith("jdg_"):
            for lk in ws.ledger.links_from(node)[:FANOUT * 2]:
                target = lk["dst_id"].split("#", 1)[0]
                out.append((target, "cites" if lk["rel"] == "used" else "link", lk["rel"], None))
            for lk in ws.ledger.links_to(node)[:FANOUT]:
                out.append((lk["src_id"], "link", lk["rel"], None))
        if reuse and node.startswith(("art_", "rec_", "evt_")):
            rs = ws.ledger.query("SELECT DISTINCT src_id FROM links WHERE (dst_id = ? OR dst_id LIKE ?) "
                                 "AND src_id LIKE 'jdg_%' LIMIT ?", (node, f"{node}#%", FANOUT))
            out += [(r["src_id"], "cited_by", "used", None) for r in rs]
        if reuse:
            if node.startswith("pg_"):
                page = ws.framework.page(node)
                if page:
                    out += [(i.split("#", 1)[0].split("@", 1)[0], "input", "input", None)
                            for i in ws.framework.inputs_of("page", node, page["head_version"])[:FANOUT]]
            else:
                out += [(p, "used_in_page", "input", None) for p in ws.retrieval._pages_using(node)[:FANOUT]]
            for e in ws.framework.edges_of(node)[:FANOUT * 2]:
                if e["review"] == "rejected":
                    continue
                other = e["dst_id"] if e["src_id"] == node else e["src_id"]
                if e["origin"] == "ai_inferred" and not other.startswith("ent_"):
                    out.append((other, "ai_edge", e["rel"], None))
                elif other.startswith("ent_"):  # 经同一实体连到另一条（实体提及）
                    for e2 in ws.framework.edges_of(other)[:FANOUT]:
                        if e2["review"] == "rejected":
                            continue
                        far = e2["src_id"] if e2["dst_id"] == other else e2["dst_id"]
                        if far != node and not far.startswith("ent_"):
                            out.append((far, "mention", e["rel"], other))
        for obj in ws.ledger.objects_of(node) if not node.startswith("pg_") else []:
            ids = [i for i in ws.ledger.entries_with_objects([obj]) if not i.startswith(("evt_", "rd_"))]
            if len(ids) <= FANOUT * 3:  # 太泛的对象不展开
                out += [(i, "object", obj, None) for i in ids[:FANOUT]]
        out += self._vector_neighbors(node, anchor)
        return out

    def _vector_neighbors(self, node: str, anchor: str | None):
        ws = self.ws
        unit = ws.index.unit_of_anchor(node, anchor) if anchor else None
        units = [unit] if unit else ws.index.units_of(node)[:1]
        out, seen = [], set()
        for u in units:
            # 最近的单元多半来自同一份原件：多取一些，跳过自己，留下其他条目里最近的 5 个
            near = ws.vectors.neighbors(u.rowid, limit=200)
            by_row = {x.rowid: x for x in ws.index.units_by_rowid([r for r, _ in near])}
            for rowid, sim in near:
                other = by_row.get(rowid)
                if other is None or other.entry_id == node or other.entry_id in seen or sim < VECTOR_MIN:
                    continue
                seen.add(other.entry_id)
                out.append((other.entry_id, "vector", sim, None))
                if len(out) >= 5:
                    break
        return out
