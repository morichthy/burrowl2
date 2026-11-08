"""原件退役与抽取器升级后的重建（设计稿 02 AC-02、AC-08 至 AC-10 中可自动验证的部分）。"""
import pytest

from burrowl.core.errors import BurrowlError
from burrowl.interfaces.registry import Ctx, call
from burrowl.services import extractors as ex

from .test_extraction import register, text_pdf


@pytest.fixture
def files(tmp_path):
    def make(name: str, data: bytes):
        path = tmp_path / name
        path.write_bytes(data)
        return path
    return make


@pytest.fixture
def derived(ws, human, ai, files):
    """旧数据的样子：一份 PDF，加一份另行登记的派生文本（metadata.derived_from 指向 PDF）。"""
    pdf = register(ws, ai, files("paper.pdf", text_pdf(["Adam uses moment estimates with bias correction."])),
                   kind="literature", source_class="external")
    txt = ws.artifacts.register(ai, kind="literature", source_class="external", title="paper（抽取文本）",
                                text="Adam uses moment estimates with bias correction.",
                                metadata={"derived_from": pdf["id"]})
    return pdf, txt


def test_only_human_can_retire_and_retraction_restores(ws, human, ai, derived):
    """AC-08：AI（含 MCP 入口）不能退役；人退役、撤销退役都不写判断（2.0.0a14），只记原件的退役历史。"""
    _, txt = derived
    with pytest.raises(BurrowlError) as e:
        ws.judgments.amend(ai, mode="retirement", target=txt["id"], reason="重复")
    assert e.value.code == "FORBIDDEN"
    with pytest.raises(BurrowlError) as e:
        call(Ctx(ws=ws, actor=ai, channel="mcp"), "judgment.amend",
             {"mode": "retirement", "target": txt["id"], "reason": "重复"})
    assert e.value.code == "FORBIDDEN"
    with pytest.raises(BurrowlError) as e:
        call(Ctx(ws=ws, actor=ai, channel="mcp"), "artifact.retire", {"artifact_id": txt["id"], "reason": "重复"})
    assert e.value.code == "FORBIDDEN"
    before = ws.ledger_db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    judgments = ws.ledger_db.execute("SELECT COUNT(*) FROM judgments").fetchone()[0]
    rec = ws.judgments.amend(human, mode="retirement", target=txt["id"], reason="内容已由 PDF 的抽取层取代")
    assert rec["id"].startswith("ret_") and ws.judgments.retirement_of(txt["id"]) == rec["id"]
    with pytest.raises(BurrowlError) as e:  # 已退役的不能再退役
        ws.judgments.amend(human, mode="retirement", target=txt["id"], reason="再退一次")
    assert e.value.code == "CONFLICT"
    with pytest.raises(BurrowlError):  # 退役只针对原件
        ws.judgments.amend(human, mode="retirement", target=rec["id"], reason="x")
    ws.judgments.restore(human, txt["id"], reason="还要用")
    assert ws.judgments.retirement_of(txt["id"]) is None
    assert ws.ledger_db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == before
    assert ws.ledger_db.execute("SELECT COUNT(*) FROM judgments").fetchone()[0] == judgments
    assert [h["action"] for h in ws.reviews.history(txt["id"])["items"]] == ["retire", "restore"]
    assert ws.ledger.get(txt["id"])["data"]["title"] == "paper（抽取文本）"  # 原件不变


def test_retired_artifact_hidden_but_readable(ws, human, ai, derived):
    """AC-09：不在条目列表与默认检索中；include_retired 时排在最后；仍可读、可解析。"""
    pdf, txt = derived
    ws.judgments.amend(human, mode="retirement", target=txt["id"], reason="重复")
    listed = [i["id"] for i in ws.overview.entries(kind="artifact")["items"]]
    assert txt["id"] not in listed and pdf["id"] in listed
    assert txt["id"] in [i["id"] for i in ws.overview.entries(kind="artifact", include_retired=True)["items"]]
    hits = [h["id"] for h in ws.retrieval.search("moment estimates")["hits"]]
    assert txt["id"] not in hits and pdf["id"] in hits
    hits = ws.retrieval.search("moment estimates", include_retired=True)["hits"]
    assert hits[-1]["id"] == txt["id"] and hits[-1]["retired"]
    assert ws.artifacts.read(ai, txt["id"], "seg-0")  # 仍可读
    assert ws.retrieval.coordinates(txt["id"])["retired"]


