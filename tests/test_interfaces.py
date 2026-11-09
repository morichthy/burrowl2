"""接口一致性、身份、agent 运行器、导出导入（DESIGN §4：test_ops_interfaces、test_agent_runner）。"""
import json
import sys

import pytest
from fastapi.testclient import TestClient

from burrowl.core.errors import BurrowlError
from burrowl.interfaces.http import create_app
from burrowl.interfaces.mcp import build_server, visible_ops
from burrowl.interfaces.registry import Ctx, call, load
from burrowl.interfaces.runtime import actor_for
from burrowl.services.workspace import Workspace


def test_mcp_hides_user_and_admin_ops():
    names = {s.name for s in visible_ops()}
    for user_op in ("judgment.amend", "framework.review", "term.decide", "agent.start", "data.export"):
        assert user_op in load() and user_op not in names
    assert "judgment.write" in names and "search" in names


def test_mcp_channel_is_ai_and_cannot_call_user_ops(ws, monkeypatch):
    monkeypatch.delenv("BURROWL_ACTOR_ID", raising=False)
    ctx = Ctx(ws=ws, actor=actor_for("mcp"), channel="mcp")
    j = call(ctx, "judgment.write", {"kind": "conclusion", "text": "压缩机出口温度偏高"})
    assert j["author_kind"] == "ai"
    with pytest.raises(BurrowlError) as e:
        call(ctx, "judgment.amend", {"mode": "retraction", "target": j["id"], "reason": "x"})
    assert e.value.code == "FORBIDDEN"
    monkeypatch.setenv("BURROWL_ACTOR_ID", "ai:claude:run_x")
    assert actor_for("cli").kind == "ai"  # agent 在子进程里调用命令行，仍记为 AI


def test_cli_ai_session_follows_parent_process(monkeypatch):
    """设计稿 07 D-11：命令行以 AI 身份调用、没有 BURROWL_SESSION 时，同一父进程、同一天是同一会话。"""
    from datetime import date

    from burrowl.core.ids import kind_of
    from burrowl.interfaces.runtime import parent_session
    monkeypatch.setenv("BURROWL_ACTOR_ID", "ai:script")
    monkeypatch.delenv("BURROWL_SESSION", raising=False)
    assert actor_for("cli").session_id == actor_for("cli").session_id == parent_session()
    day = date(2026, 11, 9)
    assert parent_session(42, day) == parent_session(42, day) != parent_session(43, day)
    assert kind_of(parent_session(42, day)) == "session"
    monkeypatch.setenv("BURROWL_SESSION", "ses_01JC0000000000000000000009")
    assert actor_for("cli").session_id == "ses_01JC0000000000000000000009"


def test_arguments_validated_all_at_once(ws, human):
    ctx = Ctx(ws=ws, actor=human, channel="cli")
    with pytest.raises(BurrowlError) as e:
        call(ctx, "judgment.write", {"kind": 1, "bogus": True})
    assert e.value.code == "INVALID_ARGUMENT" and len(e.value.details["errors"]) >= 2


def test_mcp_server_builds(ws):
    server = build_server(ws)
    assert server.name == "burrowl"


def test_http_matches_registry(ws):
    client = TestClient(create_app(ws, "tok"))
    assert client.get("/api/ops").status_code == 403
    r = client.post("/api/ops/judgment.write", headers={"x-burrowl-token": "tok"},
                    json={"kind": "conclusion", "text": "现场看到冷却塔风机停转", "local_observation": True})
    body = r.json()
    assert body["ok"] and body["result"]["author_kind"] == "human"
    assert body["result"]["data"]["credibility"]["source_classes"] == ["local"]
    r = client.post("/api/ops/entry.get", headers={"x-burrowl-token": "tok"}, json={"id": "jdg_bad"})
    assert r.status_code == 404 or not r.json()["ok"]


def test_agent_runner_keeps_output_out_of_ledger(ws, human, tmp_path):
    script = tmp_path / "fake_agent.py"
    script.write_text("import os, sys\nprint('收到任务:', sys.argv[1][-6:])\n"
                      "print('actor=' + os.environ['BURROWL_ACTOR_ID'][:9])\n", encoding="utf-8")
    ws.config["agents"]["fake"] = {"command": [sys.executable, str(script), "{prompt}"]}
    run = ws.agents.start(human, agent="fake", prompt="检查 2号泵", preamble=False)
    done = ws.agents.wait(run["id"], timeout=20)
    assert done["status"] == "done", done
    out = ws.agents.output(run["id"])
    assert any("收到任务" in line for line in out["lines"])
    assert any("actor=ai:fake:" in line for line in out["lines"])
    assert "artifact_id" not in done["data"]
    assert not ws.ledger.query("SELECT id FROM artifacts WHERE session_id = ?", (run["session_id"],))
    assert "收到任务" in (ws.root / "runs" / run["id"] / "output.log").read_text(encoding="utf-8")
    mcp_cfg = json.loads((ws.root / "runs" / run["id"] / "mcp.json").read_text(encoding="utf-8"))
    assert mcp_cfg["mcpServers"]["burrowl"]["env"]["BURROWL_SESSION"] == run["session_id"]


