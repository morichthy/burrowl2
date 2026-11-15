"""设计稿 16：判断与要点共用的论断底子——写法检查（定义、上下文）、scope_unclear、抽取变化传到要点、
使用前须知随联想与展开返回、跨来源可能矛盾、关系图默认含要点。"""
import io

import pytest

from burrowl.services.claims import ClaimService, symbols_in

PAPER = """# 低温下泵的气蚀

在 5 °C 进水条件下，2号泵型号的气蚀余量 NPSH_r 比常温高 0.4 m。

气蚀余量 NPSH_r 指泵入口处总水头超出汽化压力水头的部分。

本文只测试了一种叶轮。
"""


@pytest.fixture
def paper(ws, human):
    return ws.artifacts.register(human, kind="literature", source_class="external", text=PAPER,
                                 title="低温气蚀", external_tier="peer_reviewed")


def write_point(ws, ai, art, **kw):
    ws.artifacts.read(ai, art)
    args = dict(title="2号泵型号 5 °C 进水时气蚀余量比常温高 0.4 m",
                text="Li 等对 2号泵型号的试验中，5 °C 进水时必需气蚀余量 NPSH_r（泵入口总水头超出汽化压力水头的"
                     "部分[^2]）比常温高 0.4 m[^1]。",
                cites=[{"ref": f"{art}#seg-1", "marker": "1", "role": "直接依据"},
                       {"ref": f"{art}#seg-2", "marker": "2", "role": "定义"}],
                conditions="5 °C 进水；原文未说明：流量。读过的范围：全文", external_author="Li et al., 2020",
                objects=["2号泵"])
    args.update(kw)
    return ws.frameworks.point_write(ai, **args)


# ---------- D-04 写法检查：判断与要点相同 ----------
def test_symbols_found_outside_markers_and_ids():
    assert symbols_in("有效步长 Δ_t=α·m̂_t/√v̂_t[^1]")
    assert not symbols_in("5 °C 进水时气蚀余量高 0.4 m[^1]，见 art_01ABC#seg-1")


def test_lint_codes_are_shared():
    notes = {"art_x#seg-1": {"role": "直接依据"}}
    codes = {c for c, _ in ClaimService.lint(text="该方法的 β_2 取 0.999[^1]", title="t", conditions="c",
                                             scope_unclear=False, notes=notes, needs_conditions=True, quoted=True)}
    assert codes == {"DEFINITION_UNCITED", "CONTEXT_DEPENDENT"}
    codes = {c for c, _ in ClaimService.lint(text="β_2 取 0.999[^1]", title="t", conditions=None, scope_unclear=True,
                                             notes={"a#s": {"role": "定义"}}, needs_conditions=True, quoted=True)}
    assert codes == set()


def test_point_and_judgment_get_the_same_writing_hints(ws, ai, paper):
    art = paper["id"]
    bad = dict(text="本文测得 NPSH_r 高 0.4 m[^1]。", cites=[{"ref": f"{art}#seg-1", "marker": "1", "role": "直接依据"}])
    p = write_point(ws, ai, art, **bad)
    j = ws.judgments.write(ai, kind="conclusion", conditions="5 °C", external_author="Li et al., 2020", **bad)
    for out in (p, j):
        assert {"DEFINITION_UNCITED", "CONTEXT_DEPENDENT"} <= set(out["warning_codes"])
    good = write_point(ws, ai, art)
    assert set(good["warning_codes"]) <= {"SIMILAR_POINT"}  # 与上面那条相似（设计稿 17 D-09），写法本身没有提示


def test_point_scope_unclear(ws, ai, paper):
    p = write_point(ws, ai, paper["id"], conditions=None, scope_unclear=True)
    assert "CONDITIONS_UNSTATED" not in p["warning_codes"]
    view = ws.frameworks.point_view(p["id"])
    assert view["scope_unclear"] is True and "适用范围未明" in view["status_note"]


