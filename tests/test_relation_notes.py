"""关系说明、行内引用 [^n]、判断字段与人工更正（设计稿 11；AC-01 至 AC-05b）。"""
import pytest

from burrowl.core.errors import BurrowlError
from burrowl.interfaces.registry import Ctx, call


def note_marks(c):
    return {m["mark"] for m in c["notes"]["marks"]}


@pytest.fixture
def seg(ws, ai, pump_log):
    return ws.artifacts.read(ai, pump_log["id"], "seg:1")["cite_as"][0]


def write(ws, ai, text, **kw):
    return ws.judgments.write(ai, kind="conclusion", text=text, **kw)


# ---------- AC-01：关系说明 ----------
def test_notes_on_cites_and_other_relations_are_returned_both_ways(ws, ai, seg):
    base = write(ws, ai, "2号泵出口压力 0.82 MPa", cites=[seg])
    j = write(ws, ai, "2号泵压力正常[^1]，与上一条相符",
              cites=[{"ref": seg, "why": "这一段给出 0.82 MPa", "role": "数据", "marker": "1"}],
              relations=[{"rel": "supports", "target": base["id"], "why": "数值一致", "role": "数值一致"}])
    assert j["markers"] == {"1": 1}
    out = ws.relations.of(j["ref"])["out"]
    cite = next(r for r in out if r["predicate"] == "cites")
    assert cite["qualifiers"]["why"] == "这一段给出 0.82 MPa" and cite["qualifiers"]["role"] == "数据"
    assert cite["qualifiers"]["marker"] == "1" and cite["qualifiers"]["sha256"]  # 原有的指纹还在
    sup = next(r for r in out if r["predicate"] == "supports")
    assert sup["qualifiers"] == {"why": "数值一致", "role": "数值一致"}
    # 反向关系由关系表推出：被引的一方在入边里看到说明，且它的版本没有变
    incoming = ws.relations.of(base["id"])["in"]
    assert [x["qualifiers"]["why"] for x in incoming if x["predicate"] == "supports"] == ["数值一致"]
    assert ws.ledger.head_version(base["id"]) == 1
    art_id = seg.split("#")[0]
    assert any(x["qualifiers"].get("why") == "这一段给出 0.82 MPa" for x in ws.relations.of(art_id)["in"])
    assert ws.ledger.head_version(art_id) == 1


def test_notes_are_optional_and_reason_folds_into_why(ws, ai, seg):
    j = write(ws, ai, "没有说明的依据", cites=[seg], conditions="巡检记录")
    assert "why" not in ws.relations.of(j["ref"])["out"][0]["qualifiers"] and j["warnings"] == []
    other = write(ws, ai, "对立的说法", cites=[seg], relations=[
        {"rel": "opposes", "target": j["id"], "reason": "数值冲突"}])
    opp = next(r for r in ws.relations.of(other["ref"])["out"] if r["predicate"] == "opposes")
    assert opp["qualifiers"] == {"why": "数值冲突"}


# ---------- AC-02：[^n] 与关系对得上 ----------
def test_dangling_and_extra_markers_are_rejected(ws, ai, seg):
    with pytest.raises(BurrowlError) as e:
        write(ws, ai, "正文里有标记[^1]但没有关系", cites=[seg])
    assert e.value.code == "INVALID_ARGUMENT" and e.value.details["markers"] == ["1"]
    with pytest.raises(BurrowlError) as e:
        write(ws, ai, "正文里没有标记", cites=[{"ref": seg, "marker": "2"}])
    assert e.value.details["markers"] == ["2"]
    assert ws.ledger.query("SELECT COUNT(*) AS n FROM judgments")[0]["n"] == 0  # 被拒绝的整条都没有写入


def test_one_marker_for_several_relations_and_marker_formats(ws, ai, pump_log):
    a = ws.artifacts.read(ai, pump_log["id"], "seg:1")["cite_as"][0]
    b = ws.artifacts.read(ai, pump_log["id"], "seg:2")["cite_as"][0]
    j = write(ws, ai, "压力与开度见原文[^1]，同一句引用两处[^1]",
              cites=[{"ref": a, "marker": 1}, {"ref": b, "marker": "[^1]"}])
    assert j["markers"] == {"1": 2}
    with pytest.raises(BurrowlError) as e:  # 同一条依据不能带两个标记
        write(ws, ai, "甲[^1]乙[^2]", cites=[{"ref": a, "marker": "1"}, {"ref": a, "marker": "2"}])
    assert "只能带一个标记" in e.value.message


def test_marker_must_be_digits(ws, ai, seg):
    with pytest.raises(BurrowlError) as e:
        write(ws, ai, "甲[^1]", cites=[{"ref": seg, "marker": "a"}])
    assert e.value.code == "INVALID_ARGUMENT"


