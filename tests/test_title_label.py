"""判断的标题是标签（D-101）：改标题只追加一条标题记录，不产生新版本、不传播变化、保留历史。"""
import pytest

from burrowl.core.errors import BurrowlError


@pytest.fixture
def cited(ws, human, ai):
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力 0.82 MPa，在额定范围内。")
    page = ws.frameworks.page_write(human, type="synthesis", slug="pump", title="泵汇总", body=f"见 [[{j['id']}]]",
                                    inputs=[j["id"]])
    return j, page


def test_set_title_does_not_create_version_or_propagate(ws, human, cited):
    j, page = cited
    before_decisions = len(ws.framework.open_decisions()) if hasattr(ws.framework, "open_decisions") else None
    out = ws.judgments.set_title(human, j["id"], "泵压在额定范围内")
    assert out["changed"] and out["title"] == "泵压在额定范围内"
    head = ws.ledger.get(j["id"])
    assert head["head_version"] == 1 and head["data"]["title"] == "泵压在额定范围内"
    assert ws.ledger.get(f"{j['id']}@1")["data"]["title"] == "泵压在额定范围内"  # 标题不随版本固定
    assert ws.framework.page(page["id"])["freshness"] != "inputs_changed"
    if before_decisions is not None:
        assert len(ws.framework.open_decisions()) == before_decisions
    # 账本里的第 1 版原文没有被改
    stored = ws.ledger_db.execute("SELECT data FROM judgment_versions WHERE id = ?", (j["id"],)).fetchone()[0]
    assert "泵压在额定范围内" not in stored


def test_title_history_is_kept_and_can_be_cleared(ws, human, cited):
    j, _ = cited
    ws.judgments.set_title(human, j["id"], "第一个标题")
    ws.judgments.set_title(human, j["id"], "第二个标题")
    assert not ws.judgments.set_title(human, j["id"], "第二个标题")["changed"]
    rows = ws.ledger_db.execute("SELECT title FROM judgment_titles WHERE judgment_id = ? ORDER BY rowid",
                                (j["id"],)).fetchall()
    assert [r[0] for r in rows] == ["第一个标题", "第二个标题"]
    ws.judgments.set_title(human, j["id"], "")
    assert "title" not in ws.ledger.get(j["id"])["data"]


def test_only_humans_set_titles_and_only_on_judgments(ws, human, ai, cited):
    j, page = cited
    with pytest.raises(BurrowlError):
        ws.judgments.set_title(ai, j["id"], "AI 想改")
    with pytest.raises(BurrowlError):
        ws.judgments.set_title(human, page["id"], "不是判断")


def test_correct_with_only_title_is_not_a_new_version(ws, human, cited):
    j, page = cited
    out = ws.versions.correct(human, j["id"], reason="采用推荐标题", title="一句话标题")
    assert out["version_changed"] is False and out["version"] == 1
    assert ws.ledger.get(j["id"])["head_version"] == 1
    # 同时改了正文：产生新版本，标题仍走标题记录，新版本沿用最新标题
    new = ws.versions.correct(human, j["id"], reason="校准", text="2号泵出口压力 0.83 MPa。", title="新的标题")
    assert new["version"] == 2
    assert ws.ledger.get(j["id"])["data"]["title"] == "新的标题"
    assert ws.framework.page(page["id"])["freshness"] == "inputs_changed"  # 对照：改了正文才会让框架页过期
    assert ws.ledger.get(f"{j['id']}@1")["data"]["title"] == "新的标题"
