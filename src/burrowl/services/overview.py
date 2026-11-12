"""只读汇总：工作台的首页、条目浏览与关系图用（DESIGN §9）。不写入任何数据，也不改变排序与地位规则。"""
import re
from collections import deque
from datetime import UTC, datetime, timedelta

from ..core.errors import BurrowlError
from ..core.ids import kind_of, parse_ref
from ..core.model import INTERNAL_OPS, LAYER_OF_KIND
from ..core.refs import REF_RE
from ..core.vocab import PREDICATES, VALIDITY, relation_phrase, status_note

ENTRY_TABLES = {"artifact": "artifacts", "event": "events", "record": "records", "read": "reads",
                "judgment": "judgments"}
# 条目列表按现状筛选（设计稿 10 D-12）：有效性的取值
ENTRY_STATUSES = tuple(VALIDITY)
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


def _multi(value: str | None) -> list[str]:
    """逗号分隔的多选值 → 列表（空值得到空列表）。"""
    return list(dict.fromkeys(v.strip() for v in (value or "").split(",") if v.strip()))


class OverviewService:
    def __init__(self, ws):
        self.ws = ws

    def entry_label(self, ref: str) -> str | None:
        """显示名随读取生成。用引用本身找内容，不沿着版本链改指向。"""
        versioned, _, anchor = ref.partition("#")
        kind = kind_of(versioned)
        if not kind:
            return None
        base, version, _ = parse_ref(versioned)
        entry = self.ws.get(base) if kind in ("page", "entity") or version is None else self.ws.get(versioned)
        if entry is None:
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
            name = (data.get("title") or _first_sentence(data.get("result") or "")
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
        if version is not None and kind not in ("page", "entity") and entry.get("head_version") \
                and version != entry["head_version"]:
            suffix = " · ".join(x for x in (suffix, f"第 {version} 版") if x)
        return " · ".join(part for part in (_short_name(name), suffix) if part)

    # ---------- 最近操作 ----------
    def activity(self, limit: int = 40) -> list[dict]:
        """最近的关键操作：登记原件、写判断（含更正撤回与复核）、事实记录、页面新版本、agent 运行。"""
        ledger, fw = self.ws.ledger, self.ws.framework
        items = []
        for a in ledger.query("SELECT * FROM artifacts ORDER BY created_at DESC LIMIT ?", (limit,)):
            items.append({"at": a["created_at"], "kind": "artifact", "actor": a["captured_by"], "id": a["id"],
                          "summary": f"登记原件：{a['data'].get('title') or a['kind']}"})
        for j in ledger.query("SELECT * FROM judgment_versions ORDER BY created_at DESC LIMIT ?", (limit,)):
            items.append({"at": j["created_at"], "kind": f"judgment.{j['kind']}", "actor": j["author_id"],
                          "id": f"{j['id']}@{j['version']}",
                          "summary": (f"第 {j['version']} 版：" if j["version"] > 1 else "") + j["data"]["text"][:120]})
        for r in ledger.query("SELECT * FROM reviews ORDER BY created_at DESC LIMIT ?", (limit,)):
            what = ("撤销" if r["data"].get("revokes") else
                    {"confirm": "确认", "reject": "驳回", "unsure": "拿不准", "request": "请人复核"}[r["verdict"]])
            who = "AI 复核" if r["method"] == "ai" and r["verdict"] != "request" else "复核"
            why = (r["data"].get("reason") or r["data"].get("note") or "")[:100]
            items.append({"at": r["created_at"], "kind": f"review.{r['verdict']}", "actor": r["actor_id"],
                          "id": r["target_id"], "summary": f"{who}{what}：{why}"})
        names = {"retire": "退役原件", "restore": "撤销退役", "withdraw": "撤回", "unwithdraw": "取消撤回",
                 "defect": "标缺陷", "undefect": "取消缺陷"}
        for r in ledger.query("SELECT * FROM version_states ORDER BY created_at DESC LIMIT ?", (limit,)):
            items.append({"at": r["created_at"], "kind": f"state.{r['action']}", "actor": r["actor_id"],
                          "id": f"{r['entry_id']}@{r['version']}",
                          "summary": f"{names[r['action']]}：{r['data'].get('reason', '')[:100]}"})
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
        expected |= {r[0] for r in self.ws.ledger_db.execute("SELECT id FROM judgments")}
        expected |= {r[0] for r in self.ws.framework_db.execute("SELECT id FROM pages")}
        indexed = {r[0] for r in self.ws.index_db.execute("SELECT DISTINCT entry_id FROM docs")}
        missing = sorted(expected - indexed)
        return {"expected": len(expected), "missing": len(missing), "missing_ids": missing[:20]}

    def _daily(self, days: int = 14) -> dict:
        """近 days 天每天新增的条目数（按本机时区分日；不含过程日志和读取记录，它们是流水账，会盖过其他条目）。"""
        today = datetime.now().astimezone().date()
        counts = {(today - timedelta(days=i)).isoformat(): 0 for i in range(days - 1, -1, -1)}
        since = (datetime.now(UTC) - timedelta(days=days + 1)).isoformat(timespec="seconds")
        # 读取记录是自动日志（D-03）；各版本都算新增
        sources = [(self.ws.ledger_db, t) for t in ("artifact_versions", "record_versions", "judgment_versions")]
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
        judgments = {"total": 0, "local_only": 0, "with_external": 0, "inferred_only": 0, "mixed": 0,
                     "normative": 0, "process": 0, "replaced": 0, "opposed": 0, "quoted": 0,
                     "by_author": {"human": 0, "ai": 0, "system": 0}}
        memo: dict = {}
        for r in ledger_db.execute("SELECT id FROM judgments ORDER BY created_at"):
            c = self.ws.coordinates.of(r["id"], memo=memo)
            if c is None or c["state"]["validity"] in ("withdrawn", "lapsed"):  # 已撤回、依据全部失效的不计入
                continue
            classes = {s.split(":", 1)[0] for s in c["sources"]}
            judgments["total"] += 1
            judgments["process"] += c["kind"] == "process"
            judgments["by_author"][c["notes"]["author"]] = judgments["by_author"].get(c["notes"]["author"], 0) + 1
            if c["kind"] == "normative" and not classes:
                judgments["normative"] += 1
            elif classes == {"local"}:
                judgments["local_only"] += 1
            elif classes == {"inferred"}:
                judgments["inferred_only"] += 1
            elif classes == {"external"}:
                judgments["with_external"] += 1
            if len(classes) > 1:
                judgments["mixed"] += 1
            judgments["replaced"] += c["state"]["validity"] == "replaced"
            judgments["opposed"] += any(m["mark"] == "opposed" for m in c["state"]["marks"])
            judgments["quoted"] += bool(c["notes"].get("quoted"))
        group = lambda conn, sql: {r[0]: r[1] for r in conn.execute(sql)}  # noqa: E731
        return {
            "ledger": {t: count(ledger_db, f"SELECT COUNT(*) FROM {t}") for t in ENTRY_TABLES.values()},
            "artifacts_by_source": group(ledger_db, "SELECT source_class, COUNT(*) FROM artifacts GROUP BY 1"),
            "judgments": judgments,
            "relations": group(ledger_db, "SELECT predicate, COUNT(*) FROM effective_relations GROUP BY 1"),
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
                include_outputs: bool = False, status: str | None = None, quoted: bool | None = None) -> dict:
        """条目列表。筛选与检索页、关系图同名同序（设计稿 10 D-24、D-26）：
        依据来源 source_class（local / external / inferred）→ 类型 judgment_kind（结论 / 过程 / 规定）→
        现状 status（VALIDITY：current / replaced / withdrawn / retired / lapsed）→ 说明（作者 author_kind、
        转述 quoted）。各项可传逗号分隔的多个值：同一项内是"或"，不同项之间是"且"。
        include_retired：是否包含当前版已撤回、已退役、依据全部失效的条目（默认不含；按 status 筛这几种时自动包含）。
        scope：过程日志列哪一类，operations 操作日志（默认）/ system 系统流水 / all（设计稿 07 D-10）。
        include_outputs：原件列表是否包含运行产物（被某条过程日志 produced 的原件，默认不含，D-09）。"""
        table = ENTRY_TABLES.get(kind)
        if table is None:
            raise BurrowlError("INVALID_ARGUMENT", f"kind 必须是 {', '.join(ENTRY_TABLES)} 之一", {"kind": kind})
        where, params = ["1=1"], []
        jkinds, authors, sources, statuses = (_multi(v) for v in (judgment_kind, author_kind, source_class, status))
        if bad := [v for v in statuses if v not in ENTRY_STATUSES]:
            raise BurrowlError("INVALID_ARGUMENT", f"status 必须是 {', '.join(ENTRY_STATUSES)} 之一",
                               {"status": bad[0]})
        if bad := [v for v in sources if v not in ("local", "external", "inferred")]:
            raise BurrowlError("INVALID_ARGUMENT", "source_class 必须是 local / external / inferred",
                               {"source_class": bad[0]})
        if kind == "judgment" and jkinds:
            where.append(f"t.kind IN ({','.join('?' * len(jkinds))})")
            params += jkinds
        if kind == "event" and scope != "all":
            if scope not in ("operations", "system"):
                raise BurrowlError("INVALID_ARGUMENT", "scope 必须是 operations / system / all", {"scope": scope})
            system = " OR ".join("t.op LIKE ?" for _ in INTERNAL_OPS)
            where.append(f"({system})" if scope == "system" else f"NOT ({system})")
            params += [f"{p}%" for p in INTERNAL_OPS]
        if kind == "artifact" and not include_outputs:
            where.append("t.id NOT IN (SELECT object_id FROM relations WHERE predicate = 'produced')")
        if authors:
            col = {"events": "t.actor_kind", "judgments": "t.author_kind"}.get(table)
            if col:
                where.append(f"{col} IN ({','.join('?' * len(authors))})")
                params += authors
        if object:
            normalized = self.ws.linking.normalize_objects([object])
            where.append(f"t.id IN (SELECT entry_id FROM entry_objects WHERE object IN "
                         f"({','.join('?' * len(normalized))}))")
            params += normalized
        if query:
            where.append("t.data LIKE ?")
            params.append(f"%{query}%")
        sql = f"FROM {table} t WHERE {' AND '.join(where)}"
        memo: dict = {}
        show_gone = include_retired or bool({"withdrawn", "retired", "lapsed"} & set(statuses))
        derived = bool(sources or statuses or quoted is not None or not show_gone)
        if derived:  # 坐标是逐条推出的：先取全部候选再筛、再分页
            matched = []
            for (entry_id,) in self.ws.ledger_db.execute(f"SELECT t.id {sql} ORDER BY t.created_at DESC", params):
                c = self.ws.coordinates.of(entry_id, memo=memo)
                if c is None:
                    continue
                validity = c["state"]["validity"]
                if statuses and validity not in statuses:
                    continue
                if not show_gone and validity in ("withdrawn", "retired", "lapsed"):
                    continue
                if sources and not {s.split(":", 1)[0] for s in c["sources"]} & set(sources):
                    continue
                if quoted is not None and bool(c["notes"].get("quoted")) != quoted:
                    continue
                matched.append(entry_id)
            total, ids = len(matched), matched[offset:offset + limit]
        else:
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
            c = self.ws.coordinates.of(entry_id, memo=memo)
            item = {"id": entry_id, "created_at": e["created_at"], "preview": self.ws.retrieval.preview(entry_id),
                    "entry_kind": e.get("kind") or e.get("op"), "objects": e.get("objects", []),
                    **self.ws.coordinates.compact(c), "status_note": status_note(c)}
            if kind == "event":  # 按会话归组用（D-10）：会话、顺序、操作者、已升级为哪些事实记录、输入与产出
                item.update(session_id=e["session_id"], seq=e["seq"], actor_id=e["actor_id"], op=e["op"],
                            system=e["op"].startswith(INTERNAL_OPS), promoted_to=promoted.get(entry_id, []),
                            **self.ws.capture.run_files(entry_id))
            items.append(item)
        return {"items": items, "total": total, "offset": offset}

    # ---------- 关系图（设计稿 10 D-22 至 D-24） ----------
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

    @staticmethod
    def _layer_of(node_id: str, node_type: str) -> str:
        if node_type in ("entity", "page"):
            return "framework"
        return LAYER_OF_KIND.get(kind_of(node_id) or "", "framework")

    def _node_passes(self, node_id: str, node_type: str, memo: dict, *, layers, source_classes, source_mode,
                     kinds, quoted) -> bool:
        """关系图的筛选（设计稿 10 D-24）：综合程度 → 依据来源 → 类型 → 说明。"""
        layer = self._layer_of(node_id, node_type)
        if layers and layer not in layers:
            return False
        if layer == "framework" or not (source_classes or kinds or quoted is not None):
            return True
        c = self._coords(node_id, memo) or {}
        if kinds and layer == "judgment" and c.get("kind") not in kinds:
            return False
        if quoted is not None and layer == "judgment" and bool((c.get("notes") or {}).get("quoted")) != quoted:
            return False
        sources = c.get("sources") or []
        if source_classes and sources:  # 没有依据来源的（规定）不受依据来源筛选影响
            classes = {s.split(":", 1)[0] for s in sources}
            wanted = set(source_classes)
            if source_mode == "only":
                if not classes <= wanted:
                    return False
            elif not classes & wanted:
                return False
        return True

    def _coords(self, node_id: str, memo: dict) -> dict | None:
        try:
            return self.ws.coordinates.of(node_id, memo=memo)
        except BurrowlError:
            return None

    def _node_info(self, node_id: str, node_type: str, memo: dict) -> dict:
        if node_type == "entity":
            e = self.ws.framework.entity(node_id) or {}
            return {"label": e.get("name", node_id), "layer": "framework", "kind": "entity",
                    "entity_kind": e.get("kind")}
        coords = self._coords(node_id, memo)
        if coords is None:
            return {"label": node_id, "layer": LAYER_OF_KIND.get(kind_of(node_id) or "", "framework")}
        return {"label": self.entry_label(node_id) or node_id, **self.ws.coordinates.compact(coords),
                "status_note": status_note(coords)}
