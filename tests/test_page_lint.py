"""设计稿 12：页面体检（page_lint）与判断未进综合页（unpaged）。

AC-04（真实 AI 客户端跑一期巡检、再按 burrowl-consolidate 处理）不在这里。
"""
import pytest

from burrowl.core.actor import Actor
from burrowl.services import model_adapters
from burrowl.services.inspection import CHECKS

PAPER = """# 低温下泵的气蚀

在 5 °C 进水条件下，2号泵型号的气蚀余量比常温高 0.4 m。
"""
EVERYTHING = ("2000-01-01T00:00:00.000Z", "2999-01-01T00:00:00.000Z")


@pytest.fixture
def inspector():
    return Actor("ai:inspector", "ai", "ses_01JC0000000000000000000005")


@pytest.fixture
def no_llm(ws, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("准备巡检包时调用了大模型或 agent")
    for name in ("llm_check", "llm_health", "llm_formula"):
        monkeypatch.setattr(model_adapters, name, boom)
    monkeypatch.setattr(ws.agents, "start", boom)


def judgment(ws, ai, pump_log, text, *, objects=("2号泵",), kind="conclusion"):
    ws.artifacts.read(ai, pump_log["id"], "seg-1")
    return ws.judgments.write(ai, kind=kind, subkind={"thought": "attempt", "constraint": "action"}.get(kind), text=text, cites=[f"{pump_log['id']}#seg-1"], objects=list(objects),
                              conditions="10:05 巡检" if kind == "conclusion" else None)


def page(ws, ai, slug, body, inputs, *, summary="摘要"):
    return ws.frameworks.page_write(ai, type="synthesis", title=slug, body=body, inputs=inputs, slug=slug,
                                    summary=summary)


def lint(ws):
    return {t["targets"][0]: t for t in ws.inspection._page_lint()}


def scope(ws):
    return ws.ledger.query("SELECT * FROM judgments ORDER BY created_at")


# ---------- AC-01：页面体检 ----------
def test_page_lint_rules(ws, human, ai, pump_log):
    """没有依据、没摘要、孤立的页报三项；只有外部依据的报一项；有依据、有摘要、有链接的页不生成任务。"""
    j1 = judgment(ws, ai, pump_log, "2号泵出口压力 0.82 MPa")
    j2 = judgment(ws, ai, pump_log, "2号泵入口阀开度 60%")
    paper = ws.artifacts.register(human, kind="literature", source_class="external", text=PAPER, title="低温气蚀")
    ws.artifacts.read(ai, paper["id"], "seg-1")
    ext = ws.judgments.write(ai, kind="conclusion", text="5 °C 进水时气蚀余量比常温高 0.4 m",
                             cites=[f"{paper['id']}#seg-1"], objects=["2号泵"], external_author="Li 2020",
                             conditions="5 °C 进水")
    clean = page(ws, ai, "clean", f"压力 [[{j1['id']}]]", [j1["id"]])
    linked = page(ws, ai, "linked", f"另见 [[{clean['id']}]]，入口阀 [[{j2['id']}]]", [j2["id"]])
    external = page(ws, ai, "external", f"低温 [[{ext['id']}]]，另见 [[{clean['id']}]]", [ext["id"]])
    empty = page(ws, ai, "empty", "还没写依据", [], summary="")
    got = lint(ws)
    assert set(got) == {empty["id"], external["id"]}  # clean 被 linked、external 引用；linked 自己有链接
    assert got[empty["id"]]["detail"]["codes"] == ["no_basis", "isolated", "no_summary"]
    assert got[external["id"]]["detail"]["codes"] == ["external_only"]
    assert linked["id"] not in got and clean["id"] not in got
    task = got[external["id"]]
    assert task["check"] == "page_lint" and task["targets"] == [external["id"]]
    assert task["read"] and all(r.startswith(paper["id"]) and "#" in r for r in task["read"])
    assert task["detail"]["problems"] and "外部" in task["detail"]["basis"]


def test_page_lint_lapsed_inputs_and_stale(ws, human, ai, pump_log):
    """输入被更正出新版本后报"依据已变化"；停在输入已变化的天数超过设置后报"久未重新综合"。"""
    j = judgment(ws, ai, pump_log, "2号泵出口压力 0.82 MPa")
    keep = judgment(ws, ai, pump_log, "入口阀开度 60%")
    body = f"[[{keep['id']}]]"
    old = page(ws, ai, "old", body, [f"{j['id']}@1", keep["id"]])
    page(ws, ai, "hub", f"[[{old['id']}]]", [keep["id"]])  # 让 old 不孤立
    ws.versions.correct(human, j["id"], reason="单位更正", text="2号泵出口压力 0.82 MPa（表压）")
    got = lint(ws)
    assert old["id"] in got
    assert "lapsed_inputs" in got[old["id"]]["detail"]["codes"]
    assert "stale_long" not in got[old["id"]]["detail"]["codes"]  # 刚标记，不算久
    rederive = ws.framework.open_decision_for("rederive", old["id"])
    assert rederive
    with ws.framework.conn:
        ws.framework.conn.execute("UPDATE decisions SET created_at = '2000-01-01T00:00:00.000Z' WHERE id = ?",
                                  (rederive["id"],))
    assert "stale_long" in lint(ws)[old["id"]]["detail"]["codes"]
    ws.config["inspection"]["page_stale_days"] = 100000
    assert "stale_long" not in lint(ws)[old["id"]]["detail"]["codes"]


def test_page_lint_overlap_once_and_limits(ws, ai, pump_log):
    """两页输入高度重合：只在其中一页生成合并提示；page_lint_max 限制页数，0 关闭。"""
    js = [judgment(ws, ai, pump_log, f"2号泵第 {i} 条观察") for i in range(3)]
    first = page(ws, ai, "first", "第一页", [j["id"] for j in js])
    second = page(ws, ai, "second", f"第二页，参见 [[{first['id']}]]", [j["id"] for j in js])
    got = lint(ws)
    overlap = [t for t in got.values() if "overlap" in t["detail"]["codes"]]
    assert len(overlap) == 1 and overlap[0]["targets"][0] in (first["id"], second["id"])
    assert overlap[0]["detail"]["overlap"][0]["ratio"] == 1.0
    # 另一页的 isolated 也报（second 引用了 first，first 被引用——两页都不孤立）
    assert all("isolated" not in t["detail"]["codes"] for t in got.values())
    ws.config["inspection"]["page_lint_max"] = 0
    assert ws.inspection._page_lint() == []


def test_page_lint_ignores_rejected_and_description_pages(ws, ai, pump_log):
    j = judgment(ws, ai, pump_log, "2号泵出口压力 0.82 MPa")
    p = page(ws, ai, "p", "无链接", [j["id"]])
    assert p["id"] in lint(ws)
    ws.framework.set_state("page", p["id"], review="rejected")
    assert p["id"] not in lint(ws)


# ---------- AC-02：判断未进综合页 ----------
def test_unpaged_groups_by_object_with_candidates(ws, ai, pump_log):
    j1 = judgment(ws, ai, pump_log, "2号泵出口压力 0.82 MPa")
    j2 = judgment(ws, ai, pump_log, "2号泵入口阀开度 60%")
    j3 = judgment(ws, ai, pump_log, "咖啡机每周除垢", objects=("咖啡机",))
    judgment(ws, ai, pump_log, "试过加大入口阀，停下", kind="thought")  # 过程判断不算
    p = page(ws, ai, "pump", "泵", [j1["id"]])
    tasks = ws.inspection._unpaged(scope(ws))
    by_obj = {t["detail"]["objects"][0]: t for t in tasks}
    assert set(by_obj) == {"2号泵", "咖啡机"}
    pump = by_obj["2号泵"]
    assert pump["check"] == "unpaged" and pump["targets"] == [j2["id"]]
    assert [c["id"] for c in pump["detail"]["candidate_pages"]] == [p["id"]]  # 同一对象的判断已在这页里
    assert by_obj["咖啡机"]["targets"] == [j3["id"]] and by_obj["咖啡机"]["detail"]["candidate_pages"] == []
    assert pump["read"] and all(r.startswith(pump_log["id"]) and "#" in r for r in pump["read"])
    # 并进页面的输入后不再生成
    page(ws, ai, "pump", "泵", [j1["id"], j2["id"]])
    left = ws.inspection._unpaged(scope(ws))
    assert [t["detail"]["objects"] for t in left] == [["咖啡机"]]
    ws.config["inspection"]["unpaged_max"] = 0
    assert ws.inspection._unpaged(scope(ws)) == []


def test_unpaged_skips_withdrawn_and_counts_any_cited_version(ws, human, ai, pump_log):
    j = judgment(ws, ai, pump_log, "2号泵出口压力 0.82 MPa")
    page(ws, ai, "pinned", "旧版", [f"{j['id']}@1"])
    ws.versions.correct(human, j["id"], reason="更正", text="2号泵出口压力 0.83 MPa")
    assert ws.inspection._unpaged(scope(ws)) == []  # 页面引用的是它的旧版，按条目编号算已吸收


# ---------- 端到端：巡检包、不调用大模型、建议值 ----------
def test_prepare_includes_new_checks_without_llm(ws, human, ai, inspector, pump_log, no_llm):
    assert {"page_lint", "unpaged"} <= set(CHECKS)
    j = judgment(ws, ai, pump_log, "2号泵出口压力 0.82 MPa")
    empty = page(ws, ai, "empty", "没写依据", [], summary="")
    insp = ws.framework.inspection(ws.inspection.prepare(human)["id"])
    counts = insp["data"]["counts"]
    assert counts["page_lint"] == 1 and counts["unpaged"] == 1
    lint_task = next(t for t in insp["data"]["tasks"] if t["check"] == "page_lint")
    unpaged_task = next(t for t in insp["data"]["tasks"] if t["check"] == "unpaged")
    assert lint_task["targets"] == [empty["id"]] and unpaged_task["targets"] == [j["id"]]
    pkg = ws.inspection.get(inspector, inspection_id=insp["id"])
    assert {t["check_label"] for t in pkg["tasks"]} >= {"页面体检", "判断未进综合页"}
    assert {"refresh_page", "merge_pages", "consolidate"} <= set(pkg["suggestions"])
    ws.artifacts.read(inspector, pump_log["id"], "seg-1")
    out = ws.inspection.submit(inspector, inspection_id=insp["id"], task_id=unpaged_task["id"], outcome="issue",
                               summary="这条结论应并进新写的泵房页", cites=[f"{pump_log['id']}#seg-1"],
                               suggestion="consolidate", model="test-model")
    assert out["finding"]["data"]["check"] == "unpaged" and out["finding"]["data"]["suggestion"] == "consolidate"
    out = ws.inspection.submit(inspector, inspection_id=insp["id"], task_id=lint_task["id"], outcome="issue",
                               summary="页面没有依据，需要重新综合", cites=[j["id"]],
                               suggestion="refresh_page", model="test-model")
    assert out["finding"]["data"]["targets"] == [empty["id"]]
    # 有发现的指纹下一期不再生成
    ws.inspection.close(human, inspection_id=insp["id"])
    again = ws.framework.inspection(ws.inspection.prepare(human)["id"])
    assert not [t for t in again["data"]["tasks"] if t["check"] in ("page_lint", "unpaged")]
