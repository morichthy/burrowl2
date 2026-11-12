"""账本仓库：条目、关系、处置的读写。只提供插入与查询，没有修改和删除（数据库触发器同样拒绝）。

设计稿 10：条目 ID 稳定、版本写 `@n`（D-01）；关系一条一行、两端固定到版本（D-07）；人的处置记在版本上（D-04）。
"""
import json
import sqlite3

from ..core.clock import now
from ..core.ids import PREFIXES, make_ref, new_id, parse_ref
from .db import dumps, row, rows, transaction

# 带版本的条目：前缀 → (视图, 基表)。视图只给最新版（当前版），写入走基表
VERSIONED = {"art": ("artifacts", "artifact_versions"), "evt": ("events", "event_versions"),
             "rec": ("records", "record_versions"), "rd": ("reads", "read_versions"),
             "jdg": ("judgments", "judgment_versions")}
BASE_OF_VIEW = {view: base for view, base in VERSIONED.values()}
TABLE_OF_PREFIX = {**{p: v[0] for p, v in VERSIONED.items()},
                   "rel": "relations", "vst": "version_states", "ex": "extractions", "rev": "reviews",
                   "rpl": "replacements", "pol": "artifact_policies"}
# objects 存在 entry_objects 表里的条目（事件与事实记录另有 objects 列）
_OBJECTS_IN_TABLE = ("events", "records")


