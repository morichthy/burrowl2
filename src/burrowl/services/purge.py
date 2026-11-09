"""依赖失效与原件删除（设计稿 07）。

- 依据失效（D-01）：依据最终落在"已退役且没有替代"或"已删除且没有替代"的原件上。只算依据（used）与依赖
  （depends_on）；支持、反对等关系不算。过程日志永远不失效。
- 全部依据都失效的判断与事实记录隐藏，部分失效的标注 lapsed_basis（D-02）。都是算出来的，不写账本。
- 删除（D-04、D-05）：只有已退役的原件可以删除；人看过预览、带着预览给出的 confirm 执行。被删的行先写进
  purge_gate（触发器只放行出现在这里的行），删完在同一事务里清空，所以删除之后不留任何记录。
"""
import json
import re
import shutil
from collections.abc import Iterable

from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.hashing import sha256_text
from ..core.model import HISTORY_KINDS

DEP_RELS = ("used", "depends_on")
# 提到被删条目时一并删除的系统流水（自动日志）：登记、读取、写判断、退役、替换、抽取、复核……（D-04）
# 自动记下的系统流水；search（检索命中记录）、inspection.（巡检）见设计稿 08 D-12
SYSTEM_OPS = ("artifact.", "judgment.", "framework.", "linking.", "record.", "extraction.", "review.",
              "search", "inspection.")
_SHA = re.compile(r"\b[0-9a-f]{64}\b")


def _base(ref: str) -> str:
    return ref.split("@", 1)[0].split("#", 1)[0]


