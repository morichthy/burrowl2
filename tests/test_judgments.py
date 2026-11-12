"""判断规则、身份规则、关系与版本（DESIGN §4：test_judgment_rules、test_actor_rules；设计稿 10 AC-02 至 AC-04）。"""
import pytest

from burrowl.core.actor import Actor
from burrowl.core.errors import BurrowlError


def coords(ws, ref):
    return ws.coordinates.of(ref)


def marks(c, group="state"):
    return {m["mark"]: m for m in c[group]["marks"]}


def test_framework_cannot_be_evidence(ws, human, ai):
    ent = ws.frameworks.entity_upsert(human, kind="device", name="2号泵")
    page = ws.frameworks.page_write(human, type="entity", title="2号泵", body="x", subject_id=ent["id"])
    with pytest.raises(BurrowlError) as e:
        ws.judgments.write(ai, kind="conclusion", text="2号泵有问题", cites=[page["id"]])
    assert e.value.code == "FRAMEWORK_NOT_EVIDENCE"
    with pytest.raises(BurrowlError):  # 正文里的 [[ID]] 也算依据
        ws.judgments.write(ai, kind="conclusion", text=f"见 [[{page['id']}]]")


def test_sources_are_derived_on_read(ws, human, ai, pump_log):
    """设计稿 10 D-05、D-13：判断只存事实；依据来源读取时由自己的 cites 推出，账本里没有推论字段。"""
    paper = ws.artifacts.register(human, kind="literature", source_class="external",
                                  text="离心泵在气蚀时压力波动增大。", external_tier="peer_reviewed")
    only_local = ws.judgments.write(ai, kind="conclusion", text="2号泵 10:05 压力 0.87 MPa", cites=[pump_log["id"]])
    mixed = ws.judgments.write(ai, kind="conclusion", text="2号泵压力波动可能来自气蚀",
                               cites=[pump_log["id"], paper["id"]])
    bare = ws.judgments.write(ai, kind="conclusion", text="2号泵可能需要检修")
    assert coords(ws, only_local["id"])["sources"] == ["local"]
    assert coords(ws, mixed["id"])["sources"] == ["local", "external:peer_reviewed"]
    assert coords(ws, bare["id"])["sources"] == ["inferred"] and bare["warnings"]
    assert "no_basis" in marks(coords(ws, bare["id"]), "notes")
    # 派生判断继承所引那一版的全部来源
    derived = ws.judgments.write(ai, kind="conclusion", text="2号泵需要做气蚀检查", cites=[mixed["id"]])
    assert coords(ws, derived["id"])["sources"] == ["local", "external:peer_reviewed"]
    for j in (only_local, mixed, bare, derived):
        assert set(j["data"]) <= {"text", "conditions", "reopen_condition", "external_author", "local_observation",
                                  "change_reason", "inspection_finding"}
    c = coords(ws, mixed["id"])
    assert set(c) == {"ref", "layer", "sources", "kind", "state", "notes"}
    assert c["ref"] == f"{mixed['id']}@1" and c["kind"] == "conclusion" and c["notes"]["author"] == "ai"


def test_local_observation_only_by_human(ws, human, ai):
    h = ws.judgments.write(human, kind="conclusion", text="现场看到 2号泵 出口法兰有渗漏", local_observation=True)
    plain = ws.judgments.write(human, kind="conclusion", text="2号泵 法兰可能需要更换")
    a = ws.judgments.write(ai, kind="conclusion", text="现场人员说 2号泵 出口法兰有渗漏")
    assert coords(ws, h["id"])["sources"] == ["local"]
    assert "local_observation" in marks(coords(ws, h["id"]), "notes")
    assert coords(ws, plain["id"])["sources"] == ["inferred"]  # 没勾选本地实证就是推断
    assert coords(ws, a["id"])["sources"] == ["inferred"]  # AI 转述，人确认前不是人的判断
    with pytest.raises(BurrowlError) as e:
        ws.judgments.write(ai, kind="conclusion", text="我看到了渗漏", local_observation=True)
    assert e.value.code == "FORBIDDEN"


