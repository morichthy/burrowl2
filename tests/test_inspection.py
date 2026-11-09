"""设计稿 08：定期巡检（AC-01 至 AC-06、AC-08、AC-09 中可自动验证的部分）。

AC-07（真实 AI 客户端跑一期巡检、复核员在另一个会话复核）要用真实的 agent，不在这里。
"""
import sqlite3
import sys

import pytest

from burrowl.core.actor import Actor
from burrowl.core.errors import BurrowlError
from burrowl.interfaces.registry import Ctx, call
from burrowl.services import model_adapters
from burrowl.services.inspection import opposite

OTHER = """# 泵房日常记录

2号泵出口压力偏高，需关注。

2号泵运行时振动正常。
"""
COLD = """# 咖啡机清洁

每周用除垢剂清洗一次。
"""


@pytest.fixture
def inspector():
    return Actor("ai:inspector", "ai", "ses_01JC0000000000000000000005")


@pytest.fixture
def reviewer():
    return Actor("ai:reviewer", "ai", "ses_01JC0000000000000000000006")


@pytest.fixture
def no_llm(ws, monkeypatch):
    """准备巡检包时不能调用任何大模型或 agent（I12）。"""
    def boom(*a, **k):
        raise AssertionError("准备巡检包时调用了大模型或 agent")
    for name in ("llm_check", "llm_health", "llm_formula"):
        monkeypatch.setattr(model_adapters, name, boom)
    monkeypatch.setattr(ws.agents, "start", boom)


def research(ws, ai, pump_log):
    """一段近期研究：一对疑似冲突的结论、一条带框架性措辞的判断；引用 seg-1 时只读了 seg-1。"""
    art = pump_log["id"]
    ws.artifacts.read(ai, art, "seg-1")
    j1 = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力升高，超过 0.85 MPa",
                            cites=[f"{art}#seg-1"], objects=["2号泵"], conditions="10:05 巡检")
    j2 = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力降低，低于 0.85 MPa",
                            cites=[f"{art}#seg-1"], objects=["2号泵"])
    j3 = ws.judgments.write(ai, kind="conclusion", text="根本原因是入口阀 V-301 开度不足", cites=[f"{art}#seg-1"])
    return j1, j2, j3


def task_of(insp, check, target=None):
    for t in insp["data"]["tasks"]:
        if t["check"] == check and (target is None or target in t["targets"]):
            return t
    raise AssertionError(f"没有 {check} 任务：{[t['title'] for t in insp['data']['tasks']]}")


def test_opposite_rules():
    assert "升高" in opposite("2号泵出口压力升高", "2号泵出口压力降低")
    assert "数值" in opposite("2号泵出口压力为 0.82 MPa", "2号泵出口压力为 0.87 MPa")
    assert opposite("2号泵出口压力正常", "咖啡机每周清洗") is None


def test_search_hits_are_logged_for_ai_only(ws, human, ai, pump_log):
    """AC-01：AI 检索后过程日志有一条 search 事件，含锚点、不含全文；人在工作台检索不产生事件。"""
    call(Ctx(ws, ai, "mcp"), "search", {"query": "出口压力"})
    call(Ctx(ws, human, "http"), "search", {"query": "出口压力"})
    events = ws.ledger.query("SELECT * FROM events WHERE op = 'search'")
    assert len(events) == 1 and events[0]["actor_id"] == ai.id
    hits = events[0]["data"]["input"]["hits"]
    assert hits and hits[0]["id"] == pump_log["id"] and hits[0]["anchors"]
    assert "0.82" not in str(events[0]["data"])  # 不记全文
    found = ws.retrieval.search("出口压力")["hits"]
    assert all(not h["id"].startswith("evt_") for h in found)