def test_export_import_roundtrip(ws, human, ai, pump_log, tmp_path):
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵压力 0.82 MPa", cites=[pump_log["id"]])
    ent = ws.frameworks.entity_upsert(human, kind="device", name="2号泵")
    ws.frameworks.page_write(human, type="entity", title="2号泵", body=f"压力见 [[{j['id']}]]", subject_id=ent["id"])
    manifest = ws.portability.export(str(tmp_path / "out"))
    assert manifest["files"]["ledger/judgments.jsonl"]["rows"] == 1
    assert (tmp_path / "out" / "vault" / "2号泵.md").read_text(encoding="utf-8").startswith("---")
    other = Workspace(tmp_path / "other")
    other.portability.import_(str(tmp_path / "out"))
    assert other.ledger.get(j["id"])["data"]["text"] == "2号泵压力 0.82 MPa"
    assert other.artifacts.segments(pump_log["id"])
    assert other.retrieval.search("0.82")["hits"]
    other.close()


def test_cli_parses_arguments_without_json_quoting(tmp_path, monkeypatch):
    """Windows 上 cmd.exe 会拆坏整段 JSON，所以支持 key=value、@文件、-（H-12）。"""
    import io

    from burrowl.interfaces.cli import parse_arguments
    assert parse_arguments(["query=2号泵 压力", "limit=5", "objects=a", "objects=b"]) == {
        "query": "2号泵 压力", "limit": 5, "objects": ["a", "b"]}
    assert parse_arguments(['{"query":', '"压力"}']) == {"query": "压力"}   # 被空格拆开的 JSON 拼回
    f = tmp_path / "args.json"
    f.write_text('{"query": "阀门"}', encoding="utf-8")
    assert parse_arguments([f"@{f}"]) == {"query": "阀门"}
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b'{"limit": 3}')))
    assert parse_arguments(["-"]) == {"limit": 3}
    with pytest.raises(ValueError):
        parse_arguments(["query"])


@pytest.fixture
def two_workspaces(tmp_path, monkeypatch):
    from burrowl.interfaces import install
    monkeypatch.setenv("BURROWL_HOME", str(tmp_path / "root" / "current"))  # 安装根目录指到临时目录
    monkeypatch.delenv("BURROWL_DATA", raising=False)
    main, trial = Workspace(tmp_path / "main"), Workspace(tmp_path / "trial")
    install.register_workspace(main.root, True)
    install.register_workspace(trial.root, False)
    yield main, trial
    main.close()
    trial.close()


def test_one_workbench_switches_workspaces(two_workspaces):
    """一个工作台进程管理多个数据目录：按 x-burrowl-data 选，不带就是默认目录，互不串数据（D-18）。"""
    from burrowl.interfaces.pool import WorkspacePool
    main, trial = two_workspaces
    client = TestClient(create_app(WorkspacePool(), "tok"))
    head = {"x-burrowl-token": "tok"}
    body = {"kind": "conclusion", "text": "只写进试用目录的判断"}
    r = client.post("/api/ops/judgment.write", headers={**head, "x-burrowl-data": "trial"}, json=body).json()
    assert r["ok"]
    assert trial.ledger.get(r["result"]["id"]) and not main.ledger.get(r["result"]["id"])
    listed = client.post("/api/ops/workspace.list", headers=head).json()["result"]
    assert listed["current"] == "main" and [i["name"] for i in listed["items"]] == ["main", "trial"]
    assert client.post("/api/ops/server.info?db=trial", headers=head).json()["result"]["data_name"] == "trial"
    bad = client.post("/api/ops/workspace.list", headers={**head, "x-burrowl-data": "nope"})
    assert bad.status_code == 404
    # 改默认：之后不带目录的请求落到新默认
    client.post("/api/ops/workspace.set_default", headers=head, json={"name": "trial"})
    assert client.post("/api/ops/workspace.list", headers=head).json()["result"]["current"] == "trial"
    r = client.post("/api/ops/workspace.remove", headers=head, json={"name": "trial"})
    assert r.status_code == 409                                    # 默认目录不能移除


def test_workspace_add_needs_create_for_new_dir(two_workspaces, tmp_path, human):
    from burrowl.interfaces import install
    main, _ = two_workspaces
    ctx = Ctx(ws=main, actor=human, channel="http")
    with pytest.raises(BurrowlError) as e:
        call(ctx, "workspace.add", {"path": str(tmp_path / "fresh")})
    assert e.value.code == "NOT_FOUND"
    call(ctx, "workspace.add", {"path": str(tmp_path / "fresh"), "name": "main", "create": True})
    assert install.name_of(tmp_path / "fresh") == "main-2"        # 重名自动加后缀
    call(ctx, "workspace.remove", {"name": "main-2"})
    assert (tmp_path / "fresh" / "ledger.sqlite").exists()       # 只取消登记，数据还在
    ai_ctx = Ctx(ws=main, actor=actor_for("mcp"), channel="mcp")
    with pytest.raises(BurrowlError):
        call(ai_ctx, "workspace.set_default", {"name": "trial"})


def test_mcp_without_data_follows_default(two_workspaces):
    """不带 --data 的 MCP 每次调用都取当时的默认数据目录；带 --data 的固定不变。"""
    from burrowl.interfaces import install
    from burrowl.interfaces.pool import WorkspacePool
    main, trial = two_workspaces
    follow, pinned = WorkspacePool(), WorkspacePool(main.root)
    assert follow.resolve().root == main.root
    install.set_default_workspace("trial")
    assert follow.resolve().root == trial.root and pinned.resolve().root == main.root


def test_workbench_state_migrates_from_default_workspace(two_workspaces):
    """2.0.0a7 的状态存在各数据目录；升级后沿用默认目录的端口和 token，收藏的网址继续可用。"""
    from burrowl.interfaces import http
    main, _ = two_workspaces
    (main.root / "server.json").write_text(json.dumps({"port": 8799, "token": "old", "pid": 1}), encoding="utf-8")
    assert http.server_state() == {"port": 8799, "token": "old"}
    assert http.state_path().exists() and http.state_path().parent != main.root