def test_only_three_kinds(ws, human, ai):
    for old in ("claim", "observation", "question", "constraint", "decision", "stop_reason", "correction",
                "retraction", "defect", "review"):
        with pytest.raises(BurrowlError):
            ws.judgments.write(human, kind=old, text="x")


def test_process_is_not_evidence_for_conclusions(ws, human, ai, pump_log):
    q = ws.judgments.write(ai, kind="process", text="2号泵压力波动是否来自入口气蚀？", objects=["2号泵"])
    stop = ws.judgments.write(ai, kind="process", text="停止排查电机：电流平稳", reopen_condition="电流出现周期性波动",
                              cites=[pump_log["id"]])
    assert stop["data"]["reopen_condition"] == "电流出现周期性波动"
    # cites 的宾语、supports 的两端是证据一方：过程内容不行（AC-02）
    for bad in ({"cites": [q["id"]]}, {"relations": [{"rel": "supports", "target": q["id"]}]}):
        with pytest.raises(BurrowlError) as e:
            ws.judgments.write(ai, kind="conclusion", text="2号泵有气蚀", **bad)
        assert e.value.code == "PROCESS_NOT_EVIDENCE"
    # 回答提问可以；过程内容可以引用过程内容
    ans = ws.judgments.write(ai, kind="conclusion", text="入口压力正常，不是气蚀", cites=[pump_log["id"]],
                             relations=[{"rel": "answers", "target": q["id"]}])
    incoming = ws.relations.of(q["id"])["in"]
    assert [(x["predicate"], x["phrase"], x["other"]) for x in incoming] == [("answers", "被回答", ans["ref"])]
    ws.judgments.write(ai, kind="process", text="下一步查出口阀", cites=[q["id"]])
    with pytest.raises(BurrowlError):
        ws.judgments.write(ai, kind="conclusion", text="x", reopen_condition="y")


def test_predicates_core_and_free(ws, human, ai):
    """AC-02：AI 写人才能写的谓词被拒绝；不认识的谓词被拒绝；relates 必须带 label；两端都取得到；常用标签能列出。"""
    a = ws.judgments.write(ai, kind="conclusion", text="V-301 开度 60%")
    with pytest.raises(BurrowlError) as e:
        ws.judgments.write(ai, kind="conclusion", text="x", relations=[{"rel": "supersedes", "target": a["id"]}])
    assert e.value.code == "FORBIDDEN"
    for bad in ("retracts", "depends_on", "used", "may_contradict"):
        with pytest.raises(BurrowlError):
            ws.judgments.write(ai, kind="conclusion", text="x", relations=[{"rel": bad, "target": a["id"]}])
    with pytest.raises(BurrowlError):
        ws.judgments.write(ai, kind="conclusion", text="x", relations=[{"rel": "relates", "target": a["id"]}])
    b = ws.judgments.write(ai, kind="conclusion", text="V-301 开度变化导致出口压力变化",
                           relations=[{"rel": "relates", "label": "导致", "target": a["id"]}])
    out = ws.relations.of(b["id"])["out"]
    assert [(x["predicate"], x["label"], x["category"], x["phrase"]) for x in out] == \
        [("relates", "导致", "free", "导致")]
    assert ws.relations.of(a["id"])["in"][0]["other"] == b["ref"]
    assert ws.relations.free_labels() == [{"label": "导致", "count": 1}]
    # 自由谓词不算依据，也不产生标记
    assert coords(ws, a["id"])["state"]["marks"] == []
    # 人可以写替代
    c = ws.judgments.write(human, kind="conclusion", text="V-301 开度 40%",
                           relations=[{"rel": "supersedes", "target": a["id"]}])
    assert coords(ws, a["id"])["state"]["validity"] == "replaced"
    assert ws.relations.of(a["id"])["in"][-1]["phrase"] == "被替代" and c


