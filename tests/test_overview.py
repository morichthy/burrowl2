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
    ws.judgments.amend(human, mode="retraction", target=j2["id"], reason="不对")
    page = ws.frameworks.page_write(human, type="entity", title="2号泵", body=f"见 [[{j1['id']}]]",
                                    subject_id=pump["id"])
    return {"pump": pump, "j1": j1, "j2": j2, "page": page, "art": pump_log}


def test_activity_newest_first(ws, scene):
    items = ws.overview.activity(10)
    assert items[0]["at"] >= items[-1]["at"]
    kinds = {i["kind"] for i in items}
    assert {"artifact", "judgment.conclusion", "judgment.retraction", "page"} <= kinds


def test_stats_counts(ws, scene):
    s = ws.overview.stats()
    j = s["judgments"]
    assert j["total"] == 3 and j["superseded"] == 1 and j["opposed"] == 1
    assert j["local_only"] == 1 and j["by_author"]["human"] == 1
    assert s["pages"]["freshness"] == {"inputs_changed": 1} or s["pages"]["total"] == 1


def test_entries_filters(ws, scene):
    out = ws.overview.entries(kind="judgment", author_kind="ai")
    assert out["total"] == 2 and all(i["author_kind"] == "ai" for i in out["items"])
    assert ws.overview.entries(kind="judgment", judgment_kind="retraction")["total"] == 1
    assert ws.overview.entries(kind="judgment", source_class="local")["total"] == 1
    assert ws.overview.entries(kind="judgment", object="2号泵")["total"] == 3  # 撤回继承了目标的对象
    with pytest.raises(BurrowlError):
        ws.overview.entries(kind="page")


def test_graph_nodes_edges_and_center(ws, scene):
    g = ws.overview.graph()
    ids = {n["id"] for n in g["nodes"]}
    assert {scene["j1"]["id"], scene["page"]["id"], scene["pump"]["id"]} <= ids
    cats = {e["category"] for e in g["edges"]}
    assert {"conflict", "supersede", "derived"} <= cats
    assert next(n for n in g["nodes"] if n["id"] == scene["j2"]["id"])["superseded"]
    hidden = ws.overview.graph(hide_superseded=True)
    assert scene["j2"]["id"] not in {n["id"] for n in hidden["nodes"]}
    centered = ws.overview.graph(center=scene["page"]["id"], hops=1)
    assert scene["j2"]["id"] not in {n["id"] for n in centered["nodes"]}  # 两跳之外
    only = ws.overview.graph(categories=["conflict"], node_types=["judgment"])
    assert all(e["category"] == "conflict" for e in only["edges"])


def test_server_control_is_workbench_only(ws, human):
    names = {s.name for s in visible_ops()}
    assert "server.restart" not in names and "server.stop" not in names and "server.info" in names
    info = call(Ctx(ws=ws, actor=human, channel="cli"), "server.info", {})
    assert "token" not in info and info["version"]
    with pytest.raises(BurrowlError):
        call(Ctx(ws=ws, actor=human, channel="cli"), "server.restart", {})
