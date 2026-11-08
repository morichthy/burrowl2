"""设计稿 04：分档、按需复核、人的复核与 AI 复核（AC-01 至 AC-07、AC-10 中可自动验证的部分），
以及原件退役不再写成判断（2.0.0a14）。"""
import pytest

from burrowl.core.actor import Actor
from burrowl.core.errors import BurrowlError
from burrowl.interfaces.registry import Ctx, call

from .test_extraction import FORMULA_PAGE, formula_anchor, image_pdf, math_pdf, register


@pytest.fixture
def files(tmp_path):
    def make(name: str, data: bytes):
        path = tmp_path / name
        path.write_bytes(data)
        return path
    return make


@pytest.fixture
def ai2():
    """另一个会话里的 AI（AI 复核不能复核本会话自己写的条目，D-13 ⑥）。"""
    return Actor("ai:reviewer", "ai", "ses_01JC0000000000000000000003")


def open_reviews(ws):
    return ws.framework.decisions(kind="review")


def _recheck_setup(ws, ai, files):
    """一条判断引用识别段落，之后重新识别、文字变了：这条判断进入待复核。"""
    art = register(ws, ai, files("scan.pdf", image_pdf()), source_class="external")
    ws.extraction.submit(ai, art["id"], method="ai", model="m1", content=[{"unit": "p1", "text": "压力 0.82 MPa"}])
    ws.artifacts.read(ai, art["id"], "p1")
    j = ws.judgments.write(ai, kind="conclusion", text="扫描件记 0.82 MPa", cites=[f"{art['id']}#p1-1"])
    ws.extraction.submit(ai, art["id"], method="ai", model="m2", content=[{"unit": "p1", "text": "压力 0.92 MPa"}])
    assert ws.extraction.pending_recheck(j["id"])
    return art, j


def test_ai_pages_and_association_edges_do_not_queue(ws, ai, pump_log):
    """AC-01：AI 写综合页、加关联边、低影响术语连接，待决策列表都不增加；坐标仍为 AI 生成未复核。"""
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵压力正常", cites=[pump_log["id"]])
    page = ws.frameworks.page_write(ai, type="synthesis", title="泵", body="综合", inputs=[j["id"]])
    ws.frameworks.edge_add(ai, rel="similar", src_id=j["id"], dst_id=pump_log["id"], reason="相近")
    ent = ws.frameworks.entity_upsert(ai, kind="device", name="2号泵")
    assert ws.linking.link_term(ai, term="2号泵出口", source_id=pump_log["id"])["tier"] == "confident"
    assert open_reviews(ws) == []
    assert ws.retrieval.coordinates(page["id"])["review"] == "ai_generated"
    assert ent


def test_on_demand_review_triggers(ws, human, ai, pump_log):
    """AC-02：AI 页面成为两个页面的输入后进入待决策；有人"请人复核"后进入。"""
    base = ws.frameworks.page_write(ai, type="synthesis", title="基础", body="x", inputs=[pump_log["id"]], slug="b")
    ws.frameworks.page_write(ai, type="synthesis", title="上层一", body="x", inputs=[f"{base['id']}@1"], slug="u1")
    assert not ws.framework.open_decision_for("review", base["id"])
    ws.frameworks.page_write(ai, type="synthesis", title="上层二", body="x", inputs=[base["id"]], slug="u2")
    d = ws.framework.open_decision_for("review", base["id"])
    assert d and d["impact"] == 2 and d["data"]["trigger"] == "consumers"
    other = ws.frameworks.page_write(ai, type="synthesis", title="孤立", body="x", slug="o")
    out = call(Ctx(ws=ws, actor=ai, channel="mcp"), "review.request", {"item_id": other["id"], "note": "结论太强"})
    d = ws.framework.decision(out["decision_id"])
    assert d["subject_id"] == other["id"] and d["data"]["requested"] and d["impact"] == 1
    assert [i["verdict"] for i in ws.reviews.history(other["id"])["items"]] == ["request"]