def test_ai_cannot_correct_or_withdraw_others(ws, human, ai):
    j = ws.judgments.write(human, kind="conclusion", text="V-301 开度 60%")
    with pytest.raises(BurrowlError):
        ws.versions.change_state(ai, j["id"], "withdraw", "不对")
    with pytest.raises(BurrowlError):
        ws.versions.correct(ai, j["id"], reason="不对", text="V-301 开度 40%")
    with pytest.raises(BurrowlError) as e:  # AI 不能改写别人的判断
        ws.judgments.write(ai, kind="conclusion", text="V-301 开度 40%", revises=j["id"], revise_reason="新数据")
    assert e.value.code == "FORBIDDEN"
    # AI 只能写反驳：被反驳的一方现状里有标记，带出处
    opp = ws.judgments.write(ai, kind="conclusion", text="V-301 开度实际为 40%",
                             relations=[{"rel": "opposes", "target": j["id"]}])
    m = marks(coords(ws, j["id"]))["opposed"]
    assert m["via"][0]["end"] == opp["ref"] and m["via"][0]["rel"].startswith("rel_")


def test_human_correction_is_a_new_version_inheriting_facts(ws, human, ai, pump_log):
    """AC-03：人更正一条带原作者与关系的 AI 判断：新版保留原作者、对象、关系，最终作者为人。"""
    other = ws.judgments.write(ai, kind="conclusion", text="文献称 2号泵 同型号泵易气蚀")
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵压力正常", cites=[pump_log["id"]], objects=["2号泵"],
                           conditions="负荷 80%", external_author="Li et al., 2020",
                           relations=[{"rel": "opposes", "target": other["id"]}])
    v2 = ws.versions.correct(human, j["id"], reason="10:05 的 0.87 MPa 已超过上限", text="2号泵压力偏高")
    assert v2["id"] == j["id"] and v2["version"] == 2 and v2["ref"] == f"{j['id']}@2"
    assert ws.ledger.get(f"{j['id']}@1")["data"]["text"] == "2号泵压力正常"
    assert v2["data"]["external_author"] == "Li et al., 2020" and v2["data"]["conditions"] == "负荷 80%"
    assert v2["objects"] == ["2号泵"] and v2["author_kind"] == "human"
    rels = {(r["predicate"], r["object_id"]) for r in ws.ledger.relations_from(j["id"], version=2)}
    assert rels == {("cites", pump_log["id"]), ("opposes", other["id"])}
    c = coords(ws, j["id"])
    assert c["ref"] == v2["ref"] and c["notes"] == {"author": "human", "quoted": "Li et al., 2020", "marks": []}
    assert coords(ws, f"{j['id']}@1")["state"]["validity"] == "replaced"
    hist = ws.versions.history(j["id"])
    assert [v["version"] for v in hist["versions"]] == [1, 2]
    assert hist["versions"][1]["change_reason"].startswith("10:05") and hist["versions"][1]["author_kind"] == "human"


def test_ai_revises_own_judgment_in_same_session(ws, human, ai):
    j = ws.judgments.write(ai, kind="conclusion", text="V-301 应保持全开")
    with pytest.raises(BurrowlError):
        ws.judgments.write(ai, kind="conclusion", text="V-301 保持 60%", revises=j["id"])  # 没写理由
    v2 = ws.judgments.write(ai, kind="conclusion", text="V-301 保持 60% 开度", revises=j["id"],
                            revise_reason="新数据")
    assert v2["ref"] == f"{j['id']}@2" and v2["data"]["change_reason"] == "新数据"
    stranger = Actor("ai:other", "ai", "ses_01JC0000000000000000000005")
    with pytest.raises(BurrowlError):
        ws.judgments.write(stranger, kind="conclusion", text="x", revises=j["id"], revise_reason="y")


