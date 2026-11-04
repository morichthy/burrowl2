"""旧版数据导入：用一个最小的旧版数据目录验证映射、只读与身份规则。"""
import json

import pytest

from burrowl.core.errors import BurrowlError


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data, encoding="utf-8")


def _record(record_id, kind, revision, body, **extra):
    return {"record_id": record_id, "kind": kind, "revision": revision, "level": extra.pop("level", None),
            "title": extra.pop("title", None), "body_markdown": body, "created_at": "2026-10-01T00:00:00Z",
            "created_by": extra.pop("created_by", {"id": "mcp-client", "kind": "ai"}), "sources": extra.pop("sources", []),
            "links": extra.pop("links", []), "payload": extra.pop("payload", {}), "change_reason": extra.pop("why", None),
            "owner_id": "RES-X", **extra}


@pytest.fixture
def old_dir(tmp_path):
    root = tmp_path / "old"
    data = root / "research" / "x" / "data.csv"
    _write(data, "t,p\n0,0.82\n")
    import hashlib
    sha = hashlib.sha256(data.read_bytes()).hexdigest()
    _write(root / ".burrowl" / "sources.json", {"roots": [], "sources": [
        {"source_id": "SRC-DATA", "path": "research/x/data.csv", "sha256": sha, "title": "压力数据"},
        {"source_id": "SRC-GONE", "path": "research/x/gone.md", "sha256": "0" * 64, "title": "已移走"}]})
    _write(root / "research" / "x" / "research.json", {"research_id": "RES-X", "title": "泵站排查"})
    _write(root / "research" / "x" / "runs" / "run-1" / "run.json", {"run_id": "RUN-1", "artifacts": [{"path": "SRC-DATA"}]})
    mem = root / "research" / "x" / "memory"
    recs = {
        "C1": [_record("MEM-L0", "source", 1, "压力数据的来源说明", level="L0",
                       sources=[{"target_id": "SRC-DATA"}]),
               _record("MEM-N", "narrative", 1, "第一版：压力正常", title="压力判断", sources=[{"target_id": "SRC-DATA"}])],
        "C2": [_record("MEM-N", "narrative", 2, "第二版：压力偏高，见 [[@data#全文|数据]]", title="压力判断",
                       why="新数据", links=[{"text": "@data#全文", "ref": {"target_id": "SRC-DATA"}}]),
               _record("MEM-R", "review", 1, "", created_by={"id": "alice", "kind": "human"},
                       payload={"target_claim_id": "MEM-N", "state": "accepted", "maturity": "tested",
                                "reviewer": {"id": "alice", "kind": "human"}, "reason": "复测一致"}),
               _record("MEM-OV", "overview", 1, "概览：压力偏高 [[@n|判断]]", title="概览",
                       links=[{"text": "@n", "ref": {"target_id": "MEM-N"}}])],
    }
    heads = {}
    for commit, items in recs.items():
        for r in items:
            _write(mem / "commits" / commit / "records" / f"{r['record_id']}-{r['revision']}.json", r)
            heads[r["record_id"]] = {}
    _write(mem / "commits" / "C2" / "manifest.json", {"record_heads": heads})
    _write(mem / "HEAD.json", {"commit_id": "C2"})
    return root


def test_import_maps_columns(ws, human, old_dir):
    before = sorted((p.relative_to(old_dir), p.stat().st_mtime_ns) for p in old_dir.rglob("*") if p.is_file())
    report = ws.import_v1.run(human, str(old_dir))
    assert sorted((p.relative_to(old_dir), p.stat().st_mtime_ns) for p in old_dir.rglob("*") if p.is_file()) == before
    assert report["gaps"] and "SRC-GONE" in report["gaps"][0]["message"]

    arts = ws.ledger.query("SELECT * FROM artifacts")
    data_art = next(a for a in arts if a["data"].get("title") == "压力数据")
    assert data_art["source_class"] == "local"  # Run 的产出按本地实证导入

    js = ws.ledger.query("SELECT * FROM judgments ORDER BY created_at")
    claims = [j for j in js if j["kind"] == "conclusion" and j["data"].get("v1", {}).get("record_id") == "MEM-N"]
    assert len(claims) == 2 and claims[1]["revises"] == claims[0]["id"]  # 修订用 revises 串起
    assert f"[[{data_art['id']}|数据]]" in claims[1]["data"]["text"]       # 旧链接换成新 ID
    assert claims[1]["author_kind"] == "ai" and claims[1]["data"]["credibility"]["all_local"]

    review = next(j for j in js if j["kind"] == "review")
    assert review["author_kind"] == "human"
    assert ws.ledger.links_from(review["id"], "supports")[0]["dst_id"] == claims[1]["id"]

    pages = ws.framework.pages()
    assert {p["type"] for p in pages} == {"description", "synthesis"}
    overview = next(p for p in pages if p["title"] == "概览")
    assert claims[1]["id"] in ws.framework.inputs_of("page", overview["id"], 1)
    assert ws.framework.entities("project")[0]["name"] == "泵站排查"


def test_import_requires_human_and_empty_workspace(ws, human, ai, old_dir):
    with pytest.raises(BurrowlError):
        ws.import_v1.run(ai, str(old_dir))
    ws.import_v1.run(human, str(old_dir))
    with pytest.raises(BurrowlError) as e:
        ws.import_v1.run(human, str(old_dir))
    assert e.value.code == "CONFLICT"
