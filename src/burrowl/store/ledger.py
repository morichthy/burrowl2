"""账本仓库：原件一列与判断一列的读写。只提供插入与查询，没有修改和删除（数据库触发器同样拒绝）。"""
import sqlite3

from ..core.clock import now
from ..core.ids import PREFIXES, new_id
from .db import dumps, row, rows, transaction

TABLE_OF_PREFIX = {"art": "artifacts", "evt": "events", "rec": "records", "rd": "reads", "jdg": "judgments",
                   "lnk": "links",
                   "ex": "extractions", "rev": "reviews", "ret": "retirements"}


class Ledger:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---------- 写入 ----------
    def insert(self, table: str, prefix: str, fields: dict, *, objects: list[str] | None = None) -> dict:
        """插入一行并返回它。fields 中的 data/objects 自动序列化；objects 同时写入 entry_objects。"""
        entry_id = fields.pop("id", None) or new_id(prefix)
        values = {"id": entry_id, "created_at": now(), **fields}
        if objects is not None and table in ("events", "records"):
            values["objects"] = objects
        for key in ("data", "objects"):
            if key in values and not isinstance(values[key], str):
                values[key] = dumps(values[key])
        cols = ",".join(values)
        with transaction(self.conn):
            self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({','.join('?' * len(values))})",
                              list(values.values()))
            for obj in dict.fromkeys(objects or []):
                self.conn.execute("INSERT OR IGNORE INTO entry_objects VALUES (?, ?)", (entry_id, obj))
        return self.get(entry_id)

    def link(self, rel: str, src_id: str, dst_id: str, author_id: str, data: dict | None = None) -> dict:
        return self.insert("links", "lnk", {"rel": rel, "src_id": src_id, "dst_id": dst_id, "author_id": author_id,
                                            "data": data or {}})

    def next_seq(self, session_id: str) -> int:
        r = self.conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE session_id = ?",
                              (session_id,)).fetchone()
        return r[0]

    # ---------- 读取 ----------
    def get(self, entry_id: str) -> dict | None:
        prefix = entry_id.split("_", 1)[0]
        table = TABLE_OF_PREFIX.get(prefix)
        if table is None:
            return None
        out = row(self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (entry_id,)).fetchone())
        if out is not None:
            out["entry_kind"] = PREFIXES[prefix]
            out["objects"] = self.objects_of(entry_id) if table not in ("events", "records") else out["objects"]
        return out

    def objects_of(self, entry_id: str) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT object FROM entry_objects WHERE entry_id = ? ORDER BY object",
                                                (entry_id,))]

    def entries_with_objects(self, objects: list[str]) -> list[str]:
        if not objects:
            return []
        q = f"SELECT DISTINCT entry_id FROM entry_objects WHERE object IN ({','.join('?' * len(objects))})"
        return [r[0] for r in self.conn.execute(q, objects)]

    def links_from(self, src_id: str, rel: str | None = None) -> list[dict]:
        q, p = "SELECT * FROM links WHERE src_id = ?", [src_id]
        if rel:
            q, p = q + " AND rel = ?", [*p, rel]
        return rows(self.conn.execute(q + " ORDER BY created_at", p))

    def links_to(self, dst_id: str, rels: tuple[str, ...] | None = None) -> list[dict]:
        q, p = "SELECT * FROM links WHERE dst_id = ?", [dst_id]
        if rels:
            q += f" AND rel IN ({','.join('?' * len(rels))})"
            p += list(rels)
        return rows(self.conn.execute(q + " ORDER BY created_at", p))

    def query(self, sql: str, params: list | tuple = ()) -> list[dict]:
        return rows(self.conn.execute(sql, params))
