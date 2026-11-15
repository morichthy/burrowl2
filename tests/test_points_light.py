"""设计稿 17：要点是轻判断——跨来源、经验标签、关联、先查后写与合并、归档、活跃度、检索上限、传播、巡检。"""
import pytest

from burrowl.core.actor import Actor
from burrowl.core.errors import BurrowlError

A_TEXT = "# 甲\n\n低温 5 °C 进水时 2号泵的气蚀余量比常温高 0.4 m。\n\n只测了一种叶轮。\n"
B_TEXT = "# 乙\n\n冬季运行时 3号泵入口压力需要提高约 0.03 MPa 才不出现气蚀噪声。\n"
OTHER_AI = Actor("ai:other", "ai", "ses_01JC0000000000000000000009")


@pytest.fixture
def arts(ws, human, ai):
    a = ws.artifacts.register(human, kind="literature", source_class="external", text=A_TEXT, title="甲",
                              external_tier="peer_reviewed")["id"]
    b = ws.artifacts.register(human, kind="log", source_class="local", text=B_TEXT, title="乙")["id"]
    ws.artifacts.read(ai, a)
    ws.artifacts.read(ai, b)
    return a, b


def digest_point(ws, ai, a, **kw):
    args = dict(title="2号泵型号低温进水时气蚀余量比常温高 0.4 m", text="5 °C 进水时 2号泵型号的气蚀余量比常温高 0.4 m[^1]。",
                cites=[{"ref": f"{a}#seg-1", "marker": "1"}], conditions="5 °C 进水；原文未说明：流量",
                external_author="甲", objects=["2号泵"])
    args.update(kw)
    return ws.frameworks.point_write(ai, **args)


def test_lesson_across_sources_and_links(ws, ai, arts):
    a, b = arts
    p1 = digest_point(ws, ai, a)
    j = ws.judgments.write(ai, kind="conclusion", text="3号泵冬季入口压力提高 0.03 MPa 后气蚀噪声消失[^1]",
                           cites=[{"ref": f"{b}#seg-1", "marker": "1"}], conditions="冬季运行")
    lesson = ws.frameworks.point_write(
        ai, subkind="lesson", title="离心泵低温进水时要预留更大的气蚀余量",
        text="低温进水时离心泵需要更大的气蚀余量：文献报告 2号泵型号高 0.4 m[^1]，本地 3号泵冬季要提高入口压力[^2]。",
        cites=[{"ref": p1["id"], "marker": "1"}, {"ref": j["id"], "marker": "2"}],
        links=[{"rel": "refines", "target": p1["id"], "why": "把单个型号的结果推广到低温运行"}])
    assert lesson["subkind"] == "lesson" and "LESSON_SINGLE_SOURCE" not in lesson["warning_codes"]
    assert {c["cite_as"].split("@")[0] for c in lesson["cites"]} == {p1["id"], j["id"]}
    assert lesson["links"][0]["rel"] == "refines" and lesson["links"][0]["other"] == p1["id"]
    assert lesson["use"]["sources"] == 2 and lesson["use"]["links"] == 1
    single = ws.frameworks.point_write(ai, subkind="lesson", title="只有一处", text="只引了一处",
                                       cites=[f"{a}#seg-1"])
    assert "LESSON_SINGLE_SOURCE" in single["warning_codes"]
    g = ws.overview.graph(node_types=["artifact", "judgment", "point"])
    edges = {(e["source"], e["target"], e["rel"]) for e in g["edges"]}
    assert (lesson["id"], p1["id"], "refines") in edges and (lesson["id"], j["id"], "derived_from") in edges
    assert next(n for n in g["nodes"] if n["id"] == lesson["id"])["subkind"] == "lesson"
    with pytest.raises(BurrowlError, match="links 的 rel"):
        digest_point(ws, ai, a, links=[{"rel": "supports", "target": p1["id"]}])


