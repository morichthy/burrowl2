"""账本只追加、迁移幂等、格式版本（DESIGN §4：test_ledger_append_only、test_migrations）。"""
import sqlite3

import pytest

from burrowl import FORMAT_VERSION
from burrowl.store.db import connect, get_meta, migrate, split_sql

LEDGER_TABLES = ("artifacts", "events", "records", "reads", "judgments", "links", "entry_objects", "extractions",
                 "retirements", "replacements")


def test_ledger_rejects_update_and_delete(ws, human, pump_log, tmp_path):
    # 每张表都要有行：空表上的 DELETE 不会触发触发器
    photo = tmp_path / "photo.png"
    photo.write_bytes(b"not really a png")
    ws.artifacts.register(human, kind="image", source_class="local", path=str(photo))  # 写入抽取层的单元清单
    rd = ws.artifacts.read(human, pump_log["id"], "seg:1")["read"]
    ws.artifacts.promote(human, artifact_id=pump_log["id"], locator="seg:1", objects=["2号泵"])
    ws.judgments.write(human, kind="conclusion", text="2号泵出口压力在 10:05 升到 0.87 MPa", cites=[rd["id"]],
                       objects=["2号泵"])
    other = ws.artifacts.register(human, kind="log", source_class="local", text="2号泵旧记录")
    ws.judgments.retire(human, other["id"], reason="重复")
    ws.judgments.replace(human, other["id"], replacement=pump_log["id"], reason="以巡检记录为准")
    for table in LEDGER_TABLES:
        assert ws.ledger_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0, table
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            ws.ledger_db.execute(f"DELETE FROM {table}")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            ws.ledger_db.execute(f"UPDATE {table} SET rowid = rowid")


def test_page_versions_are_append_only(ws, human):
    ent = ws.frameworks.entity_upsert(human, kind="device", name="2号泵")
    page = ws.frameworks.page_write(human, type="entity", title="2号泵", body="正文", subject_id=ent["id"])
    with pytest.raises(sqlite3.IntegrityError):
        ws.framework_db.execute("UPDATE page_versions SET version = 9 WHERE page_id = ?", (page["id"],))


def test_migrations_idempotent_and_versioned(tmp_path, ws):
    conn = connect(tmp_path / "x.sqlite")
    first = migrate(conn, "ledger")
    assert first == ["0001_init.sql", "0002_source_class_names.sql", "0003_extractions.sql",
                     "0004_reviews_retirements.sql", "0005_replacements_purge.sql"]
    assert migrate(conn, "ledger") == []
    assert get_meta(ws.ledger_db, "format_version") == FORMAT_VERSION


def test_split_sql_keeps_trigger_bodies():
    stmts = split_sql("CREATE TABLE a (x);\nCREATE TRIGGER t BEFORE DELETE ON a BEGIN SELECT 1; SELECT 2; END;\n")
    assert len(stmts) == 2 and stmts[1].endswith("END;")


def test_migration_0002_renames_source_classes(tmp_path):
    """0001 时期写入的 executed / discussion 在 0002 后变成 local / inferred，只追加触发器仍然有效。"""
    from importlib.resources import files

    from burrowl.store.db import split_sql
    conn = connect(tmp_path / "old.sqlite")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    for stmt in split_sql((files("burrowl.store.migrations") / "ledger" / "0001_init.sql").read_text(encoding="utf-8")):
        conn.execute(stmt)
    conn.execute("INSERT INTO schema_migrations VALUES ('0001_init.sql', 'x')")
    for i, cls in enumerate(("executed", "discussion", "external")):
        conn.execute("INSERT INTO artifacts (id, created_at, kind, source_class, sha256, storage, captured_by) "
                     "VALUES (?, 'x', 'log', ?, 'h', 'managed', 't')", (f"art_{i}", cls))
    assert migrate(conn, "ledger") == ["0002_source_class_names.sql", "0003_extractions.sql",
                                       "0004_reviews_retirements.sql", "0005_replacements_purge.sql"]
    got = [r[0] for r in conn.execute("SELECT source_class FROM artifacts ORDER BY id")]
    assert got == ["local", "inferred", "external"]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM artifacts")


def test_purge_gate_is_the_only_way_to_delete(ws, human, pump_log):
    """设计稿 07 D-05：只有出现在 purge_gate 里的行能删；UPDATE 永远不行；purge_gate 不是账本表。"""
    db = ws.ledger_db
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("DELETE FROM artifacts WHERE id = ?", (pump_log["id"],))
    db.execute("PRAGMA foreign_keys=OFF")
    try:
        db.execute("BEGIN")
        db.execute("INSERT INTO purge_gate VALUES (?)", (pump_log["id"],))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("UPDATE artifacts SET kind = 'x' WHERE id = ?", (pump_log["id"],))
        db.execute("DELETE FROM artifacts WHERE id = ?", (pump_log["id"],))
        db.execute("DELETE FROM purge_gate")
        db.execute("COMMIT")
    finally:
        db.execute("PRAGMA foreign_keys=ON")
    assert ws.ledger.get(pump_log["id"]) is None
