"""框架仓库：实体、别名、页面与版本、边、派生输入清单、待决策、agent 运行、巡检包。可修改，页面版本只增。

巡检发现不单独存放：每条就是一项待决策（设计稿 08 §9）。"""
import sqlite3

from ..core.clock import now
from ..core.ids import new_id
from .db import dumps, row, rows, transaction


class Framework:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---------- 实体与别名 ----------
    def entity(self, entity_id: str) -> dict | None:
        out = row(self.conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone())
        if out:
            out["aliases"] = [r[0] for r in self.conn.execute("SELECT alias FROM aliases WHERE entity_id = ?",
                                                              (entity_id,))]
        return out

    def entity_by_name(self, kind: str, name: str) -> dict | None:
        r = self.conn.execute("SELECT id FROM entities WHERE kind = ? AND name = ?", (kind, name)).fetchone()
        return self.entity(r[0]) if r else None

    def add_entity(self, kind: str, name: str, data: dict | None = None, user_marked: bool = False) -> dict:
        entity_id = new_id("ent")
        with transaction(self.conn):
            self.conn.execute("INSERT INTO entities VALUES (?,?,?,?,?,?)",
                              (entity_id, now(), kind, name, int(user_marked), dumps(data or {})))
        return self.entity(entity_id)

    def mark_entity(self, entity_id: str) -> None:
        with transaction(self.conn):
            self.conn.execute("UPDATE entities SET user_marked = 1 WHERE id = ?", (entity_id,))

    def entities(self, kind: str | None = None) -> list[dict]:
        if kind:
            return rows(self.conn.execute("SELECT * FROM entities WHERE kind = ? ORDER BY name", (kind,)))
        return rows(self.conn.execute("SELECT * FROM entities ORDER BY kind, name"))

    def add_alias(self, alias: str, entity_id: str, decided_by: str) -> None:
        with transaction(self.conn):
            self.conn.execute("INSERT OR IGNORE INTO aliases VALUES (?,?,?,?)", (alias, entity_id, decided_by, now()))

    def alias_targets(self, alias: str) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT entity_id FROM aliases WHERE alias = ?", (alias,))]

    # ---------- 页面 ----------
    def page(self, page_id: str) -> dict | None:
        return row(self.conn.execute("SELECT * FROM pages WHERE id = ?", (page_id,)).fetchone())

    def page_by_slug(self, slug: str) -> dict | None:
        return row(self.conn.execute("SELECT * FROM pages WHERE slug = ?", (slug,)).fetchone())

    def page_version(self, page_id: str, version: int) -> dict | None:
        return row(self.conn.execute("SELECT * FROM page_versions WHERE page_id = ? AND version = ?",
                                     (page_id, version)).fetchone())

    def page_versions(self, page_id: str) -> list[dict]:
        return rows(self.conn.execute(
            "SELECT page_id, version, created_at, author_id FROM page_versions WHERE page_id = ? ORDER BY version",
            (page_id,)))

    def pages(self, *, type_: str | None = None, freshness: str | None = None) -> list[dict]:
        q, p = "SELECT * FROM pages WHERE 1=1", []
        if type_:
            q, p = q + " AND type = ?", [*p, type_]
        if freshness:
            q, p = q + " AND freshness = ?", [*p, freshness]
        return rows(self.conn.execute(q + " ORDER BY updated_at DESC", p))

    def write_page(self, *, page_id: str | None, type_: str, slug: str, title: str, subject_id: str | None,
                   author_id: str, review: str, version_data: dict, inputs: list[str], page_data: dict) -> dict:
        """新增一个页面版本并记下输入清单；页面头指向新版本，时效回到 valid。"""
        ts = now()
        with transaction(self.conn):
            if page_id is None:
                page_id, version = new_id("pg"), 1
                self.conn.execute("INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                  (page_id, ts, ts, type_, slug, title, subject_id, 1, "valid", review,
                                   dumps(page_data)))
            else:
                version = self.page(page_id)["head_version"] + 1
                self.conn.execute("UPDATE pages SET updated_at=?, title=?, head_version=?, freshness='valid', "
                                  "review=?, data=? WHERE id=?", (ts, title, version, review, dumps(page_data),
                                                                  page_id))
            self.conn.execute("INSERT INTO page_versions VALUES (?,?,?,?,?)",
                              (page_id, version, ts, author_id, dumps(version_data)))
            self.add_inputs("page", page_id, version, inputs)
        return self.page(page_id)

    # ---------- 边 ----------
    def edge(self, edge_id: str) -> dict | None:
        return row(self.conn.execute("SELECT * FROM edges WHERE id = ?", (edge_id,)).fetchone())

    def add_edge(self, *, rel: str, src_id: str, dst_id: str, origin: str, review: str, data: dict | None = None,
                 inputs: list[str] | None = None) -> dict:
        """同一 (rel, src, dst, origin) 只保留一条；重复添加返回已有的边。"""
        existing = self.conn.execute("SELECT id FROM edges WHERE rel=? AND src_id=? AND dst_id=? AND origin=?",
                                     (rel, src_id, dst_id, origin)).fetchone()
        if existing:
            return self.edge(existing[0])
        edge_id, ts = new_id("edg"), now()
        with transaction(self.conn):
            self.conn.execute("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?,?)",
                              (edge_id, ts, ts, rel, src_id, dst_id, origin, review, "valid", dumps(data or {})))
            self.add_inputs("edge", edge_id, 1, inputs or [])
        return self.edge(edge_id)

    def edges_of(self, node_id: str) -> list[dict]:
        return rows(self.conn.execute("SELECT * FROM edges WHERE src_id = ? OR dst_id = ? ORDER BY created_at",
                                      (node_id, node_id)))

    def edges(self, *, rel: str | None = None, origin: str | None = None, review: str | None = None) -> list[dict]:
        q, p = "SELECT * FROM edges WHERE 1=1", []
        for col, val in (("rel", rel), ("origin", origin), ("review", review)):
            if val:
                q, p = q + f" AND {col} = ?", [*p, val]
        return rows(self.conn.execute(q + " ORDER BY created_at", p))

    def set_state(self, kind: str, item_id: str, **fields) -> None:
        table = {"page": "pages", "edge": "edges"}[kind]
        assign = ", ".join(f"{k} = ?" for k in fields)
        with transaction(self.conn):
            self.conn.execute(f"UPDATE {table} SET {assign}, updated_at = ? WHERE id = ?",
                              [*fields.values(), now(), item_id])

    # ---------- 派生输入清单 ----------
    def add_inputs(self, derived_kind: str, derived_id: str, version: int, inputs: list[str]) -> None:
        self.conn.executemany("INSERT OR IGNORE INTO derivation_inputs VALUES (?,?,?,?)",
                              [(derived_kind, derived_id, version, i) for i in dict.fromkeys(inputs)])

    def inputs_of(self, derived_kind: str, derived_id: str, version: int) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT input_id FROM derivation_inputs WHERE derived_kind=? AND derived_id=? AND derived_version=?",
            (derived_kind, derived_id, version))]

    def dependents(self, input_ids: list[str]) -> list[tuple[str, str]]:
        """返回以这些条目为输入、且用的是当前版本的框架条目 (kind, id)。旧版本的输入清单不再参与传播。"""
        if not input_ids:
            return []
        marks = ",".join("?" * len(input_ids))
        q = (f"SELECT DISTINCT di.derived_kind, di.derived_id FROM derivation_inputs di "
             f"LEFT JOIN pages p ON di.derived_kind = 'page' AND p.id = di.derived_id "
             f"WHERE di.input_id IN ({marks}) AND (di.derived_kind != 'page' OR di.derived_version = p.head_version)")
        return [(r[0], r[1]) for r in self.conn.execute(q, input_ids)]

    # ---------- 待决策 ----------
    def add_decision(self, kind: str, subject_id: str | None, impact: int, data: dict) -> dict:
        decision_id, ts = new_id("dec"), now()
        with transaction(self.conn):
            self.conn.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?)",
                              (decision_id, ts, ts, kind, "open", subject_id, impact, dumps(data)))
        return self.decision(decision_id)

    def decision(self, decision_id: str) -> dict | None:
        return row(self.conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone())

    def decisions(self, status: str | None = "open", kind: str | None = None) -> list[dict]:
        q, p = "SELECT * FROM decisions WHERE 1=1", []
        if status:
            q, p = q + " AND status = ?", [*p, status]
        if kind:
            q, p = q + " AND kind = ?", [*p, kind]
        return rows(self.conn.execute(q + " ORDER BY impact DESC, created_at", p))

    def close_decision(self, decision_id: str, status: str, resolution: dict) -> dict:
        current = self.decision(decision_id)
        data = {**current["data"], "resolution": resolution}
        with transaction(self.conn):
            self.conn.execute("UPDATE decisions SET status=?, updated_at=?, data=? WHERE id=?",
                              (status, now(), dumps(data), decision_id))
        return self.decision(decision_id)

    def update_decision(self, decision_id: str, *, data: dict | None = None, impact: int | None = None) -> None:
        """改一条仍打开的待决策项的附注或影响范围（AI 复核附上结论，设计稿 04 D-14）。"""
        current = self.decision(decision_id)
        with transaction(self.conn):
            self.conn.execute("UPDATE decisions SET updated_at=?, data=?, impact=? WHERE id=?",
                              (now(), dumps(data if data is not None else current["data"]),
                               impact if impact is not None else current["impact"], decision_id))

    def open_decision_for(self, kind: str, subject_id: str) -> dict | None:
        r = self.conn.execute("SELECT id FROM decisions WHERE kind=? AND subject_id=? AND status='open'",
                              (kind, subject_id)).fetchone()
        return self.decision(r[0]) if r else None

    # ---------- agent 运行 ----------
    def add_run(self, run_id: str, agent: str, session_id: str, data: dict) -> dict:
        ts = now()
        with transaction(self.conn):
            self.conn.execute("INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?)",
                              (run_id, ts, ts, agent, "running", session_id, dumps(data)))
        return self.run(run_id)

    def run(self, run_id: str) -> dict | None:
        return row(self.conn.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone())

    def runs(self, limit: int = 50) -> list[dict]:
        return rows(self.conn.execute("SELECT * FROM agent_runs ORDER BY created_at DESC LIMIT ?", (limit,)))

    def finish_run(self, run_id: str, status: str, data: dict) -> None:
        current = self.run(run_id)
        with transaction(self.conn):
            self.conn.execute("UPDATE agent_runs SET status=?, updated_at=?, data=? WHERE id=?",
                              (status, now(), dumps({**current["data"], **data}), run_id))

    # ---------- 巡检包（设计稿 08 D-14） ----------
    def add_inspection(self, period: int, data: dict) -> dict:
        inspection_id, ts = new_id("insp"), now()
        with transaction(self.conn):
            self.conn.execute("INSERT INTO inspections VALUES (?,?,?,?,?,?)",
                              (inspection_id, ts, ts, period, "ready", dumps(data)))
        return self.inspection(inspection_id)

    def inspection(self, inspection_id: str) -> dict | None:
        return row(self.conn.execute("SELECT * FROM inspections WHERE id = ?", (inspection_id,)).fetchone())

    def inspections(self, limit: int = 20) -> list[dict]:
        return rows(self.conn.execute("SELECT * FROM inspections ORDER BY created_at DESC, rowid DESC LIMIT ?",
                                      (limit,)))

    def update_inspection(self, inspection_id: str, *, status: str | None = None, data: dict | None = None) -> dict:
        current = self.inspection(inspection_id)
        with transaction(self.conn):
            self.conn.execute("UPDATE inspections SET status=?, updated_at=?, data=? WHERE id=?",
                              (status or current["status"], now(),
                               dumps(data if data is not None else current["data"]), inspection_id))
        return self.inspection(inspection_id)
