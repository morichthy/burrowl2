"""一套身份与版本（设计稿 10 D-01 至 D-04、D-18 至 D-21；AC-01、AC-03、AC-05）。"""
import pytest

from burrowl.core.errors import BurrowlError
from burrowl.interfaces.registry import Ctx, call


def marks(c, group="state"):
    return {m["mark"]: m for m in c[group]["marks"]}


def test_every_entry_kind_gets_versions_with_stable_id(ws, human, pump_log):
    """AC-01：所有条目可写第 2 版；`art_…@1#p…`、`jdg_…@2`、`rel_…` 都能解析；旧版内容不变。"""
    ctx = Ctx(ws, human, "http")
    event = ws.capture.log(human, "measure.pressure", output="原始读数 2")
    rec = ws.artifacts.promote(human, event_id=event["id"])
    rd = ws.artifacts.read(human, pump_log["id"], "seg:1")["read"]
    j = ws.judgments.write(human, kind="conclusion", text="读数 2", cites=[rec["id"]])
    bodies = {"evt": "output", "rec": "result", "rd": "excerpt"}
    for original in (event, rec, rd, j, pump_log):
        new = call(ctx, "entry.correct", {"id": original["id"], "reason": "校准", "text": "校准后 1.5"})
        assert new["id"] == original["id"] and new["version"] == 2 and new["ref"] == f"{original['id']}@2"
        assert ws.get(f"{original['id']}@1")["data"] == original["data"]
        prefix = original["id"].split("_")[0]
        if prefix in bodies:
            assert new["data"][bodies[prefix]] == "校准后 1.5" and new["data"]["change_reason"] == "校准"
    assert ws.get(f"{j['id']}@2")["data"]["text"] == "校准后 1.5"
    rel = ws.ledger.relations_from(j["id"], "cites", version=1)[0]
    assert rel["object"] == f"{rec['id']}@1" and ws.get(rel["id"])["predicate"] == "cites"
    seg = ws.extraction.segments(ws.ledger.get(f"{pump_log['id']}@1"))[1]
    assert ws.coordinates.ref_status(f"{pump_log['id']}@1#{seg['anchor']}")["current_ref"] == \
        f"{pump_log['id']}@2#{seg['anchor']}"


def test_defect_on_fact_record_and_cancel(ws, human, ai):
    ctx = Ctx(ws, human, "http")
    event = ws.capture.log(human, "measure.pressure", output="实测 0.82 MPa")
    record = ws.artifacts.promote(human, event_id=event["id"])
    call(ctx, "entry.version_state", {"id": record["id"], "action": "defect", "reason": "记录待查"})
    assert "defective" in marks(ws.coordinates.of(record["id"]))
    downstream = ws.judgments.write(human, kind="conclusion", text="引用原测量", cites=[record["id"]])
    assert "DEFECTIVE_CITATION" in downstream["warning_codes"]
    assert marks(ws.coordinates.of(downstream["id"]))["basis_changed"]["via"][0]["detail"] == "所引版本有缺陷"
    args = {"id": record["id"], "action": "undefect", "reason": "确认原记录无缺陷"}
    with pytest.raises(BurrowlError):
        call(Ctx(ws, ai, "mcp"), "entry.version_state", args)
    with pytest.raises(BurrowlError):  # 撤回只针对判断
        call(ctx, "entry.version_state", {"id": record["id"], "action": "withdraw", "reason": "x"})
    call(ctx, "entry.version_state", args)
    detail = call(ctx, "entry.get", {"id": record["id"]})
    assert detail["entry"]["data"] == record["data"]
    assert detail["coordinates"]["state"]["marks"] == []
    version = detail["version_history"]["versions"][0]
    assert not version["defective"] and [c["action"] for c in version["changes"]] == ["defect", "undefect"]
    assert "basis_changed" not in marks(ws.coordinates.of(downstream["id"]))
    with pytest.raises(BurrowlError, match="没有待取消"):
        call(ctx, "entry.version_state", args)


def test_withdraw_and_reactivate_a_history_version(ws, human, ai):
    ctx = Ctx(ws, human, "http")
    v1 = ws.judgments.write(human, kind="conclusion", text="版本一")["id"]
    call(ctx, "entry.correct", {"id": v1, "text": "版本二", "reason": "核对"})
    with pytest.raises(BurrowlError):
        call(Ctx(ws, ai, "mcp"), "entry.version_state", {"id": f"{v1}@1", "action": "reactivate", "reason": "x"})
    call(ctx, "entry.version_state", {"id": v1, "action": "withdraw", "reason": "待查"})
    assert ws.coordinates.of(v1)["state"]["validity"] == "withdrawn"
    assert v1 in ws.versions.hidden_ids()
    assert v1 not in {i["id"] for i in call(ctx, "entries.list", {"kind": "judgment"})["items"]}
    assert v1 in {i["id"] for i in call(ctx, "entries.list", {"kind": "judgment", "status": "withdrawn"})["items"]}
    v3 = call(ctx, "entry.version_state", {"id": f"{v1}@1", "action": "reactivate", "reason": "原版重新核对"})
    assert v3["ref"] == f"{v1}@3" and v3["data"]["text"] == "版本一"
    assert v3["data"]["change_reason"].startswith("重新生效第 1 版")
    assert ws.coordinates.of(v1)["state"]["validity"] == "current" and v1 not in ws.versions.hidden_ids()
    with pytest.raises(BurrowlError, match="已是当前版"):
        call(ctx, "entry.version_state", {"id": f"{v1}@3", "action": "reactivate", "reason": "x"})
    assert [v["version"] for v in ws.versions.history(v1)["versions"]] == [1, 2, 3]