def test_citing_retired_artifact_warns_and_keeps_credibility(ws, human, ai, derived):
    """AC-09：引用已退役原件写入成功、可信度不变，返回 RETIRED_CITATION；以它为输入的框架页标为输入已变化。"""
    pdf, txt = derived
    ws.artifacts.read(ai, txt["id"], "seg-0")
    old = ws.judgments.write(ai, kind="conclusion", text="Adam 使用一阶与二阶矩估计", cites=[f"{txt['id']}#seg-0"])
    page = ws.frameworks.page_write(human, type="synthesis", title="Adam 综述", body="见判断",
                                    inputs=[txt["id"], old["id"]])
    ws.judgments.amend(human, mode="retirement", target=txt["id"], reason="重复")
    assert ws.framework.page(page["id"])["freshness"] == "inputs_changed"
    new = ws.judgments.write(ai, kind="conclusion", text="Adam 带偏差修正", cites=[f"{txt['id']}#seg-0"])
    assert "RETIRED_CITATION" in new["warning_codes"]
    assert new["data"]["credibility"] == old["data"]["credibility"]
    assert ws.judgments.status(old["id"])["superseded"] is False  # 旧判断不受影响


def test_retired_artifacts_do_not_count_for_page_threshold(ws, human, ai):
    ent = ws.frameworks.entity_upsert(ai, kind="device", name="5号阀")
    a1 = ws.artifacts.register(human, kind="log", source_class="local", text="5号阀开度 30%")
    ws.artifacts.register(human, kind="log", source_class="local", text="5号阀关闭")
    ws.judgments.amend(human, mode="retirement", target=a1["id"], reason="重复登记")
    with pytest.raises(BurrowlError) as e:
        ws.frameworks.page_write(ai, type="entity", title="5号阀", body="x", subject_id=ent["id"])
    assert e.value.code == "PAGE_THRESHOLD"


def test_retire_suggestions_list_old_derived_texts(ws, human, derived):
    """AC-10：旧派生文本列为建议退役；确认（退役）后不再列出。"""
    pdf, txt = derived
    suggestions = ws.extraction.status_report()["retire_suggestions"]
    assert [s["artifact_id"] for s in suggestions] == [txt["id"]] and suggestions[0]["source_id"] == pdf["id"]
    ws.judgments.amend(human, mode="retirement", target=txt["id"], reason=suggestions[0]["reason"])
    assert ws.extraction.status_report()["retire_suggestions"] == []


def test_backfill_rebuilds_outdated_extraction(ws, human, ai, files):
    """AC-02：抽取器升级后，补抽按新版重建；引用了已变化段落的判断进入待复核，未变的不受影响。"""
    art = register(ws, ai, files("paper.pdf", text_pdf(["Adam uses moment estimates.", "Second page text here."])))
    # 模拟旧版抽取器做的抽取层：manifest 记旧版本号，第 1 页的文字与新版不同，第 2 页相同
    manifest = ws.extraction.manifest(art["id"])["data"]
    ws.extraction._write(ai, ws.ledger.get(art["id"]), "manifest", "", {**manifest, "extractor_version": 1})
    ws.extraction._content(ai, ws.ledger.get(art["id"]), "p1", status="text", text="Adam uses moment",
                           blocks=[{"type": "paragraph", "text": "Adam uses moment"}], meta={}, method="old",
                           fidelity="parsed", reason="旧版")
    ws.artifacts.read(ai, art["id"], "p1")
    ws.artifacts.read(ai, art["id"], "p2")
    changed = ws.judgments.write(ai, kind="conclusion", text="第 1 页", cites=[f"{art['id']}#p1-1"])
    same = ws.judgments.write(ai, kind="conclusion", text="第 2 页", cites=[f"{art['id']}#p2-1"])
    assert [o["artifact_id"] for o in ws.extraction.status_report()["outdated"]] == [art["id"]]
    out = ws.extraction.backfill(human)
    assert out["rebuilt"] == [art["id"]] and not out["failed"]
    assert ws.extraction.manifest(art["id"])["data"]["extractor_version"] == ex.EXTRACTOR_VERSION
    assert all(b.get("box") for u in ws.extraction.layer(art["id"])["units"] for b in u.get("blocks", []))
    recheck = [r["judgment_id"] for r in ws.extraction.needs_recheck()]
    assert changed["id"] in recheck and same["id"] not in recheck
    assert ws.extraction.status_report()["outdated"] == []