def test_coverage_five_states(ws, human, ai, pump_log):
    """AC-02：被引用、读过未引、命中未读、相关未读、冷区各有段落；已退役原件不出现。"""
    art = pump_log["id"]
    other = ws.artifacts.register(human, kind="log", source_class="local", text=OTHER, title="泵房日常")
    cold = ws.artifacts.register(human, kind="log", source_class="local", text=COLD, title="咖啡机")
    gone = ws.artifacts.register(human, kind="log", source_class="local", text="# 旧记录\n\n旧的泵压力。\n", title="旧")
    ws.judgments.retire(human, gone["id"], reason="作废")
    ws.artifacts.read(ai, art, "seg-1")
    ws.artifacts.read(ai, art, "seg-2")
    ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力 0.82 MPa", cites=[f"{art}#seg-1"],
                       objects=["2号泵"])
    for _ in range(3):
        ws.coverage.log_search(ai, "search", "表格", "reuse", {"hits": [{"id": art, "passages": [
            {"anchors": ["seg-3"]}]}]})
    view = ws.coverage.view()
    states = {a["id"]: a["counts"] for a in view["artifacts"]}
    assert gone["id"] not in states
    assert states[art]["cited"] == 1 and states[art]["read"] == 1 and states[art]["hit_unread"] == 1
    assert states[other["id"]]["related_unread"] >= 1
    assert states[cold["id"]]["cold"] >= 1 and states[cold["id"]]["related_unread"] == 0
    detail = ws.coverage.view(art)
    by_anchor = {s["anchor"]: s for s in detail["segments"]}
    assert by_anchor["seg-1"]["state"] == "cited" and by_anchor["seg-1"]["cited_by"]
    assert by_anchor["seg-3"]["state"] == "hit_unread" and by_anchor["seg-3"]["hits"] == 3


def test_prepare_finds_planted_problems_without_llm(ws, human, ai, pump_log, no_llm):
    """AC-03：埋下的冲突、未读的相邻段落、带"根本原因是"的判断都生成任务；准备过程不调用大模型。"""
    j1, j2, j3 = research(ws, ai, pump_log)
    summary = ws.inspection.prepare(human)
    insp = ws.framework.inspection(summary["id"])
    conflict = task_of(insp, "conflict", j1["id"])
    assert set(conflict["targets"]) == {j1["id"], j2["id"]}
    neighbor = task_of(insp, "unread_neighbor", j1["id"])
    assert f"{pump_log['id']}#seg-2" in neighbor["read"]
    rule = task_of(insp, "rule", j3["id"])
    assert any("根本原因是" in p for p in rule["detail"]["problems"])
    assert summary["status"] == "ready" and summary["period"] == 1
    again = ws.inspection.prepare(human)  # 还没开跑：就地更新，不另起一期
    assert again["id"] == summary["id"]


def test_schedule_prepares_once(ws, ai, pump_log, no_llm):
    research(ws, ai, pump_log)
    assert ws.inspection.due()
    first = ws.inspection.run_due()
    assert first and first["trigger"] == "schedule"
    assert not ws.inspection.due() and ws.inspection.run_due() is None
    ws.config["inspection"]["interval_days"] = 0
    assert not ws.inspection.due()


def _submit_conflict(ws, ai, inspector, pump_log):
    j1, j2, _ = research(ws, ai, pump_log)
    insp_id = ws.inspection.prepare(Actor("human:t", "human", "ses_h"))["id"]
    pkg = ws.inspection.get(inspector, inspection_id=insp_id)
    task = next(t for t in pkg["tasks"] if t["check"] == "conflict")
    ws.artifacts.read(inspector, pump_log["id"], "seg-1")
    out = ws.inspection.submit(inspector, inspection_id=insp_id, task_id=task["id"], outcome="issue",
                               summary="两条结论对同一次巡检的出口压力方向相反", cites=[f"{pump_log['id']}#seg-1"],
                               suggestion="contradict_edge", model="test-model")
    return insp_id, task, out["finding"], j1, j2