def test_citation_warnings_and_basis_status(ws, human, pump_log):
    source = ws.judgments.write(human, kind="conclusion", text="待核对", cites=[pump_log["id"]])
    ws.versions.change_state(human, source["id"], "withdraw", "待查")
    ws.versions.change_state(human, pump_log["id"], "defect", "仪器偏移")
    assert "defective" in marks(ws.coordinates.of(pump_log["id"]))
    result = ws.judgments.write(human, kind="conclusion", text="引用测试", cites=[source["id"], pump_log["id"]])
    assert {"WITHDRAWN_CITATION", "DEFECTIVE_CITATION"} <= set(result["warning_codes"])
    assert {r["object"] for r in ws.ledger.relations_from(result["id"], "cites")} == \
        {source["ref"], f"{pump_log['id']}@1"}
    basis = ws.retrieval._basis(result["ref"], include_process=True, limit=3)
    assert "已撤回" in basis[0]["status_note"] and "被替代" not in basis[0]["status_note"]
    assert "本版有缺陷" in basis[1]["status_note"]
    detail = call(Ctx(ws, human, "http"), "entry.get", {"id": result["id"]})
    details = {v["detail"] for v in marks(detail["coordinates"])["basis_changed"]["via"]}
    assert details == {"所引版本已撤回", "所引版本有缺陷"}
    out = detail["relations"]["out"]
    assert {x["other_validity"] for x in out} == {"withdrawn", "current"}


def test_artifact_new_version_pins_citations(ws, human, ai, pump_log):
    """原件新版本是同一 ID 的下一版；引用旧版段落的判断 sources 不变，带"依据有变化"指向当前版。"""
    seg = ws.artifacts.read(ai, pump_log["id"], "seg:1")
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力 0.82 MPa", cites=[seg["cite_as"][0]])
    assert seg["cite_as"][0].startswith(f"{pump_log['id']}#")
    v2 = ws.artifacts.register(human, kind="log", source_class="local", text="2号泵出口压力 0.90 MPa",
                               version_of=pump_log["id"])
    assert v2["id"] == pump_log["id"] and v2["version"] == 2
    c = ws.coordinates.of(j["id"])
    assert c["sources"] == ["local"]
    via = marks(c)["basis_changed"]["via"][0]
    assert via["end"] == seg["cite_as"][0].replace("#", "@1#") and via["current"].startswith(f"{pump_log['id']}@2#")
    old_segments = ws.extraction.segments(ws.ledger.get(f"{pump_log['id']}@1"))
    assert "0.82" in old_segments[1]["text"]
    assert "0.90" in ws.artifacts.segments(pump_log["id"])[0]["text"]


def test_artifact_new_version_can_update_metadata(ws, human, pump_log):
    """新版本可以按键覆盖说明字段，其余沿用上一版。"""
    first = ws.artifacts.register(human, kind="log", source_class="local", text="第一版",
                                  metadata={"note": "旧说明", "keep": "沿用"})
    v2 = ws.artifacts.register(human, kind="log", source_class="local", text="第二版", version_of=first["id"],
                               metadata={"note": "新说明"})
    assert v2["version"] == 2 and v2["data"]["metadata"] == {"note": "新说明", "keep": "沿用"}
    assert ws.ledger.get(f"{first['id']}@1")["data"]["metadata"]["note"] == "旧说明"
    v3 = ws.artifacts.register(human, kind="log", source_class="local", text="第三版", version_of=first["id"])
    assert v3["data"]["metadata"] == {"note": "新说明", "keep": "沿用"}


def test_search_returns_current_version_and_old_hits(ws, human, ai):
    """AC-05：只有旧版命中时返回当前版，old_hits 带旧版引用、命中段落与改动理由。"""
    j = ws.judgments.write(ai, kind="conclusion", text="离心泵入口发生气蚀导致出口压力波动")
    call(Ctx(ws, human, "http"), "entry.correct", {"id": j["id"], "text": "出口压力波动来自出口阀开度变化",
                                                   "reason": "现场复测排除了入口问题"})
    out = ws.retrieval.search("入口气蚀", limit=5)
    hit = next(h for h in out["hits"] if h["id"] == j["id"])
    assert hit["ref"] == f"{j['id']}@2"
    old = hit["old_hits"][0]
    assert old["ref"] == f"{j['id']}@1" and "气蚀" in old["snippet"]
    assert old["replaced_by"] == f"{j['id']}@2" and old["change_reason"] == "现场复测排除了入口问题"
    assert "第 1 版也命中，当前为第 2 版" in hit["status_note"]
    exact = ws.retrieval.search_exact("入口发生气蚀")
    assert exact["hits"][0]["old_hits"][0]["ref"] == f"{j['id']}@1"
    detail = call(Ctx(ws, human, "http"), "entry.get", {"id": f"{j['id']}@1"})
    assert detail["note"].startswith("这是第 1 版，当前是第 2 版")


