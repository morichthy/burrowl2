"""只读汇总：工作台的首页、条目浏览与关系图用（DESIGN §9）。不写入任何数据，也不改变排序与地位规则。"""
import json
import re
from collections import deque
from datetime import UTC, datetime, timedelta

from ..core.errors import BurrowlError
from ..core.ids import kind_of, split_version
from ..core.model import AMEND_KINDS, HISTORY_KINDS, INTERNAL_OPS, LAYER_OF_KIND, SUPERSEDING_RELS
from ..core.refs import REF_RE
from .versions import STATE_LINK

ENTRY_TABLES = {"artifact": "artifacts", "event": "events", "record": "records", "read": "reads",
                "judgment": "judgments"}

# 关系图的关系类别：同一类用同一种画法（前端图例与筛选按类别）
REL_CATEGORY = {
    "used": "evidence", "defect_of": "evidence", "documents": "evidence",
    "consumed": "structure", "produced": "structure",
    "supports": "support",
    "opposes": "conflict", "may_contradict": "conflict",
    "supersedes": "supersede", "corrects": "supersede", "retracts": "supersede", "wasRevisionOf": "supersede",
    "may_supersede": "supersede", "retires": "supersede",
    "depends_on": "structure", "answers": "structure", "targets": "structure", "coexists_under": "structure",
    "input": "derived", "about": "derived",
    "mentions": "mention",
    "similar": "association", "analogy": "association", "related": "association",
}
NODE_TYPES = ("artifact", "record", "read", "judgment", "page", "entity")
DISPLAY_LIMIT = 64
EVENT_NAMES = {
    "artifact.register": "登记原件",
    "artifact.read": "读取原件",
    "framework.page_write": "写框架页",
    "judgment.write": "写判断",
    "measure.pressure": "测量压力",
    "record.promote": "整理事实记录",
}


