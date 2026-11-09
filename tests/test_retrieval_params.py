"""检索参数（设计稿 06 D-21）：config.json 的 retrieval 组；工作台与 AI 读同一份，保存后别的进程下一次调用就生效。"""
import json

import pytest

from burrowl.core.errors import BurrowlError
from burrowl.interfaces.pool import WorkspacePool
from burrowl.interfaces.registry import Ctx, call
from burrowl.services.retrieval import RETRIEVAL_DEFAULTS
from burrowl.services.workspace import DEFAULT_CONFIG, Workspace

# 六节，每节都提到"偏差修正"：同一条目命中多个检索单元
DOC = "\n\n".join(f"# 第{i}节\n\n第{i}节讨论偏差修正。" + "这一节的正文说明滑动平均从零开始。" * 30 for i in range(1, 7))


def _register(ws, human):
    return ws.artifacts.register(human, kind="literature", source_class="external", text=DOC, title="偏差修正笔记")


def test_defaults_and_params_in_result(ws, human):
    assert DEFAULT_CONFIG["retrieval"] == RETRIEVAL_DEFAULTS
    art = _register(ws, human)
    res = ws.retrieval.search("偏差修正")
    assert res["params"]["limit"] == 20 and res["params"]["passages_shown"] == 3
    hit = next(h for h in res["hits"] if h["id"] == art["id"])
    assert len(hit["passages"]) == 3 and hit["more_matches"] > 0


def test_settings_change_search_output(ws, human):
    art = _register(ws, human)
    ctx = Ctx(ws=ws, actor=human, channel="http")
    call(ctx, "settings.set", {"values": {"retrieval.passages_shown": 5, "retrieval.snippet_chars": 200,
                                          "retrieval.limit": 7}})
    res = ws.retrieval.search("偏差修正")
    hit = next(h for h in res["hits"] if h["id"] == art["id"])
    assert len(hit["passages"]) == 5
    assert all(len(p["text"]) <= 202 for p in hit["passages"])  # 截取窗口时前后可能各加一个省略号
    assert res["params"]["limit"] == 7 and res["params"]["snippet_chars"] == 200
    assert ws.retrieval.search("偏差修正", limit=3)["params"]["limit"] == 3  # 显式给出时以参数为准


def test_numeric_settings_validated_and_logged(ws, human, ai):
    ctx = Ctx(ws=ws, actor=human, channel="http")
    got = call(ctx, "settings.get", {})
    assert got["numbers"]["retrieval.passages_shown"] == {"min": 1, "max": 10, "default": 3}
    for bad in (0, 11, 2.5, "三", True):
        with pytest.raises(BurrowlError):
            call(ctx, "settings.set", {"values": {"retrieval.passages_shown": bad}})
    call(ctx, "settings.set", {"values": {"retrieval.associate_vector_min": "0.5"}})
    assert ws.config["retrieval"]["associate_vector_min"] == 0.5
    call(ctx, "settings.set", {"values": {"retrieval.passages_shown": 4}})
    logs = ws.ledger.query("SELECT data FROM events WHERE op = 'settings.set' ORDER BY seq")
    assert logs[-1]["data"]["input"]["changes"] == {"retrieval.passages_shown": {"from": 3, "to": 4}}
    call(ctx, "settings.set", {"values": {"retrieval.passages_shown": 4}})  # 没有变化不记日志
    assert len(ws.ledger.query("SELECT id FROM events WHERE op = 'settings.set'")) == len(logs)
    with pytest.raises(BurrowlError):  # 设置只能由人改；MCP 不注册 user 操作
        call(Ctx(ws=ws, actor=ai, channel="mcp"), "settings.set", {"values": {"retrieval.passages_shown": 2}})


def test_other_process_sees_saved_settings(ws, human):
    """MCP 进程长期持有自己的 Workspace：工作台保存后，它下一次取 Workspace 就用新值，不用重启。"""
    _register(ws, human)
    pool = WorkspacePool(ws.root)
    mcp_ws = pool.get(ws.root)
    try:
        assert mcp_ws is not ws and mcp_ws.retrieval.params()["passages_shown"] == 3
        call(Ctx(ws=ws, actor=human, channel="http"), "settings.set", {"values": {"retrieval.passages_shown": 10}})
        assert pool.get(ws.root) is mcp_ws  # 同一个对象，只重读了配置
        assert mcp_ws.retrieval.params()["passages_shown"] == 10
        assert mcp_ws.retrieval.search("偏差修正")["params"]["passages_shown"] == 10
        assert mcp_ws.refresh_config() is False  # 没有再变化时不重读
    finally:
        mcp_ws.close()


def test_old_config_without_retrieval_group(tmp_path):
    """旧 config.json 没有 retrieval 组：取默认值，旧数据目录照常打开。"""
    root = tmp_path / "old"
    w = Workspace(root)
    w.close()
    path = root / "config.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored.pop("retrieval")
    path.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
    w = Workspace(root)
    try:
        assert w.retrieval.params() == RETRIEVAL_DEFAULTS
    finally:
        w.close()


