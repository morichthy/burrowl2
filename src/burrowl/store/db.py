"""SQLite 连接与迁移。每个库一个迁移目录，文件按编号顺序执行，执行过的记在 schema_migrations（DESIGN §3.4）。"""
import json
import sqlite3
from importlib.resources import files
from pathlib import Path
from typing import Any

from ..core.clock import now
from ..core.sql import transaction  # noqa: F401  对外沿用 store.db.transaction


def connect(path: Path | str) -> sqlite3.Connection:
    # isolation_level=None：由 transaction() 显式控制事务边界
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def migrate(conn: sqlite3.Connection, name: str) -> list[str]:
    """执行 migrations/<name>/ 下尚未执行的 SQL 文件，返回本次执行的文件名。重复调用幂等。"""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    folder = files("burrowl.store.migrations") / name
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if not entry.name.endswith(".sql") or entry.name in done:
            continue
        with transaction(conn):
            for statement in split_sql(entry.read_text(encoding="utf-8")):
                conn.execute(statement)
            conn.execute("INSERT INTO schema_migrations VALUES (?, ?)", (entry.name, now()))
        applied.append(entry.name)
    return applied


def split_sql(script: str) -> list[str]:
    """逐句切分 SQL：触发器体内也有分号，所以用 sqlite3.complete_statement 判断语句是否完整。"""
    statements, buffer = [], ""
    for line in script.splitlines():
        if not buffer and (not line.strip() or line.strip().startswith("--")):
            continue
        buffer += line + "\n"
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        statements.append(buffer.strip())
    return statements


def set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute("INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, dumps(value)))


def get_meta(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    r = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return json.loads(r[0]) if r else default


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def row(r: sqlite3.Row | None) -> dict | None:
    """一行转成字典，并解析 JSON 列（data、objects）。"""
    if r is None:
        return None
    out = dict(r)
    for key in ("data", "objects"):
        if isinstance(out.get(key), str):
            out[key] = json.loads(out[key])
    return out


def rows(rs) -> list[dict]:
    return [row(r) for r in rs]
