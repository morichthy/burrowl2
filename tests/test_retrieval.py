"""检索排序、约束、索引版本、展开（DESIGN §4：test_retrieval）。"""


def test_ranking_order_and_superseded_last(ws, human, ai, pump_log):
    paper = ws.artifacts.register(human, kind="literature", source_class="external",
                                  text="离心泵出口压力波动与气蚀有关", external_tier="preprint")
    j_exec = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力波动 0.05 MPa", cites=[pump_log["id"]])
    j_disc = ws.judgments.write(ai, kind="conclusion", text="出口压力波动也许是传感器问题")
    j_old = ws.judgments.write(ai, kind="conclusion", text="出口压力波动可以忽略", cites=[pump_log["id"]])
    ws.versions.change_state(human, j_old["id"], "withdraw", "已证明不能忽略")
    assert j_old["id"] not in {h["id"] for h in ws.retrieval.search("出口压力")["hits"]}  # 已撤回默认不返回
    hits = ws.retrieval.search("出口压力", order="standing", include_retired=True)["hits"]
    ids = [h["id"] for h in hits]
    # order=standing：本地实证排在外部报告前，外部报告在推断前；已撤回的排在最后
    assert ids.index(pump_log["id"]) < ids.index(paper["id"]) < ids.index(j_disc["id"])
    assert ids.index(j_exec["id"]) < ids.index(paper["id"])
    assert ids[-1] == j_old["id"] and hits[-1]["state"]["validity"] == "withdrawn"
    # 默认按相关度（设计稿 06 D-09）：被撤回的仍排在当前条目之后，每条都有地位说明
    default = ws.retrieval.search("出口压力", include_retired=True)["hits"]
    assert default[-1]["id"] == j_old["id"] and "已撤回" in default[-1]["status_note"]
    assert "被替代" not in default[-1]["status_note"]
    ranks = [h["relevance_rank"] for h in default if "state" not in h]
    assert ranks == sorted(ranks)
    assert all(h["status_note"] for h in default)


def test_constraints_first_and_unchecked_flag(ws, human, ai):
    ws.frameworks.entity_upsert(human, kind="device", name="3号阀")
    c = ws.judgments.write(human, kind="normative", text="检修完成前不要操作3号阀", objects=["3号阀"])
    res = ws.retrieval.search("3号阀", objects=["3号阀"])
    assert res["constraints"][0]["id"] == c["id"]
    ws.capture.log(ai, "exec.valve_open", input={"valve": "3号阀"}, objects=["3号阀"])
    assert ws.framework.decisions(kind="constraint_unchecked")
    ws.retrieval.check_constraints(ai, ["3号阀"])
    before = len(ws.framework.decisions(kind="constraint_unchecked"))
    ws.capture.log(ai, "exec.valve_close", objects=["3号阀"])
    assert len(ws.framework.decisions(kind="constraint_unchecked")) == before  # 检查过就不再生成


def test_explore_mode_hides_process_by_default(ws, ai):
    p = ws.judgments.write(ai, kind="process", text="冷凝水回收率为什么偏低？")
    assert any(h["id"] == p["id"] for h in ws.retrieval.search("回收率")["hits"])
    assert not any(h["id"] == p["id"] for h in ws.retrieval.search("回收率", mode="explore")["hits"])
    assert any(h["id"] == p["id"] for h in ws.retrieval.search("回收率", mode="explore", include_process=True)["hits"])


def test_explore_mode_hides_framework_and_stale_index(ws, human, ai):
    ent = ws.frameworks.entity_upsert(human, kind="device", name="冷却塔")
    page = ws.frameworks.page_write(human, type="entity", title="冷却塔", body="冷却塔风机振动偏大",
                                    subject_id=ent["id"])
    assert any(h["id"] == page["id"] for h in ws.retrieval.search("风机振动")["hits"])
    assert not any(h["layer"] == "framework" for h in ws.retrieval.search("风机振动", mode="explore")["hits"])
    ws.frameworks.page_write(human, type="entity", title="冷却塔", body="冷却塔已更换轴承", subject_id=ent["id"])
    hit = ws.retrieval.search("风机振动")["hits"][0]  # 只有旧版命中：返回当前版，旧版命中列在 old_hits（设计稿 10 D-19）
    assert hit["ref"] == f"{page['id']}@2" and hit["old_hits"][0]["ref"] == f"{page['id']}@1"
    assert ws.retrieval.search("更换轴承")["hits"]


def test_expand_order(ws, ai, pump_log):
    rd = ws.artifacts.read(ai, pump_log["id"], "seg:1")["read"]
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵压力 0.82 MPa", cites=[rd["id"]])
    out = ws.retrieval.expand(f"{pump_log['id']}#seg-2")
    assert {s["ordinal"] for s in out["neighbors"]} == {1, 2, 3}
    out_rd = ws.retrieval.expand(rd["id"])
    assert out_rd["interpretations"][0]["judgment_id"] == j["id"]
    assert "interpretations" not in ws.retrieval.expand(rd["id"], mode="explore")


def test_short_query_and_exact_identifier(ws, human):
    ent = ws.frameworks.entity_upsert(human, kind="device", name="P-102")
    ws.judgments.write(human, kind="conclusion", text="泵在下午停机", local_observation=True, objects=["P-102"])
    hits = ws.retrieval.search("P-102")["hits"]
    assert hits and hits[0].get("exact")
    assert ws.retrieval.search("停机")["hits"]  # 不足 3 个字时退回 LIKE
    assert ws.retrieval.timeline(ent["id"])


def test_index_rebuild(ws, ai, pump_log):
    ws.judgments.write(ai, kind="conclusion", text="冷凝水回收率偏低")
    before = len(ws.retrieval.search("回收率")["hits"])
    ws.index.clear()
    assert not ws.retrieval.search("回收率")["hits"]
    ws.rebuild_index()
    assert len(ws.retrieval.search("回收率")["hits"]) == before


def test_exact_identifier_excludes_process_log(ws, human, ai):
    ws.frameworks.entity_upsert(human, kind="device", name="V-301")
    ws.judgments.write(ai, kind="conclusion", text="入口阀开度 60%", objects=["V-301"])  # 同时写了一条带对象的过程事件
    ids = [h["id"] for h in ws.retrieval.search("V-301")["hits"]]
    assert ids and not any(i.startswith("evt_") for i in ids)
    assert any(h["id"].startswith("evt_") for h in ws.retrieval.search("V-301", include_log=True)["hits"])


def test_constraints_are_normative_not_evidence_ranked(ws, human):
    c = ws.judgments.write(human, kind="normative", text="检修完成前不要调整 V-301 开度")
    coords = ws.coordinates.of(c["id"])
    assert coords["kind"] == "normative" and coords["sources"] == [] and coords["notes"]["marks"] == []