def test_wiki_refs_in_text_still_become_cites(ws, ai, seg):
    base = write(ws, ai, "基础结论", cites=[seg])
    j = write(ws, ai, f"见 [[{base['id']}]]")
    assert [r["predicate"] for r in ws.relations.of(j["ref"])["out"]] == ["cites"]


# ---------- 改写沿用说明 ----------
def test_revise_carries_notes_and_strips_stale_markers(ws, ai, seg):
    j = write(ws, ai, "压力 0.82 MPa[^1]", cites=[{"ref": seg, "why": "读数", "role": "数据", "marker": "1"}])
    kept = ws.judgments.revise(ai, j["id"], text="压力 0.82 MPa[^1]（复核）", reason="补充")
    q = ws.relations.of(kept["ref"])["out"][0]["qualifiers"]
    assert q["why"] == "读数" and q["marker"] == "1"
    dropped = ws.judgments.revise(ai, j["id"], text="压力 0.82 MPa（去掉标记）", reason="去掉引用标记")
    q = ws.relations.of(dropped["ref"])["out"][0]["qualifiers"]
    assert q["why"] == "读数" and "marker" not in q  # 关系还在，只去掉对不上的标记
    with pytest.raises(BurrowlError):  # 显式给的 cites 要严格对上
        ws.judgments.revise(ai, j["id"], text="没有标记", cites=[{"ref": seg, "marker": "1"}], reason="x")


# ---------- AC-03：索引与返回不含标记 ----------
def test_markers_are_not_indexed_or_shown_in_snippets(ws, ai, seg):
    j = write(ws, ai, "出口压力稳定在 0.82 MPa[^1]", cites=[{"ref": seg, "marker": "1"}])
    hits = ws.retrieval.search("出口压力稳定")["hits"]
    hit = next(h for h in hits if h["id"] == j["id"])
    assert "[^" not in hit["text"] and "[^" not in str(hit.get("passages"))
    assert not [h for h in ws.retrieval.search("[^1]")["hits"] if h["id"] == j["id"]]
    assert "[^1]" in ws.get(j["ref"])["data"]["text"]  # 落盘的正文保留标记
    label = ws.overview.entry_label(j["ref"])
    assert "[^" not in (label or "")


# ---------- AC-04：scope_unclear ----------
def test_scope_unclear_is_an_explicit_field(ws, ai, human, seg):
    j = write(ws, ai, "150 ℃ 下强度下降", cites=[seg], conditions="已知：试样 S1；不清楚：其他温度",
              scope_unclear=True)
    c = ws.coordinates.of(j["ref"])
    assert "scope_unclear" in note_marks(c) and "适用范围未明" in ws.retrieval.status_note(c)
    plain = write(ws, ai, "条件里碰巧写了：适用范围未明", cites=[seg], conditions="适用范围未明：x")
    assert "scope_unclear" not in note_marks(ws.coordinates.of(plain["ref"]))  # 系统不按写法推断
    assert c["sources"] == ws.coordinates.of(plain["ref"])["sources"]
    revised = ws.judgments.revise(ai, j["id"], text="150 ℃ 下强度下降（更新）", reason="x")
    assert "scope_unclear" in note_marks(ws.coordinates.of(revised["ref"]))  # 沿用
    cleared = ws.versions.correct(human, j["id"], reason="范围已澄清", scope_unclear=False)
    assert "scope_unclear" not in note_marks(ws.coordinates.of(cleared["ref"]))


# ---------- AC-05b：人工更正 ----------
def test_one_correction_changes_fields_and_relations_in_one_version(ws, ai, human, seg):
    j = write(ws, ai, "压力 0.82 MPa[^1]", cites=[{"ref": seg, "why": "读数", "marker": "1"}],
              conditions="旧条件", external_author="某文献", objects=["2号泵"])
    other = write(ws, ai, "另一条", cites=[seg])
    cites_rel = next(r for r in ws.relations.of(j["ref"])["out"] if r["predicate"] == "cites")
    v = ws.versions.correct(human, j["id"], reason="校对", conditions="新条件", external_author="",
                            objects=["2号泵", "V-301"], scope_unclear=True, text="压力 0.82 MPa[^1]（校对）",
                            relations_add=[{"predicate": "supports", "target": other["id"], "why": "数值一致"}])
    assert v["version"] == 2 and ws.ledger.head_version(j["id"]) == 2
    d = ws.ledger.get(j["ref"].split("@")[0])
    assert d["data"]["conditions"] == "新条件" and not d["data"].get("external_author")
    assert d["data"]["scope_unclear"] is True and set(d["objects"]) >= {"2号泵", "v-301"}
    history = ws.versions.history(j["id"])["versions"]
    assert history[0]["fields_changed"] == []
    assert set(history[1]["fields_changed"]) == {"text", "conditions", "scope_unclear", "external_author", "objects"}
    out = {r["predicate"]: r for r in ws.relations.of(v["ref"])["out"]}
    assert out["cites"]["qualifiers"]["why"] == "读数" and out["cites"]["qualifiers"]["marker"] == "1"
    assert out["supports"]["qualifiers"]["why"] == "数值一致"
    # 去掉依据：关系只在新版本上消失，旧版本保留
    v3 = ws.versions.correct(human, j["id"], reason="去掉依据", relations_remove=[out["supports"]["id"]])
    assert [r["predicate"] for r in ws.relations.of(v3["ref"])["out"]] == ["cites"]
    assert any(r["predicate"] == "supports" for r in ws.relations.of(f"{j['id']}@2")["out"])
    assert cites_rel["id"]  # 旧版关系行仍在