class Ledger:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---------- 写入 ----------
    def insert(self, table: str, prefix: str, fields: dict, *, objects: list[str] | None = None) -> dict:
        """插入一行并返回它。带版本的条目写成第 1 版；fields 中的 data/objects/qualifiers/args 自动序列化。"""
        entry_id = fields.pop("id", None) or new_id(prefix)
        values = {"id": entry_id, "created_at": now(), **fields}
        base = BASE_OF_VIEW.get(table, table)
        if base != table:
            values.setdefault("version", 1)
        self._insert_row(base, values, objects)
        return self.get(make_ref(entry_id, values.get("version")) if base != table else entry_id)

    def new_version(self, entry_id: str, changes: dict, *, data: dict | None = None,
                    objects: list[str] | None = None, created_at: str | None = None) -> dict:
        """写一个新版本（D-02）：复制当前版，替换 changes 中的列与 data 中的键，对象默认沿用上一版。"""
        prefix = entry_id.split("_", 1)[0]
        view, base = VERSIONED[prefix]
        with transaction(self.conn):
            head = self.get(entry_id)
            if head is None:
                raise KeyError(entry_id)
            values = {k: v for k, v in head.items() if k not in ("entry_kind", "ref", "head_version", "objects")}
            values.update(changes)
            values["version"] = head["version"] + 1
            values["created_at"] = created_at or now()
            values["data"] = {**head["data"], **(data or {})}
            if view in _OBJECTS_IN_TABLE:
                values["objects"] = objects if objects is not None else head["objects"]
            self._insert_row(base, values, objects if objects is not None else head["objects"])
        return self.get(make_ref(entry_id, values["version"]))

    def _insert_row(self, table: str, values: dict, objects: list[str] | None) -> None:
        values = dict(values)
        if objects is not None and table in ("event_versions", "record_versions"):
            values["objects"] = objects
        for key in ("data", "objects", "qualifiers", "args"):
            if key in values and not isinstance(values[key], str):
                values[key] = dumps(values[key])
        cols = ",".join(values)
        with transaction(self.conn):
            self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({','.join('?' * len(values))})",
                              list(values.values()))
            if table in ("artifact_versions", "read_versions", "judgment_versions", "event_versions",
                         "record_versions"):
                for obj in dict.fromkeys(objects or []):
                    self.conn.execute("INSERT OR IGNORE INTO entry_objects VALUES (?, ?, ?)",
                                      (values["id"], values["version"], obj))

    def relate(self, predicate: str, subject: str, obj: str, asserted_by: str, *, session_id: str | None = None,
               label: str | None = None, qualifiers: dict | None = None, args: dict | None = None) -> dict:
        """写一条关系（D-07）。两端不带 `@n` 时补成写入时的当前版；不检查谓词规则（由 services/relations.py 做）。"""
        s_id, s_ver, _ = parse_ref(subject)
        o_id, o_ver, anchor = parse_ref(obj)
        return self.insert("relations", "rel", {
            "predicate": predicate, "label": label, "subject_id": s_id,
            "subject_version": s_ver or self.head_version(s_id), "object_id": o_id,
            "object_version": o_ver or self.head_version(o_id), "object_anchor": anchor,
            "asserted_by": asserted_by, "session_id": session_id, "qualifiers": qualifiers or {}, "args": args or {}})

    def next_seq(self, session_id: str) -> int:
        r = self.conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM event_versions WHERE session_id = ?",
                              (session_id,)).fetchone()
        return r[0]

    # ---------- 读取 ----------
    def head_version(self, entry_id: str) -> int | None:
        """条目的最新版本号；不带版本的条目（关系、框架）返回 None。"""
        prefix = entry_id.split("_", 1)[0]
        if prefix not in VERSIONED:
            return None
        r = self.conn.execute(f"SELECT MAX(version) FROM {VERSIONED[prefix][1]} WHERE id = ?", (entry_id,)).fetchone()
        return r[0] if r else None

    def get(self, ref: str) -> dict | None:
        """按引用取一行：`jdg_X` 取当前版，`jdg_X@2` 取第 2 版（段落锚点忽略）。

        带版本的条目附上 entry_kind、ref（`id@版本`）、head_version、objects；关系附上 subject、object 两端引用。"""
        entry_id, version, _ = parse_ref(ref)
        prefix = entry_id.split("_", 1)[0]
        table = TABLE_OF_PREFIX.get(prefix)
        if table is None:
            return None
        if prefix in VERSIONED:
            base = VERSIONED[prefix][1]
            if version:
                r = self.conn.execute(f"SELECT * FROM {base} WHERE id = ? AND version = ?", (entry_id, version))
            else:
                r = self.conn.execute(f"SELECT * FROM {base} WHERE id = ? ORDER BY version DESC LIMIT 1", (entry_id,))
            out = row(r.fetchone())
            if out is None:
                return None
            out["entry_kind"] = PREFIXES[prefix]
            out["ref"] = make_ref(entry_id, out["version"])
            out["head_version"] = out["version"] if not version else self.head_version(entry_id)
            if table not in _OBJECTS_IN_TABLE:
                out["objects"] = self.objects_of(entry_id, out["version"])
            return out
        out = row(self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (entry_id,)).fetchone())
        if out is not None:
            out["entry_kind"] = PREFIXES[prefix]
            if table == "relations":
                out = relation_row(out)
        return out

    def versions(self, entry_id: str) -> list[dict]:
        """条目的全部版本（从第 1 版起）。"""
        prefix = entry_id.split("_", 1)[0]
        if prefix not in VERSIONED:
            return []
        out = []
        for n in [r[0] for r in self.conn.execute(
                f"SELECT version FROM {VERSIONED[prefix][1]} WHERE id = ? ORDER BY version", (entry_id,))]:
            out.append(self.get(make_ref(entry_id, n)))
        return out

    def objects_of(self, entry_id: str, version: int | None = None) -> list[str]:
        version = version or self.head_version(entry_id)
        return [r[0] for r in self.conn.execute(
            "SELECT object FROM entry_objects WHERE entry_id = ? AND version = ? ORDER BY object",
            (entry_id, version))]

    def entries_with_objects(self, objects: list[str]) -> list[str]:
        if not objects:
            return []
        q = f"SELECT DISTINCT entry_id FROM entry_objects WHERE object IN ({','.join('?' * len(objects))})"
        ids = [r[0] for r in self.conn.execute(q, objects)]
        q = (f"SELECT DISTINCT id FROM events WHERE EXISTS (SELECT 1 FROM json_each(events.objects) "
             f"WHERE value IN ({','.join('?' * len(objects))})) UNION SELECT DISTINCT id FROM records "
             f"WHERE EXISTS (SELECT 1 FROM json_each(records.objects) WHERE value IN ({','.join('?' * len(objects))}))")
        return list(dict.fromkeys(ids + [r[0] for r in self.conn.execute(q, [*objects, *objects])]))

    def relations_from(self, subject_id: str, predicate: str | tuple[str, ...] | None = None, *,
                       version: int | None = None) -> list[dict]:
        """主语是这个条目的有效关系（出边）；给了 version 只取那一版的出边。"""
        q, p = "SELECT * FROM effective_relations WHERE subject_id = ?", [subject_id]
        if version is not None:
            q, p = q + " AND subject_version = ?", [*p, version]
        q, p = _predicate_filter(q, p, predicate)
        return [relation_row(r) for r in rows(self.conn.execute(q + " ORDER BY _row", p))]

    def relations_to(self, object_id: str, predicate: str | tuple[str, ...] | None = None, *,
                     version: int | None = None) -> list[dict]:
        """宾语是这个条目的有效关系（入边）；给了 version 只取指向那一版的。"""
        q, p = "SELECT * FROM effective_relations WHERE object_id = ?", [object_id]
        if version is not None:
            q, p = q + " AND object_version = ?", [*p, version]
        q, p = _predicate_filter(q, p, predicate)
        return [relation_row(r) for r in rows(self.conn.execute(q + " ORDER BY _row", p))]

    def version_states(self, entry_id: str, version: int | None = None) -> list[dict]:
        q, p = "SELECT * FROM version_states WHERE entry_id = ?", [entry_id]
        if version is not None:
            q, p = q + " AND version = ?", [*p, version]
        return rows(self.conn.execute(q + " ORDER BY rowid", p))

    def query(self, sql: str, params: list | tuple = ()) -> list[dict]:
        return rows(self.conn.execute(sql, params))


def _predicate_filter(q: str, p: list, predicate) -> tuple[str, list]:
    if predicate is None:
        return q, p
    names = (predicate,) if isinstance(predicate, str) else tuple(predicate)
    return q + f" AND predicate IN ({','.join('?' * len(names))})", [*p, *names]


def relation_row(r: dict) -> dict:
    """关系行补上两端引用 subject、object（`id@版本#段落`），并解析 qualifiers、args。"""
    out = dict(r)
    out.pop("_row", None)
    for key in ("qualifiers", "args"):
        if isinstance(out.get(key), str):
            out[key] = json.loads(out[key])
    out["subject"] = make_ref(out["subject_id"], out.get("subject_version"))
    out["object"] = make_ref(out["object_id"], out.get("object_version"), out.get("object_anchor") or "")
    return out
