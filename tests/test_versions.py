"""同条目的各版有独立 ID，引用固定；只销毁确认的退役版本。"""
import pytest

from burrowl.core.errors import BurrowlError
from burrowl.interfaces.registry import Ctx, call


@pytest.mark.parametrize("legacy", [False, True])
def test_cancel_defect_on_fact_record_preserves_history(ws, human, ai, legacy):
    """事实记录的新旧缺陷标记都可取消，撤回状态和历史引用保持独立。"""
    ctx = Ctx(ws, human, "http")
    event = ws.capture.log(human, "measure.pressure", output="实测 0.82 MPa")
    record = ws.artifacts.promote(human, event_id=event["id"])
    entry_id = record["id"]
    if legacy:
        ws.judgments.amend(human, mode="defect", target=entry_id, reason="旧入口标记")
    else:
        call(ctx, "entry.version_state", {"id": entry_id, "action": "defect", "reason": "记录待查"})
    downstream = ws.judgments.write(human, kind="conclusion", text="引用原测量", cites=[entry_id])
    assert "DEFECTIVE_CITATION" in downstream["warning_codes"]
    call(ctx, "entry.version_state", {"id": entry_id, "action": "withdraw", "reason": "另有待核对项"})
    args = {"id": entry_id, "action": "undefect", "reason": "确认原记录无缺陷"}
    with pytest.raises(BurrowlError):
        call(Ctx(ws, ai, "mcp"), "entry.version_state", args)
    call(ctx, "entry.version_state", args)
    detail = call(ctx, "entry.get", {"id": entry_id})
    assert detail["entry"]["data"] == record["data"]
    assert detail["coordinates"]["complete"] and not detail["coordinates"]["defective"]
    version = detail["version_history"]["versions"][0]
    assert version["withdrawn"] and not version["defective"]
    assert [c["data"]["action"] for c in version["changes"]] == ["defect", "withdraw", "undefect"]
    link = call(ctx, "entry.get", {"id": downstream["id"]})["links_out"][0]
    assert link["dst_id"] == entry_id and not link["basis_status"]["defective"]
    with pytest.raises(BurrowlError, match="没有待取消"):
        call(ctx, "entry.version_state", args)


@pytest.mark.parametrize("destroy_latest", [False, True])
def test_history_requires_explicit_reactivation_and_keeps_publication_numbers(ws, human, ai, destroy_latest):
    ctx = Ctx(ws, human, "http")
    v1 = ws.judgments.write(human, kind="conclusion", text="版本一")["id"]
    v2 = call(ctx, "entry.correct", {"id": v1, "text": "版本二", "reason": "核对"})["id"]
    args = {"id": v1, "action": "reactivate", "reason": "原版重新核对"}
    with pytest.raises(BurrowlError, match="较新的版本生效"):
        call(ctx, "entry.version_state", args)
    with pytest.raises(BurrowlError):
        call(Ctx(ws, ai, "mcp"), "entry.version_state", args)
    call(ctx, "entry.version_state", {"id": v1, "action": "withdraw", "reason": "待查"})
    call(ctx, "entry.version_state", {"id": v2, "action": "withdraw", "reason": "待查"})
    coords = ws.retrieval.coordinates(v2)
    assert coords["withdrawn"] and not coords["replaced"]
    with pytest.raises(BurrowlError, match="未撤回"):
        call(ctx, "entry.version_state", args)
    call(ctx, "entry.version_state", {"id": v1, "action": "unwithdraw", "reason": "核对完成"})
    assert ws.versions.history(v1)["current_id"] is None
    if destroy_latest:
        call(ctx, "entry.version_state", {"id": v2, "action": "retire", "reason": "停止使用"})
        plan = call(ctx, "entry.destroy_preview", {"id": v2})
        call(ctx, "entry.destroy", {"id": v2, "confirm": plan["confirm"]})
        assert ws.versions.history(v1)["latest_number"] == 2
        assert ws.versions.history(v1)["current_id"] is None
        assert v1 in ws.versions.hidden_ids()
    call(ctx, "entry.version_state", args)
    assert ws.versions.history(v1)["current_id"] == v1
    assert v1 not in ws.versions.hidden_ids()
    assert not ws.judgments.status(v1)["superseded"]
    v3 = call(ctx, "entry.correct", {"id": v1, "text": "版本三", "reason": "重新发布"})["id"]
    history = ws.versions.history(v1)
    assert history["current_id"] == v3 and history["latest_number"] == 3
    call(ctx, "entry.version_state", {"id": v3, "action": "withdraw", "reason": "待查"})
    assert ws.versions.history(v1)["current_id"] is None


