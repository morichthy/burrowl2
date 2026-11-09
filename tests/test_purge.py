"""原件的替换与删除、依赖失效（设计稿 07 AC-02 至 AC-05）。"""
import sqlite3

import pytest

from burrowl.core.errors import BurrowlError
from burrowl.interfaces.registry import Ctx, call

OLD = "Adam uses moment estimates.\n\nBias correction fixes the start."


@pytest.fixture
def setup(ws, human, ai):
    """一份要退役的文本原件 old，和引用它的各种判断：
    only_read 只经读取记录引用它；only_seg 只引用它的段落；dep 只依赖 only_seg；
    multi 同时引用它和一条本地事实记录；proc 是没有依据的过程内容。"""
    old = ws.artifacts.register(ai, kind="literature", source_class="external", title="旧文本", text=OLD)
    rd = ws.artifacts.read(ai, old["id"], "seg-0")["read"]
    ws.artifacts.read(ai, old["id"], "seg-1")
    ev = ws.capture.log(ai, "exec.python", output="loss 0.48")
    rec = ws.artifacts.promote(ai, event_id=ev["id"], method="运行脚本")
    j = {
        "only_read": ws.judgments.write(ai, kind="conclusion", text="Adam 用矩估计", cites=[rd["id"]]),
        "only_seg": ws.judgments.write(ai, kind="conclusion", text="偏差修正", cites=[f"{old['id']}#seg-1"]),
        "multi": ws.judgments.write(ai, kind="conclusion", text="本地损失 0.48，文献说用矩估计",
                                    cites=[f"{old['id']}#seg-0", rec["id"]]),
        "proc": ws.judgments.write(ai, kind="process", text="还没在真实数据上试"),
    }
    j["dep"] = ws.judgments.write(ai, kind="conclusion", text="因此开头的步子要小",
                                  relations=[{"rel": "depends_on", "target": j["only_seg"]["id"]}])
    from_old = ws.artifacts.promote(ai, artifact_id=old["id"], locator="seg-0", method="摘录")
    ids = {k: v["id"] for k, v in j.items()}
    return old, ids, from_old["id"], rec["id"]


def listed(ws, kind="judgment", **kw):
    return {i["id"] for i in ws.overview.entries(kind=kind, limit=200, **kw)["items"]}


def test_retire_hides_single_dependency_and_marks_multi(ws, human, setup):
    """AC-02：只引用退役原件的（含经读取记录、依赖关系、从它升级的事实记录）隐藏；多依赖的标注；撤销后复原。"""
    old, j, from_old, rec = setup
    ws.judgments.retire(human, old["id"], reason="不满意这份导入")
    hidden = ws.purge.hidden_ids()
    assert {j["only_read"], j["only_seg"], j["dep"], from_old} <= hidden
    assert j["multi"] not in hidden and j["proc"] not in hidden and rec not in hidden
    shown = listed(ws)
    assert j["only_read"] not in shown and j["dep"] not in shown and j["multi"] in shown and j["proc"] in shown
    assert j["only_read"] in listed(ws, include_retired=True)
    assert from_old not in listed(ws, kind="record")
    c = ws.retrieval.coordinates(j["multi"])
    assert c["lapsed_basis"][0]["reason"] == "retired" and c["complete"] is False
    assert ws.retrieval.coordinates(j["only_seg"])["hidden"]
    assert j["only_seg"] not in {h["id"] for h in ws.retrieval.search("偏差修正")["hits"]}
    assert ws.overview.stats()["judgments"]["total"] == 2  # multi、proc
    ws.judgments.restore(human, old["id"], reason="还要用")
    assert not ws.purge.hidden_ids() and j["only_seg"] in listed(ws)


def test_citing_through_read_of_retired_artifact_warns(ws, human, ai, setup):
    """AC-05：经读取记录引用退役原件也返回 RETIRED_CITATION。"""
    old, *_ = setup
    rd = ws.artifacts.read(ai, old["id"], "seg-0")["read"]
    ws.judgments.retire(human, old["id"], reason="重复")
    out = ws.judgments.write(ai, kind="conclusion", text="Adam 用矩估计（再写一次）", cites=[rd["id"]])
    assert "RETIRED_CITATION" in out["warning_codes"]


def test_replace_compares_fingerprints_and_restores(ws, human, ai, setup):
    """AC-03：替换后段落都在的照常有效、恢复显示；段落变了的进入待复核；只有人能替换，未退役的不能替换。"""
    old, j, _, _ = setup
    new = ws.artifacts.register(ai, kind="literature", source_class="external", title="新文本",
                                text="Adam uses moment estimates.\n\nBias correction is applied at every step.")
    with pytest.raises(BurrowlError) as e:
        ws.judgments.replace(human, old["id"], replacement=new["id"], reason="x")
    assert e.value.code == "NOT_RETIRED"
    ws.judgments.retire(human, old["id"], reason="换成新文本")
    with pytest.raises(BurrowlError) as e:
        call(Ctx(ws=ws, actor=ai, channel="mcp"), "artifact.replace",
             {"artifact_id": old["id"], "replacement": new["id"], "reason": "x"})
    assert e.value.code == "FORBIDDEN"
    page = ws.frameworks.page_write(human, type="synthesis", title="Adam", body="见判断", inputs=[j["multi"]])
    out = ws.judgments.replace(human, old["id"], replacement=new["id"], reason="换成新文本")
    assert out["id"].startswith("rpl_") and ws.judgments.replacement_of(old["id"]) == new["id"]
    assert not ws.purge.hidden_ids()
    assert "lapsed_basis" not in ws.retrieval.coordinates(j["multi"])
    recheck = {r["judgment_id"] for r in ws.extraction.needs_recheck()}
    assert j["only_seg"] in recheck  # 第 2 段变了
    assert j["only_read"] not in recheck and j["multi"] not in recheck  # 第 1 段没变
    assert ws.framework.page(page["id"])["freshness"] == "inputs_changed"