def test_ai_latex_citation_is_low_fidelity(ws, human, ai, files):
    """AC-03：引用带 AI LaTeX、未经人确认的公式块，返回 LOW_FIDELITY_CITATION；人确认后不再提示。"""
    art = register(ws, ai, files("f.pdf", math_pdf(FORMULA_PAGE)))
    anchor, unit = formula_anchor(ws, art["id"])
    ws.artifacts.read(ai, art["id"], anchor)
    plain = ws.judgments.write(ai, kind="conclusion", text="式 (1)", cites=[f"{art['id']}#{anchor}"])
    assert "LOW_FIDELITY_CITATION" not in plain["warning_codes"]
    ws.extraction.submit_latex(ai, art["id"], method="ai", model="m", blocks=[{"anchor": anchor, "latex": "a+b=g"}])
    ws.artifacts.read(ai, art["id"], anchor)
    j = ws.judgments.write(ai, kind="conclusion", text="式 (1) 是 a+b=g", cites=[f"{art['id']}#{anchor}"])
    assert "LOW_FIDELITY_CITATION" in j["warning_codes"]
    ws.extraction.verify(human, art["id"], units=[unit["unit"]])
    again = ws.judgments.write(ai, kind="conclusion", text="式 (1) 已确认", cites=[f"{art['id']}#{anchor}"])
    assert "LOW_FIDELITY_CITATION" not in again["warning_codes"]


def test_human_review_of_judgment(ws, human, ai, files, tmp_path):
    """AC-04：人复核判断并补充本地实证：坐标显示当前地位与人已复核，写入时可信度不变，检索不多出条目；
    AI 引用或支持它不让它离开待复核，人复核后离开；导出再导入后复核历史还在。"""
    art, j = _recheck_setup(ws, ai, files)
    ws.judgments.write(ai, kind="conclusion", text="沿用 0.82 MPa", cites=[j["id"]])
    total = ws.retrieval.search("0.82")["total"]
    assert ws.extraction.pending_recheck(j["id"])  # AI 的引用不算处理（D-09）
    with pytest.raises(BurrowlError):
        call(Ctx(ws=ws, actor=ai, channel="mcp"), "review.submit",
             {"item_id": j["id"], "verdict": "confirm", "reason": "x"})
    out = ws.reviews.submit(human, item_id=j["id"], verdict="confirm", reason="我在现场读到 0.82 MPa",
                            local_observation=True)
    assert out["review"] == "human_reviewed" and not ws.extraction.pending_recheck(j["id"])
    coords = ws.retrieval.coordinates(j["id"])
    assert coords["review"] == "human_reviewed" and "local" in coords["source_classes"]
    assert coords["written_credibility"] == ws.ledger.get(j["id"])["data"]["credibility"]
    assert "local" not in coords["written_credibility"]["source_classes"]
    assert ws.retrieval.search("0.82")["total"] == total  # 复核不是新条目
    hist = ws.reviews.history(j["id"])["items"]
    assert [(h["verdict"], h["method"]) for h in hist] == [("confirm", "human")]
    ws.portability.export(str(tmp_path / "exp"))
    from burrowl.services.workspace import Workspace
    other = Workspace(tmp_path / "copy")
    try:
        other.portability.import_(str(tmp_path / "exp"))
        assert other.retrieval.coordinates(j["id"])["review"] == "human_reviewed"
    finally:
        other.close()


def test_rejected_judgment_ranks_lower_but_stays(ws, human, ai, pump_log):
    a = ws.judgments.write(ai, kind="conclusion", text="泵压读数 甲", cites=[pump_log["id"]])
    b = ws.judgments.write(ai, kind="conclusion", text="泵压读数 乙", cites=[pump_log["id"]])
    ws.reviews.submit(human, item_id=a["id"], verdict="reject", reason="巡检记录不支持")
    hits = [h["id"] for h in ws.retrieval.search("泵压读数", layers=["judgment"])["hits"]]
    assert hits.index(b["id"]) < hits.index(a["id"])
    assert ws.retrieval.coordinates(a["id"])["review"] == "rejected"


