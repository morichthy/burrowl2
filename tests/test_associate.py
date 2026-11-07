"""联想模式（设计稿 04 D-17）：顺着已有关系扩大召回，带路径；探索模式只走判断层关系、引用、共享对象。"""


def test_associate_follows_relations_with_paths(ws, human, ai, pump_log):
    ws.artifacts.read(ai, pump_log["id"], "seg-1")
    j1 = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力稳定", cites=[f"{pump_log['id']}#seg-1"])
    j2 = ws.judgments.write(ai, kind="conclusion", text="入口滤网堵塞会造成气蚀",
                            relations=[{"rel": "supports", "target": j1["id"]}])
    res = ws.associate.run(seeds=[pump_log["id"]], hops=2)
    by = {h["id"]: h for h in res["hits"]}
    assert j1["id"] in by and by[j1["id"]]["via"][0]["rel"] == "cited_by"
    assert j2["id"] in by and by[j2["id"]]["hop"] == 2  # 第二跳：经 j1 连到支持它的判断
    assert all(h["label"] == "联想，非检索命中" and h["status_note"] for h in res["hits"])
    assert pump_log["id"] not in by  # 出发点不算联想结果


def test_associate_explore_skips_framework_and_interpretations(ws, human, ai, pump_log):
    ws.artifacts.read(ai, pump_log["id"], "seg-1")
    j = ws.judgments.write(ai, kind="conclusion", text="2号泵出口压力稳定", cites=[f"{pump_log['id']}#seg-1"],
                           objects=["2号泵"])
    ws.frameworks.page_write(human, type="synthesis", title="泵", body=f"见 [[{j['id']}]]")
    reuse = {h["id"] for h in ws.associate.run(seeds=[j["id"]], hops=1)["hits"]}
    assert any(i.startswith("pg_") for i in reuse) and pump_log["id"] in reuse
    explore = ws.associate.run(seeds=[pump_log["id"]], hops=2, mode="explore")
    assert not any(h["layer"] == "framework" for h in explore["hits"])
    assert j["id"] not in {h["id"] for h in explore["hits"]}  # 原件 → 引用它的判断是解读，探索模式不走


def test_associate_shared_objects_and_query_seeds(ws, human, ai):
    a = ws.judgments.write(ai, kind="conclusion", text="3号阀密封老化", objects=["3号阀"])
    b = ws.judgments.write(ai, kind="conclusion", text="更换垫片后泄漏停止", objects=["3号阀"])
    res = ws.associate.run(query="密封老化")
    assert res["seeds"][0] == a["id"]
    hit = next(h for h in res["hits"] if h["id"] == b["id"])
    assert hit["via"][0]["rel"] == "object"
