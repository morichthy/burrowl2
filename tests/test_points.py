"""设计稿 15：思路与约束的标签、思路可被佐证、前提、推断不作依据、同源佐证、使用约束随附、要点、消化、
覆盖图"要点已收"、要点体检与孤立的外部结论、关系图的要点节点、旧数据目录。"""
import sqlite3

import pytest

from burrowl.core.errors import BurrowlError
from burrowl.interfaces.ops import Ctx
from burrowl.interfaces.registry import call
from burrowl.services.workspace import Workspace

PAPER = """# 低温下泵的气蚀

在 5 °C 进水条件下，2号泵型号的气蚀余量比常温高 0.4 m。

气蚀余量指泵入口处总水头超出汽化压力水头的部分。

本文只测试了一种叶轮。
"""


@pytest.fixture
def paper(ws, human):
    return ws.artifacts.register(human, kind="literature", source_class="external", text=PAPER,
                                 title="低温气蚀", external_tier="peer_reviewed")


def point(ws, ai, paper, **kw):
    art = paper["id"]
    ws.artifacts.read(ai, art)
    args = dict(title="低温时气蚀余量更高", text="5 °C 进水时气蚀余量比常温高 0.4 m[^1]；气蚀余量的定义见[^2]。",
                cites=[{"ref": f"{art}#seg-1", "marker": "1", "role": "直接依据"},
                       {"ref": f"{art}#seg-2", "marker": "2", "role": "定义"}],
                conditions="5 °C 进水；原文未说明：流量。读过的范围：全文", external_author="Li et al., 2020",
                objects=["2号泵"])
    args.update(kw)
    return ws.frameworks.point_write(ai, **args)


# ---------- T-01：思路、约束与标签 ----------
def test_subkind_rules(ws, human, ai, pump_log):
    with pytest.raises(BurrowlError, match="subkind"):
        ws.judgments.write(ai, kind="thought", text="x")
    with pytest.raises(BurrowlError, match="结论不带 subkind"):
        ws.judgments.write(ai, kind="conclusion", subkind="attempt", text="x")
    with pytest.raises(BurrowlError, match="reopen_condition"):
        ws.judgments.write(ai, kind="thought", subkind="stopped", text="停下排查电机")
    for old in ("process", "normative"):
        with pytest.raises(BurrowlError):
            ws.judgments.write(ai, kind=old, text="x")
    q = ws.judgments.write(ai, kind="thought", subkind="question", text="2号泵为什么压力波动？")
    with pytest.raises(BurrowlError, match="至少连两个条目"):
        ws.judgments.write(ai, kind="thought", subkind="association", text="和3号泵像", cites=[q["id"]])
    assoc = ws.judgments.write(ai, kind="thought", subkind="association", text="2号泵与3号泵的波动可能同源",
                               cites=[pump_log["id"]], relations=[{"rel": "relates", "label": "类比", "target": q["id"]}])
    c = ws.coordinates.of(assoc["id"])
    assert c["kind"] == "thought" and c["subkind"] == "association"
    assert "思路（联想）" in ws.coordinates.note(c)


def test_usage_constraint_needs_target_and_rides_along(ws, human, ai, paper):
    art = paper["id"]
    ws.artifacts.read(ai, art)
    with pytest.raises(BurrowlError, match="targets"):
        ws.judgments.write(ai, kind="constraint", subkind="usage", text="原文只测了一种叶轮")
    caution = ws.judgments.write(
        ai, kind="constraint", subkind="usage", text="这篇只测了一种叶轮，换叶轮时不能直接套用[^1]",
        cites=[{"ref": f"{art}#seg-3", "marker": "1"}], conditions="读过的范围：全文",
        relations=[{"rel": "targets", "target": f"{art}#seg-1"}])
    hits = ws.retrieval.search("气蚀余量", actor=ai)["hits"]
    hit = next(h for h in hits if h["id"] == art)
    assert hit["cautions"][0]["ref"] == caution["ref"]
    ctx = Ctx(ws, ai, "mcp")
    assert call(ctx, "artifact.read", {"artifact_id": art, "locator": "seg-2"})["cautions"][0]["ref"] == caution["ref"]
    # 使用约束不进 constraints_check
    assert ws.retrieval.check_constraints(ai, ["2号泵"])["constraints"] == []
    # 被反驳后不再随附
    ws.judgments.write(human, kind="conclusion", text="附录 B 还测了第二种叶轮", relations=[
        {"rel": "opposes", "target": caution["id"]}], local_observation=True)
    hit = next(h for h in ws.retrieval.search("气蚀余量", actor=ai)["hits"] if h["id"] == art)
    assert "cautions" not in hit