def test_submit_rules_and_effects(ws, human, ai, inspector, pump_log):
    """AC-04：未读先报、以框架页为依据、针对本会话写的条目被拒绝；涉及判断时请人复核；原判断不变。"""
    j1, j2, _ = research(ws, ai, pump_log)
    insp_id = ws.inspection.prepare(human)["id"]
    pkg = ws.inspection.get(inspector, inspection_id=insp_id)
    assert ws.framework.inspection(insp_id)["status"] == "running"
    task = next(t for t in pkg["tasks"] if t["check"] == "conflict")
    seg = f"{pump_log['id']}#seg-1"
    with pytest.raises(BurrowlError) as e:
        ws.inspection.submit(inspector, inspection_id=insp_id, task_id=task["id"], outcome="issue", summary="x",
                             cites=[seg], model="m")
    assert e.value.code == "UNREAD_FINDING"
    page = ws.frameworks.page_write(ai, type="synthesis", title="泵", body="综合", inputs=[j1["id"]])
    with pytest.raises(BurrowlError) as e:
        ws.inspection.submit(inspector, inspection_id=insp_id, task_id=task["id"], outcome="issue", summary="x",
                             cites=[page["id"]], model="m")
    assert e.value.code == "FRAMEWORK_NOT_EVIDENCE"
    ws.artifacts.read(ai, pump_log["id"], "seg-1")
    with pytest.raises(BurrowlError) as e:  # 写判断的会话不能针对自己写的判断
        ws.inspection.submit(ai, inspection_id=insp_id, task_id=task["id"], outcome="issue", summary="x",
                             cites=[seg], model="m")
    assert e.value.code == "SAME_SESSION"
    before = ws.ledger.get(j1["id"])["data"]["credibility"]
    ws.artifacts.read(inspector, pump_log["id"], "seg-1")
    out = ws.inspection.submit(inspector, inspection_id=insp_id, task_id=task["id"], outcome="issue",
                               summary="方向相反", cites=[seg], suggestion="contradict_edge", model="m")
    f = out["finding"]
    # 设计稿 08 §9：一条发现就是一项待决策，不另开"请人复核"或可能矛盾边
    assert f["id"].startswith("dec_") and f["kind"] == "finding" and f["data"]["review"] == "ai_generated"
    assert f["subject_id"] in (j1["id"], j2["id"]) and set(f["data"]["targets"]) == {j1["id"], j2["id"]}
    assert ws.framework.decisions(kind="review") == []
    assert ws.framework.edges(rel="may_contradict") == []
    assert ws.ledger.get(j1["id"])["data"]["credibility"] == before
    with pytest.raises(BurrowlError) as e:  # 发现不能作为依据（I2）
        ws.judgments.write(ai, kind="conclusion", text="x", cites=[f["id"]])
    assert e.value.code == "FRAMEWORK_NOT_EVIDENCE"
    rule = next(t for t in pkg["tasks"] if t["check"] == "rule")
    ws.inspection.submit(inspector, inspection_id=insp_id, task_id=rule["id"], outcome="clear", model="m")
    assert len(ws.inspection.findings(insp_id)) == 1


def test_reviewer_and_human_handling(ws, human, ai, inspector, reviewer, pump_log):
    """AC-05：复核员没读就确认被拒绝；按运行分组的待决策带复核员意见；人驳回后记录并关闭待决策项。"""
    insp_id, task, f, *_ = _submit_conflict(ws, ai, inspector, pump_log)
    with pytest.raises(BurrowlError) as e:
        ws.reviews.ai_submit(inspector, item_id=f["id"], verdict="confirm", reason="对", model="m",
                             cites=[f"{pump_log['id']}#seg-1"])
    assert e.value.code == "SAME_SESSION"
    pkg = ws.inspection.get(reviewer, inspection_id=insp_id, role="reviewer")
    assert [x["id"] for x in pkg["findings"]] == [f["id"]]
    with pytest.raises(BurrowlError) as e:
        ws.reviews.ai_submit(reviewer, item_id=f["id"], verdict="confirm", reason="对", model="m")
    assert e.value.code == "UNREAD_FINDING"
    ws.artifacts.read(reviewer, pump_log["id"], "seg-1")
    out = ws.reviews.ai_submit(reviewer, item_id=f["id"], verdict="confirm", reason="两条确实相反", model="m2")
    assert out["review"] == "ai_reviewed"
    d = ws.framework.decision(f["id"])
    assert d["impact"] == 3 and d["data"]["reviewer"]["verdict"] == "confirm"
    with pytest.raises(BurrowlError) as e:  # 一条发现只由复核员看一次
        ws.reviews.ai_submit(reviewer, item_id=f["id"], verdict="reject", reason="x", model="m2",
                             cites=[f"{pump_log['id']}#seg-1"])
    assert e.value.code == "REVIEW_NOT_ALLOWED"
    with pytest.raises(BurrowlError):
        ws.inspection.resolve(ai, decision_id=f["id"], action="reject")
    ws.inspection.resolve(human, decision_id=f["id"], action="reject", reason="条件不同")
    d = ws.framework.decision(f["id"])
    assert d["status"] == "dismissed" and d["data"]["resolution"]["action"] == "reject"
    history = ws.reviews.history(f["id"])["history"]
    assert [h["type"] for h in history] == ["submit", "ai_review", "resolve"]
    # D-19：处理过的发现，同一范围再准备时不再生成这个任务
    fp = next(t for t in ws.framework.inspection(insp_id)["data"]["tasks"] if t["id"] == task["id"])["fingerprint"]
    data = ws.inspection._build("2000-01-01T00:00:00.000Z", "2999-01-01T00:00:00.000Z", exclude=None)
    assert fp not in {t["fingerprint"] for t in data["tasks"]}
    assert data["skipped"]["known"] >= 1


