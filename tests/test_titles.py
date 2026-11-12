"""判断的标题：写入时可带 title，改写沿用，人可更正；没有标题的判断显示正文第一句作推荐标题（2.1.8）。"""
import pytest

from burrowl.core.errors import BurrowlError
from burrowl.interfaces.registry import Ctx, call

LONG = "2号泵出口压力在 0.82 MPa 附近波动，波动范围 ±0.05 MPa。入口阀 V-301 开度 60%，未见气蚀迹象。"


def test_title_is_stored_inherited_and_shown(ws, ai, human):
    j = ws.judgments.write(ai, kind="conclusion", text=LONG, title="  2号泵   出口压力稳定  ")
    assert j["data"]["title"] == "2号泵 出口压力稳定"
    assert ws.overview.entry_label(j["ref"]) == "2号泵 出口压力稳定"
    v2 = ws.judgments.revise(ai, j["id"], text=LONG + "补充。", reason="补充")
    assert v2["data"]["title"] == "2号泵 出口压力稳定"  # 没给就沿用
    v3 = ws.judgments.revise(ai, j["id"], reason="改标题", title="压力稳定")
    assert v3["data"]["title"] == "压力稳定"
    v4 = ws.judgments.revise(ai, j["id"], reason="清掉", title="")
    assert not v4["data"].get("title")


def test_title_length_limit(ws, ai):
    with pytest.raises(BurrowlError) as e:
        ws.judgments.write(ai, kind="conclusion", text="x", title="长" * 61)
    assert e.value.code == "INVALID_ARGUMENT"


def test_human_can_correct_title_only(ws, ai, human):
    j = ws.judgments.write(ai, kind="conclusion", text=LONG)
    new = ws.versions.correct(human, j["id"], reason="加标题", title="2号泵压力稳定")
    assert new["version"] == 2 and new["data"]["title"] == "2号泵压力稳定" and new["data"]["text"] == LONG
    with pytest.raises(BurrowlError):  # 判断仍不能改来源档次等原件字段
        ws.versions.correct(human, j["id"], reason="x", external_tier="web")


def test_list_and_entry_get_give_short_title_and_suggestion(ws, ai, human):
    j = ws.judgments.write(ai, kind="conclusion", text=LONG)
    ctx = Ctx(ws=ws, actor=human, channel="http")
    item = next(i for i in call(ctx, "entries.list", {"kind": "judgment"})["items"] if i["id"] == j["id"])
    assert item["title"] == "2号泵出口压力在 0.82 MPa 附近波动，波动范围 ±0.05 MPa。"
    assert item["preview"].startswith("2号泵出口压力") and len(item["title"]) <= 65
    got = call(ctx, "entry.get", {"id": j["id"]})
    assert got["suggested_title"] == item["title"]
    ws.versions.correct(human, j["id"], reason="采用", title="2号泵压力稳定")
    assert "suggested_title" not in call(ctx, "entry.get", {"id": j["id"]})


def test_mcp_write_accepts_title(ws, ai):
    out = call(Ctx(ws=ws, actor=ai, channel="mcp"), "judgment.write",
               {"kind": "conclusion", "text": LONG, "title": "泵压稳定"})
    assert out["data"]["title"] == "泵压稳定"