def test_point_lint_reports_writing_problems(ws, ai, paper):
    art = paper["id"]
    write_point(ws, ai, art, text="本文测得 NPSH_r 高 0.4 m[^1]。",
                cites=[{"ref": f"{art}#seg-1", "marker": "1", "role": "直接依据"}])
    tasks = [t for t in ws.inspection._point_lint()]
    assert tasks and {"no_definition", "context_dependent"} <= set(tasks[0]["detail"]["codes"])


# ---------- D-09 抽取变化传到要点 ----------
def image_pdf() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), (240, 240, 240)).save(buf, format="PDF")
    return buf.getvalue()


def test_reextraction_marks_points_citing_changed_segment(ws, human, ai, tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(image_pdf())
    art = ws.artifacts.register(human, kind="literature", source_class="external", path=str(path),
                                external_tier="peer_reviewed")["id"]
    ws.extraction.submit(ai, art, method="ai", model="m1", content=[{"unit": "p1", "text": "压力 0.82 MPa"}])
    ws.artifacts.read(ai, art, "p1")
    p = ws.frameworks.point_write(ai, title="扫描件记压力 0.82 MPa", text="扫描件记的出口压力是 0.82 MPa[^1]。",
                                  cites=[{"ref": f"{art}#p1-1", "marker": "1", "role": "直接依据"}],
                                  conditions="原文未说明：工况。读过的范围：第 1 页")
    assert ws.framework.page(p["id"])["freshness"] == "valid"
    out = ws.extraction.submit(ai, art, method="ai", model="m2", content=[{"unit": "p1", "text": "压力 0.92 MPa"}])
    assert p["id"] in out["marked"]
    assert ws.framework.page(p["id"])["freshness"] == "inputs_changed"
    assert ws.framework.open_decision_for("rederive", p["id"])


# ---------- D-11 使用前须知：要点、联想、展开 ----------
def test_cautions_follow_points_associate_and_expand(ws, human, ai, paper):
    art = paper["id"]
    p = write_point(ws, ai, art)
    c = ws.judgments.write(ai, kind="constraint", subkind="usage", text="低温结论只测了一种叶轮，换叶轮前要复测",
                           cites=[f"{art}#seg-3"], relations=[{"rel": "targets", "target": f"{art}#seg-1"}])
    assert [x["ref"] for x in ws.retrieval.cautions_of(p["id"])] == [c["ref"]]
    hit = next(h for h in ws.retrieval.search("气蚀余量 0.4 m", limit=20)["hits"] if h["id"] == p["id"])
    assert hit["cautions"][0]["ref"] == c["ref"]
    assert ws.retrieval.expand(art)["cautions"][0]["ref"] == c["ref"]
    other = write_point(ws, ai, art, title="叶轮", text="试验只用了一种叶轮[^1]。",
                        cites=[{"ref": f"{art}#seg-3", "marker": "1", "role": "直接依据"}])
    assert ws.retrieval.cautions_of(other["id"]) == []  # 约束针对的是 seg-1，不是它引的 seg-3


# ---------- D-10 跨来源可能矛盾 ----------
def test_point_conflict_candidates(ws, human, ai, paper):
    art = paper["id"]
    write_point(ws, ai, art)
    log = ws.artifacts.register(human, kind="log", source_class="local", text="2号泵 5 °C 进水试验：气蚀余量比常温高 0.1 m。")
    ws.artifacts.read(ai, log["id"])
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵型号 5 °C 进水时气蚀余量比常温高 0.1 m[^1]。",
                           cites=[{"ref": f"{log['id']}#seg-0", "marker": "1"}], conditions="5 °C 进水",
                           objects=["2号泵"])
    tasks = ws.inspection._point_conflicts()
    assert len(tasks) == 1 and j["id"] in tasks[0]["targets"] and "数值不同" in tasks[0]["detail"]["reason"]
    ws.judgments.write(ai, kind="constraint", subkind="usage", text="文献与本地数值不同：叶轮与流量都不同",
                       cites=[f"{art}#seg-3"], relations=[{"rel": "targets", "target": f"{art}#seg-1"},
                                                         {"rel": "targets", "target": j["id"]}])
    assert ws.inspection._point_conflicts() == []  # 已有约束同时针对两边，条件已写清
