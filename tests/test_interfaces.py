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


def test_agent_runner_records_conversation(ws, human, tmp_path):
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
    art = ws.ledger.get(done["data"]["artifact_id"])
    assert art["kind"] == "conversation" and art["source_class"] == "inferred"
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


def test_port_not_shared_between_workspaces(tmp_path, monkeypatch):
    """另一个已登记的数据目录记下的端口，即使它没在运行，也不分给新目录（H-12）。"""
    import json

    from burrowl.interfaces import http, install
    from burrowl.services.workspace import Workspace
    monkeypatch.setenv("BURROWL_HOME", str(tmp_path / "root" / "current"))  # 安装根目录指到临时目录
    main, trial = Workspace(tmp_path / "main"), Workspace(tmp_path / "trial")
    install.register_workspace(main.root, True)
    install.register_workspace(trial.root, False)
    main_port = http.server_state(main)["port"]
    assert http.server_state(trial)["port"] != main_port
    # 旧版本已经分到同一端口的情况：非默认目录启动时换端口，默认目录保留
    (trial.root / "server.json").write_text(json.dumps({"port": main_port, "token": "t"}), encoding="utf-8")
    state, reason = http.settle_port(trial)
    assert state["port"] != main_port and reason
    assert http.settle_port(main)[0]["port"] == main_port
