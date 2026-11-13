"""账本只追加、迁移幂等、格式版本（DESIGN §4：test_ledger_append_only、test_migrations）。"""
import sqlite3

import pytest

from burrowl import FORMAT_VERSION
from burrowl.store.db import connect, get_meta, migrate, split_sql

# 账本基表（设计稿 10 D-01、D-04、D-07）：条目的各版本、关系、处置都只追加
LEDGER_TABLES = ("artifact_versions", "event_versions", "record_versions", "read_versions", "judgment_versions",
                 "relations", "entry_objects", "extractions", "version_states", "replacements", "artifact_policies",
                 "judgment_titles")


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
    ws.inspection.set_policy(human, artifact_id=pump_log["id"], outbound=False, reason="涉密")
    ws.judgments.set_title(human, ws.judgments.write(human, kind="conclusion", text="标题测试判断")["id"], "测试标题")
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
    assert first == ["0001_init.sql", "0002_judgment_titles.sql"]  # 0001 是 2.1.0 的新基线（设计稿 10 D-03）；0002 判断标题（D-101）
    assert migrate(conn, "ledger") == []
    assert get_meta(ws.ledger_db, "format_version") == FORMAT_VERSION == 2


def test_refuses_2_0_data_directory_without_writing(tmp_path):
    """设计稿 10 D-03：2.0 的数据目录（有迁移记录、没有 relations 表）被拒绝，且不做任何写入。"""
    from burrowl.core.errors import BurrowlError
    from burrowl.services.workspace import Workspace
    root = tmp_path / "old"
    root.mkdir()
    conn = sqlite3.connect(root / "ledger.sqlite")
    conn.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE links (id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()
    before = {p.name: p.stat().st_mtime_ns for p in root.iterdir()}
    with pytest.raises(BurrowlError) as e:
        Workspace(root)
    assert e.value.code == "OLD_FORMAT"
    assert {p.name: p.stat().st_mtime_ns for p in root.iterdir()} == before


def test_split_sql_keeps_trigger_bodies():
    stmts = split_sql("CREATE TABLE a (x);\nCREATE TRIGGER t BEFORE DELETE ON a BEGIN SELECT 1; SELECT 2; END;\n")
    assert len(stmts) == 2 and stmts[1].endswith("END;")


def test_purge_gate_is_the_only_way_to_delete(ws, human, pump_log):
    """设计稿 07 D-05：只有出现在 purge_gate 里的行能删；UPDATE 永远不行；purge_gate 不是账本表。"""
    db = ws.ledger_db
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("DELETE FROM artifact_versions WHERE id = ?", (pump_log["id"],))
    db.execute("PRAGMA foreign_keys=OFF")
    try:
        db.execute("BEGIN")
        db.execute("INSERT INTO purge_gate VALUES (?)", (pump_log["id"],))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("UPDATE artifact_versions SET kind = 'x' WHERE id = ?", (pump_log["id"],))
        db.execute("DELETE FROM artifact_versions WHERE id = ?", (pump_log["id"],))
        db.execute("DELETE FROM purge_gate")
        db.execute("COMMIT")
    finally:
        db.execute("PRAGMA foreign_keys=ON")
    assert ws.ledger.get(pump_log["id"]) is None