def test_action_constraint_still_checked(ws, human, ai):
    ws.judgments.write(human, kind="constraint", subkind="action", text="检修完成前不要操作3号阀", objects=["3号阀"])
    assert len(ws.retrieval.check_constraints(ai, ["3号阀"])["constraints"]) == 1


# ---------- T-11、T-02：思路可被佐证、前提、推断不作依据 ----------
def test_hypothesis_can_be_supported_and_assumed(ws, human, ai, pump_log):
    seg = f"{pump_log['id']}#seg-1"
    ws.artifacts.read(ai, pump_log["id"])
    hyp = ws.judgments.write(ai, kind="thought", subkind="hypothesis", text="2号泵波动来自入口气蚀")
    q = ws.judgments.write(ai, kind="thought", subkind="question", text="波动从哪来？")
    ok = ws.judgments.write(ai, kind="conclusion", text="出口压力波动 ±0.05 MPa", cites=[seg], conditions="10:00",
                            relations=[{"rel": "supports", "target": hyp["id"]}])
    assert any(m["mark"] == "corroborated" for m in ws.coordinates.of(hyp["id"])["state"]["marks"])
    with pytest.raises(BurrowlError) as e:  # 提问不能被佐证
        ws.judgments.write(ai, kind="conclusion", text="x", cites=[seg], relations=[{"rel": "supports", "target": q["id"]}])
    assert e.value.code == "THOUGHT_NOT_EVIDENCE"
    with pytest.raises(BurrowlError) as e:  # 思路不能佐证别人
        ws.judgments.write(ai, kind="thought", subkind="attempt", text="y", relations=[{"rel": "supports", "target": ok["id"]}])
    assert e.value.code == "THOUGHT_NOT_EVIDENCE"
    plan = ws.judgments.write(ai, kind="constraint", subkind="action", text="在气蚀排除前不要提高转速",
                              objects=["2号泵"], relations=[{"rel": "assumes", "target": hyp["id"]}])
    assert ws.coordinates.sources(plan["id"]) == []  # 前提不是依据
    assert not any(m["mark"] == "premise_changed" for m in ws.coordinates.of(plan["id"])["state"]["marks"])
    ws.judgments.write(human, kind="conclusion", text="入口压力充足，没有气蚀", local_observation=True,
                       relations=[{"rel": "opposes", "target": hyp["id"]}])
    assert any(m["mark"] == "premise_changed" for m in ws.coordinates.of(plan["id"])["state"]["marks"])


def test_inferred_only_conclusion_is_not_evidence(ws, human, ai, pump_log):
    guess = ws.judgments.write(ai, kind="conclusion", text="3号阀可能内漏")
    with pytest.raises(BurrowlError) as e:
        ws.judgments.write(ai, kind="conclusion", text="要换 3号阀", cites=[guess["id"]])
    assert e.value.code == "INFERRED_NOT_EVIDENCE"
    ws.reviews.submit(human, item_id=guess["id"], verdict="confirm", reason="现场看过")
    ws.judgments.write(ai, kind="conclusion", text="要换 3号阀", cites=[guess["id"]])


