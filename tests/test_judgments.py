"""判断规则与身份规则（DESIGN §4：test_judgment_rules、test_actor_rules）。"""
import pytest

from burrowl.core.errors import BurrowlError


def test_framework_cannot_be_evidence(ws, human, ai):
    ent = ws.frameworks.entity_upsert(human, kind="device", name="2号泵")
    page = ws.frameworks.page_write(human, type="entity", title="2号泵", body="x", subject_id=ent["id"])
    with pytest.raises(BurrowlError) as e:
        ws.judgments.write(ai, kind="conclusion", text="2号泵有问题", cites=[page["id"]])
    assert e.value.code == "FRAMEWORK_NOT_EVIDENCE"
    with pytest.raises(BurrowlError):  # 正文里的 [[ID]] 也算依据
        ws.judgments.write(ai, kind="conclusion", text=f"见 [[{page['id']}]]")


def test_credibility_is_derived_by_system(ws, human, ai, pump_log):
    paper = ws.artifacts.register(human, kind="literature", source_class="external",
                                  text="离心泵在气蚀时压力波动增大。", external_tier="peer_reviewed")
    only_exec = ws.judgments.write(ai, kind="conclusion", text="2号泵 10:05 压力 0.87 MPa", cites=[pump_log["id"]])
    mixed = ws.judgments.write(ai, kind="conclusion", text="2号泵压力波动可能来自气蚀", cites=[pump_log["id"], paper["id"]])
    bare = ws.judgments.write(ai, kind="conclusion", text="2号泵可能需要检修")
    c1, c2, c3 = (x["data"]["credibility"] for x in (only_exec, mixed, bare))
    assert c1["all_local"] and c1["source_classes"] == ["local"]
    assert not c2["all_local"] and c2["mixed"] and c2["source_classes"] == ["external", "local"]
    assert c2["external_tiers"] == ["peer_reviewed"]
    assert c3["source_classes"] == ["inferred"] and bare["warnings"]
    # 派生判断继承依据的全部来源
    derived = ws.judgments.write(ai, kind="conclusion", text="2号泵需要做气蚀检查", cites=[mixed["id"]])
    assert derived["data"]["credibility"]["source_classes"] == ["external", "local"]


def test_local_observation_only_by_human(ws, human, ai):
    h = ws.judgments.write(human, kind="conclusion", text="现场看到 2号泵 出口法兰有渗漏", local_observation=True)
    plain = ws.judgments.write(human, kind="conclusion", text="2号泵 法兰可能需要更换")
    a = ws.judgments.write(ai, kind="conclusion", text="现场人员说 2号泵 出口法兰有渗漏")
    assert h["data"]["credibility"]["source_classes"] == ["local"] and h["data"]["credibility"]["all_local"]
    assert plain["data"]["credibility"]["source_classes"] == ["inferred"]  # 没勾选本地实证就是推断
    assert a["data"]["credibility"]["source_classes"] == ["inferred"]  # AI 转述，人确认前不是人的判断
    with pytest.raises(BurrowlError) as e:
        ws.judgments.write(ai, kind="conclusion", text="我看到了渗漏", local_observation=True)
    assert e.value.code == "FORBIDDEN"


def test_only_three_kinds_and_system_records(ws, human, ai):
    for old in ("claim", "observation", "question", "constraint", "decision", "stop_reason"):
        with pytest.raises(BurrowlError):
            ws.judgments.write(human, kind=old, text="x")


def test_process_is_not_evidence_for_conclusions(ws, human, ai, pump_log):
    q = ws.judgments.write(ai, kind="process", text="2号泵压力波动是否来自入口气蚀？", objects=["2号泵"])
    stop = ws.judgments.write(ai, kind="process", text="停止排查电机：电流平稳", reopen_condition="电流出现周期性波动",
                              cites=[pump_log["id"]])
    assert stop["data"]["reopen_condition"] == "电流出现周期性波动"
    for bad in ({"cites": [q["id"]]}, {"relations": [{"rel": "depends_on", "target": q["id"]}]}):
        with pytest.raises(BurrowlError) as e:
            ws.judgments.write(ai, kind="conclusion", text="2号泵有气蚀", **bad)
        assert e.value.code == "PROCESS_NOT_EVIDENCE"
    # 回答提问可以；过程内容可以引用过程内容
    ans = ws.judgments.write(ai, kind="conclusion", text="入口压力正常，不是气蚀", cites=[pump_log["id"]],
                             relations=[{"rel": "answers", "target": q["id"]}])
    assert ws.judgments.status(q["id"])["answered_by"] == [ans["id"]]
    ws.judgments.write(ai, kind="process", text="下一步查出口阀", cites=[q["id"]])
    with pytest.raises(BurrowlError):
        ws.judgments.write(ai, kind="conclusion", text="x", reopen_condition="y")