def test_delete_requires_retirement_preview_and_human(ws, human, ai, setup):
    old, *_ = setup
    with pytest.raises(BurrowlError) as e:
        ws.purge.preview(old["id"])
    assert e.value.code == "NOT_RETIRED"
    ws.judgments.retire(human, old["id"], reason="错误导入")
    preview = ws.purge.preview(old["id"])
    with pytest.raises(BurrowlError) as e:
        ws.purge.delete(ai, old["id"], confirm=preview["confirm"])
    assert e.value.code == "FORBIDDEN"
    with pytest.raises(BurrowlError) as e:
        ws.purge.delete(human, old["id"], confirm="wrong")
    assert e.value.code == "CONFLICT"
    from burrowl.interfaces.mcp import visible_ops  # MCP 里没有删除与替换
    names = {s.name for s in visible_ops()}
    assert "artifact.delete" not in names and "artifact.replace" not in names


def test_delete_removes_everything_and_leaves_no_trace(ws, human, ai, setup):
    """AC-04：删除后原件、读取、抽取、退役记录、单依赖条目、相关系统流水、索引都不在，purge_gate 为空；
    多依赖判断保留并标为已删除；之后仍可以替换。"""
    old, j, from_old, rec = setup
    ws.judgments.retire(human, old["id"], reason="错误导入")
    preview = ws.purge.preview(old["id"])
    doomed = {x["id"] for x in preview["delete"]["judgments"]} | {x["id"] for x in preview["delete"]["records"]}
    assert doomed == {j["only_read"], j["only_seg"], j["dep"], from_old}
    assert [x["id"] for x in preview["keep_with_gap"]] == [j["multi"]]
    blob = ws.blobs.path(old["sha256"])
    assert blob.exists()
    ws.purge.delete(human, old["id"], confirm=preview["confirm"])
    led = ws.ledger_db
    for entry_id in [old["id"], *doomed]:
        assert ws.ledger.get(entry_id) is None
    assert not led.execute("SELECT 1 FROM reads WHERE artifact_id = ?", (old["id"],)).fetchall()
    assert not led.execute("SELECT 1 FROM retirements").fetchall()
    assert not led.execute("SELECT 1 FROM purge_gate").fetchall()
    assert not led.execute("SELECT 1 FROM events WHERE data LIKE ?", (f"%{old['id']}%",)).fetchall()
    assert not led.execute("SELECT 1 FROM entry_objects WHERE entry_id = ?", (j["only_seg"],)).fetchall()
    assert not blob.exists()
    assert old["id"] not in {h["id"] for h in ws.retrieval.search_exact("moment estimates")["hits"]}
    assert ws.ledger.get(j["multi"]) and ws.ledger.get(rec) and ws.ledger.get(j["proc"])
    c = ws.retrieval.coordinates(j["multi"])
    assert c["lapsed_basis"] == [{"ref": f"{old['id']}#seg-0", "reason": "deleted"}]
    assert j["multi"] in listed(ws)
    # 删除之后仍可以给被删的原件指定替代原件：引用它的判断恢复，按段落指纹比对
    new = ws.artifacts.register(ai, kind="literature", source_class="external", title="新文本",
                                text="Adam uses moment estimates.")
    ws.judgments.replace(human, old["id"], replacement=new["id"], reason="重新导入")
    assert "lapsed_basis" not in ws.retrieval.coordinates(j["multi"])
    assert j["multi"] not in {r["judgment_id"] for r in ws.extraction.needs_recheck()}
    # 账本照样拒绝任何没有放行的删除
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        led.execute("DELETE FROM judgments WHERE id = ?", (j["multi"],))


def test_delete_keeps_shared_blob_and_unrelated_hidden(ws, human, ai):
    """别的原件也在用的 blob 不删；因为别的退役原件才隐藏的条目不归这次删除。"""
    a = ws.artifacts.register(ai, kind="log", source_class="local", text="同一段内容", title="a")
    other = ws.artifacts.register(ai, kind="log", source_class="local", text="另一份", title="b")
    ws.artifacts.read(ai, other["id"], "seg-0")
    j_other = ws.judgments.write(ai, kind="conclusion", text="另一份说了什么", cites=[f"{other['id']}#seg-0"])
    ws.judgments.retire(human, other["id"], reason="x")
    ws.judgments.retire(human, a["id"], reason="x")
    preview = ws.purge.preview(a["id"])
    assert j_other["id"] not in {x["id"] for x in preview["delete"]["judgments"]}
    ws.purge.delete(human, a["id"], confirm=preview["confirm"])
    assert ws.ledger.get(j_other["id"]) and j_other["id"] in ws.purge.hidden_ids()