def test_correction_needs_a_change_and_a_reason(ws, ai, human, seg):
    j = write(ws, ai, "x", cites=[seg])
    with pytest.raises(BurrowlError):
        ws.versions.correct(human, j["id"], reason="没改任何东西")
    with pytest.raises(BurrowlError):
        ws.versions.correct(human, j["id"], reason="", conditions="c")


def test_kind_change_to_process_is_checked_against_dependents(ws, ai, human, seg):
    base = write(ws, ai, "基础结论", cites=[seg])
    write(ws, ai, "被依据的结论", cites=[base["id"]])
    with pytest.raises(BurrowlError) as e:
        ws.versions.correct(human, base["id"], reason="改成过程", kind="thought", subkind="attempt")
    assert e.value.code == "THOUGHT_NOT_EVIDENCE"
    free = write(ws, ai, "没人依据")
    assert ws.versions.correct(human, free["id"], reason="改成规定", kind="constraint", subkind="action")["kind"] == "constraint"


def test_human_relate_keeps_notes_and_accepts_why_role(ws, ai, human, seg):
    j = write(ws, ai, "压力[^1]", cites=[{"ref": seg, "why": "读数", "role": "数据", "marker": "1"}])
    other = write(ws, ai, "旁证", cites=[seg])
    new = call(Ctx(ws, human, "http"), "entry.relate", {
        "id": j["id"], "reason": "补佐证", "add": [{"predicate": "supports", "target": other["id"],
                                                    "why": "旁证一致", "role": "数值一致"}]})
    out = {r["predicate"]: r["qualifiers"] for r in ws.relations.of(new["ref"])["out"]}
    assert out["cites"]["why"] == "读数" and out["cites"]["marker"] == "1"
    assert out["supports"] == {"why": "旁证一致", "role": "数值一致"}


def test_artifact_fields_can_be_corrected_without_new_content(ws, human, pump_log):
    before = ws.extraction.segments(ws.ledger.get(pump_log["ref"]))
    v = ws.versions.correct(human, pump_log["id"], reason="改标题与来源", title="2号泵巡检（校对）",
                            source_class="external", external_tier="vendor", metadata={"note": "厂家资料"},
                            objects=["2号泵"])
    assert v["version"] == 2 and v["sha256"] == pump_log["sha256"] and v["source_class"] == "external"
    assert v["data"]["title"] == "2号泵巡检（校对）" and v["data"]["external_tier"] == "vendor"
    assert v["data"]["metadata"]["note"] == "厂家资料" and "2号泵" in ws.ledger.get(v["id"])["objects"]
    assert [s["text"] for s in ws.extraction.segments(ws.ledger.get(v["ref"]))] == [s["text"] for s in before]
    assert ws.ledger.get(pump_log["ref"])["source_class"] == "local"  # 旧版不变
    with pytest.raises(BurrowlError):
        ws.versions.correct(human, pump_log["id"], reason="x", external_tier="nonsense")
    with pytest.raises(BurrowlError):  # 判断的字段不能用在原件上
        ws.versions.correct(human, pump_log["id"], reason="x", conditions="c")


def test_event_and_record_only_correct_text(ws, human):
    event = ws.capture.log(human, "measure.pressure", output="0.82")
    with pytest.raises(BurrowlError):
        ws.versions.correct(human, event["id"], reason="x", conditions="c")
    assert ws.versions.correct(human, event["id"], reason="x", text="0.83")["version"] == 2


def test_correction_ops_are_human_only(ws, ai, seg):
    j = write(ws, ai, "x", cites=[seg])
    for name, args in (("entry.correct", {"id": j["id"], "reason": "r", "conditions": "c"}),
                       ("entry.relate", {"id": j["id"], "reason": "r", "remove": ["rel_x"]})):
        with pytest.raises(BurrowlError) as e:
            call(Ctx(ws, ai, "mcp"), name, args)
        assert e.value.code == "FORBIDDEN"


def test_vocab_exports_role_hints(ws, human):
    v = call(Ctx(ws, human, "http"), "vocab.get", {})
    assert "定义" in v["role_hints"]["cites"] and "scope_unclear" in v["marks"]