def test_recheck_citation_notice(ws, human, ai, files):
    """AC-05：引用或支持待复核的判断，写入成功并返回提示，状态检查列出。"""
    art, j = _recheck_setup(ws, ai, files)
    k = ws.judgments.write(ai, kind="conclusion", text="据此判断压力正常", cites=[j["id"]])
    assert "RECHECK_CITATION" in k["warning_codes"]
    m = ws.judgments.write(ai, kind="conclusion", text="支持", relations=[{"rel": "supports", "target": j["id"]}])
    assert "RECHECK_CITATION" in m["warning_codes"]
    listed = {i["judgment_id"] for i in ws.extraction.status_report()["recheck_citations"]}
    assert {k["id"], m["id"]} <= listed


def test_ai_review_rules(ws, human, ai, ai2, pump_log):
    """AC-06：以框架页为依据、未读先复核、复核同一会话写的、复核写回判断层的边、依据不相关，都被拒绝；
    confirm 后待决策关闭、排序不变；reject 后内容仍可检索、待决策排到前面。"""
    ws.artifacts.read(ai, pump_log["id"], "seg-1")
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力 0.82 MPa", cites=[f"{pump_log['id']}#seg-1"])
    page = ws.frameworks.page_write(ai, type="synthesis", title="2号泵综述", body="压力 0.82", inputs=[j["id"]],
                                    slug="pump")
    other = ws.frameworks.page_write(ai, type="synthesis", title="别的", body="x", slug="other")
    ctx = Ctx(ws=ws, actor=ai2, channel="mcp")
    cite = f"{pump_log['id']}#seg-1"

    def codes(**args):
        with pytest.raises(BurrowlError) as e:
            call(ctx, "review.ai_submit", {"model": "m", "reason": "r", **args})
        return e.value.code

    with pytest.raises(BurrowlError) as e:  # 同一会话
        ws.reviews.ai_submit(ai, item_id=page["id"], verdict="confirm", reason="r", model="m", cites=[cite])
    assert e.value.code == "SAME_SESSION"
    assert codes(item_id=page["id"], verdict="confirm", cites=[other["id"]]) == "FRAMEWORK_NOT_EVIDENCE"
    assert codes(item_id=page["id"], verdict="confirm", cites=[]) == "INVALID_ARGUMENT"
    assert codes(item_id=page["id"], verdict="confirm", cites=[cite]) == "UNREAD_REVIEW"
    ws.artifacts.read(ai2, pump_log["id"], "seg-1")
    assert codes(item_id=other["id"], verdict="confirm", cites=[cite]) == "IRRELEVANT_EVIDENCE"
    k = ws.judgments.write(ai, kind="conclusion", text="另一读数")
    edge = ws.frameworks.edge_add(ai, rel="may_contradict", src_id=k["id"], dst_id=j["id"], reason="冲突")
    assert codes(item_id=edge["id"], verdict="unsure") == "REVIEW_NOT_ALLOWED"
    assert codes(item_id=pump_log["id"], verdict="unsure") == "REVIEW_NOT_ALLOWED"

    rank_before = [h["id"] for h in ws.retrieval.search("2号泵")["hits"]]
    ws.reviews.request(human, item_id=page["id"], note="看一下")
    out = call(ctx, "review.ai_submit", {"item_id": page["id"], "verdict": "confirm", "reason": "与巡检记录一致",
                                         "model": "m", "cites": [cite]})
    assert out["review"] == "ai_reviewed"
    d = ws.framework.decision(out["decision_id"])
    assert d["status"] == "open" and d["data"]["notes"][-1]["verdict"] == "confirm"  # 请人复核开出的不关闭
    assert [h["id"] for h in ws.retrieval.search("2号泵")["hits"]] == rank_before  # 排序不变
    # 人之后仍可复核，人的结论优先
    ws.reviews.submit(human, item_id=page["id"], verdict="confirm", reason="ok")
    assert ws.framework.page(page["id"])["review"] == "human_reviewed"

    sim = ws.frameworks.edge_add(ai, rel="related", src_id=j["id"], dst_id=pump_log["id"], reason="相关")
    out = call(ctx, "review.ai_submit", {"item_id": sim["id"], "verdict": "reject", "reason": "无关",
                                         "model": "m", "cites": [cite]})
    d = ws.framework.decision(out["decision_id"])
    assert d["status"] == "open" and d["impact"] == 2
    assert ws.framework.edge(sim["id"])["review"] == "ai_generated"  # AI 驳回不隐藏、不改状态
    assert ws.retrieval.coordinates(sim["id"])["ai_flag"]
    assert open_reviews(ws)[0]["subject_id"] == sim["id"]  # 排到前面