def test_citer_keeps_sources_but_sees_basis_changed(ws, human, ai, pump_log):
    """AC-05 的下游部分：所引判断出新版后，引用方的 sources 不变、带 basis_changed（出处带当前版）。"""
    base = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力 0.87 MPa", cites=[pump_log["id"]])
    user = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力超限", cites=[base["id"]])
    before = coords(ws, user["id"])
    ws.versions.correct(human, base["id"], reason="读数改正", text="2号泵出口压力 0.86 MPa")
    after = coords(ws, user["id"])
    assert after["sources"] == before["sources"] == ["local"]
    m = marks(after)["basis_changed"]
    assert m["via"][0]["end"] == f"{base['id']}@1" and m["via"][0]["current"] == f"{base['id']}@2"


def test_corroboration_does_not_change_standing(ws, human, ai, pump_log):
    """AC-04：被本地实证佐证的转述结论，sources 不变、现状有 corroborated（出处带佐证方的依据来源）。"""
    paper = ws.artifacts.register(human, kind="literature", source_class="external", text="离心泵气蚀时压力波动增大。",
                                  external_tier="peer_reviewed")
    claim = ws.judgments.write(ai, kind="conclusion", text="离心泵气蚀时出口压力波动增大", cites=[paper["id"]],
                               external_author="Li et al., 2020", conditions="离心泵")
    local = ws.judgments.write(ai, kind="conclusion", text="2号泵 压力波动 ±0.05 MPa", cites=[pump_log["id"]],
                               relations=[{"rel": "supports", "target": claim["id"]}])
    c = coords(ws, claim["id"])
    assert c["sources"] == ["external:peer_reviewed"]
    via = marks(c)["corroborated"]["via"][0]
    assert via["end"] == local["ref"] and via["detail"] == "本地实证"
    assert c["notes"]["quoted"] == "Li et al., 2020"
    assert "转述 · 原作者 Li et al., 2020" in ws.coordinates.note(c)


def test_conditions_unstated_mark(ws, human, ai):
    paper = ws.artifacts.register(human, kind="literature", source_class="external", text="某材料在高温下变脆。")
    j = ws.judgments.write(ai, kind="conclusion", text="某材料在高温下变脆", cites=[paper["id"]],
                           external_author="Wang 2019")
    assert "CONDITIONS_UNSTATED" in j["warning_codes"]
    assert "conditions_unstated" in marks(coords(ws, j["id"]), "notes")


def test_coexists_requires_condition(ws, ai):
    a = ws.judgments.write(ai, kind="conclusion", text="低负荷时 2号泵 压力 0.8 MPa")
    with pytest.raises(BurrowlError):
        ws.judgments.write(ai, kind="conclusion", text="高负荷时 2号泵 压力 0.9 MPa",
                           relations=[{"rel": "coexists_under", "target": a["id"]}])
    ok = ws.judgments.write(ai, kind="conclusion", text="高负荷时 2号泵 压力 0.9 MPa",
                            relations=[{"rel": "coexists_under", "target": a["id"], "condition": "负荷不同"}])
    assert ws.ledger.relations_from(ok["id"], "coexists_under")[0]["qualifiers"]["condition"] == "负荷不同"


def test_local_roots(ws, human, ai):
    a1 = ws.artifacts.register(human, kind="log", source_class="local", text="第一次测量 0.87 MPa")
    a2 = ws.artifacts.register(Actor("human:other", "human", "ses_01JC0000000000000000000009"), kind="log",
                               source_class="local", text="第二次测量 0.88 MPa")
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵压力高于 0.85 MPa", cites=[a1["id"], a2["id"]])
    m = marks(coords(ws, j["id"]), "notes")["local_roots"]
    assert m["count"] == 2
    assert "本地依据来自 2 个独立来源" in ws.coordinates.note(coords(ws, j["id"]))
