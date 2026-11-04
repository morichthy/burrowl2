"""框架层、传播、术语连接（DESIGN §4：test_propagation、test_linking）。"""
import pytest

from burrowl.core.errors import BurrowlError


def _page(ws, actor, subject, inputs, slug="p"):
    return ws.frameworks.page_write(actor, type="synthesis", title=slug, body="综合", inputs=inputs, slug=slug,
                                    subject_id=subject)


def test_page_threshold(ws, human, ai):
    ent = ws.frameworks.entity_upsert(ai, kind="device", name="3号阀")
    with pytest.raises(BurrowlError) as e:
        ws.frameworks.page_write(ai, type="entity", title="3号阀", body="x", subject_id=ent["id"])
    assert e.value.code == "PAGE_THRESHOLD"
    ws.artifacts.register(human, kind="log", source_class="local", text="今天检查了3号阀，正常")
    ws.artifacts.register(human, kind="log", source_class="local", text="3号阀有轻微泄漏")
    page = ws.frameworks.page_write(ai, type="entity", title="3号阀", body="x", subject_id=ent["id"])
    assert page["review"] == "ai_generated"
    # 判断也算条目：只出现在一条判断中还不够，两条才行；过程日志不算
    other = ws.frameworks.entity_upsert(ai, kind="device", name="4号阀")
    ws.judgments.write(ai, kind="process", text="4号阀是否内漏？", objects=[other["id"]])
    ws.capture.log(ai, "inspect.valve", objects=[other["id"]])
    with pytest.raises(BurrowlError):
        ws.frameworks.page_write(ai, type="entity", title="4号阀", body="x", subject_id=other["id"])
    ws.judgments.write(ai, kind="conclusion", text="4号阀关闭后下游压力不降", objects=[other["id"]])
    assert ws.frameworks.page_write(ai, type="entity", title="4号阀", body="x", subject_id=other["id"])
    assert ws.framework.open_decision_for("review", page["id"])


def test_new_judgment_marks_pages_and_only_downgrades(ws, human, ai, pump_log):
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵压力正常", cites=[pump_log["id"]])
    p1 = _page(ws, ai, None, [j["id"]], "p1")
    p2 = _page(ws, ai, None, [f"{p1['id']}@1"], "p2")  # 页面依赖页面的固定版本
    ws.judgments.amend(human, mode="retraction", target=j["id"], reason="数据有误")
    assert ws.framework.page(p1["id"])["freshness"] == "inputs_changed"
    assert ws.framework.page(p2["id"])["freshness"] == "inputs_changed"  # 传递
    assert ws.framework.open_decision_for("rederive", p1["id"])
    # 重写后回到 valid，新版本的输入清单才参与之后的传播
    p1b = _page(ws, ai, None, [pump_log["id"]], "p1")
    assert p1b["head_version"] == 2 and ws.framework.page(p1["id"])["freshness"] == "valid"
    view = ws.frameworks.page_get(f"{p1['id']}@1")
    assert view["superseded_inputs"] == [j["id"]]


def test_propagation_limit_marks_unchecked(ws, ai, pump_log):
    ws.config["propagation"] = {"max_depth": 2, "max_items": 1000}
    j = ws.judgments.write(ai, kind="conclusion", text="x", cites=[pump_log["id"]])
    prev = _page(ws, ai, None, [j["id"]], "c0")
    chain = [prev]
    for i in range(1, 4):
        prev = _page(ws, ai, None, [f"{prev['id']}@1"], f"c{i}")
        chain.append(prev)
    ws.judgments.write(ai, kind="conclusion", text="y", cites=[j["id"]])
    states = [ws.framework.page(p["id"])["freshness"] for p in chain]
    assert states[:2] == ["inputs_changed", "inputs_changed"]
    assert "unchecked" in states[2:]
    assert ws.framework.decisions(kind="propagation_overflow")


def test_review_writes_back_judgment(ws, human, ai):
    a = ws.judgments.write(ai, kind="conclusion", text="旧结论：V-301 开度 60%")
    b = ws.judgments.write(ai, kind="conclusion", text="新结论：V-301 开度 40%")
    edge = ws.frameworks.edge_add(ai, rel="may_supersede", src_id=b["id"], dst_id=a["id"], reason="更晚的读数")
    assert not ws.judgments.status(a["id"])["superseded"]
    with pytest.raises(BurrowlError):
        ws.frameworks.review(ai, item_id=edge["id"], verdict="confirm", reason="ok")
    out = ws.frameworks.review(human, item_id=edge["id"], verdict="confirm", reason="以 11 月 3 日读数为准")
    assert ws.judgments.status(a["id"])["superseded"]  # 复核确认后写回判断层
    assert ws.ledger.get(out["judgment_id"])["kind"] == "review"
    assert ws.framework.edge(edge["id"])["origin"] == "projection"


def test_term_linking_tiers(ws, human, ai, pump_log):
    pump2 = ws.frameworks.entity_upsert(human, kind="device", name="2号泵")
    # 确定：实体名精确
    assert ws.linking.link_term(ai, term="2号泵", source_id=pump_log["id"])["tier"] == "certain"
    # 较有把握：唯一候选
    assert ws.linking.link_term(ai, term="2号泵出口", source_id=pump_log["id"])["tier"] == "confident"
    # 拿不准：多个候选
    ws.frameworks.entity_upsert(human, kind="device", name="2号泵备用")
    out = ws.linking.link_term(ai, term="2号", source_id=pump_log["id"], excerpt="2号 压力")
    assert out["tier"] == "uncertain"
    dec = out["decision"]
    with pytest.raises(BurrowlError):
        ws.linking.decide(ai, decision_id=dec["id"], entity_id=pump2["id"])
    res = ws.linking.decide(human, decision_id=dec["id"], entity_id=pump2["id"])
    assert ws.ledger.get(res["judgment_id"])["author_kind"] == "human"
    # 人的决定加入别名表，同一叫法下次直接落入"确定"档
    assert ws.linking.link_term(ai, term="2号", source_id=pump_log["id"])["tier"] == "certain"


def test_import_links_mentions(ws, human):
    ent = ws.frameworks.entity_upsert(human, kind="device", name="V-301")
    art = ws.artifacts.register(human, kind="log", source_class="local", text="入口阀 V-301 开度 60%")
    edges = [e for e in ws.framework.edges_of(ent["id"]) if e["rel"] == "mentions"]
    assert edges and edges[0]["src_id"] == art["id"] and edges[0]["origin"] == "mechanical"
