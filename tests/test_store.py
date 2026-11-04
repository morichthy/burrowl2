"""账本只追加、迁移幂等、格式版本（DESIGN §4：test_ledger_append_only、test_migrations）。"""
import sqlite3

import pytest

from burrowl import FORMAT_VERSION
from burrowl.store.db import connect, get_meta, migrate, split_sql

LEDGER_TABLES = ("artifacts", "events", "records", "reads", "judgments", "links", "entry_objects")


def test_ledger_rejects_update_and_delete(ws, human, pump_log):
    # 每张表都要有行：空表上的 DELETE 不会触发触发器
    rd = ws.artifacts.read(human, pump_log["id"], "seg:1")["read"]
    ws.artifacts.promote(human, artifact_id=pump_log["id"], locator="seg:1", objects=["2号泵"])
    ws.judgments.write(human, kind="observation", text="2号泵出口压力在 10:05 升到 0.87 MPa", cites=[rd["id"]],
                       objects=["2号泵"])
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
    assert first == ["0001_init.sql"]
    assert migrate(conn, "ledger") == []
    assert get_meta(ws.ledger_db, "format_version") == FORMAT_VERSION


def test_split_sql_keeps_trigger_bodies():
    stmts = split_sql("CREATE TABLE a (x);\nCREATE TRIGGER t BEFORE DELETE ON a BEGIN SELECT 1; SELECT 2; END;\n")
    assert len(stmts) == 2 and stmts[1].endswith("END;")
