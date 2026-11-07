"""检索单元、词法双路、结果线索、字面查找（设计稿 04）。"""
from burrowl.index.tokenize import estimate_tokens, tokens
from burrowl.index.units import MAX, build_units

PAPER = """# 初始化偏差修正

Adam 用指数滑动平均估计梯度的一阶矩和二阶矩。

滑动平均从零开始，所以早期的估计偏向零。

为此 Adam 对两个矩估计都做偏差修正：除以 1 减去衰减率的 t 次方。

# 学习率

步长 alpha 给出了每一步更新幅度的近似上界。
"""


def test_tokens_bigram_and_identifiers():
    assert tokens("温度漂移") == ["温度", "度漂", "漂移"]
    assert "momentestimate" not in tokens("moment_estimate")
    assert {"moment_estimate", "moment", "estimate"} <= set(tokens("moment_estimate"))
    assert tokens("停机") == ["停机"]


def test_units_merge_short_segments_and_respect_headings():
    segs = [{"anchor": f"p1-{i}", "unit": "p1", "text": t, "heading": h}
            for i, (t, h) in enumerate([("1 引言", 1), ("短句一。", None), ("短句二。", None),
                                        ("2 方法", 1), ("方法正文。", None)], 1)]
    units = build_units(segs, title="论文")
    assert [u.anchors for u in units] == [["p1-1", "p1-2", "p1-3"], ["p1-4", "p1-5"]]
    assert units[1].context == "论文"  # 标题本身作为单元第一行，上下文是它的上一级
    long = [{"anchor": "seg-0", "text": "很长的句子。" * 400}]
    pieces = build_units(long)
    assert len(pieces) > 1 and all(estimate_tokens(u.text) <= MAX for u in pieces)
    assert all(u.anchors == ["seg-0"] for u in pieces)  # 切开的几块都指向同一段


def test_natural_language_and_two_char_queries(ws, human):
    art = ws.artifacts.register(human, kind="literature", source_class="external", text=PAPER, title="Adam 笔记")
    res = ws.retrieval.search("为什么 Adam 要对矩估计做偏差修正")
    assert res["hits"] and res["hits"][0]["id"] == art["id"]  # 部分命中也能召回（OR + bm25）
    hit = res["hits"][0]
    assert hit["cite_as"].startswith(art["id"] + "#seg-")
    assert hit["passages"][0]["anchors"] and hit["passages"][0]["read_as"]
    assert ws.retrieval.search("步长 上界")["hits"]  # 两个双字词不再整条退回 LIKE


def test_read_as_reads_the_passage_range(ws, human, ai):
    art = ws.artifacts.register(human, kind="literature", source_class="external", text=PAPER, title="Adam 笔记")
    p = ws.retrieval.search("偏差修正 滑动平均")["hits"][0]["passages"][0]
    out = ws.artifacts.read(ai, art["id"], p["read_as"])
    assert [s["anchor"] for s in out["segments"]] == p["anchors"]
    assert ws.retrieval.search("偏差修正", actor=ai)["hits"][0]["read_before"]


def test_more_matches_and_size(ws, human):
    text = "\n\n".join(f"# 第{i}节\n\n泵的振动记录第{i}条，振动值偏大。" for i in range(8))
    art = ws.artifacts.register(human, kind="log", source_class="local", text=text, title="振动日志")
    hit = ws.retrieval.search("振动")["hits"][0]
    assert hit["id"] == art["id"] and len(hit["passages"]) == 3
    assert hit["more_matches"] >= 1 and hit["size"]["units"] >= 4
    assert any("未展示" in h for h in ws.retrieval.search("振动")["hints"])


def test_basis_relations_and_explore_mode(ws, human, ai, pump_log):
    ws.artifacts.read(ai, pump_log["id"], "seg-1")
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力稳定在 0.82 MPa 附近",
                           cites=[f"{pump_log['id']}#seg-1"])
    page = ws.frameworks.page_write(human, type="synthesis", title="2号泵压力", body=f"压力见 [[{j['id']}]]")
    res = ws.retrieval.search("出口压力")
    by = {h["id"]: h for h in res["hits"]}
    assert by[j["id"]]["basis"][0]["ref"] == f"{pump_log['id']}#seg-1"
    assert "0.82" in by[j["id"]]["basis"][0]["text"]
    assert j["id"] in by[pump_log["id"]]["relations"]["cited_by"]["ids"]
    assert page["id"] in by[j["id"]]["relations"]["in_pages"]
    assert by[page["id"]]["basis"][0]["ref"] == j["id"]
    explore = {h["id"]: h for h in ws.retrieval.search("出口压力", mode="explore")["hits"]}
    assert page["id"] not in explore  # 探索模式不给框架页、框架关系和解读（AC-05）
    assert "cited_by" not in explore[pump_log["id"]]["relations"]
    assert "in_pages" not in explore[j["id"]]["relations"]


def test_search_exact(ws, human, pump_log):
    ws.artifacts.register(human, kind="log", source_class="local", text="阀门 V-3010 关闭", title="另一条")
    res = ws.retrieval.search_exact("V-301")
    ids = [h["id"] for h in res["hits"]]
    assert pump_log["id"] in ids
    seg = next(h for h in res["hits"] if h["id"] == pump_log["id"])["segments"][0]
    assert seg["cite_as"].startswith(pump_log["id"] + "#seg-") and "V-301" in seg["text"]
    assert ws.retrieval.search_exact("v-301")["total"] == res["total"]  # 不区分大小写


def test_without_models_lexical_still_works(ws, human):
    ws.artifacts.register(human, kind="literature", source_class="external", text=PAPER, title="Adam 笔记")
    res = ws.retrieval.search("偏差修正")
    assert res["hits"]
    assert res["channels"]["dense"]["state"] == "missing" and res["channels"]["rerank"]["state"] == "off"
    assert any("向量通道" in h for h in res["hints"])  # AC-03：写明向量未启用
    ws.config["index"]["rerank"] = "auto"
    res = ws.retrieval.search("偏差修正")
    assert res["hits"] and res["channels"]["rerank"]["state"] == "missing"
    assert any("重排未启用" in h for h in res["hints"])


def test_rebuild_keeps_cited_segments(ws, human, ai):
    art = ws.artifacts.register(human, kind="literature", source_class="external", text=PAPER, title="Adam 笔记")
    ws.artifacts.read(ai, art["id"], "seg-2")
    j = ws.judgments.write(ai, kind="conclusion", text="Adam 的早期估计偏向零", cites=[f"{art['id']}#seg-2"])
    before = {c["ref"]: c["sha256"] for c in j["data"]["cited_segments"]}
    ws.index.clear()
    ws.rebuild_index()
    segs = {f"{art['id']}#{s['anchor']}": s["sha256"] for s in ws.artifacts.segments(art["id"])}
    assert all(segs.get(ref) == sha for ref, sha in before.items())  # AC-04：段落编号与指纹不变
    assert ws.retrieval.search("早期估计")["hits"]