def test_ai_cannot_correct_or_retract(ws, human, ai):
    j = ws.judgments.write(ai, kind="conclusion", text="V-301 开度 60%")
    for kind in ("correction", "retraction", "defect", "review"):  # 系统记录
        with pytest.raises(BurrowlError) as e:
            ws.judgments.write(ai, kind=kind, text="不对")
        assert e.value.code == "FORBIDDEN"
    with pytest.raises(BurrowlError):
        ws.judgments.write(ai, kind="conclusion", text="x", relations=[{"rel": "retracts", "target": j["id"]}])
    with pytest.raises(BurrowlError):
        ws.judgments.amend(ai, mode="retraction", target=j["id"], reason="不对")
    # AI 只能写反对
    opp = ws.judgments.write(ai, kind="conclusion", text="V-301 开度实际为 40%", relations=[{"rel": "opposes",
                                                                                     "target": j["id"]}])
    assert ws.judgments.status(j["id"])["opposed_by"] == [opp["id"]]


def test_human_amend_keeps_original(ws, human, ai, pump_log):
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵压力正常", cites=[pump_log["id"]])
    fix = ws.judgments.amend(human, mode="correction", target=j["id"], reason="10:05 的 0.87 MPa 已超过上限")
    assert ws.ledger.get(j["id"])["data"]["text"] == "2号泵压力正常"
    st = ws.judgments.status(j["id"])
    assert st["superseded"] and st["corrected"] and st["superseded_by"] == [fix["id"]]
    defect = ws.judgments.amend(human, mode="defect", target=pump_log["id"], reason="压力表未标定")
    assert defect["kind"] == "defect"
    later = ws.judgments.write(ai, kind="conclusion", text="2号泵压力 0.82 MPa", cites=[pump_log["id"]])
    assert later["data"]["credibility"]["basis_complete"] is False  # 有缺陷的原件让依据不完整


def test_revision_only_by_same_author(ws, human, ai):
    j = ws.judgments.write(human, kind="conclusion", text="V-301 应保持全开")
    with pytest.raises(BurrowlError):
        ws.judgments.write(ai, kind="conclusion", text="V-301 保持 60%", revises=j["id"], revise_reason="新数据")
    with pytest.raises(BurrowlError):
        ws.judgments.write(human, kind="conclusion", text="V-301 保持 60%", revises=j["id"])
    v2 = ws.judgments.write(human, kind="conclusion", text="V-301 保持 60% 开度", revises=j["id"], revise_reason="新数据")
    assert ws.judgments.status(j["id"])["superseded_by"] == [v2["id"]]


def test_coexists_requires_condition(ws, ai):
    a = ws.judgments.write(ai, kind="conclusion", text="低负荷时 2号泵 压力 0.8 MPa")
    with pytest.raises(BurrowlError):
        ws.judgments.write(ai, kind="conclusion", text="高负荷时 2号泵 压力 0.9 MPa",
                           relations=[{"rel": "coexists_under", "target": a["id"]}])
    ok = ws.judgments.write(ai, kind="conclusion", text="高负荷时 2号泵 压力 0.9 MPa",
                            relations=[{"rel": "coexists_under", "target": a["id"], "condition": "负荷不同"}])
    assert ws.ledger.links_from(ok["id"], "coexists_under")[0]["data"]["condition"] == "负荷不同"


def test_independent_support(ws, human, ai):
    a1 = ws.artifacts.register(human, kind="log", source_class="local", text="第一次测量 0.87 MPa")
    a2 = ws.artifacts.register(Actor_other(), kind="log", source_class="local", text="第二次测量 0.88 MPa")
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵压力高于 0.85 MPa", cites=[a1["id"], a2["id"]])
    assert ws.judgments.status(j["id"])["independent_support"] == 2


def Actor_other():
    from burrowl.core.actor import Actor
    return Actor("human:other", "human", "ses_01JC0000000000000000000009")