def test_policies_are_append_only(ws, human, pump_log):
    ws.inspection.set_policy(human, artifact_id=pump_log["id"], outbound=False, reason="受限")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ws.ledger_db.execute("DELETE FROM artifact_policies")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ws.ledger_db.execute("UPDATE artifact_policies SET id = id")


def fake_agent(ws, tmp_path, name="fake"):
    script = tmp_path / f"{name}.py"
    script.write_text("import os, sys\nif sys.argv[1:] == ['--version']:\n    print('fake 1.0')\n"
                      "else:\n    print(os.environ['BURROWL_ACTOR_ID'])\n", encoding="utf-8")
    ws.config["agents"][name] = {"command": [sys.executable, str(script), "{prompt}"]}


def test_agent_test_and_settings(ws, human, tmp_path):
    """AC-06：测试连接三步分别能通过与失败；两个角色选同一个 agent 时提示但能保存。"""
    fake_agent(ws, tmp_path)
    ok = ws.agents.test(human, agent="fake", timeout=30)
    assert ok["ok"], ok
    assert [s["step"] for s in ok["steps"]] == ["command", "run", "identity"]
    assert ok["steps"][0]["detail"] == "fake 1.0"
    ws.config["agents"]["missing"] = {"command": ["no-such-agent-xyz", "{prompt}"]}
    bad = ws.agents.test(human, agent="missing")
    assert not bad["ok"] and bad["steps"][0]["step"] == "command"
    script = tmp_path / "silent.py"
    script.write_text("print('hello')\n", encoding="utf-8")
    ws.config["agents"]["silent"] = {"command": [sys.executable, str(script), "{prompt}"]}
    silent = ws.agents.test(human, agent="silent", timeout=30)
    assert not silent["ok"] and silent["steps"][-1]["step"] == "identity" and not silent["steps"][-1]["ok"]
    script = tmp_path / "nologin.py"  # 运行失败时测试结果带上 agent 的最后一行输出
    script.write_text("import sys\nif sys.argv[1:] == ['--version']:\n    print('2.1 (fake)')\n    sys.exit(0)\n"
                      "print('Not logged in · Please run /login')\nsys.exit(1)\n", encoding="utf-8")
    ws.config["agents"]["nologin"] = {"command": [sys.executable, str(script), "{prompt}"]}
    nologin = ws.agents.test(human, agent="nologin", timeout=30)
    assert "Not logged in" in nologin["steps"][1]["detail"] and not nologin["steps"][1]["ok"]
    with pytest.raises(BurrowlError):
        ws.agents.test(Actor("ai:x", "ai", "ses_x"), agent="fake")
    ctx = Ctx(ws, human, "http")
    ws.save_config({"agents": ws.config["agents"]})
    call(ctx, "settings.set", {"values": {"inspection.inspector": "fake", "inspection.reviewer": "fake"}})
    assert ws.inspection.status()["same_agent"]
    with pytest.raises(BurrowlError):
        call(ctx, "settings.set", {"values": {"inspection.reviewer": "nobody"}})
    with pytest.raises(BurrowlError):
        call(Ctx(ws, human, "mcp"), "agent.test", {"agent": "fake"})


