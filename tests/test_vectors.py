"""向量通道：补建、缓存、检索、整库重建后复用（设计稿 06 D-07）。用确定的假模型，不依赖本机模型目录。"""
import os

import numpy as np
import pytest

from burrowl.index.tokenize import tokens


class FakeEmbedder:
    """按双字词做哈希的词袋向量：同义词不相近，但足以检验管线（补建、缓存、合并、过滤）。"""
    np = np
    dim = 64
    fingerprint = "fake:1"
    truncated = 0

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += len(texts)
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for tok in tokens(t):
                out[i, hash(tok) % self.dim] += 1
        out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-12)
        return out


@pytest.fixture
def fake(ws, monkeypatch):
    model = FakeEmbedder()
    monkeypatch.setattr(ws.vectors, "_embedder", lambda: (model, None))
    return model


def test_build_search_and_reuse_after_rebuild(ws, human, fake):
    art = ws.artifacts.register(human, kind="log", source_class="local", text="冷却塔风机振动偏大，轴承温度升高",
                                title="冷却塔巡检")
    assert ws.vectors.status()["state"] == "building"
    built = ws.vectors.build()
    assert built["built"] >= 1 and ws.vectors.status()["state"] == "ready"
    res = ws.retrieval.search("风机振动")
    assert res["channels"]["dense"]["state"] == "ready"
    assert res["hits"][0]["id"] == art["id"] and "dense" in res["hits"][0]["channels"]
    calls = fake.calls
    ws.index.clear()
    ws.rebuild_index()
    assert ws.vectors.status()["state"] == "ready"  # 向量按内容指纹缓存，重建索引不用重新编码
    ws.vectors.build()
    assert fake.calls == calls + 0


def test_dense_respects_layers_and_explore(ws, human, ai, fake):
    ws.judgments.write(ai, kind="conclusion", text="冷却塔风机振动来自轴承磨损")
    ent = ws.frameworks.entity_upsert(human, kind="device", name="冷却塔")
    page = ws.frameworks.page_write(human, type="entity", title="冷却塔", body="风机振动的综合判断",
                                    subject_id=ent["id"])
    ws.vectors.build()
    hits = ws.retrieval.search("风机振动", mode="explore")["hits"]
    assert hits and all(h["layer"] != "framework" for h in hits)
    assert page["id"] in [h["id"] for h in ws.retrieval.search("风机振动")["hits"]]


@pytest.mark.skipif(not os.environ.get("BURROWL_TEST_MODELS"), reason="设置 BURROWL_TEST_MODELS=<模型目录> 才用真实模型测")
def test_real_model_cross_language(ws, human, monkeypatch):
    monkeypatch.setenv("BURROWL_MODELS_DIR", os.environ["BURROWL_TEST_MODELS"])
    en = ws.artifacts.register(human, kind="literature", source_class="external", title="Adam",
                               text="Adam utilizes initialization bias correction terms for both moment estimates.")
    ws.artifacts.register(human, kind="literature", source_class="external", title="锁相环",
                          text="光学锁相环具有结构简单、伺服频率带宽大、锁定准确度高等优势。")
    ws.vectors.build()
    hits = ws.retrieval.search("初始化偏差修正")["hits"]
    assert hits and hits[0]["id"] == en["id"]
