"""工作台的只读汇总（activity / stats / entries / graph）与服务控制操作的开放范围。"""
import pytest

from burrowl.core.errors import BurrowlError
from burrowl.interfaces.mcp import visible_ops
from burrowl.interfaces.registry import Ctx, call


@pytest.fixture
def scene(ws, human, ai, pump_log):
    pump = ws.frameworks.entity_upsert(human, kind="device", name="2号泵")
    rd = ws.artifacts.read(ai, pump_log["id"], "seg:1")["read"]
    j1 = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力 0.82 MPa", cites=[rd["id"]], objects=[pump["id"]])
    j2 = ws.judgments.write(ai, kind="conclusion", text="2号泵压力正常", objects=[pump["id"]],
                            relations=[{"rel": "opposes", "target": j1["id"]}])
    j3 = ws.judgments.write(human, kind="conclusion", text="2号泵压力 0.82 MPa 在额定范围内", objects=[pump["id"]],
                            relations=[{"rel": "supersedes", "target": j2["id"]}])
    page = ws.frameworks.page_write(human, type="entity", title="2号泵", body=f"见 [[{j1['id']}]]",
                                    subject_id=pump["id"])
    return {"pump": pump, "j1": j1, "j2": j2, "j3": j3, "page": page, "art": pump_log}


def test_activity_newest_first(ws, human, scene):
    ws.versions.change_state(human, scene["j2"]["id"], "withdraw", "不对")
    items = ws.overview.activity(10)
    assert items[0]["at"] >= items[-1]["at"]
    kinds = {i["kind"] for i in items}
    assert {"artifact", "judgment.conclusion", "state.withdraw", "page"} <= kinds


def test_stats_counts(ws, scene):
    s = ws.overview.stats()
    j = s["judgments"]
    assert j["total"] == 3 and j["replaced"] == 1 and j["opposed"] == 1
    assert j["local_only"] == 1 and j["inferred_only"] == 2 and j["by_author"]["human"] == 1
    assert s["relations"]["opposes"] == 1 and s["relations"]["supersedes"] == 1
    assert s["pages"]["total"] == 1


def test_entries_filters(ws, scene):
    out = ws.overview.entries(kind="judgment", author_kind="ai")
    assert out["total"] == 2 and all(i["notes"]["author"] == "ai" for i in out["items"])
    assert ws.overview.entries(kind="judgment", source_class="local")["total"] == 1
    assert ws.overview.entries(kind="judgment", object="2号泵")["total"] == 3
    assert ws.overview.entries(kind="judgment", judgment_kind="thought")["total"] == 0
    assert ws.overview.entries(kind="judgment", quoted=True)["total"] == 0
    item = ws.overview.entries(kind="judgment", source_class="local")["items"][0]
    assert item["ref"] == f"{scene['j1']['id']}@1" and item["status_note"].startswith("判断 · 本地实证；结论")
    with pytest.raises(BurrowlError):
        ws.overview.entries(kind="page")


def test_entries_status_filter(ws, human, scene):
    """按现状的有效性筛选：被替代、已撤回；原件退役后它在"已退役"里，只依据它的判断在"依据失效"里。"""
    ids = lambda **kw: {i["id"] for i in ws.overview.entries(**kw)["items"]}  # noqa: E731
    assert ids(kind="judgment", status="replaced") == {scene["j2"]["id"]}
    assert ids(kind="judgment", status="current") == {scene["j1"]["id"], scene["j3"]["id"]}
    ws.judgments.retire(human, scene["art"]["id"], reason="不再需要")
    assert ids(kind="artifact", status="retired") == {scene["art"]["id"]}
    assert scene["art"]["id"] not in ids(kind="artifact", status="current")
    out = ws.overview.entries(kind="judgment", status="lapsed")
    assert {i["id"] for i in out["items"]} == {scene["j1"]["id"]} and out["total"] == 1
    with pytest.raises(BurrowlError):
        ws.overview.entries(kind="judgment", status="superseded")  # 2.0 的旧取值
    # 多选：同一项内是"或"
    assert ids(kind="judgment", status="replaced,current,lapsed") == ids(kind="judgment", status="replaced") | ids(
        kind="judgment", status="current") | ids(kind="judgment", status="lapsed")
    assert ids(kind="judgment", author_kind="ai,human", include_retired=True) == ids(
        kind="judgment", include_retired=True)


def test_graph_nodes_edges_and_center(ws, scene):
    g = ws.overview.graph()
    ids = {n["id"] for n in g["nodes"]}
    assert {scene["j1"]["id"], scene["page"]["id"], scene["pump"]["id"]} <= ids
    cats = {e["category"] for e in g["edges"]}
    assert {"evidence", "replace", "framework"} <= cats
    opp = next(e for e in g["edges"] if e["predicate"] == "opposes")
    assert opp["source"] == scene["j2"]["id"] and opp["target"] == scene["j1"]["id"]
    assert opp["evidence_from"] == scene["j2"]["id"] and opp["count"] == 1
    node = next(n for n in g["nodes"] if n["id"] == scene["j2"]["id"])
    assert node["state"]["validity"] == "replaced"
    hidden = ws.overview.graph(hide_superseded=True)
    assert scene["j2"]["id"] not in {n["id"] for n in hidden["nodes"]}
    centered = ws.overview.graph(center=scene["page"]["id"], hops=1)
    assert scene["j2"]["id"] not in {n["id"] for n in centered["nodes"]}  # 两跳之外
    only = ws.overview.graph(categories=["evidence"], node_types=["judgment"])
    assert only["edges"] and all(e["category"] == "evidence" for e in only["edges"])