def test_start_records_run(ws, human, ai, pump_log, tmp_path):
    fake_agent(ws, tmp_path)
    ws.config["inspection"]["inspector"] = "fake"
    research(ws, ai, pump_log)
    insp_id = ws.inspection.prepare(human)["id"]
    run = ws.inspection.start(human, inspection_id=insp_id)
    ws.agents.wait(run["id"], timeout=20)
    insp = ws.framework.inspection(insp_id)
    assert insp["status"] == "running" and insp["data"]["runs"][0]["run_id"] == run["id"]
    assert run["session_id"] in ws.inspection.inspection_sessions()
    assert "inspection_get" in ws.inspection.prompt(inspection_id=insp_id)
    with pytest.raises(BurrowlError):
        ws.inspection.start(ai, inspection_id=insp_id)


def test_no_outbound(ws, human, ai, inspector, pump_log):
    """AC-08：不外发的原件原文不进巡检包；巡检会话读它被拒绝，平时的会话照常可读。"""
    research(ws, ai, pump_log)
    ws.inspection.set_policy(human, artifact_id=pump_log["id"], outbound=False, reason="客户数据")
    insp_id = ws.inspection.prepare(human)["id"]
    insp = ws.framework.inspection(insp_id)
    assert all(not r.startswith(pump_log["id"]) for t in insp["data"]["tasks"] for r in t["read"])
    assert any(t.get("human_only") for t in insp["data"]["tasks"])
    assert "2号泵出口压力 0.82" not in ws.inspection.export(inspection_id=insp_id)["markdown"]
    ws.inspection.get(inspector, inspection_id=insp_id)
    with pytest.raises(BurrowlError) as e:
        ws.artifacts.read(inspector, pump_log["id"], "seg-1")
    assert e.value.code == "NOT_OUTBOUND"
    result = call(Ctx(ws, inspector, "mcp"), "search", {"query": "出口压力"})
    assert all(not h["id"].startswith(pump_log["id"]) for h in result["hits"])
    assert ws.artifacts.read(ai, pump_log["id"], "seg-1")["segments"]  # 平时的会话不受影响
    ws.inspection.set_policy(human, artifact_id=pump_log["id"], outbound=True, reason="已脱敏")
    assert ws.artifacts.read(inspector, pump_log["id"], "seg-1")["segments"]
    with pytest.raises(BurrowlError):
        ws.inspection.set_policy(ai, artifact_id=pump_log["id"], outbound=False, reason="x")


def test_offline_import(ws, human, ai, reviewer, pump_log):
    """AC-09：贴回的发现标为经人转交，复核员不能确认。"""
    research(ws, ai, pump_log)
    insp_id = ws.inspection.prepare(human)["id"]
    md = ws.inspection.export(inspection_id=insp_id)["markdown"]
    assert "2号泵出口压力" in md and "JSON" in md
    task = ws.framework.inspection(insp_id)["data"]["tasks"][0]
    text = ('结果如下：[{"task_id": "' + task["id"] + '", "outcome": "issue", "summary": "需要再看", '
            '"cites": ["' + pump_log["id"] + '#seg-1"]}]')
    out = ws.inspection.import_result(human, inspection_id=insp_id, text=text, model="web-chat")
    f = ws.framework.decision(out["created"][0])
    assert f["data"]["method"] == "relayed" and f["data"]["relayed_by"] == human.id
    ws.artifacts.read(reviewer, pump_log["id"], "seg-1")
    with pytest.raises(BurrowlError) as e:
        ws.reviews.ai_submit(reviewer, item_id=f["id"], verdict="confirm", reason="对", model="m",
                             cites=[f"{pump_log['id']}#seg-1"])
    assert e.value.code == "REVIEW_NOT_ALLOWED"
    assert ws.reviews.ai_submit(reviewer, item_id=f["id"], verdict="unsure", reason="没有读取记录",
                                model="m")["review"] == "ai_unsure"