def test_merge_then_archive(ws, human, ai, arts):
    a, b = arts
    p1 = digest_point(ws, ai, a)
    p2 = digest_point(ws, OTHER_AI, a, title="2号泵低温时气蚀余量高 0.4 m")
    assert "SIMILAR_POINT" in p2["warning_codes"] and p2["similar"][0]["id"] == p1["id"]
    merged = ws.frameworks.point_write(OTHER_AI, revises=p1["id"], reason="并入同一结果的另一处来源",
                                       add_cites=[f"{b}#seg-1"])
    assert merged["ref"].endswith("@2") and len(merged["cites"]) == 2 and merged["text"] == p1["text"]
    with pytest.raises(BurrowlError, match="合并时"):
        ws.frameworks.point_archive(OTHER_AI, p2["id"], reason="没用")
    ws.frameworks.point_archive(OTHER_AI, p2["id"], reason="重复", merged_into=p1["id"])
    assert "已归档" in ws.frameworks.point_view(p2["id"])["status_note"]
    assert p2["id"] not in {h["id"] for h in ws.retrieval.search("气蚀余量 0.4", limit=20)["hits"]}
    assert p2["id"] not in {n["id"] for n in ws.overview.graph(node_types=["artifact", "point"])["nodes"]}
    assert ws.overview.stats()["pages"]["points"] == 1
    with pytest.raises(BurrowlError):
        ws.frameworks.point_restore(ai, p2["id"], reason="x")
    ws.frameworks.point_restore(human, p2["id"], reason="其实不同")
    assert ws.overview.stats()["pages"]["points"] == 2


def test_human_points_only_humans_change(ws, human, ai, arts):
    a, _ = arts
    p = digest_point(ws, human, a)
    with pytest.raises(BurrowlError, match="只有人能改"):
        ws.frameworks.point_write(ai, revises=p["id"], reason="x", add_cites=[f"{a}#seg-2"])
    q = digest_point(ws, ai, a, title="另一条")
    with pytest.raises(BurrowlError, match="合并时"):
        ws.frameworks.point_archive(ai, p["id"], reason="重复", merged_into=q["id"])


def test_point_citing_judgment_follows_its_changes(ws, ai, arts):
    _, b = arts
    j = ws.judgments.write(ai, kind="conclusion", text="3号泵冬季要提高入口压力", cites=[f"{b}#seg-1"],
                           conditions="冬季")
    p = ws.frameworks.point_write(ai, title="3号泵冬季要提高入口压力", text="见判断", cites=[j["id"]])
    assert ws.framework.page(p["id"])["freshness"] == "valid"
    ws.judgments.revise(ai, j["id"], text="3号泵冬季入口压力要提高 0.03 MPa", reason="补数值")
    assert ws.framework.page(p["id"])["freshness"] == "inputs_changed"


def test_search_caps_points(ws, ai, arts):
    a, _ = arts
    for i in range(4):
        digest_point(ws, ai, a, title=f"气蚀余量第 {i} 条")
    ws.config.setdefault("retrieval", {})["points_max"] = 2
    hits = ws.retrieval.search("气蚀余量", limit=20)["hits"]
    assert sum(1 for h in hits if h["id"].startswith("pg_")) == 2


def test_inspection_idle_and_dup(ws, ai, arts):
    a, _ = arts
    p1 = digest_point(ws, ai, a)
    p2 = digest_point(ws, OTHER_AI, a, title="2号泵低温时气蚀余量高 0.4 m")
    dups = ws.inspection._point_dups()
    assert len(dups) == 1 and set(dups[0]["targets"]) == {p1["id"], p2["id"]}
    ws.inspection.settings()  # 默认 30 天：刚写的不算闲置
    assert ws.inspection._point_idle() == []
    ws.config.setdefault("inspection", {})["point_idle_days"] = 1
    ws.framework.conn.execute("UPDATE pages SET created_at = '2020-01-01T00:00:00.000Z'")
    idle = {t["targets"][0] for t in ws.inspection._point_idle()}
    assert {p1["id"], p2["id"]} <= idle
    ws.frameworks.edge_add(ai, rel="related", src_id=p1["id"], dst_id=p2["id"], reason="同一结果")
    assert ws.inspection._point_dups() == []
    assert p1["id"] not in {t["targets"][0] for t in ws.inspection._point_idle()}