def test_graph_aggregates_citations_per_entry(ws, ai, pump_log):
    """设计稿 10 D-22：同一判断依据同一份原件的多个段落只画一条边，count 是段数；证据流画成"证据 → 结论"。"""
    segs = ws.artifacts.read(ai, pump_log["id"])["cite_as"]
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵压力 0.82–0.87 MPa", cites=segs[:3])
    g = ws.overview.graph(node_types=["artifact", "judgment"])
    edges = [e for e in g["edges"] if e["source"] == j["id"]]
    assert len(edges) == 1 and edges[0]["count"] == 3 and edges[0]["evidence_from"] == pump_log["id"]


def test_entry_labels_use_original_text_and_keep_versioned_names(ws, human, ai):
    ctx = Ctx(ws, human, "http")
    art = ws.artifacts.register(human, kind="log", source_class="local", title="泵的测试报告", text="检查记录")
    source = f"{art['id']}#p3-2"
    original = ws.judgments.write(human, kind="conclusion",
                                  text=f"[[{art['id']}]]\n> **在本次测试中，压力为 0.82 MPa。** 后续仍需核对。")["id"]
    newer = ws.versions.correct(human, original, reason="核对读数", text="压力为 0.83 MPa。")["ref"]
    first = f"{original}@1"
    page = ws.frameworks.page_write(human, type="synthesis", slug="report", title="首次汇总", body="报告")
    ws.frameworks.page_write(human, type="synthesis", slug="report", title="更新后的汇总", body="报告")
    event = ws.capture.log(human, "measure.pressure", objects=["2号泵"], output="压力为 0.82 MPa。")
    record = ws.artifacts.promote(human, event_id=event["id"])
    read = ws.artifacts.read(ai, art["id"], "seg:0")["read"]
    history = f"{page['id']}@1"
    absent = f"{page['id']}@99"
    labels = call(ctx, "entry.labels", {"refs": [
        source, first, newer, original, page["id"], history, absent, event["id"], record["id"], read["id"], source,
    ]})
    assert labels == {
        source: "泵的测试报告 · 第 3 页 · 段落 2",
        first: "在本次测试中，压力为 0.82 MPa。 · 第 1 版",
        newer: "压力为 0.83 MPa。",
        original: "压力为 0.83 MPa。",
        page["id"]: "更新后的汇总",
        history: "首次汇总 · 第 1 版",
        absent: None,
        event["id"]: "测量压力 · 2号泵",
        record["id"]: "压力为 0.82 MPa。",
        read["id"]: "读取《泵的测试报告》 · 段落 0",
    }
    assert "entry.labels" not in {s.name for s in visible_ops()}


def test_server_control_is_workbench_only(ws, human):
    names = {s.name for s in visible_ops()}
    assert "server.restart" not in names and "server.stop" not in names and "server.info" in names
    info = call(Ctx(ws=ws, actor=human, channel="cli"), "server.info", {})
    assert "token" not in info and info["version"]
    with pytest.raises(BurrowlError):
        call(Ctx(ws=ws, actor=human, channel="cli"), "server.restart", {})


def test_event_scope_and_run_outputs(ws, human, ai):
    """设计稿 07 D-09、D-10：过程日志默认只列操作日志；运行产物默认不在原件列表里。"""
    ev = ws.capture.log(ai, "exec.python", output="ok")
    out = ws.artifacts.register(ai, kind="dataset", source_class="local", text="{}", title="out.json",
                                produced_by=ev["id"])
    ws.artifacts.promote(ai, event_id=ev["id"])
    ops = ws.overview.entries(kind="event")["items"]
    assert [i["op"] for i in ops] == ["exec.python"]
    assert ops[0]["outputs"] == [out["id"]] and ops[0]["promoted_to"] and ops[0]["session_id"] == ai.session_id
    system = ws.overview.entries(kind="event", scope="system")["items"]
    assert system and all(i["system"] for i in system)
    assert ws.overview.entries(kind="event", scope="all")["total"] == len(ops) + len(system)
    assert out["id"] not in {i["id"] for i in ws.overview.entries(kind="artifact")["items"]}
    assert out["id"] in {i["id"] for i in ws.overview.entries(kind="artifact", include_outputs=True)["items"]}
    with pytest.raises(BurrowlError):
        ws.overview.entries(kind="event", scope="bogus")


def test_stats_runs_ignore_terminal_runs_left_by_a_previous_process(ws, human):
    """服务重启后，旧进程的终端运行库里仍是 running，但本进程没有它的句柄：角标不能算它在运行。"""
    ws.framework.add_run("run_old", "claude", "ses_old", {"terminal": True})
    ws.framework.add_run("run_cli", "claude", "ses_cli", {})
    http = call(Ctx(ws=ws, actor=human, channel="http"), "stats.overview", {})
    assert http["runs"] == {"failed": 1, "running": 1}  # 只有终端运行被重新判定；非终端运行仍按库里的状态
    assert call(Ctx(ws=ws, actor=human, channel="cli"), "stats.overview", {})["runs"] == {"running": 2}