def test_destroy_retired_artifact_keeps_dependents_with_gap(ws, human):
    ctx = Ctx(ws, human, "http")
    art = ws.artifacts.register(human, kind="file", source_class="local", text="初版读数")
    other = ws.artifacts.register(human, kind="file", source_class="local", text="另一份读数")
    keep = ws.judgments.write(human, kind="conclusion", text="两份读数", cites=[art["id"], other["id"]])
    gone = ws.judgments.write(human, kind="conclusion", text="只看初版", cites=[art["id"]])
    with pytest.raises(BurrowlError):
        call(ctx, "entry.destroy_preview", {"id": art["id"]})  # 没退役不能删
    ws.judgments.retire(human, art["id"], reason="撤出")
    preview = call(ctx, "entry.destroy_preview", {"id": art["id"]})
    assert keep["id"] in {e["id"] for e in preview["keep_with_gap"]}
    assert gone["id"] in {j["id"] for j in preview["delete"]["judgments"]}
    call(ctx, "entry.destroy", {"id": art["id"], "confirm": preview["confirm"]})
    assert ws.get(art["id"]) is None and ws.get(gone["id"]) is None
    lapsed = marks(ws.coordinates.of(keep["id"]))["basis_lapsed"]["via"]
    assert [v["detail"] for v in lapsed] == ["已删除"]
    assert not ws.ledger.query("SELECT id FROM purge_gate")


def test_human_changes_relations_as_new_version(ws, human, ai):
    """人增删关系（entry.relate）：写成新版本，正文不变；旧版本关系保留；只有人能做；supersedes 只有人能写。"""
    ctx = Ctx(ws, human, "http")
    event = ws.capture.log(human, "measure.pressure", output="实测 0.82 MPa")
    rec = ws.artifacts.promote(human, event_id=event["id"])
    other = ws.judgments.write(human, kind="conclusion", text="另一条结论", cites=[rec["id"]])["id"]
    old = ws.judgments.write(human, kind="conclusion", text="旧说法", cites=[rec["id"]])["id"]
    j = ws.judgments.write(human, kind="conclusion", text="新说法", cites=[rec["id"]])["id"]
    with pytest.raises(BurrowlError):
        call(Ctx(ws, ai, "mcp"), "entry.relate", {"id": j, "reason": "x", "add": [{"predicate": "supports", "target": other}]})
    new = call(ctx, "entry.relate", {"id": j, "reason": "补关系", "add": [
        {"predicate": "supports", "target": other}, {"predicate": "supersedes", "target": old},
        {"predicate": "relates", "target": other, "label": "导致"}]})
    assert new["ref"] == f"{j}@2" and new["data"]["text"] == "新说法" and new["data"]["change_reason"] == "补关系"
    preds = {(r["predicate"], r.get("label")) for r in ws.ledger.relations_from(j, version=2)}
    assert {("cites", None), ("supports", None), ("supersedes", None), ("relates", "导致")} <= preds
    assert [r["predicate"] for r in ws.ledger.relations_from(j, version=1)] == ["cites"]
    assert ws.coordinates.of(old)["state"]["validity"] == "replaced"
    with pytest.raises(BurrowlError, match="已经存在"):
        call(ctx, "entry.relate", {"id": j, "reason": "重复", "add": [{"predicate": "supports", "target": other}]})
    with pytest.raises(BurrowlError):  # coexists_under 必须写 condition
        call(ctx, "entry.relate", {"id": j, "reason": "缺条件", "add": [{"predicate": "coexists_under", "target": other}]})
    gone = [r["id"] for r in ws.ledger.relations_from(j, version=2) if r["predicate"] in ("supports", "supersedes")]
    third = call(ctx, "entry.relate", {"id": j, "reason": "去掉", "remove": gone})
    assert third["version"] == 3
    left = {r["predicate"] for r in ws.ledger.relations_from(j, version=3)}
    assert left == {"cites", "relates"}
    cite = ws.ledger.relations_from(j, "cites", version=3)[0]["id"]
    swapped = call(ctx, "entry.relate", {"id": j, "reason": "换依据", "remove": [cite],
                                          "add": [{"predicate": "cites", "target": other}]})
    assert [r["object"] for r in ws.ledger.relations_from(j, "cites", version=swapped["version"])][0].startswith(other)
    with pytest.raises(BurrowlError, match="只能|当前版"):
        call(ctx, "entry.relate", {"id": f"{j}@1", "reason": "旧版", "add": [{"predicate": "supports", "target": other}]})
    with pytest.raises(BurrowlError):  # 原件、记录上不能直接写判断层关系
        call(ctx, "entry.relate", {"id": rec["id"], "reason": "x", "add": [{"predicate": "supports", "target": other}]})