def test_same_source_support_is_not_corroboration(ws, ai, paper, pump_log):
    art = paper["id"]
    ws.artifacts.read(ai, art)
    a = ws.judgments.write(ai, kind="conclusion", text="低温气蚀余量高 0.4 m", cites=[f"{art}#seg-1"], conditions="5 °C")
    b = ws.judgments.write(ai, kind="conclusion", text="定义同上", cites=[f"{art}#seg-2"], conditions="5 °C",
                           relations=[{"rel": "supports", "target": a["id"]}])
    marks = ws.coordinates.of(a["id"])
    assert not any(m["mark"] == "corroborated" for m in marks["state"]["marks"])
    assert any(m["mark"] == "same_source_support" for m in marks["notes"]["marks"])
    ws.artifacts.read(ai, pump_log["id"])
    ws.judgments.write(ai, kind="conclusion", text="本地也测到余量偏高", cites=[f"{pump_log['id']}#seg-1"],
                       conditions="10:00", relations=[{"rel": "supports", "target": a["id"]}])
    assert any(m["mark"] == "corroborated" for m in ws.coordinates.of(a["id"])["state"]["marks"])
    assert b


def test_external_only_and_conditions_notices(ws, ai, paper):
    art = paper["id"]
    ws.artifacts.read(ai, art)
    j = ws.judgments.write(ai, kind="conclusion", text="低温气蚀余量高 0.4 m", cites=[f"{art}#seg-1"])
    assert "EXTERNAL_ONLY" in j["warning_codes"] and "CONDITIONS_UNSTATED" in j["warning_codes"]


# ---------- T-03、T-04：要点 ----------
def test_point_write_rules(ws, ai, paper, pump_log):
    art = paper["id"]
    with pytest.raises(BurrowlError, match="直接依据"):
        point(ws, ai, paper, cites=[{"ref": f"{art}#seg-1", "marker": "1", "role": "背景"},
                                    {"ref": f"{art}#seg-2", "marker": "2", "role": "定义"}])
    with pytest.raises(BurrowlError, match="原件段落"):
        point(ws, ai, paper, cites=[art])
    with pytest.raises(BurrowlError, match=r"\[\^2\]"):
        point(ws, ai, paper, cites=[{"ref": f"{art}#seg-1", "marker": "1", "role": "直接依据"}])
    with pytest.raises(BurrowlError):
        ws.frameworks.page_write(ai, type="point", title="x", body="y")
    p = point(ws, ai, paper, conditions=None)
    assert "CONDITIONS_UNSTATED" in p["warning_codes"]
    assert p["kind"] == "point" and "不能作为依据" in p["status_note"]
    assert {c["role"] for c in p["cites"]} == {"直接依据", "定义"} and p["cites"][0]["text"]
    # 判断不能引用要点，错误里给出段落
    with pytest.raises(BurrowlError) as e:
        ws.judgments.write(ai, kind="conclusion", text="x", cites=[p["id"]])
    assert e.value.code == "FRAMEWORK_NOT_EVIDENCE"


def test_point_returned_whole_and_source_change(ws, human, ai, paper):
    p = point(ws, ai, paper)
    hit = next(h for h in ws.retrieval.search("气蚀余量", actor=ai)["hits"] if h["id"] == p["id"])
    assert hit["point"]["conditions"].startswith("5 °C") and hit["point"]["external_author"] == "Li et al., 2020"
    assert hit["point"]["cites"][0]["cite_as"].startswith(paper["id"])
    assert all(h["id"] != p["id"] for h in ws.retrieval.search("气蚀余量", mode="explore", actor=ai)["hits"])
    got = ws.frameworks.page_get(p["id"])
    assert got["point"]["text"] == p["text"]
    ws.artifacts.register(human, kind="literature", source_class="external", text=PAPER + "\n补充一段。\n",
                          version_of=paper["id"], external_tier="peer_reviewed")
    assert ws.framework.page(p["id"])["freshness"] == "inputs_changed"
    assert ws.frameworks.point_view(p["id"])["source_changed"]
    # 关系图：要点是单独的节点类型，默认不画
    assert all(n["type"] != "point" for n in ws.overview.graph()["nodes"])
    g = ws.overview.graph(node_types=["artifact", "point"])
    assert any(n["id"] == p["id"] and n["type"] == "point" for n in g["nodes"])
    assert ws.overview.stats()["pages"]["points"] == 1 and ws.overview.stats()["pages"]["total"] == 0