class PurgeService:
    def __init__(self, ws):
        self.ws = ws
        self._cache: tuple | None = None

    # ---------- 依赖失效（D-01、D-02） ----------
    def lapse(self) -> dict:
        """{"hidden": {条目: [失效的依据…]}, "partial": {条目: [{ref, reason}…]}}。按账本行数缓存。"""
        key = self._generation()
        if self._cache and self._cache[0] == key:
            return self._cache[1]
        out = self._compute()
        self._cache = (key, out)
        return out

    def hidden_ids(self) -> set[str]:
        return set(self.lapse()["hidden"])

    def excluded_ids(self) -> set[str]:
        """默认不出现在列表、检索、关系图、统计里的条目：已退役的原件与被隐藏的条目。"""
        return self.ws.judgments.retired_ids() | self.hidden_ids() | self.ws.versions.hidden_ids()

    def coordinates(self, entry_id: str) -> dict:
        """坐标里的 hidden（全部依据失效）与 lapsed_basis（部分依据失效）。"""
        lp = self.lapse()
        if entry_id in lp["hidden"]:
            return {"hidden": lp["hidden"][entry_id], "complete": False}
        if entry_id in lp["partial"]:
            return {"lapsed_basis": lp["partial"][entry_id], "complete": False}
        return {}

    def _generation(self) -> tuple:
        db = self.ws.ledger_db
        return tuple(db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                     for t in ("artifacts", "judgments", "records", "events", "reads", "links",
                               "retirements", "replacements"))

    def _compute(self, *, extra_dead: Iterable[str] = (), dropped_targets: Iterable[str] = (),
                 alive: Iterable[str] = ()) -> dict:
        """删除预览用的假设：extra_dead 这些原件已删除；dropped_targets 以它们为替代原件的替换记录已不在；
        alive 这些原件既没退役也没删除。"""
        led = self.ws.ledger
        retired = self.ws.judgments.retired_ids() - set(alive)
        extra_dead, dropped_targets = set(extra_dead), set(dropped_targets)
        links: dict[str, list[str]] = {}
        for r in led.query(f"SELECT src_id, dst_id FROM links WHERE rel IN ({','.join('?' * len(DEP_RELS))})",
                           DEP_RELS):
            links.setdefault(r["src_id"], []).append(r["dst_id"])
        for r in led.query("SELECT id, COALESCE(artifact_id,event_id) AS source FROM records"):
            links.setdefault(r["id"], []).append(r["source"])
        if not retired and not extra_dead and not self._dangling(links, set(alive)):
            return {"hidden": {}, "partial": {}}
        exists: dict[str, bool] = {}

        def present(entry_id: str) -> bool:
            if entry_id in extra_dead:
                return False
            if entry_id not in exists:
                exists[entry_id] = led.get(entry_id) is not None
            return exists[entry_id]

        def replaced(artifact_id: str) -> bool:
            info = self.ws.judgments.replacement_info(artifact_id)
            return bool(info and info["new_id"] not in dropped_targets and info["new_id"] not in extra_dead
                        and present(info["new_id"]))

        memo: dict[str, list[dict] | None] = {}  # 条目 → 全部依据失效时的失效清单；None 表示没有被隐藏

        def reason_of(ref: str, stack: frozenset) -> str | None:
            base = _base(ref)
            prefix = base.split("_", 1)[0]
            if prefix == "art":
                if not present(base):
                    return None if replaced(base) else "deleted"
                return "retired" if base in retired and not replaced(base) else None
            if not present(base):
                return "deleted"
            if prefix == "rd":
                return reason_of(led.get(base)["artifact_id"], stack)
            if prefix in ("rec", "jdg"):
                return "hidden" if hidden(base, stack) is not None else None
            return None  # 过程日志永远不失效

        def deps(entry_id: str) -> list[str]:
            if entry_id.startswith("rec_"):
                rec = led.get(entry_id)
                source = (rec.get("artifact_id") or rec.get("event_id")) if rec else None
                return [source] if source else []
            return links.get(entry_id, [])

        def hidden(entry_id: str, stack: frozenset = frozenset()) -> list[dict] | None:
            if entry_id in memo:
                return memo[entry_id]
            if entry_id in stack:
                return None  # 依赖成环：不当作失效
            refs = deps(entry_id)
            lapsed = [{"ref": r, "reason": reason} for r in refs
                      if (reason := reason_of(r, stack | {entry_id}))]
            memo[entry_id] = lapsed if refs and len(lapsed) == len(refs) else None
            partial_of[entry_id] = lapsed if lapsed and memo[entry_id] is None else []
            return memo[entry_id]

        partial_of: dict[str, list[dict]] = {}
        history = {r["id"] for r in led.query(
            f"SELECT id FROM judgments WHERE kind IN ({','.join('?' * len(HISTORY_KINDS))})", HISTORY_KINDS)}
        candidates = [r["id"] for r in led.query("SELECT id FROM records")]
        candidates += [j for j in links if j.startswith("jdg_") and j not in history]
        for entry_id in candidates:
            hidden(entry_id)
        return {"hidden": {k: v for k, v in memo.items() if v is not None},
                "partial": {k: v for k, v in partial_of.items() if v}}

    def _dangling(self, links: dict[str, list[str]], alive: set[str]) -> bool:
        """有没有依据指向已经不存在的条目（删除之后）。"""
        targets = {_base(d) for ds in links.values() for d in ds} - alive
        return any(self.ws.ledger.get(t) is None for t in targets)

    # ---------- 删除（D-04、D-05） ----------
    def preview(self, artifact_id: str) -> dict:
        """删除一份已退役原件会删掉什么、保留哪些并标为"已删除"。confirm 用于执行时核对预览没有过期。
        每一项都带标题或摘要，工作台不用再逐个打开条目才知道影响了什么。"""
        plan = self._plan(artifact_id)
        led, fw = self.ws.ledger, self.ws.framework
        gone = set(plan["entries"])

        def brief(entry_id: str) -> dict:
            e = led.get(entry_id) or {}
            return {"id": entry_id, "entry_kind": e.get("entry_kind"), "kind": e.get("kind"),
                    "author_id": e.get("author_id") or e.get("promoted_by"),
                    "author_kind": e.get("author_kind"), "preview": self.ws.retrieval.preview(entry_id)}

        def label(node_id: str) -> str:
            base = _base(node_id)
            if base.startswith("ent_"):
                return (fw.entity(base) or {}).get("name") or base
            if base.startswith("pg_"):
                return (fw.page(base) or {}).get("title") or base
            return self.ws.retrieval.preview(base) or base

        art = led.get(artifact_id)
        edges = []
        for edge_id in plan["edges"]:
            e = fw.edge(edge_id)
            if e:
                edges.append({"id": edge_id, "rel": e["rel"], "src_id": e["src_id"], "dst_id": e["dst_id"],
                              "src": label(e["src_id"]), "dst": label(e["dst_id"]), "origin": e.get("origin")})
        pages = []
        for page_id in plan["pages"]:
            pg = fw.page(page_id) or {}
            hit = [r[0] for r in self.ws.framework_db.execute(
                f"SELECT DISTINCT input_id FROM derivation_inputs WHERE derived_kind = 'page' AND derived_id = ? "
                f"AND input_id IN ({','.join('?' * len(gone))})", [page_id, *gone])]
            total = self.ws.framework_db.execute(
                "SELECT COUNT(DISTINCT input_id) FROM derivation_inputs WHERE derived_kind = 'page' "
                "AND derived_id = ? AND derived_version = ?", (page_id, pg.get("head_version"))).fetchone()[0]
            pages.append({"id": page_id, "title": pg.get("title"), "type": pg.get("type"), "inputs_hit": hit,
                          "inputs_total": total})
        # 保留下来、但有关系指向被删条目的条目：依据部分失效的（keep），以及出处、支持、反对等其他关系
        refs: dict[str, set[str]] = {}
        marks = ",".join("?" * len(gone))
        for r in led.query(f"SELECT src_id, dst_id, rel FROM links WHERE dst_id IN ({marks}) "
                           f"OR substr(dst_id, 1, instr(dst_id || '#', '#') - 1) IN ({marks})", [*gone, *gone]):
            if r["src_id"] not in gone:
                refs.setdefault(r["src_id"], set()).add(r["rel"])
        for j in plan["keep"]:
            refs.setdefault(j, set()).add("used")
        kept = [{**brief(i), "rels": sorted(rels), "lapsed": i in plan["keep"]} for i, rels in sorted(refs.items())]
        events: dict[str, int] = {}
        for evt in plan["rows"].get("events", []):
            op = (led.get(evt) or {}).get("op") or "?"
            events[op] = events.get(op, 0) + 1
        # 内容文件的去向：受管文件没有别的原件在用时删除；还被用着的保留；外部引用的原件不动磁盘上的文件
        if art["entry_kind"] != "artifact":
            file = None
        elif art.get("storage") != "managed":
            file = "external"
        else:
            file = "deleted" if art["sha256"] in plan["blobs"] else "shared"
        return {"artifact": {"id": artifact_id, "title": art["data"].get("title"), "uri": art.get("uri"),
                             "file": file},
                "delete": {"judgments": [brief(j) for j in plan["judgments"]],
                           "records": [brief(r) for r in plan["records"]],
                           "counts": {t: len(plan["rows"].get(t, [])) for t in plan["rows"]},
                           "events_by_op": events,
                           "blobs": len(plan["blobs"]), "edges": edges},
                "keep_with_gap": kept,
                "pages": pages,
                "confirm": plan["confirm"],
                "note": "删除后不留任何记录，不能撤销；数据目录以外的备份与导出不受影响"}

    def delete(self, actor: Actor, artifact_id: str, *, confirm: str) -> dict:
        actor.require_human("删除原件")
        plan = self._plan(artifact_id)
        if confirm != plan["confirm"]:
            raise BurrowlError("CONFLICT", "影响范围与预览时不同，请重新预览后再确认", {"artifact_id": artifact_id})
        marked = self.ws.propagation.propagate([artifact_id, *plan["judgments"], *plan["records"]],
                                               reason="依据的原件已删除")
        db = self.ws.ledger_db
        gate = sorted({i for ids in plan["rows"].values() for i in ids})
        db.execute("PRAGMA foreign_keys=OFF")  # 保留的条目可以悬空引用被删的条目（D-04），外键在删除时放开
        db.execute("PRAGMA secure_delete=ON")
        try:
            db.execute("BEGIN IMMEDIATE")
            try:
                if self._plan(artifact_id)["confirm"] != confirm:
                    raise BurrowlError("CONFLICT", "销毁范围已变化，请重新预览")
                self.ws.versions.preserve_family_before_destroy(artifact_id)
                db.executemany("INSERT INTO purge_gate VALUES (?)", [(i,) for i in gate])
                for table in ("links", "reviews", "replacements", "retirements", "artifact_policies", "records",
                              "reads", "extractions", "events", "judgments", "artifacts"):
                    ids = plan["rows"].get(table, [])
                    for chunk in _chunks(ids):
                        db.execute(f"DELETE FROM {table} WHERE id IN ({','.join('?' * len(chunk))})", chunk)
                for chunk in _chunks(plan["entries"]):
                    db.execute(f"DELETE FROM entry_objects WHERE entry_id IN ({','.join('?' * len(chunk))})", chunk)
                db.execute("DELETE FROM purge_gate")
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        finally:
            db.execute("PRAGMA foreign_keys=ON")
        for entry_id in plan["entries"]:
            self.ws.index.remove(entry_id)
        fw = self.ws.framework_db
        fw.execute("PRAGMA secure_delete=ON")
        for edge_id in plan["edges"]:
            fw.execute("DELETE FROM edges WHERE id = ?", (edge_id,))
        for chunk in _chunks(plan["entries"]):
            fw.execute(f"DELETE FROM decisions WHERE subject_id IN ({','.join('?' * len(chunk))})", chunk)
        self._scrub_decisions(plan["entries"])
        self.ws.inspection.forget(plan["entries"])  # 巡检发现与巡检包里提到它们的部分（设计稿 08）
        for sha in plan["blobs"]:
            self.ws.blobs.path(sha).unlink(missing_ok=True)
        for sha in plan["cache_keys"]:
            shutil.rmtree(self.ws.root / "cache" / "pages" / sha, ignore_errors=True)
            for f in (self.ws.root / "cache" / "models").glob(f"*/{sha}.json"):
                f.unlink(missing_ok=True)
        for conn in (db, fw, self.ws.index.conn):
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self._cache = None
        return {"deleted": {t: len(v) for t, v in plan["rows"].items()}, "blobs": len(plan["blobs"]),
                "edges": len(plan["edges"]), "kept_with_gap": plan["keep"], "marked": marked}

    def _plan(self, artifact_id: str) -> dict:
        led = self.ws.ledger
        art = led.get(artifact_id)
        if art is None:
            raise BurrowlError("NOT_FOUND", "版本不存在", {"id": artifact_id})
        if art["entry_kind"] != "artifact":
            return self._version_plan(art)
        if not self.ws.judgments.retirement_of(artifact_id):
            raise BurrowlError("NOT_RETIRED", "只有已退役的原件可以删除：请先退役它", {"artifact_id": artifact_id})
        ids = lambda sql, p=(): [r["id"] for r in led.query(sql, p)]  # noqa: E731
        lapse = self._compute(extra_dead=[artifact_id], dropped_targets=[artifact_id])
        # 只删因为这次删除才隐藏的条目：假如这份原件仍在使用也会隐藏的（依赖别的退役原件），不归这次删除
        hidden = set(lapse["hidden"]) - set(self._compute(alive=[artifact_id])["hidden"])
        history = self.ws.versions.history(artifact_id)
        version_only = bool(led.links_from(artifact_id, "entry_version")
                            or (history and len(history["versions"]) > 1))
        judgments = sorted(j for j in hidden if j.startswith("jdg_") and not version_only)
        records = [] if version_only else sorted({*(r for r in hidden if r.startswith("rec_")),
                                                  *ids("SELECT id FROM records WHERE artifact_id = ?", (artifact_id,))})
        # 关于这份原件的旧版退役判断、原件缺陷，以及对它们的撤回
        about = ids("SELECT src_id AS id FROM links WHERE rel IN ('retires', 'defect_of') AND dst_id = ?",
                    (artifact_id,))
        about += ids(f"SELECT src_id AS id FROM links WHERE rel = 'retracts' "
                     f"AND dst_id IN ({','.join('?' * len(about))})",
                     about) if about else []
        judgments = sorted({*judgments, *about})
        reads = ids("SELECT id FROM reads WHERE artifact_id = ?", (artifact_id,))
        entries = [artifact_id, *reads, *records, *judgments]
        marks = ",".join("?" * len(entries))
        links = ids(f"SELECT id FROM links WHERE src_id IN ({marks})", entries)
        links += ids(f"SELECT id FROM links WHERE rel IN ('produced', 'consumed') AND dst_id IN ({marks})", entries)
        links += ids(f"SELECT id FROM links WHERE dst_id IN ({marks}) AND src_id IN ({marks})", [*entries, *entries])
        extractions = ids("SELECT id FROM extractions WHERE artifact_id = ?", (artifact_id,))
        events = []
        kept_records = {r["event_id"] for r in led.query("SELECT event_id FROM records WHERE event_id IS NOT NULL")}
        for e in led.query("SELECT id, op, data FROM events"):
            if e["id"] in kept_records or not e["op"].startswith(SYSTEM_OPS):
                continue
            text = json.dumps(e["data"], ensure_ascii=False)
            if any(x in text for x in entries):
                events.append(e["id"])
        rows = {"artifacts": [artifact_id], "reads": reads, "records": records, "judgments": judgments,
                "links": sorted(set(links)), "extractions": extractions, "events": events,
                "reviews": ids(f"SELECT id FROM reviews WHERE target_id IN ({marks})", entries),
                "retirements": ids("SELECT id FROM retirements WHERE artifact_id = ?", (artifact_id,)),
                "replacements": ids("SELECT id FROM replacements WHERE new_id = ?", (artifact_id,)),
                "artifact_policies": ids("SELECT id FROM artifact_policies WHERE artifact_id = ?", (artifact_id,))}
        # 别处不再用到的 blob：原件内容、抽取记录里的嵌入图片与快照、被删系统流水的长输出
        candidates = {art["sha256"]} if art["storage"] == "managed" else set()
        for r in led.query("SELECT data FROM extractions WHERE artifact_id = ?", (artifact_id,)):
            candidates |= set(_SHA.findall(json.dumps(r["data"])))
        cache_keys = {art["sha256"], *candidates}
        gone = {*rows["extractions"], *rows["events"]}
        blobs = sorted(sha for sha in candidates
                       if self.ws.blobs.has(sha) and not self._blob_used(sha, artifact_id, gone))
        edges = sorted({e["id"] for x in entries for e in self.ws.framework.edges_of(x)})
        gone_entries = set(entries)
        keep = sorted(j for j, gaps in {**lapse["partial"], **lapse["hidden"]}.items()
                      if j not in gone_entries and any(_base(g["ref"]) in gone_entries for g in gaps))
        pages = sorted({pid for kind, pid in self.ws.framework.dependents(entries) if kind == "page"})
        fingerprint = sha256_text(json.dumps({"rows": rows, "keep": keep}, sort_keys=True))
        return {"rows": {k: v for k, v in rows.items() if v}, "entries": entries, "judgments": judgments,
                "records": records, "keep": keep, "blobs": blobs, "cache_keys": sorted(cache_keys), "edges": edges,
                "pages": pages, "confirm": fingerprint[:16]}

    def _version_plan(self, entry: dict) -> dict:
        """单独销毁一个非文件版本。引用仍固定在该版，依赖项保留并显示缺口。"""
        entry_id = entry["id"]
        kind = entry["entry_kind"]
        tables = {"judgment": "judgments", "record": "records", "event": "events", "read": "reads"}
        if kind not in tables or not self.ws.versions.state(entry_id)["retired"]:
            raise BurrowlError("NOT_RETIRED", "只有已退役的版本可以销毁", {"id": entry_id})
        led = self.ws.ledger
        rows = {
            tables[kind]: [entry_id],
            "links": [r["id"] for r in led.query(
                "SELECT id FROM links WHERE src_id=? OR (dst_id=? AND rel IN ('produced','consumed'))",
                (entry_id, entry_id))],
            "reviews": [r["id"] for r in led.query("SELECT id FROM reviews WHERE target_id=?", (entry_id,))],
        }
        # 状态、修订和证据引用只保存 ID。下游正文和幸存版本不随该版删除。
        lapse = self._compute(extra_dead=[entry_id])
        keep = sorted(i for i, gaps in {**lapse["partial"], **lapse["hidden"]}.items()
                      if i != entry_id and any(_base(g["ref"]) == entry_id for g in gaps))
        sha = entry["data"].get("output_sha256") if kind == "event" else None
        blobs = [sha] if sha and not self._blob_used(sha, "", {entry_id}) else []
        edges = sorted(e["id"] for e in self.ws.framework.edges_of(entry_id))
        pages = sorted({pid for t, pid in self.ws.framework.dependents([entry_id]) if t == "page"})
        fingerprint = sha256_text(json.dumps({"rows": rows, "keep": keep, "edges": edges, "pages": pages},
                                            sort_keys=True))
        return {"rows": rows, "entries": [entry_id], "judgments": [], "records": [], "keep": keep,
                "blobs": blobs, "cache_keys": [], "edges": edges, "pages": pages, "confirm": fingerprint[:16]}

    def _scrub_decisions(self, entries: list[str]) -> None:
        """主体还在、但附注里写着被删条目 ID 的待决策（例如退役时给框架页记下的"需要重新综合"，理由里有原件 ID）：
        需要重新综合的改写理由，其余的删掉。巡检发现由 inspection.forget 处理（D-05：删除之后不留记录）。"""
        fw = self.ws.framework
        gone = set(entries)
        for d in fw.conn.execute("SELECT id, kind, data FROM decisions").fetchall():
            text = d[2] or ""
            if d[1] == "finding" or not any(e in text for e in gone):
                continue
            if d[1] == "rederive":
                data = json.loads(text)
                fw.update_decision(d[0], data={"title": data.get("title"), "reason": "所依据的原件已删除"})
            else:
                fw.conn.execute("DELETE FROM decisions WHERE id = ?", (d[0],))

    def _blob_used(self, sha: str, artifact_id: str, gone: set[str]) -> bool:
        led = self.ws.ledger
        if led.query("SELECT 1 FROM artifacts WHERE sha256 = ? AND id != ? LIMIT 1", (sha, artifact_id)):
            return True
        for table in ("extractions", "events"):
            for r in led.query(f"SELECT id FROM {table} WHERE data LIKE ?", (f"%{sha}%",)):
                if r["id"] not in gone:
                    return True
        return False


def _chunks(items: list[str], size: int = 500):
    for i in range(0, len(items), size):
        yield items[i:i + size]