def test_guidelines_default_custom_and_sync(ws, human, ai, inspector, pump_log):
    """D-36：巡检原则为空时用默认文本；人改了以后领取结果、离线包、记录的版本都跟着变；另一个进程读同一份配置。"""
    from burrowl.services.inspection import DEFAULT_GUIDELINES
    from burrowl.services.workspace import Workspace
    research(ws, ai, pump_log)
    insp_id = ws.inspection.prepare(human)["id"]
    g = call(Ctx(ws, human, "http"), "inspection.guidelines", {})
    assert g["is_default"] and g["text"] == DEFAULT_GUIDELINES and "inspection_submit" in g["fixed"]["inspector"]
    call(Ctx(ws, human, "http"), "settings.set", {"values": {"inspection.guidelines": "只看 2号泵 的结论。"}})
    other = Workspace(ws.root)  # 相当于 MCP 进程：读同一个数据目录的 config.json
    got = other.inspection.get(inspector, inspection_id=insp_id)
    assert got["guidelines"] == "只看 2号泵 的结论。"
    sha = other.inspection.guidelines()["sha"]
    assert other.framework.inspection(insp_id)["data"]["claims"][0]["guidelines_sha"] == sha
    assert "只看 2号泵 的结论。" in ws.inspection.export(inspection_id=insp_id)["markdown"]
    call(Ctx(ws, human, "http"), "settings.set", {"values": {"inspection.guidelines": "   "}})  # 全部删掉：回到默认
    assert ws.inspection.guidelines()["is_default"]
    with pytest.raises(BurrowlError):
        call(Ctx(ws, human, "http"), "settings.set", {"values": {"inspection.guidelines": "长" * 4001}})
    with pytest.raises(BurrowlError):
        call(Ctx(ws, ai, "mcp"), "settings.set", {"values": {"inspection.guidelines": "x"}})


def test_process_judgments_may_contain_evaluation(ws, human, ai, pump_log):
    """D-38：过程判断里的评价与“几种思路”不算与规则不符；结论照查。"""
    ws.judgments.write(ai, kind="process", text="目前有两种思路，关键在于先排除入口阀")
    concl = ws.judgments.write(ai, kind="conclusion", text="显然是入口阀的问题", cites=[pump_log["id"]],
                               objects=["2号泵"], conditions="10:05")
    insp_id = ws.inspection.prepare(human)["id"]
    tasks = call(Ctx(ws, human, "http"), "inspection.tasks", {"inspection_id": insp_id})["tasks"]
    rules = [t for t in tasks if t["check"] == "rule"]
    assert [t["targets"] for t in rules] == [[concl["id"]]]
    assert "显然" in rules[0]["detail"]["problems"][0]
    assert ws.framework.inspection(insp_id)["data"].get("claims") in (None, [])  # 工作台查看不记领取


def test_agent_executable_can_be_set_by_human(ws, human, ai, tmp_path):
    """D-39：命令不在 PATH 里时，人可以填完整路径；留空恢复默认；AI 不能改；找不到的路径被拒绝。"""
    ctx = Ctx(ws, human, "http")
    with pytest.raises(BurrowlError):
        call(ctx, "agent.set_command", {"agent": "claude", "executable": str(tmp_path / "none.exe")})
    with pytest.raises(BurrowlError):
        call(ctx, "agent.set_command", {"agent": "claude", "executable": "claude & del x"})
    with pytest.raises(BurrowlError):
        call(Ctx(ws, ai, "mcp"), "agent.set_command", {"agent": "claude", "executable": sys.executable})
    out = call(ctx, "agent.set_command", {"agent": "claude", "executable": sys.executable})
    assert out["executable"] == sys.executable and out["available"] and out["default_executable"] == "claude"
    assert ws.config["agents"]["claude"]["command"][1:] == ["-p", "{prompt}", "--mcp-config", "{mcp_config}",
                                                            "--output-format", "text"]
    assert ws.ledger.query("SELECT 1 FROM events WHERE op = 'settings.set'")
    restored = call(ctx, "agent.set_command", {"agent": "claude", "executable": ""})  # 留空：恢复默认，找不到也照样恢复
    assert restored["executable"] == "claude" and ws.config["agents"]["claude"]["command"][0] == "claude"


