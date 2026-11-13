"""人复核与时效联动（D-103）：输入已变化的页面，人确认后回到有效；驳回、未核查不清；撤销后恢复。"""
import pytest


@pytest.fixture
def stale(ws, human, ai):
    """一个依据判断的框架页，判断被人更正后页面变成"输入已变化"，待决策里有"重新综合"。"""
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力 0.82 MPa。")
    page = ws.frameworks.page_write(ai, type="synthesis", slug="pump", title="泵汇总", body=f"见 [[{j['id']}]]",
                                    inputs=[j["id"]])
    ws.versions.correct(human, j["id"], reason="校准读数", text="2号泵出口压力 0.83 MPa。")
    page = ws.framework.page(page["id"])
    assert page["freshness"] == "inputs_changed"
    assert ws.framework.open_decision_for("rederive", page["id"])
    return page


def test_human_confirm_clears_inputs_changed_and_closes_decision(ws, human, stale):
    out = ws.reviews.submit(human, item_id=stale["id"], verdict="confirm", reason="变化很小，核对过，仍然成立")
    page = ws.framework.page(stale["id"])
    assert page["freshness"] == "valid" and page["review"] == "human_reviewed"
    assert page["head_version"] == stale["head_version"]  # 内容不变，没有新版本
    assert ws.framework.open_decision_for("rederive", stale["id"]) is None
    record = next(r for r in ws.reviews.rows(stale["id"]) if r["id"] == out["review_id"])
    assert record["data"]["cleared_freshness"] is True and record["data"]["inputs"]
    hist = ws.reviews.history(stale["id"])
    assert hist["freshness"] == "valid" and any(i["cleared_freshness"] for i in hist["items"])


def test_reject_and_ai_review_do_not_clear(ws, human, ai, stale):
    ws.reviews.submit(human, item_id=stale["id"], verdict="reject", reason="不成立")
    assert ws.framework.page(stale["id"])["freshness"] == "inputs_changed"
    assert ws.framework.open_decision_for("rederive", stale["id"])


def test_unchecked_page_is_not_cleared_by_confirm(ws, human, stale):
    ws.framework.set_state("page", stale["id"], freshness="unchecked")
    ws.reviews.submit(human, item_id=stale["id"], verdict="confirm", reason="看过了")
    assert ws.framework.page(stale["id"])["freshness"] == "unchecked"


def test_revoke_restores_inputs_changed_and_reopens_decision(ws, human, stale):
    out = ws.reviews.submit(human, item_id=stale["id"], verdict="confirm", reason="核对过")
    ws.reviews.revoke(human, item_id=stale["id"], record_ids=[out["review_id"]], reason="还是不放心")
    page = ws.framework.page(stale["id"])
    assert page["freshness"] == "inputs_changed" and page["review"] != "human_reviewed"
    assert ws.framework.open_decision_for("rederive", stale["id"])


def test_new_input_change_after_confirm_marks_stale_again(ws, human, ai, stale):
    ws.reviews.submit(human, item_id=stale["id"], verdict="confirm", reason="核对过")
    assert ws.framework.page(stale["id"])["freshness"] == "valid"
    j = next(i for i in ws.framework.inputs_of("page", stale["id"], stale["head_version"]))
    ws.versions.correct(human, j.split("@")[0], reason="再校准", text="2号泵出口压力 0.84 MPa。")
    assert ws.framework.page(stale["id"])["freshness"] == "inputs_changed"


def test_confirm_on_valid_page_changes_nothing_else(ws, human, ai):
    page = ws.frameworks.page_write(ai, type="synthesis", slug="ok", title="没变的页", body="内容")
    out = ws.reviews.submit(human, item_id=page["id"], verdict="confirm", reason="看过")
    assert ws.framework.page(page["id"])["freshness"] == "valid"
    record = next(r for r in ws.reviews.rows(page["id"]) if r["id"] == out["review_id"])
    assert "cleared_freshness" not in record["data"]