def _short_name(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= DISPLAY_LIMIT else text[:DISPLAY_LIMIT].rstrip() + "…"


def _first_sentence(text: str) -> str:
    """提取原句，不推断条目含义。小数点后的数字不当成下一句。"""
    text = re.sub(r"(?ms)^\s*(?:```|~~~).*?^\s*(?:```|~~~)[^\n]*$", "", text)
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:(?:#{1,6}|>|[-*+]|\d+\.)\s+)+", "", line).strip()
        if not line or line.startswith("|") or re.fullmatch(r"[-*_]{3,}", line):
            continue
        line = REF_RE.sub(lambda match: match[0][2:-2].partition("|")[2], line)
        line = line.replace("**", "").replace("__", "").strip("` ").strip()
        if line:
            sentence = re.split(r"(?<=[。！？])|(?<=[.!?])\s+", line, maxsplit=1)[0]
            return _short_name(sentence)
    return ""


def _location(anchor: str) -> str:
    page = re.fullmatch(r"p(\d+)(?:-(\d+))?", anchor)
    if page:
        return f"第 {page[1]} 页" + (f" · 段落 {page[2]}" if page[2] else "")
    # 文本段落锚点可以从 0 开始，直接展示编号以免误报位置。
    if anchor.startswith("seg-"):
        return f"段落 {anchor[4:]}"
    return f"#{anchor}" if anchor else ""


class OverviewService:
    def __init__(self, ws):
        self.ws = ws

    def entry_label(self, ref: str) -> str | None:
        """显示名随读取生成。用引用本身找内容，不沿着版本链改指向。"""
        versioned, _, anchor = ref.partition("#")
        kind = kind_of(versioned)
        if not kind:
            return None
        base, version = split_version(versioned)
        entry = self.ws.get(base)
        if entry is None or (version is not None and kind != "page"):
            return None
        data = entry.get("data") or {}
        suffix = ""
        if kind == "artifact":
            name = data.get("title") or data.get("filename") or "未命名原件"
            suffix = _location(anchor)
        elif kind == "page":
            name = entry["title"]
            if version is not None:
                snapshot = self.ws.framework.page_version(base, version)
                if snapshot is None:
                    return None
                name = snapshot["data"].get("title") or name
                suffix = f"第 {version} 版"
        elif kind == "entity":
            name = entry["name"]
        elif kind == "judgment":
            name = data.get("title") or _first_sentence(data.get("text") or "") or "判断"
        elif kind == "record":
            name = (data.get("title") or _first_sentence(data.get("corrected_text") or data.get("result") or "")
                    or _first_sentence(data.get("method") or "") or "事实记录")
        elif kind == "read":
            artifact = self.ws.ledger.get(entry["artifact_id"])
            artifact_data = artifact["data"] if artifact else {}
            title = artifact_data.get("title") or artifact_data.get("filename")
            name = f"读取《{_short_name(title)}》" if title else "读取原件"
            locator = entry.get("locator") or ""
            suffix = _location(locator.replace("seg:", "seg-")) if locator not in ("", "all") else ""
        elif kind == "event":
            name = EVENT_NAMES.get(entry["op"], entry["op"])
            objects = entry.get("objects") or []
            if objects:
                target = self.ws.framework.entity(objects[0]) if objects[0].startswith("ent_") else None
                subject = target["name"] if target else objects[0]
                if not kind_of(subject):
                    name = f"{name} · {subject}"
        else:
            name = _first_sentence(data.get("reason") or "") or self.ws.retrieval.preview(base)
        return " · ".join(part for part in (_short_name(name), suffix) if part)

    # ---------- 最近操作 ----------
    def activity(self, limit: int = 40) -> list[dict]:
        """最近的关键操作：登记原件、写判断（含更正撤回与复核）、事实记录、页面新版本、agent 运行。"""
        ledger, fw = self.ws.ledger, self.ws.framework
        items = []
        for a in ledger.query("SELECT * FROM artifacts ORDER BY created_at DESC LIMIT ?", (limit,)):
            items.append({"at": a["created_at"], "kind": "artifact", "actor": a["captured_by"], "id": a["id"],
                          "summary": f"登记原件：{a['data'].get('title') or a['kind']}"})
        for j in ledger.query("SELECT * FROM judgments ORDER BY created_at DESC LIMIT ?", (limit,)):
            items.append({"at": j["created_at"], "kind": f"judgment.{j['kind']}", "actor": j["author_id"],
                          "id": j["id"], "summary": j["data"]["text"][:120]})
        for r in ledger.query("SELECT * FROM reviews ORDER BY created_at DESC LIMIT ?", (limit,)):
            what = ("撤销" if r["data"].get("revokes") else
                    {"confirm": "确认", "reject": "驳回", "unsure": "拿不准", "request": "请人复核"}[r["verdict"]])
            who = "AI 复核" if r["method"] == "ai" and r["verdict"] != "request" else "复核"
            why = (r["data"].get("reason") or r["data"].get("note") or "")[:100]
            items.append({"at": r["created_at"], "kind": f"review.{r['verdict']}", "actor": r["actor_id"],
                          "id": r["target_id"], "summary": f"{who}{what}：{why}"})
        for r in ledger.query("SELECT * FROM retirements ORDER BY created_at DESC LIMIT ?", (limit,)):
            what = "退役原件" if r["action"] == "retire" else "撤销退役"
            items.append({"at": r["created_at"], "kind": f"artifact.{r['action']}", "actor": r["actor_id"],
                          "id": r["artifact_id"], "summary": f"{what}：{r['data'].get('reason', '')[:100]}"})
        for r in ledger.query("SELECT * FROM records ORDER BY created_at DESC LIMIT ?", (limit,)):
            what = (r["data"].get("method") or r["data"].get("result") or "")[:80]
            items.append({"at": r["created_at"], "kind": "record", "actor": r["promoted_by"], "id": r["id"],
                          "summary": f"升级事实记录：{what}"})
        for v in fw.conn.execute("SELECT v.page_id, v.version, v.created_at, v.author_id, p.title FROM page_versions v "
                                 "JOIN pages p ON p.id = v.page_id ORDER BY v.created_at DESC LIMIT ?", (limit,)):
            items.append({"at": v["created_at"], "kind": "page", "actor": v["author_id"],
                          "id": f"{v['page_id']}@{v['version']}",
                          "summary": f"框架页第 {v['version']} 版：{v['title']}"})
        for run in fw.runs(limit):
            prompt = run["data"].get("prompt", "")[:80]
            items.append({"at": run["created_at"], "kind": "agent_run", "actor": run["data"].get("started_by", ""),
                          "id": run["id"], "summary": f"agent {run['agent']}（{run['status']}）：{prompt}"})
        items.sort(key=lambda i: i["at"], reverse=True)
        return items[:limit]

    # ---------- 索引是否覆盖账本与框架 ----------
    def index_health(self) -> dict:
        """应当有索引行的条目（原件、事实记录、判断、框架页）里，缺索引的有几条。缺了可以用 index.rebuild 重建。"""
        expected = {r[0] for t in ("artifacts", "records") for r in self.ws.ledger_db.execute(f"SELECT id FROM {t}")}
        expected |= {r[0] for r in self.ws.ledger_db.execute(
            "SELECT id FROM judgments WHERE kind NOT IN ('review', 'retirement')")}
        expected |= {r[0] for r in self.ws.framework_db.execute("SELECT id FROM pages")}
        indexed = {r[0] for r in self.ws.index_db.execute("SELECT DISTINCT entry_id FROM docs")}
        missing = sorted(expected - indexed)
        return {"expected": len(expected), "missing": len(missing), "missing_ids": missing[:20]}

    def _daily(self, days: int = 14) -> dict:
        """近 days 天每天新增的条目数（按本机时区分日；不含过程日志和读取记录，它们是流水账，会盖过其他条目）。"""
        today = datetime.now().astimezone().date()
        counts = {(today - timedelta(days=i)).isoformat(): 0 for i in range(days - 1, -1, -1)}
        since = (datetime.now(UTC) - timedelta(days=days + 1)).isoformat(timespec="seconds")
        sources = [(self.ws.ledger_db, t) for t in ("artifacts", "records", "judgments")]  # 读取记录是自动日志（D-03）
        sources.append((self.ws.framework_db, "page_versions"))
        for conn, table in sources:
            for (at,) in conn.execute(f"SELECT created_at FROM {table} WHERE created_at >= ?", (since,)):
                try:
                    day = datetime.fromisoformat(at).astimezone().date().isoformat()
                except ValueError:
                    continue
                if day in counts:
                    counts[day] += 1
        return counts

    # ---------- 首页计数 ----------
    def stats(self) -> dict:
        ledger_db, fw_db = self.ws.ledger_db, self.ws.framework_db
        count = lambda conn, sql, *p: conn.execute(sql, p).fetchone()[0]  # noqa: E731
        replacement_rels = tuple(r for r in SUPERSEDING_RELS if r != "retracts")
        superseded = {r[0] for r in ledger_db.execute(
            f"SELECT DISTINCT dst_id FROM effective_links WHERE rel IN ({','.join('?' * len(replacement_rels))})",
            replacement_rels)}
        superseded.update(r[0] for r in ledger_db.execute(
            "SELECT DISTINCT dst_id FROM links WHERE rel IN ('retracts', ?) AND dst_id LIKE 'jdg_%'", (STATE_LINK,))
            if self.ws.versions.state(r[0])["withdrawn"])
        opposed = {r[0] for r in ledger_db.execute("SELECT DISTINCT dst_id FROM effective_links WHERE rel = 'opposes'")}
        judgments = {"total": 0, "local_only": 0, "with_external": 0, "inferred_only": 0, "mixed": 0,
                     "normative": 0, "process": 0, "superseded": 0, "opposed": 0,
                     "by_author": {"human": 0, "ai": 0, "system": 0}}
        sql = ("SELECT id, kind, author_kind, json_extract(data, '$.credibility') AS c FROM judgments "
               "WHERE kind NOT IN ('review', 'retirement')")
        hidden = self.ws.purge.hidden_ids()
        for r in ledger_db.execute(sql):
            if r["id"] in hidden:  # 依据全部失效而隐藏的判断不计入（设计稿 07 D-02）
                continue
            c = json.loads(r["c"] or "{}")
            classes = set(c.get("source_classes", []))
            judgments["total"] += 1
            judgments["process"] += r["kind"] == "process"
            judgments["by_author"][r["author_kind"]] = judgments["by_author"].get(r["author_kind"], 0) + 1
            if c.get("normative"):
                judgments["normative"] += 1
            elif classes == {"local"}:
                judgments["local_only"] += 1
            elif classes == {"inferred"}:
                judgments["inferred_only"] += 1
            elif "external" in classes and len(classes) == 1:
                judgments["with_external"] += 1
            if len(classes) > 1:
                judgments["mixed"] += 1
            judgments["superseded"] += r["id"] in superseded
            judgments["opposed"] += r["id"] in opposed
        group = lambda conn, sql: {r[0]: r[1] for r in conn.execute(sql)}  # noqa: E731
        return {
            "ledger": {t: count(ledger_db, f"SELECT COUNT(*) FROM {t}") for t in ENTRY_TABLES.values()},
            "artifacts_by_source": group(ledger_db, "SELECT source_class, COUNT(*) FROM artifacts GROUP BY 1"),
            "judgments": judgments,
            "pages": {"total": count(fw_db, "SELECT COUNT(*) FROM pages"),
                      "freshness": group(fw_db, "SELECT freshness, COUNT(*) FROM pages GROUP BY 1"),
                      "review": group(fw_db, "SELECT review, COUNT(*) FROM pages GROUP BY 1")},
            "edges": {"total": count(fw_db, "SELECT COUNT(*) FROM edges"),
                      "origin": group(fw_db, "SELECT origin, COUNT(*) FROM edges GROUP BY 1")},
            "entities": count(fw_db, "SELECT COUNT(*) FROM entities"),
            # 影响范围为 0 的低影响项另计，工作台默认折叠、不进角标（设计稿 04 D-07）
            "decisions": group(fw_db, "SELECT kind, COUNT(*) FROM decisions WHERE status = 'open' AND impact > 0 "
                                       "GROUP BY 1"),
            "decisions_low": count(fw_db, "SELECT COUNT(*) FROM decisions WHERE status = 'open' AND impact <= 0"),
            "runs": group(fw_db, "SELECT status, COUNT(*) FROM agent_runs GROUP BY 1"),
            "daily": self._daily(),
        }

    # ---------- 条目浏览 ----------
    def entries(self, *, kind: str = "judgment", judgment_kind: str | None = None, author_kind: str | None = None,
                source_class: str | None = None, object: str | None = None, query: str | None = None,
                include_retired: bool = False, limit: int = 50, offset: int = 0, scope: str = "operations",
                include_outputs: bool = False) -> dict:
        """include_retired：是否包含已退役的原件、依据全部失效而隐藏的条目（默认不含，设计稿 02 D-12、07 D-02）。
        scope：过程日志列哪一类，operations 操作日志（默认）/ system 系统流水 / all（设计稿 07 D-10）。
        include_outputs：原件列表是否包含运行产物（被某条过程日志 produced 的原件，默认不含，D-09）。"""
        table = ENTRY_TABLES.get(kind)
        if table is None:
            raise BurrowlError("INVALID_ARGUMENT", f"kind 必须是 {', '.join(ENTRY_TABLES)} 之一", {"kind": kind})
        where, params = ["1=1"], []
        if kind == "judgment":  # 旧版写成判断的复核、退役记录是变更历史，不列出（2.0.0a14）
            where.append(f"t.kind NOT IN ({','.join('?' * len(HISTORY_KINDS))})")
            params += list(HISTORY_KINDS)
        if kind == "judgment" and judgment_kind == "system":  # 系统记录：更正、撤回、原件缺陷
            where.append(f"t.kind IN ({','.join('?' * len(AMEND_KINDS))})")
            params += list(AMEND_KINDS)
        elif kind == "judgment" and judgment_kind:
            where.append("t.kind = ?")
            params.append(judgment_kind)
        elif kind == "judgment":
            where.append(f"t.kind NOT IN ({','.join('?' * len(AMEND_KINDS))})")
            params += list(AMEND_KINDS)
        if kind == "event" and scope != "all":
            if scope not in ("operations", "system"):
                raise BurrowlError("INVALID_ARGUMENT", "scope 必须是 operations / system / all", {"scope": scope})
            system = " OR ".join("t.op LIKE ?" for _ in INTERNAL_OPS)
            where.append(f"({system})" if scope == "system" else f"NOT ({system})")
            params += [f"{p}%" for p in INTERNAL_OPS]
        if kind == "artifact" and not include_outputs:
            where.append("t.id NOT IN (SELECT dst_id FROM links WHERE rel = 'produced')")
        if author_kind:
            col = {"artifacts": None, "events": "t.actor_kind", "judgments": "t.author_kind"}.get(table)
            if col:
                where.append(f"{col} = ?")
                params.append(author_kind)
        if source_class and kind == "artifact":
            where.append("t.source_class = ?")
            params.append(source_class)
        if source_class and kind == "judgment":
            where.append("EXISTS (SELECT 1 FROM json_each(json_extract(t.data, '$.credibility.source_classes')) "
                         "WHERE value = ?)")
            params.append(source_class)
        if object:
            normalized = self.ws.linking.normalize_objects([object])
            where.append(f"t.id IN (SELECT entry_id FROM entry_objects WHERE object IN "
                         f"({','.join('?' * len(normalized))}))")
            params += normalized
        if query:
            where.append("t.data LIKE ?")
            params.append(f"%{query}%")
        if not include_retired:  # 已退役的原件、依据全部失效而隐藏的判断与事实记录（设计稿 07 D-02）
            excluded = sorted(self.ws.purge.excluded_ids())
            if excluded:
                where.append(f"t.id NOT IN ({','.join('?' * len(excluded))})")
                params += excluded
        sql = f"FROM {table} t WHERE {' AND '.join(where)}"
        total = self.ws.ledger_db.execute(f"SELECT COUNT(*) {sql}", params).fetchone()[0]
        ids = [r[0] for r in self.ws.ledger_db.execute(
            f"SELECT t.id {sql} ORDER BY t.created_at DESC LIMIT ? OFFSET ?", [*params, limit, offset])]
        items = []
        promoted: dict[str, list[str]] = {}
        if kind == "event" and ids:
            for r in self.ws.ledger.query(f"SELECT id, event_id FROM records WHERE event_id IN "
                                          f"({','.join('?' * len(ids))})", ids):
                promoted.setdefault(r["event_id"], []).append(r["id"])
        for entry_id in ids:
            e = self.ws.ledger.get(entry_id)
            item = {"id": entry_id, "created_at": e["created_at"],
                    "preview": self.ws.retrieval.preview(entry_id), "kind": e.get("kind") or e.get("op"),
                    "objects": e.get("objects", []),
                    **self.ws.retrieval.coordinates(entry_id)}
            if kind == "event":  # 按会话归组用（D-10）：会话、顺序、操作者、已升级为哪些事实记录、输入与产出
                item.update(session_id=e["session_id"], seq=e["seq"], actor_id=e["actor_id"], op=e["op"],
                            system=e["op"].startswith(INTERNAL_OPS), promoted_to=promoted.get(entry_id, []),
                            **self.ws.capture.run_files(entry_id))
            items.append(item)
        return {"items": items, "total": total, "offset": offset}

    # ---------- 关系图 ----------
    def graph(self, *, center: str | None = None, hops: int = 2, node_types: list[str] | None = None,
              categories: list[str] | None = None, hide_superseded: bool = False, limit: int = 300) -> dict:
        """节点：原件、事实记录、读取记录、判断、框架页、实体；边：判断层关系、框架的边、页面的输入、页面的主题。"""
        node_types = set(node_types or ["artifact", "judgment", "page", "entity"])
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        ledger, fw = self.ws.ledger, self.ws.framework

        excluded = self.ws.purge.excluded_ids()  # 已退役的原件、依据全部失效的条目不画（设计稿 07 D-02）

        def add_node(node_id: str) -> bool:
            base = node_id.split("@", 1)[0].split("#", 1)[0]
            if base in excluded:
                return False
            t = {"jdg": "judgment", "art": "artifact", "rec": "record", "rd": "read", "pg": "page",
                 "ent": "entity"}.get(base.split("_")[0])
            if t is None or t not in node_types:
                return False
            if base not in nodes:
                nodes[base] = {"id": base, "type": t}
            return True

        def base_of(ref: str) -> str:
            return ref.split("@", 1)[0].split("#", 1)[0]

        def add_edge(src: str, dst: str, rel: str, **extra) -> None:
            edges.append({"source": base_of(src), "target": base_of(dst),
                          "rel": rel, "category": REL_CATEGORY.get(rel, "association"), **extra})

        history = {r["id"]: r for r in ledger.query("SELECT id, kind FROM judgments WHERE kind IN "
                                                    "('review', 'retirement')")}
        for link in ledger.query("SELECT * FROM effective_links"):
            src = link["src_id"]
            if link["rel"] == STATE_LINK:
                continue  # 版本状态在条目历史中展示，无需在关系图上画自环。
            if link["rel"] == "retracts" and self.ws.versions.state(link["dst_id"])["withdrawn"] != src:
                continue
            if link["rel"] == "defect_of" and self.ws.versions.state(link["dst_id"])["defective"] != src:
                continue  # 旧缺陷关系已取消时，仍可从版本历史查阅。
            if src in history:  # 旧版复核判断写回的替代、反对：画在边的起点判断上；退役记录不画
                src = link["data"].get("successor")
                if not src or link["rel"] in ("used", "retires"):
                    continue
            if link["dst_id"] in history:
                continue
            add_edge(src, link["dst_id"], link["rel"], origin="judgment", id=link["id"])
        for e in fw.edges():
            add_edge(e["src_id"], e["dst_id"], e["rel"], origin=e["origin"], review=e["review"],
                     freshness=e["freshness"], id=e["id"])
        for p in fw.pages():
            for ref in fw.inputs_of("page", p["id"], p["head_version"]):
                add_edge(p["id"], ref, "input", origin="derivation", id=f"in:{p['id']}:{ref}")
            if p["subject_id"]:
                add_edge(p["id"], p["subject_id"], "about", origin="derivation", id=f"about:{p['id']}")
        if categories:
            edges = [e for e in edges if e["category"] in categories]
        edges = [e for e in edges if add_node(e["source"]) and add_node(e["target"])]
        # 没有任何边的条目也显示（例如刚登记的原件）
        if center is None:
            for t, sql in (("artifact", "SELECT id FROM artifacts"),
                           ("judgment", "SELECT id FROM judgments WHERE kind NOT IN ('review', 'retirement')")):
                if t in node_types:
                    for r in ledger.query(f"{sql} ORDER BY created_at DESC LIMIT ?", (limit,)):
                        add_node(r["id"])
            if "page" in node_types:
                for p in fw.pages():
                    add_node(p["id"])

        if center:
            base = center.split("@", 1)[0].split("#", 1)[0]
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
            node.update(self._node_info(node["id"], node["type"]))
        if hide_superseded:
            nodes = {k: v for k, v in nodes.items() if not v.get("superseded")}
        edges = [e for e in edges if e["source"] in nodes and e["target"] in nodes]
        return {"nodes": list(nodes.values()), "edges": edges, "truncated": truncated, "center": center}

    def _node_info(self, node_id: str, node_type: str) -> dict:
        if node_type == "entity":
            e = self.ws.framework.entity(node_id) or {}
            return {"label": e.get("name", node_id), "layer": "framework", "entity_kind": e.get("kind")}
        try:
            coords = self.ws.retrieval.coordinates(node_id)
        except BurrowlError:
            return {"label": node_id, "layer": LAYER_OF_KIND.get(kind_of(node_id) or "", "framework")}
        if node_type == "page":
            page = self.ws.framework.page(node_id) or {}
            coords.update(page_type=page.get("type"))
        return {"label": self.entry_label(node_id) or node_id, **coords}
