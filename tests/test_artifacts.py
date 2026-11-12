"""原件登记、分段、读取记录、事实记录、新版本（DESIGN §4：test_artifact_import）。"""
import pytest

from burrowl.core.errors import BurrowlError
from tests.conftest import PUMP_LOG


def test_register_is_idempotent_and_segmented(ws, human, pump_log):
    again = ws.artifacts.register(human, kind="log", source_class="local", text=PUMP_LOG)
    assert again["id"] == pump_log["id"] and again["existing"]
    segs = ws.artifacts.segments(pump_log["id"])
    texts = [s["text"] for s in segs]
    assert texts[0].startswith("# 2号泵巡检记录")          # 标题自成一段
    assert any(t.startswith("| 时间") for t in texts)        # 表格整体是一段
    assert all(s["locator"] == f"seg:{s['ordinal']}" for s in segs)


def test_referenced_file_keeps_fingerprint(ws, human, tmp_path):
    f = tmp_path / "wave.csv"
    f.write_text("t,v\n0,1\n", encoding="utf-8")
    art = ws.artifacts.register(human, kind="dataset", source_class="local", path=str(f), storage="referenced")
    assert art["storage"] == "referenced" and not ws.blobs.has(art["sha256"])
    f.write_text("t,v\n0,2\n", encoding="utf-8")
    with pytest.raises(BurrowlError) as e:
        ws.artifacts.read(human, art["id"])
    assert e.value.code == "CONFLICT"  # 外部原件被改动后不能静默读到新内容


def test_read_creates_read_record(ws, ai, pump_log):
    out = ws.artifacts.read(ai, pump_log["id"], "seg:1")
    rd = out["read"]
    assert rd["artifact_sha256"] == pump_log["sha256"] and rd["locator"] == "seg:1"
    assert "0.82 MPa" in rd["data"]["excerpt"]


def test_promote_cannot_backfill_conditions(ws, ai):
    ev = ws.capture.log(ai, "measure.pressure", output="0.82 MPa", conditions={"pump": "2号泵", "time": "10:00"},
                        objects=["2号泵"])
    rec = ws.artifacts.promote(ai, event_id=ev["id"], method="压力表读数", boundary="complete")
    assert rec["data"]["conditions"] == {"pump": "2号泵", "time": "10:00"}
    assert rec["data"]["result"] == "0.82 MPa"
    with pytest.raises(BurrowlError) as e:
        ws.artifacts.promote(ai, event_id=ev["id"], conditions={"temperature": "35℃"})
    assert e.value.code == "CONDITION_BACKFILL"
    with pytest.raises(BurrowlError) as e:
        ws.artifacts.promote(ai, event_id=ev["id"], result="0.9 MPa")
    assert e.value.code == "NOT_VERBATIM"


def test_new_version_marks_dependent_pages(ws, human, ai, pump_log):
    rd = ws.artifacts.read(ai, pump_log["id"], "seg:1")["read"]
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力约 0.82 MPa", cites=[rd["id"]])
    ent = ws.frameworks.entity_upsert(human, kind="device", name="2号泵")
    page = ws.frameworks.page_write(ai, type="synthesis", title="2号泵压力", body="见 [[{}]]".format(rd["id"]),
                                    inputs=[j["id"]], subject_id=ent["id"])
    new = ws.artifacts.register(human, kind="log", source_class="local",
                                text=PUMP_LOG.replace("0.82 MPa，", "0.91 MPa，"), version_of=pump_log["id"])
    assert new["version_diff"]["removed_segments"] >= 1
    assert ws.framework.page(page["id"])["freshness"] == "inputs_changed"
    # 针对旧版的判断仍然成立：判断本身不被修改
    assert ws.ledger.get(j["id"])["data"]["text"] == "2号泵出口压力约 0.82 MPa"


def test_promote_cites_definitions_and_links_run_files(ws, ai):
    """设计稿 07 D-07、D-08：cites 写成 documents；日志的输入、产出自动连上；方法无引用有提示；
    事实记录只能引用原件一列。"""
    script = ws.artifacts.register(ai, kind="file", source_class="local", title="run.py",
                                   text="# 指标：损失降到最优终值 +0.01 以内所用的轮数\nprint('loss')")
    ws.artifacts.read(ai, script["id"], "seg-0")
    ev = ws.capture.log(ai, "exec.python", input={"command": "python run.py", "script": script["id"]},
                        output="SGD 2 轮", conditions={"seed": 0})
    result = ws.artifacts.register(ai, kind="dataset", source_class="local", title="results.json",
                                   text='{"sgd": 2}', produced_by=ev["id"])
    assert ws.capture.run_files(ev["id"]) == {"inputs": [], "outputs": [result["id"]]}
    bare = ws.artifacts.promote(ai, event_id=ev["id"], method="比较 SGD 的收敛轮数")
    assert "METHOD_UNCITED" in bare["warning_codes"]
    assert set(bare["documents"]) == {script["id"], result["id"]}  # 日志输入里的脚本、日志的产出
    rec = ws.artifacts.promote(ai, event_id=ev["id"], method="指标定义见脚本第 1 段",
                               cites=[f"{script['id']}#seg-0"])
    assert "METHOD_UNCITED" not in rec["warning_codes"] and ws.ledger.relations_from(rec["id"], "cites")[0]["qualifiers"]["sha256"]
    rels = {(r["predicate"], r["object"]) for r in ws.ledger.relations_from(rec["id"])}
    assert ("cites", f"{script['id']}@1#seg-0") in rels and ("cites", f"{result['id']}@1") in rels
    j = ws.judgments.write(ai, kind="conclusion", text="SGD 用了 2 轮", cites=[rec["id"]])
    with pytest.raises(BurrowlError) as e:
        ws.artifacts.promote(ai, event_id=ev["id"], cites=[j["id"]])
    assert e.value.code == "INVALID_REFERENCE"
    with pytest.raises(BurrowlError):
        ws.capture.log(ai, "exec.python", inputs=[j["id"]])
    used = ws.capture.log(ai, "exec.python", inputs=[script["id"]], outputs=[result["id"]])
    assert ws.capture.run_files(used["id"]) == {"inputs": [script["id"]], "outputs": [result["id"]]}