def test_ai_review_of_recheck_judgment_and_setting(ws, human, ai, ai2, files):
    """AC-07：review.ai=framework 时待复核的判断被拒绝；=off 时全部拒绝；=all 时 confirm 后移到"AI 已核对"。"""
    art, j = _recheck_setup(ws, ai, files)
    ctx = Ctx(ws=ws, actor=ai2, channel="mcp")
    ws.artifacts.read(ai2, art["id"], "p1")
    args = {"item_id": j["id"], "verdict": "confirm", "reason": "新识别仍支持", "model": "m",
            "cites": [f"{art['id']}#p1-1"]}
    with pytest.raises(BurrowlError) as e:
        call(ctx, "review.ai_submit", args)
    assert e.value.code == "REVIEW_DISABLED"
    call(Ctx(ws=ws, actor=human, channel="http"), "settings.set", {"values": {"review.ai": "all"}})
    with pytest.raises(BurrowlError) as e:  # 依据只有未确认的识别段落，不能 confirm
        call(ctx, "review.ai_submit", args)
    assert e.value.code == "LOW_FIDELITY_REVIEW"
    call(ctx, "review.ai_submit", {**args, "verdict": "unsure"})
    ws.extraction.verify(human, art["id"])
    ws.artifacts.read(ai2, art["id"], "p1")
    call(ctx, "review.ai_submit", args)
    report = ws.extraction.status_report()
    assert j["id"] not in [r["judgment_id"] for r in report["needs_recheck"]]
    assert j["id"] in [r["judgment_id"] for r in report["ai_checked_recheck"]]
    assert ws.retrieval.coordinates(j["id"])["review"] == "ai_reviewed"
    call(Ctx(ws=ws, actor=human, channel="http"), "settings.set", {"values": {"review.ai": "off"}})
    with pytest.raises(BurrowlError) as e:
        call(ctx, "review.ai_submit", {**args, "verdict": "unsure"})
    assert e.value.code == "REVIEW_DISABLED"


def test_sample_is_stable_within_a_week(ws, ai):
    for i in range(8):
        ws.frameworks.page_write(ai, type="synthesis", title=f"页{i}", body="x", slug=f"s{i}")
    a, b = ws.reviews.sample(), ws.reviews.sample()
    assert len(a["pages"]) == 5 and a == b and a["pool"] == 8


def test_legacy_retirement_and_review_judgments_are_history(ws, human, ai, pump_log):
    """2.0.0a13 以前的退役判断、复核判断：照常生效，但不作为判断出现在列表、检索里；撤回旧退役即恢复。"""
    art = ws.artifacts.register(human, kind="log", source_class="local", text="旧数据 不再使用 甲乙丙")
    old = ws.ledger.insert("judgments", "jdg", {"kind": "retirement", "author_id": human.id, "author_kind": "human",
                                                "session_id": human.session_id,
                                                "data": {"text": "旧数据，不再使用", "credibility": {}}})
    ws.ledger.link("retires", old["id"], art["id"], human.id)
    ws.judgments.index_judgment(old["id"])
    assert ws.judgments.retirement_of(art["id"]) == old["id"]
    listed = [i["id"] for i in ws.overview.entries(kind="judgment")["items"]]
    assert old["id"] not in listed
    assert old["id"] not in [h["id"] for h in ws.retrieval.search("不再使用")["hits"]]
    assert old["id"] not in [n["id"] for n in ws.overview.graph()["nodes"]]
    with pytest.raises(BurrowlError):  # 不能再写成判断
        ws.judgments.write(human, kind="retirement", text="x")
    out = ws.judgments.amend(human, mode="retraction", target=old["id"], reason="还要用")
    assert out["id"].startswith("ret_") and ws.judgments.retirement_of(art["id"]) is None
    assert [h["action"] for h in ws.reviews.history(art["id"])["items"]] == ["retire", "restore"]
