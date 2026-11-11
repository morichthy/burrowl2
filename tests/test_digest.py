"""设计稿 09：消化外部材料、文献论断、按来源筛选、依据构成、关系图两轴筛选、高依赖的外部论断。"""
import pytest

from burrowl.core.actor import Actor
from burrowl.core.errors import BurrowlError
from burrowl.services import model_adapters

PAPER = """# 低温下泵的气蚀

在 5 °C 进水条件下，2号泵型号的气蚀余量比常温高 0.4 m。

本文只测试了一种叶轮。
"""


@pytest.fixture
def other_ai():
    return Actor("ai:other", "ai", "ses_01JC0000000000000000000009")


@pytest.fixture
def paper(ws, human):
    return ws.artifacts.register(human, kind="literature", source_class="external", text=PAPER,
                                 title="低温气蚀", external_tier="peer_reviewed")


def claim(ws, ai, paper, **kw):
    art = paper["id"]
    ws.artifacts.read(ai, art, "seg-1")
    return ws.judgments.write(ai, kind="conclusion", text="5 °C 进水时气蚀余量比常温高 0.4 m",
                              cites=[f"{art}#seg-1"], objects=["2号泵"], **kw)


# ---------- AC-01：文献论断标签与来源筛选 ----------
def test_external_claim_label_and_source_filter(ws, human, ai, paper, pump_log):
    c1 = claim(ws, ai, paper, external_author="Li et al., 2020", conditions="5 °C 进水；原文未说明：流量")
    ws.artifacts.read(ai, pump_log["id"], "seg-1")
    local = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力 0.82 MPa",
                               cites=[f"{pump_log['id']}#seg-1"], objects=["2号泵"])
    mixed = ws.judgments.write(ai, kind="conclusion", text="2号泵在低温下气蚀余量更高，出口压力 0.82 MPa",
                               cites=[f"{paper['id']}#seg-1", f"{pump_log['id']}#seg-1"], objects=["2号泵"])
    coords = ws.retrieval.coordinates
    assert coords(c1["id"])["external_claim"] is True
    assert coords(local["id"])["external_claim"] is False
    assert coords(mixed["id"])["external_claim"] is False  # 混了本地实证的不算
    assert "文献论断" in ws.retrieval.status_note(coords(c1["id"]))

    ids = {h["id"] for h in ws.retrieval.search("气蚀 压力", source="local")["hits"]}
    assert local["id"] in ids and c1["id"] not in ids and mixed["id"] not in ids
    assert paper["id"] not in ids
    ext = {h["id"] for h in ws.retrieval.search("气蚀 压力", source="external")["hits"]}
    assert c1["id"] in ext and mixed["id"] in ext and local["id"] not in ext
    with pytest.raises(BurrowlError):
        ws.retrieval.search("气蚀", source="bogus")


# ---------- AC-04：条件未说明 ----------
def test_conditions_unstated_notice(ws, ai, paper):
    j = claim(ws, ai, paper, external_author="Li et al., 2020")
    assert "CONDITIONS_UNSTATED" in j["warning_codes"]
    c = ws.retrieval.coordinates(j["id"])
    assert c["conditions_unstated"] is True
    assert "条件未说明" in ws.retrieval.status_note(c)
    j2 = claim(ws, ai, paper, external_author="Li et al., 2020", conditions="5 °C 进水")
    assert "CONDITIONS_UNSTATED" not in j2["warning_codes"]


# ---------- AC-02：消化记录与待消化 ----------
def test_digest_pending_submit_skip(ws, human, ai, other_ai, paper, pump_log):
    pending = {i["id"] for i in ws.digest.pending()["items"]}
    assert paper["id"] in pending and pump_log["id"] not in pending  # 本地实证原件不进待消化

    j = claim(ws, ai, paper, external_author="Li et al., 2020", conditions="5 °C 进水")
    with pytest.raises(BurrowlError):  # 不是本会话写的
        ws.digest.submit(other_ai, artifact_id=paper["id"], claims=[j["id"]])
    with pytest.raises(BurrowlError):  # 零条论断要写原因
        ws.digest.submit(ai, artifact_id=paper["id"], claims=[])
    ws.artifacts.read(ai, pump_log["id"], "seg-1")
    other = ws.judgments.write(ai, kind="conclusion", text="出口压力 0.82 MPa", cites=[f"{pump_log['id']}#seg-1"])
    with pytest.raises(BurrowlError):  # 没引用这份原件
        ws.digest.submit(ai, artifact_id=paper["id"], claims=[other["id"]])

    out = ws.digest.submit(ai, artifact_id=paper["id"], claims=[j["id"]])
    assert out["claims"] == [j["id"]]
    assert paper["id"] not in {i["id"] for i in ws.digest.pending()["items"]}
    view = ws.digest.view(paper["id"])
    assert view["claims"] == [j["id"]] and not view["pending"]
    # 系统流水：不进操作日志
    ev = ws.ledger.get(out["event_id"])
    assert ev["op"] == "digest.submit"

    # 新版本重新进入待消化
    v2 = ws.artifacts.register(human, kind="literature", source_class="external", text=PAPER + "\n补充数据。\n",
                               title="低温气蚀 v2", version_of=paper["id"])
    assert v2["id"] in {i["id"] for i in ws.digest.pending()["items"]}

    # 跳过只能由人做
    with pytest.raises(BurrowlError):
        ws.digest.skip(ai, artifact_id=v2["id"])
    ws.digest.skip(human, artifact_id=v2["id"], reason="只是补了附录")
    assert v2["id"] not in {i["id"] for i in ws.digest.pending()["items"]}