def test_point_not_staled_by_judgments_citing_same_paper(ws, human, ai, paper):
    """D-34：别人写引用同一份原件（同一段落）的判断，不让要点过期；原件退役才过期。"""
    p = point(ws, ai, paper)
    art = paper["id"]
    ws.judgments.write(ai, kind="conclusion", text="低温气蚀余量高 0.4 m", cites=[f"{art}#seg-1", art],
                       conditions="5 °C")
    ws.digest.submit(ai, artifact_id=art, points=[p["id"]])
    assert ws.framework.page(p["id"])["freshness"] == "valid"
    assert not ws.framework.open_decision_for("rederive", p["id"])
    ws.judgments.retire(human, art, reason="换成正式出版版本")
    assert ws.framework.page(p["id"])["freshness"] == "inputs_changed"


def test_point_revise_only_own_session(ws, human, ai, paper):
    from burrowl.core.actor import Actor
    p = point(ws, ai, paper)
    other = Actor("ai:other", "ai", "ses_01JC0000000000000000000009")
    with pytest.raises(BurrowlError):
        point(ws, other, paper, revises=p["id"], reason="改")
    p2 = point(ws, ai, paper, revises=p["id"], reason="凝练", text="5 °C 时余量高 0.4 m[^1]，定义见[^2]。")
    assert p2["ref"].endswith("@2")


# ---------- T-06：消化 ----------
def test_digest_with_points(ws, ai, paper):
    p = point(ws, ai, paper)
    assert ws.digest.pending()["items"][0]["points"] == 1
    out = ws.digest.submit(ai, artifact_id=paper["id"], points=[p["id"]])
    assert out["points"] == [p["id"]] and ws.digest.pending()["total"] == 0
    assert ws.digest.view(paper["id"])["points"] == [p["id"]]
    from burrowl.core.actor import Actor
    with pytest.raises(BurrowlError, match="本会话"):
        ws.digest.submit(Actor("ai:x", "ai", "ses_01JC0000000000000000000008"), artifact_id=paper["id"],
                         points=[p["id"]])


# ---------- T-12：覆盖图 ----------
def test_coverage_pointed_state(ws, ai, paper):
    point(ws, ai, paper)
    rows = ws.coverage.compute(artifact_ids=[paper["id"]])[paper["id"]]["segments"]
    states = {r["anchor"]: r["state"] for r in rows}
    assert states["seg-1"] == "pointed" and states["seg-2"] == "pointed"


# ---------- T-07、T-09：巡检 ----------
def test_point_lint_and_external_orphan(ws, ai, paper, monkeypatch):
    p = point(ws, ai, paper, conditions=None)
    tasks = ws.inspection._point_lint()
    assert tasks and tasks[0]["targets"] == [p["id"]] and "no_conditions" in tasks[0]["detail"]["codes"]
    art = paper["id"]
    j = ws.judgments.write(ai, kind="conclusion", text="低温气蚀余量高 0.4 m", cites=[f"{art}#seg-1"], conditions="5 °C")
    monkeypatch.setitem(ws.config.setdefault("inspection", {}), "orphan_days", 1)
    from burrowl.services import inspection as mod
    monkeypatch.setattr(mod, "_ago", lambda days: "9999")
    assert [t["targets"] for t in ws.inspection._external_orphan()] == [[j["id"]]]


# ---------- I10：旧数据目录 ----------
def test_old_data_directory_is_refused(tmp_path):
    root = tmp_path / "old"
    root.mkdir()
    conn = sqlite3.connect(root / "ledger.sqlite")
    conn.execute("CREATE TABLE schema_migrations (name TEXT)")
    conn.execute("CREATE TABLE relations (id TEXT)")
    conn.execute("CREATE TABLE judgment_versions (kind TEXT NOT NULL CHECK (kind IN ('conclusion','process','normative')))")
    conn.commit()
    conn.close()
    with pytest.raises(BurrowlError) as e:
        Workspace(root)
    assert e.value.code == "OLD_FORMAT"
