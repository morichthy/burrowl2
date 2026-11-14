"""撤销到某个时刻与恢复（设计稿 14 D-10 至 D-17）。"""
import time

import pytest

from burrowl.core.errors import BurrowlError


def _pause():
    time.sleep(0.005)  # 时间戳精确到毫秒：让前后两次写入的时间一定不同


def test_undo_to_activity_removes_later_writes_and_restore_puts_them_back(ws, human, ai, pump_log):
    seg1 = f"{pump_log['id']}#seg-1"
    ws.artifacts.read(ai, pump_log["id"], "seg-1")
    keep = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力 0.82 MPa", cites=[seg1])
    _pause()
    bad = ws.judgments.write(ai, kind="conclusion", text="AI 写错的结论", cites=[seg1])
    _pause()
    ws.judgments.revise(human, keep["id"], title="改了标题", reason="改标题")
    extra = ws.artifacts.register(ai, kind="log", source_class="local", text="之后登记的原件", title="之后")
    page = ws.frameworks.page_write(ai, type="synthesis", title="综合", body=f"见 [[{keep['id']}]]",
                                    inputs=[keep["id"]])
    at = next(i["at"] for i in ws.overview.activity() if i["id"] == f"{bad['id']}@1")

    with pytest.raises(BurrowlError):  # 只有人能撤销
        ws.undo.apply(ai, at, confirm="x")
    pv = ws.undo.preview(at)
    ids = {e["id"] for e in pv["entries"]}
    assert {bad["id"], keep["id"], extra["id"]} <= ids and pump_log["id"] not in ids
    with pytest.raises(BurrowlError) as e:
        ws.undo.apply(human, at, confirm="wrong")
    assert e.value.code == "CONFLICT"
    res = ws.undo.apply(human, at, confirm=pv["confirm"], reason="AI 误写")

    assert ws.ledger.get(bad["id"]) is None and ws.ledger.get(extra["id"]) is None
    kept = ws.ledger.get(keep["id"])
    assert kept["head_version"] == 1 and "title" not in kept["data"]
    assert ws.framework.page(page["id"]) is None
    assert all(h["id"] != bad["id"] for h in ws.retrieval.search("AI 写错的结论")["hits"])
    assert ws.ledger.get(pump_log["id"]) is not None
    feed = ws.overview.activity()
    assert feed[0]["kind"] == "undo.apply" and feed[0]["undo_id"] == res["undo_id"]
    # 撤销后照常写入，图与坐标不出错
    again = ws.judgments.write(ai, kind="conclusion", text="撤销后重写", cites=[seg1])
    assert ws.coordinates.of(again["id"])

    restored = ws.undo.restore(human, res["undo_id"])
    assert restored["restored"]
    assert ws.ledger.get(bad["id"]) is not None and ws.ledger.get(extra["id"]) is not None
    assert ws.ledger.get(keep["id"])["head_version"] == 2
    assert ws.framework.page(page["id"]) is not None
    with pytest.raises(BurrowlError):  # 只能恢复一次
        ws.undo.restore(human, res["undo_id"])
    assert ws.undo.packages()[0]["restored"]
    applied = next(i for i in ws.overview.activity() if i["kind"] == "undo.apply")
    assert applied["restored"] is True  # 首页不再显示"恢复"按钮


def test_restore_refuses_when_same_version_was_written_again(ws, human, ai, pump_log):
    j = ws.judgments.write(ai, kind="conclusion", text="第一版")
    _pause()
    ws.judgments.revise(ai, j["id"], text="第二版", reason="改")
    at = next(i["at"] for i in ws.overview.activity() if i["id"] == f"{j['id']}@2")
    pv = ws.undo.preview(at)
    res = ws.undo.apply(human, at, confirm=pv["confirm"])
    ws.judgments.revise(ai, j["id"], text="撤销后另写的第二版", reason="重写")
    with pytest.raises(BurrowlError) as e:
        ws.undo.restore(human, res["undo_id"])
    assert e.value.code == "CONFLICT"


def test_page_version_rolls_back_and_is_marked_changed(ws, human, ai):
    j = ws.judgments.write(ai, kind="conclusion", text="结论")
    page = ws.frameworks.page_write(ai, type="synthesis", title="综合", body=f"[[{j['id']}]]", inputs=[j["id"]])
    _pause()
    j2 = ws.judgments.write(ai, kind="conclusion", text="后来的结论")
    ws.frameworks.page_write(ai, type="synthesis", title="综合", slug=page["slug"],
                             body=f"[[{j['id']}]] [[{j2['id']}]]", inputs=[j["id"], j2["id"]])
    at = next(i["at"] for i in ws.overview.activity() if i["id"] == f"{j2['id']}@1")
    ws.undo.apply(human, at, confirm=ws.undo.preview(at)["confirm"])
    p = ws.framework.page(page["id"])
    assert p["head_version"] == 1 and p["freshness"] == "inputs_changed"