def test_version_citation_warnings_and_defect_coordinates(ws, human, pump_log):
    source = ws.judgments.write(human, kind="conclusion", text="待核对", cites=[pump_log["id"]])
    ws.versions.change_state(human, source["id"], "withdraw", "待查")
    ws.versions.change_state(human, pump_log["id"], "defect", "仪器偏移")
    coords = ws.retrieval.coordinates(pump_log["id"])
    assert coords["defective"] and not coords["complete"]
    result = ws.judgments.write(human, kind="conclusion", text="引用测试", cites=[source["id"], pump_log["id"]])
    assert {"WITHDRAWN_CITATION", "DEFECTIVE_CITATION"} <= set(result["warning_codes"])
    assert {r["dst_id"] for r in ws.ledger.links_from(result["id"], "used")} == {source["id"], pump_log["id"]}
    basis = ws.retrieval._basis(result["id"], include_process=True, limit=3)
    assert "已撤回" in basis[0]["status_note"] and "已被替代" not in basis[0]["status_note"]
    assert "有缺陷" in basis[1]["status_note"]
    detail = call(Ctx(ws, human, "http"), "entry.get", {"id": result["id"]})
    assert detail["links_out"][0]["basis_status"]["withdrawn"]
    assert detail["links_out"][1]["basis_status"]["defective"]


@pytest.mark.parametrize("legacy", [False, True])
def test_unwithdraw_restores_same_version_and_preserves_history(ws, human, ai, legacy):
    """兼容旧撤回；取消撤回只改状态，不建新版，不解除退役。"""
    ctx = Ctx(ws, human, "http")
    item = ws.judgments.write(human, kind="conclusion", text="需要恢复的判断")
    version_id = item["id"]
    if legacy:
        ws.judgments.amend(human, mode="retraction", target=version_id, reason="旧入口撤回")
    else:
        call(ctx, "entry.version_state", {"id": version_id, "action": "withdraw", "reason": "误操作"})
    assert ws.judgments.status(version_id)["retracted"]
    args = {"id": version_id, "action": "unwithdraw", "reason": "核对原文与依据"}
    with pytest.raises(BurrowlError):
        call(Ctx(ws, ai, "mcp"), "entry.version_state", args)
    call(ctx, "entry.version_state", args)
    version = ws.versions.history(version_id)
    assert version["latest_id"] == version_id and len(version["versions"]) == 1
    assert [c["data"]["action"] for c in version["versions"][0]["changes"]] == ["withdraw", "unwithdraw"]
    assert not ws.judgments.status(version_id)["superseded"]
    assert version_id in {r["id"] for r in call(ctx, "entries.list", {"kind": "judgment"})["items"]}
    with pytest.raises(BurrowlError, match="尚未撤回"):
        call(ctx, "entry.version_state", args)
    v2 = call(ctx, "entry.correct", {"id": version_id, "text": "新版", "reason": "补充适用范围"})
    call(ctx, "entry.version_state", {"id": version_id, "action": "withdraw", "reason": "待查"})
    call(ctx, "entry.version_state", {"id": version_id, "action": "retire", "reason": "收起旧版"})
    call(ctx, "entry.version_state", args)
    assert ws.versions.state(version_id)["retired"] and not ws.versions.state(version_id)["withdrawn"]
    assert ws.versions.history(version_id)["latest_id"] == v2["id"]
    assert ws.judgments.status(version_id)["superseded"]
    call(ctx, "entry.version_state", {"id": version_id, "action": "restore", "reason": "取消退役"})
    assert not ws.versions.state(version_id)["retired"]
    assert version_id in ws.versions.hidden_ids()