def test_digest_note_only_and_prompt(ws, ai, paper):
    ws.digest.submit(ai, artifact_id=paper["id"], claims=[], note="综述，没有自己的发现")
    assert ws.digest.pending()["total"] == 0
    with pytest.raises(BurrowlError):
        ws.digest.prompt()


def test_digest_list_calls_no_llm(ws, paper, monkeypatch):
    """AC-03：算待消化清单时不调用大模型或 agent（I12）。"""
    def boom(*a, **k):
        raise AssertionError("算待消化清单时调用了大模型或 agent")
    for name in ("llm_check", "llm_health", "llm_formula"):
        monkeypatch.setattr(model_adapters, name, boom)
    monkeypatch.setattr(ws.agents, "start", boom)
    assert ws.digest.pending()["total"] == 1
    assert paper["id"] in ws.digest.prompt()
    assert ws.inspection.status()["digest_pending"] == 1


# ---------- AC-05：页面的依据构成 ----------
def test_basis_mix(ws, human, ai, paper, pump_log):
    c1 = claim(ws, ai, paper, external_author="Li et al., 2020", conditions="5 °C 进水")
    ws.artifacts.read(ai, pump_log["id"], "seg-1")
    local = ws.judgments.write(ai, kind="conclusion", text="出口压力 0.82 MPa", cites=[f"{pump_log['id']}#seg-1"])
    page = ws.frameworks.page_write(ai, type="synthesis", title="2号泵低温运行", body="正文",
                                    inputs=[c1["id"], local["id"], paper["id"]])
    mix = ws.frameworks.page_get(page["id"])["basis_mix"]
    assert mix["local"] == 1 and mix["external"] == 2 and mix["external_only_claims"] == 1
    assert "只有外部依据的结论 1" in mix["note"]


# ---------- AC-07：关系图两轴筛选 ----------
def test_graph_axes(ws, human, ai, paper, pump_log):
    c1 = claim(ws, ai, paper, external_author="Li et al., 2020", conditions="5 °C 进水")
    ws.artifacts.read(ai, pump_log["id"], "seg-1")
    local = ws.judgments.write(ai, kind="conclusion", text="出口压力 0.82 MPa", cites=[f"{pump_log['id']}#seg-1"],
                               relations=[{"rel": "supports", "target": c1["id"]}])
    proc = ws.judgments.write(ai, kind="process", text="低温下要不要换叶轮？还没定")
    ws.frameworks.page_write(ai, type="synthesis", title="低温", body="正文", inputs=[c1["id"]])

    def ids(**kw):
        return {n["id"] for n in ws.overview.graph(**kw)["nodes"]}

    explore = ids(node_types=["artifact", "record", "judgment"], layers=["original", "judgment"],
                  judgment_kinds=["conclusion", "normative"])
    assert proc["id"] not in explore and c1["id"] in explore
    assert not any(i.startswith(("pg_", "ent_")) for i in explore)

    only_local = ids(source_classes=["local"], source_mode="only", layers=["original", "judgment"])
    assert local["id"] in only_local and pump_log["id"] in only_local
    assert c1["id"] not in only_local and paper["id"] not in only_local

    literature = ids(source_classes=["external"], layers=["original", "judgment"])
    assert c1["id"] in literature and local["id"] not in literature
    with_related = ids(source_classes=["external"], layers=["original", "judgment"], keep_related=True)
    assert local["id"] in with_related  # 支持文献论断的本地判断

    claims_only = ids(judgment_kinds=["external_claim"], layers=["judgment"])
    assert claims_only == {c1["id"]}


# ---------- AC-09：高依赖的外部论断 ----------
def test_external_reliance_check(ws, human, ai, other_ai, paper, pump_log):
    c1 = claim(ws, ai, paper, external_author="Li et al., 2020", conditions="5 °C 进水")
    for text in ("低温季节要提高入口压力", "低温季节要检查叶轮"):
        ws.judgments.write(other_ai, kind="conclusion", text=text, cites=[c1["id"]])
    status = ws.inspection.prepare(human)
    tasks = ws.framework.inspection(status["id"])["data"]["tasks"]
    hit = [t for t in tasks if t["check"] == "external_reliance"]
    assert [t["targets"] for t in hit] == [[c1["id"]]]
    ws.inspection.close(human, inspection_id=status["id"])

    # 有了本地实证的支持后不再生成
    ws.artifacts.read(ai, pump_log["id"], "seg-1")
    ws.judgments.write(ai, kind="conclusion", text="本地测得同样趋势", cites=[f"{pump_log['id']}#seg-1"],
                       relations=[{"rel": "supports", "target": c1["id"]}])
    status = ws.inspection.prepare(human)
    tasks = ws.framework.inspection(status["id"])["data"]["tasks"]
    assert not [t for t in tasks if t["check"] == "external_reliance"]
