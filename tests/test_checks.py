"""原件检查（services/checks.py）与索引覆盖检查。"""
import os


def _ref(ws, human, path, text):
    path.write_text(text, encoding="utf-8")
    return ws.artifacts.register(human, kind="dataset", source_class="local", path=str(path), storage="referenced")


def test_check_reports_changed_and_missing(ws, human, tmp_path, pump_log):
    a = _ref(ws, human, tmp_path / "a.csv", "t,v\n0,1\n")
    b = _ref(ws, human, tmp_path / "b.csv", "t,v\n0,1\n0,2\n")
    c = _ref(ws, human, tmp_path / "c.csv", "x\n")
    first = ws.source_check.run()
    assert (first["checked"], first["changed"], first["missing"]) == (3, 0, 0)  # 复制保存的 pump_log 不在检查范围

    (tmp_path / "a.csv").write_text("t,v\n0,9\n", encoding="utf-8")  # 大小不变、内容变了：要靠重算指纹发现
    (tmp_path / "c.csv").unlink()
    result = ws.source_check.run()
    status = {p["artifact_id"]: p["status"] for p in result["problems"]}
    assert status == {a["id"]: "changed", c["id"]: "missing"}
    assert b["id"] not in status
    # 结果存在状态文件里，不写账本；status 不重新检查
    assert ws.source_check.status()["changed"] == 1 and (ws.root / "checks.json").exists()


def test_check_skips_hash_when_size_and_mtime_unchanged(ws, human, tmp_path, monkeypatch):
    f = tmp_path / "big.bin"
    _ref(ws, human, f, "0123456789")
    ws.source_check.run()
    calls = []
    import burrowl.services.checks as checks
    monkeypatch.setattr(checks, "sha256_file", lambda p: calls.append(p) or "x")
    assert ws.source_check.run()["changed"] == 0 and calls == []   # 大小、修改时间都没变：不重算
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    assert ws.source_check.run()["changed"] == 1 and calls          # 修改时间变了：重算后发现不一致


def test_check_only_latest_version(ws, human, tmp_path):
    f = tmp_path / "w.csv"
    old = _ref(ws, human, f, "v1\n")
    f.write_text("v2 longer\n", encoding="utf-8")
    new = ws.artifacts.register(human, kind="dataset", source_class="local", path=str(f), storage="referenced",
                                version_of=old["id"])
    result = ws.source_check.run()
    assert result["checked"] == 1 and result["changed"] == 0 and not result["problems"]
    assert new["id"] in ws.source_check._load()["files"]


def test_schedule_follows_config(ws):
    ws.config["artifact_check"] = {"interval_hours": 0}
    ws.source_check.start_schedule()
    assert ws.source_check.status()["schedule"] == {"enabled": False, "interval_hours": 0.0, "running": False}
    ws.config["artifact_check"] = {"interval_hours": 6}
    assert ws.source_check.status()["schedule"]["enabled"]


def test_index_health_detects_missing(ws, pump_log):
    assert ws.overview.index_health()["missing"] == 0
    ws.index.remove(pump_log["id"])
    health = ws.overview.index_health()
    assert health["missing"] == 1 and health["missing_ids"] == [pump_log["id"]]
    ws.rebuild_index()
    assert ws.overview.index_health()["missing"] == 0


def test_daily_counts_today(ws, pump_log):
    daily = ws.overview.stats()["daily"]
    assert len(daily) == 14 and list(daily.values())[-1] >= 1   # 最后一天是今天，pump_log 算在内