def test_custom_agent_command_can_be_saved_and_used_for_inspection(ws, human, ai, pump_log, tmp_path):
    """从工作台操作保存并选择自定义命令，再实际启动脚本，核对参数和本次 MCP 配置。"""
    ctx = Ctx(ws, human, "http")
    script = tmp_path / "custom agent.py"
    script.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    sys.exit(2)\n"
        "prompt, config = sys.argv[1:]\n"
        "assert prompt and Path(config).is_file()\n"
        "env = json.loads(Path(config).read_text(encoding='utf-8'))['mcpServers']['burrowl']['env']\n"
        "assert all(os.environ[key] == value for key, value in env.items())\n"
        "print(env['BURROWL_ACTOR_ID'])\n",
        encoding="utf-8",
    )
    params = {"agent": "自定义", "command": [sys.executable, str(script), "{prompt}", "{mcp_config}"]}
    with pytest.raises(BurrowlError):
        call(Ctx(ws, ai, "mcp"), "agent.save_command", params)
    with pytest.raises(BurrowlError):
        call(ctx, "agent.save_command", {**params, "command": [sys.executable, str(script)]})
    saved = call(ctx, "agent.save_command", params)
    assert saved["available"] and saved["command"] == params["command"]
    assert {"codex", "claude", "自定义"} <= {item["name"] for item in call(ctx, "agent.list", {})}
    call(ctx, "agent.save_command", {**params, "agent": "inspection-reviewer"})
    call(ctx, "settings.set", {"values": {"inspection.inspector": "自定义", "inspection.reviewer": "inspection-reviewer"}})
    ws.config = ws._load_config()
    assert call(ctx, "agent.test", {"agent": "自定义", "timeout": 20})["ok"]
    research(ws, ai, pump_log)
    insp_id = ws.inspection.prepare(human)["id"]
    run = ws.inspection.start(human, inspection_id=insp_id)
    assert run["agent"] == "自定义"
    assert ws.agents.wait(run["id"], timeout=20)["status"] == "done"
    review = ws.inspection.start(human, inspection_id=insp_id, role="reviewer")
    assert review["agent"] == "inspection-reviewer"
    assert ws.agents.wait(review["id"], timeout=20)["status"] == "done"


def test_codex_preset_passes_run_context_to_mcp(ws, human, tmp_path):
    """用脚本代替 Codex，解析实际传入的 TOML 参数并检查运行上下文。"""
    ctx = Ctx(ws, human, "http")
    preset = call(ctx, "settings.get", {})["agent_cli_presets"]["codex"]
    assert preset == ["codex", "exec", "--skip-git-repo-check", "-c", "{codex_mcp_config}", "{prompt}"]
    script = tmp_path / "fake codex.py"
    script.write_text(
        "import os, sys, tomllib\n"
        "from pathlib import Path\n"
        "assert sys.argv[1:4] == ['exec', '--skip-git-repo-check', '-c']\n"
        "server = tomllib.loads(sys.argv[4])['mcp_servers']['burrowl']\n"
        "assert Path(server['command']) == Path(sys.executable)\n"
        "assert server['args'] == ['-m', 'burrowl.interfaces.cli', 'mcp']\n"
        "assert server['env_vars'] == ['BURROWL_ACTOR_ID', 'BURROWL_SESSION', 'BURROWL_DATA']\n"
        "assert all(os.environ.get(key) for key in server['env_vars'])\n"
        "assert sys.argv[5] == '保留 {codex_mcp_config} 原文'\n",
        encoding="utf-8",
    )
    call(ctx, "agent.save_command", {"agent": "fake-codex", "command": [sys.executable, str(script), *preset[1:]]})
    run = ws.agents.start(human, agent="fake-codex", prompt="保留 {codex_mcp_config} 原文", preamble=False)
    assert ws.agents.wait(run["id"], timeout=20)["status"] == "done"
