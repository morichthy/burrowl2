"""阅读会话（设计稿 13）：读了什么由读取记录与检索命中算出，目的、认知、handoff 是 AI 的会话内笔记。"""
import pytest

from burrowl.core.errors import BurrowlError
from burrowl.interfaces.registry import Ctx, call


def _ctx(ws, actor):
    return Ctx(ws=ws, actor=actor, channel="mcp")


def test_reading_view_collects_reads_hits_and_notes(ws, ai, pump_log):
    ctx = _ctx(ws, ai)
    call(ctx, "search", {"query": "2号泵 出口压力"})
    read = call(ctx, "artifact.read", {"artifact_id": pump_log["id"]})
    j = call(ctx, "judgment.write", {"kind": "conclusion", "text": "2号泵出口压力 0.82 MPa",
                                     "cites": read["cite_as"][:1]})
    call(ctx, "reading.note", {"purpose": "核对泵压", "findings": [{"text": "出口压力 0.82", "refs": [j["id"]]}]})
    call(ctx, "reading.note", {"handoff": "# 交接\n下一步看入口阀"})

    sessions = call(ctx, "reading.list", {})
    assert [s["session_id"] for s in sessions] == [ai.session_id]
    s = sessions[0]
    assert (s["purpose"], s["findings"], s["has_handoff"]) == ("核对泵压", 1, True)
    assert s["searches"] == 1 and s["artifacts_read"] == 1 and s["notes"] == 2

    view = call(ctx, "reading.get", {})
    assert view["purpose"] == "核对泵压"  # 第二次只更新 handoff，目的沿用
    assert view["handoff"].startswith("# 交接")
    assert [r["id"] for r in view["read"]] == [pump_log["id"]]
    assert any(h["id"] == pump_log["id"] and h["read"] for h in view["returned"])
    assert [w["id"] for w in view["written"]] == [j["id"]]
    assert view["refs_in_findings"] == [j["id"]]
    assert len(view["notes"]) == 2


def test_returned_but_not_read_is_distinguished(ws, ai, pump_log):
    ctx = _ctx(ws, ai)
    call(ctx, "search", {"query": "2号泵"})
    view = call(ctx, "reading.get", {})
    assert view["read"] == []
    assert view["returned"] and not any(h["read"] for h in view["returned"])


def test_note_rules(ws, ai, human):
    with pytest.raises(BurrowlError) as e:
        ws.reading.note(human, purpose="x")
    assert e.value.code == "FORBIDDEN"
    with pytest.raises(BurrowlError) as e:
        ws.reading.note(ai)
    assert e.value.code == "INVALID_ARGUMENT"
    with pytest.raises(BurrowlError) as e:
        ws.reading.note(ai, findings=[{"text": "x", "refs": ["art_nope"]}])
    assert e.value.code == "NOT_FOUND"
    assert ws.reading.sessions() == []


def test_long_handoff_is_kept_whole(ws, ai):
    text = "交接内容。" * 2000
    ws.reading.note(ai, handoff=text, handoff_source="D:/work/HANDOFF.md")
    view = ws.reading.get(ai.session_id)
    assert view["handoff"] == text and view["handoff_source"] == "D:/work/HANDOFF.md"


def test_search_nudges_until_note_then_again_after_more_use(ws, ai, pump_log):
    ctx = _ctx(ws, ai)
    first = call(ctx, "search", {"query": "2号泵"})
    assert any("reading_note" in h for h in first["hints"])
    call(ctx, "reading.note", {"purpose": "核对泵压"})
    assert not any("reading_note" in h for h in call(ctx, "search", {"query": "2号泵"})["hints"])
    for _ in range(4):
        out = call(ctx, "search", {"query": "2号泵"})
    assert any("reading_note" in h for h in out["hints"])


def test_human_search_gets_no_nudge_and_no_session(ws, human, pump_log):
    out = call(Ctx(ws=ws, actor=human, channel="http"), "search", {"query": "2号泵"})
    assert not any("reading_note" in h for h in out["hints"])
    assert ws.reading.sessions() == []


def test_unknown_session(ws):
    with pytest.raises(BurrowlError) as e:
        ws.reading.get("ses_none")
    assert e.value.code == "NOT_FOUND"


def test_handoff_file_is_read_live_but_only_the_registered_path(ws, ai, tmp_path):
    ctx = _ctx(ws, ai)
    http = Ctx(ws=ws, actor=ai, channel="http")
    f = tmp_path / "HANDOFF.md"
    f.write_text("# v1", encoding="utf-8")
    call(ctx, "reading.note", {"purpose": "x", "handoff": "# 快照", "handoff_source": str(f)})
    assert call(http, "reading.handoff_file", {"session_id": ai.session_id})["text"] == "# v1"
    f.write_text("# v2 已更新", encoding="utf-8")  # 文件改了，实时读到新内容
    live = call(http, "reading.handoff_file", {"session_id": ai.session_id})
    assert live["available"] and live["text"] == "# v2 已更新"
    assert call(http, "reading.get", {"session_id": ai.session_id})["handoff"] == "# 快照"  # 快照不变
    with pytest.raises(BurrowlError) as e:  # MCP 不能用它读本机文件
        call(ctx, "reading.handoff_file", {"session_id": ai.session_id})
    assert e.value.code == "FORBIDDEN"


@pytest.mark.parametrize("name,why", [("secret.pem", "只读"), ("missing.md", "不存在"), ("rel", "绝对路径")])
def test_handoff_file_refuses_unsafe_or_missing(ws, ai, tmp_path, name, why):
    (tmp_path / "secret.pem").write_text("KEY", encoding="utf-8")
    source = name if name == "rel" else str(tmp_path / name)
    ws.reading.note(ai, purpose="x", handoff_source=source)
    out = ws.reading.handoff_file(ai.session_id)
    assert out["available"] is False and why in out["reason"] and "text" not in out


def test_handoff_file_size_limit_and_no_source(ws, ai, tmp_path):
    big = tmp_path / "big.md"
    big.write_bytes(b"a" * (512 * 1024 + 1))
    ws.reading.note(ai, purpose="x")
    assert ws.reading.handoff_file(ai.session_id)["available"] is False
    ws.reading.note(ai, handoff_source=str(big), purpose="y")
    assert "512 KB" in ws.reading.handoff_file(ai.session_id)["reason"]

