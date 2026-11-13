"""参照实现（设计稿 10 D-38）：2.2.0 用 SQL 取关系、框架边与不画的条目的关系图，原样保留，只在测试里用。

对比测试要求两个新开关（history、dispositions）都关时，读内存图的 graph.view 与它输出一致。
节点的坐标、名称仍走 OverviewService 的同名方法（坐标本身另有对比测试）。
"""
from collections import deque

from burrowl.core.errors import BurrowlError
from burrowl.core.ids import parse_ref
from burrowl.core.vocab import PREDICATES, relation_phrase
from burrowl.services.overview import OverviewService


class SqlGraph(OverviewService):
    def graph(self, *, center: str | None = None, hops: int = 2, node_types: list[str] | None = None,
              categories: list[str] | None = None, hide_superseded: bool = False, limit: int = 300,
              layers: list[str] | None = None, source_classes: list[str] | None = None, source_mode: str = "any",
              kinds: list[str] | None = None, quoted: bool | None = None, keep_related: bool = False,
              judgment_kinds: list[str] | None = None) -> dict:
        """节点是条目，边是关系（判断不拆成论点）。默认按条目聚合：同一主语对同一条目的同一谓词画成一条边，
        count 是关系条数（如"依据 5 段"）；evidence_from 是证据一端（证据流统一画成"证据 → 结论"）。

        筛选与条目页、检索页同名同序（D-24），在裁剪到 limit 之前进行：
        layers 综合程度 → source_classes 依据来源（local / external / inferred；source_mode any 含其一 / only 全部在内）
        → kinds 类型（结论 / 过程 / 规定）→ quoted 说明（只要转述的）；categories 关系类别（词表 CATEGORIES）；
        keep_related：同时保留与筛中节点有佐证、反驳关系的原件与判断（"文献对照"组合用）。"""
        if source_mode not in ("any", "only"):
            raise BurrowlError("INVALID_ARGUMENT", "source_mode 必须是 any 或 only")
        kinds = kinds or judgment_kinds
        node_types = set(node_types or ["artifact", "judgment", "page", "entity"])
        nodes: dict[str, dict] = {}
        ledger, fw = self.ws.ledger, self.ws.framework
        excluded = self.ws.purge.excluded_ids()  # 已退役的原件、依据全部失效的条目不画（设计稿 07 D-02）

        def add_node(node_id: str) -> bool:
            base = parse_ref(node_id)[0]
            if base in excluded:
                return False
            t = {"jdg": "judgment", "art": "artifact", "rec": "record", "rd": "read", "pg": "page",
                 "ent": "entity", "evt": "event"}.get(base.split("_")[0])
            if t is None or t not in node_types:
                return False
            if base not in nodes:
                nodes[base] = {"id": base, "type": t}
            return True

        agg: dict[tuple, dict] = {}

        def add_edge(subject: str, obj: str, predicate: str, *, origin: str, label: str | None = None,
                     rel_id: str | None = None, **extra) -> None:
            s, o = parse_ref(subject)[0], parse_ref(obj)[0]
            key = (s, o, predicate, label or "")
            edge = agg.get(key)
            if edge is None:
                p = PREDICATES.get(predicate, {})
                flow = p.get("flow")
                edge = agg[key] = {"id": rel_id or f"{predicate}:{s}:{o}", "source": s, "target": o,
                                   "predicate": predicate, "rel": predicate, "label": label,
                                   "category": p.get("category", "free"), "origin": origin, "count": 0,
                                   "phrase": relation_phrase(predicate, outgoing=True, label=label),
                                   **({"evidence_from": o if flow == "object_to_subject" else s} if flow else {}),
                                   **extra}
            edge["count"] += 1

        # 只画当前版的出边（旧版的关系在版本历史里看）
        for r in ledger.query("SELECT r.* FROM effective_relations r WHERE r.subject_version IS NULL OR "
                              "r.subject_version = (SELECT MAX(version) FROM ("
                              "SELECT version FROM judgment_versions WHERE id = r.subject_id UNION ALL "
                              "SELECT version FROM record_versions WHERE id = r.subject_id UNION ALL "
                              "SELECT version FROM event_versions WHERE id = r.subject_id UNION ALL "
                              "SELECT version FROM artifact_versions WHERE id = r.subject_id UNION ALL "
                              "SELECT version FROM read_versions WHERE id = r.subject_id))"):
            add_edge(r["subject_id"], r["object_id"], r["predicate"], origin=PREDICATES.get(
                r["predicate"], {}).get("origin", "judgment"), label=r.get("label"), rel_id=r["id"])
        for e in fw.edges():
            if e["review"] == "rejected":
                continue
            add_edge(e["src_id"], e["dst_id"], e["rel"], origin="framework", rel_id=e["id"], review=e["review"],
                     freshness=e["freshness"])
        for p in fw.pages():
            for ref in fw.inputs_of("page", p["id"], p["head_version"]):
                add_edge(p["id"], ref, "derived_from", origin="framework")
            if p["subject_id"]:
                add_edge(p["subject_id"], p["id"], "subject_of", origin="framework")
        edges = list(agg.values())
        if categories:
            edges = [e for e in edges if e["category"] in categories]
        edges = [e for e in edges if add_node(e["source"]) and add_node(e["target"])]
        # 没有任何边的条目也显示（例如刚登记的原件）
        if center is None:
            for t, sql in (("artifact", "SELECT id FROM artifacts"), ("judgment", "SELECT id FROM judgments")):
                if t in node_types:
                    for r in ledger.query(f"{sql} ORDER BY created_at DESC LIMIT ?", (limit,)):
                        add_node(r["id"])
            if "page" in node_types:
                for p in fw.pages():
                    add_node(p["id"])
        memo: dict = {}
        if layers or source_classes or kinds or quoted is not None:
            keep = {k for k, v in nodes.items()
                    if self._node_passes(k, v["type"], memo, layers=layers, source_classes=source_classes,
                                         source_mode=source_mode, kinds=kinds, quoted=quoted)}
            if keep_related:
                for e in edges:
                    if e["predicate"] not in ("supports", "opposes", "may_contradict"):
                        continue
                    for a, b in ((e["source"], e["target"]), (e["target"], e["source"])):
                        if a in keep and b in nodes and nodes[b]["type"] in ("artifact", "judgment", "record") \
                                and (not layers or self._layer_of(b, nodes[b]["type"]) in layers):
                            keep.add(b)
            nodes = {k: v for k, v in nodes.items() if k in keep}
            edges = [e for e in edges if e["source"] in nodes and e["target"] in nodes]

        if center:
            base = parse_ref(center)[0]
            adjacency: dict[str, set[str]] = {}
            for e in edges:
                adjacency.setdefault(e["source"], set()).add(e["target"])
                adjacency.setdefault(e["target"], set()).add(e["source"])
            keep, frontier = {base}, deque([(base, 0)])
            while frontier and len(keep) < limit:
                node, depth = frontier.popleft()
                if depth >= hops:
                    continue
                for nxt in adjacency.get(node, ()):
                    if nxt not in keep:
                        keep.add(nxt)
                        frontier.append((nxt, depth + 1))
            add_node(base)
            nodes = {k: v for k, v in nodes.items() if k in keep}
        truncated = len(nodes) > limit
        if truncated:
            degree: dict[str, int] = {}
            for e in edges:
                degree[e["source"]] = degree.get(e["source"], 0) + 1
                degree[e["target"]] = degree.get(e["target"], 0) + 1
            nodes = dict(sorted(nodes.items(), key=lambda kv: -degree.get(kv[0], 0))[:limit])
        for node in nodes.values():
            node.update(self._node_info(node["id"], node["type"], memo))
        if hide_superseded:
            nodes = {k: v for k, v in nodes.items() if (v.get("state") or {}).get("validity", "current") == "current"}
        edges = [e for e in edges if e["source"] in nodes and e["target"] in nodes]
        return {"nodes": list(nodes.values()), "edges": edges, "truncated": truncated, "center": center}