def test_associate_uses_settings(ws, human):
    _register(ws, human)
    ctx = Ctx(ws=ws, actor=human, channel="http")
    call(ctx, "settings.set", {"values": {"retrieval.associate_seeds": 2}})
    res = ws.associate.run(query="偏差修正")
    assert res["params"]["associate_seeds"] == 2 and len(res["seeds"]) <= 2


# ---------- 检索单元长度（设计稿 06 D-22）：改了要整库重建索引，段落编号与引用不受影响 ----------
def test_unit_length_settings_rebuild_index_and_keep_citations(ws, human, ai):
    art = _register(ws, human)
    ws.artifacts.read(ai, art["id"], "seg-1")
    j = ws.judgments.write(ai, kind="conclusion", text="第1节讨论偏差修正", cites=[f"{art['id']}#seg-1"])
    before_units = len(ws.index.units_of(art["id"]))
    anchors = [s["anchor"] for s in ws.artifacts.segments(art["id"])]
    version = ws.index_version()
    ctx = Ctx(ws=ws, actor=human, channel="http")
    out = call(ctx, "settings.set", {"values": {"index.units_target": 100, "index.units_max": 150}})
    assert out["rebuild"]["state"] == "running"  # 在后台重建，请求立即返回
    done = ws.wait_rebuild(30)
    assert done["state"] == "done" and done["done"] == done["total"] >= 2 and not done["errors"]
    assert ws.index_version() != version and not ws.index_stale()
    health = call(ctx, "index.health", {})
    assert health["units"]["current"] and health["units"]["rebuild"]["state"] == "done"
    assert len(ws.index.units_of(art["id"])) > before_units  # 单元变短、变多
    assert [s["anchor"] for s in ws.artifacts.segments(art["id"])] == anchors  # 引用段落不变
    segs = {f"{art['id']}#{s['anchor']}": s["sha256"] for s in ws.artifacts.segments(art["id"])}
    assert all(segs.get(c["ref"]) == c["sha256"] for c in j["data"]["cited_segments"])
    assert ws.retrieval.search("偏差修正")["hits"]
    # 改回默认值：版本回到不带后缀的写法，已有数据目录升级时不会因此重建
    call(ctx, "settings.set", {"values": {"index.units_target": 300, "index.units_max": 400}})
    ws.wait_rebuild(30)
    assert ws.index_version() == ws.INDEX_VERSION and len(ws.index.units_of(art["id"])) == before_units


def test_unit_length_cross_checks(ws, human):
    ctx = Ctx(ws=ws, actor=human, channel="http")
    with pytest.raises(BurrowlError):  # 目标长度大于上限
        call(ctx, "settings.set", {"values": {"index.units_target": 500}})
    call(ctx, "settings.set", {"values": {"index.units_max": 600}})
    with pytest.raises(BurrowlError):  # 单元上限超过重排模型的输入时不能打开重排
        call(ctx, "settings.set", {"values": {"index.rerank": "auto"}})
    with pytest.raises(BurrowlError):
        call(ctx, "settings.set", {"values": {"index.units_max": 400, "index.units_context_chars": 300,
                                              "index.rerank": "auto"}})
    call(ctx, "settings.set", {"values": {"index.units_max": 400, "index.rerank": "auto"}})
    assert ws.config["index"]["rerank"] == "auto"


def test_other_process_hint_while_index_stale(ws, human):
    """另一个进程改了单元长度：重建完成前，本进程的检索结果提示可能不全；重建后提示消失。"""
    _register(ws, human)
    other = Workspace(ws.root)
    try:
        other.save_config({"index": {"units_target": 120, "units_max": 160}})  # 只改配置，还没重建
        ws.refresh_config()
        assert ws.index_stale()
        assert any("正在按新的检索单元长度重建" in h for h in ws.retrieval.search("偏差修正")["hints"])
        other.rebuild_index()
        assert not ws.index_stale()
        assert not any("重建" in h for h in ws.retrieval.search("偏差修正")["hints"])
    finally:
        other.close()


def test_background_rebuild_keeps_search_working_and_reruns(ws, human):
    """后台重建不先清空索引，逐条替换；重建中又改了设置，完成后按新设置再来一遍。"""
    _register(ws, human)
    ctx = Ctx(ws=ws, actor=human, channel="http")
    with ws.lock:  # 占着锁：后台线程一条也建不了，模拟"重建刚开始"
        call(ctx, "settings.set", {"values": {"index.units_target": 120, "index.units_max": 160}})
        assert ws.rebuild_status()["state"] == "running"
        assert ws.retrieval.search("偏差修正")["hits"]  # 旧索引行还在，检索照常
        call(ctx, "settings.set", {"values": {"index.units_target": 150}})  # 重建期间又改
        assert ws.rebuild_status()["again"] is True
    done = ws.wait_rebuild(30)
    assert done["state"] == "done" and not ws.index_stale()
    assert ws.index_version().endswith("t150m160c160")


def test_index_rebuild_op_background(ws, human):
    _register(ws, human)
    ctx = Ctx(ws=ws, actor=human, channel="http")
    assert call(ctx, "index.rebuild", {"background": True})["rebuild"]["state"] == "running"
    assert ws.wait_rebuild(30)["state"] == "done"
    assert call(ctx, "index.rebuild", {})["artifacts"] == 1  # 命令行：等重建完再返回