def test_history_keeps_fixed_references_and_survives_middle_destruction(ws, human, ai, pump_log):
    ctx = Ctx(ws, human, "http")
    v1 = ws.judgments.write(human, kind="conclusion", text="初始读数", cites=[pump_log["id"]])
    v2 = call(ctx, "entry.correct", {"id": v1["id"], "reason": "重新核对", "text": "第二次核实"})
    downstream = ws.judgments.write(ai, kind="conclusion", text="使用二版", cites=[v2["id"], pump_log["id"]])
    v3 = call(ctx, "entry.correct", {"id": v2["id"], "reason": "重新计算", "text": "第三次核实"})
    chain = call(ctx, "entry.get", {"id": v1["id"]})["version_history"]
    assert chain["referenced_id"] == v1["id"] and chain["latest_id"] == v3["id"]
    assert [v["entry"]["data"]["text"] for v in chain["versions"]] == ["初始读数", "第二次核实", "第三次核实"]
    assert ws.ledger.links_from(downstream["id"], "used")[0]["dst_id"] == v2["id"]
    listed = call(ctx, "entries.list", {"kind": "judgment"})["items"]
    assert not {v1["id"], v2["id"]} & {item["id"] for item in listed}
    with pytest.raises(BurrowlError):
        call(ctx, "entry.destroy_preview", {"id": v2["id"]})
    with pytest.raises(BurrowlError):
        call(Ctx(ws, ai, "mcp"), "entry.version_state", {"id": v2["id"], "action": "retire", "reason": "x"})
    call(ctx, "entry.version_state", {"id": v2["id"], "action": "retire", "reason": "重复历史"})
    preview = call(ctx, "entry.destroy_preview", {"id": v2["id"]})
    assert downstream["id"] in {e["id"] for e in preview["keep_with_gap"]}
    call(ctx, "entry.destroy", {"id": v2["id"], "confirm": preview["confirm"]})
    assert ws.get(v2["id"]) is None
    assert [v["id"] for v in ws.versions.history(v1["id"])["versions"]] == [v1["id"], v3["id"]]
    assert ws.purge.coordinates(downstream["id"])["lapsed_basis"] == [{"ref": v2["id"], "reason": "deleted"}]
    assert not ws.ledger.query("SELECT id FROM links WHERE src_id=? AND rel LIKE 'entry_version%'", (v2["id"],))
    assert not ws.ledger.query("SELECT id FROM purge_gate")


def test_versions_keep_raw_process_and_separate_state(ws, human, pump_log):
    ctx = Ctx(ws, human, "http")
    event = ws.capture.log(human, "measure.pressure", output="原始读数 2")
    rec = ws.artifacts.promote(human, event_id=event["id"])
    for original in (event, rec, pump_log):
        new = call(ctx, "entry.correct", {"id": original["id"], "reason": "校准", "text": "校准后 1.5"})
        assert ws.get(original["id"])["data"] == original["data"]
        assert ws.versions.history(original["id"])["latest_id"] == new["id"]
        call(ctx, "entry.version_state", {"id": new["id"], "action": "withdraw", "reason": "需复测"})
        assert ws.versions.state(new["id"])["withdrawn"]
        assert {original["id"], new["id"]} <= ws.versions.hidden_ids()
        if original["entry_kind"] != "artifact":
            assert new["data"]["corrected_text"] == "校准后 1.5"
    assert not ws.ledger.query("SELECT id FROM judgments")


def test_destroy_legacy_artifact_middle_keeps_family_and_dependent_record(ws, human):
    ctx = Ctx(ws, human, "http")
    v1 = ws.artifacts.register(human, kind="file", source_class="local", text="初版读数")
    v2 = ws.artifacts.register(human, kind="file", source_class="local", text="二版读数", version_of=v1["id"])
    v3 = ws.artifacts.register(human, kind="file", source_class="local", text="三版读数", version_of=v2["id"])
    rec = ws.artifacts.promote(human, artifact_id=v2["id"])
    ws.judgments.retire(human, v2["id"], reason="撤出旧版本")
    preview = call(ctx, "entry.destroy_preview", {"id": v2["id"]})
    assert rec["id"] in {r["id"] for r in preview["keep_with_gap"]}
    call(ctx, "entry.destroy", {"id": v2["id"], "confirm": preview["confirm"]})
    assert ws.get(v2["id"]) is None and ws.get(rec["id"]) is not None
    assert [v["id"] for v in ws.versions.history(v1["id"])["versions"]] == [v1["id"], v3["id"]]
    rec1 = ws.artifacts.promote(human, artifact_id=v1["id"])
    for version in (v3, v1):
        ws.judgments.retire(human, version["id"], reason="退出历史版本")
        planned = call(ctx, "entry.destroy_preview", {"id": version["id"]})
        call(ctx, "entry.destroy", {"id": version["id"], "confirm": planned["confirm"]})
    assert ws.get(rec1["id"]) is not None
