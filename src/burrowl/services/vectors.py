"""向量通道与重排（设计稿 06 D-07、D-08）。都是可选的：没有模型或没建完时，检索照常只用词法路，并在结果里写明。

- 模型放在模型目录（`BURROWL_MODELS_DIR`，否则 `<安装根目录>/models`），不进安装包。
- 向量按检索单元的内容指纹缓存在 index.sqlite（`vectors`），整库重建索引时不删。
- 补建：工作台进程的后台线程逐批补（`interfaces/pool.py`），命令行 `index.embed` 一次补完。
  登记原件、写判断不等向量：检索结果报告"已建 m / n"。
- 重排：`index.rerank=auto` 时装了模型就重排；默认 off（回归题上降低了段落命中，设计稿 06 D-08 修订）；
  出错退回融合顺序，结果里写明。
"""
import os
import threading
import time
from pathlib import Path

from ..index import embed as embed_mod
from ..index import rerank as rerank_mod
from ..index.fts import UnitHit

# 名称 → 模型目录名。名称写在 config.json 的 index.embedding_model
EMBEDDING_MODELS = {"jina-v2-base-zh": "jina-embeddings-v2-base-zh"}
RERANK_DIR = "cross-encoder"
BUILD_BATCH = 48


def models_dir(config: dict) -> Path:
    if config.get("index", {}).get("models_dir"):
        return Path(config["index"]["models_dir"])
    if os.environ.get("BURROWL_MODELS_DIR"):
        return Path(os.environ["BURROWL_MODELS_DIR"])
    if os.environ.get("BURROWL_ROOT"):
        return Path(os.environ["BURROWL_ROOT"]) / "models"
    for parent in Path(__file__).resolve().parents:  # 安装布局 <root>/versions/<版本>/python/…
        if parent.parent.name == "versions" and (parent / "python").is_dir():
            return parent.parent.parent / "models"
    return Path.home() / ".burrowl2-dev" / "models"


class VectorService:
    def __init__(self, ws):
        self.ws = ws
        self._matrix: tuple | None = None  # (缓存键, rowids, layers, 矩阵)
        self._error: str | None = None
        self.build_lock = threading.Lock()

    # ---------- 模型 ----------
    def model_name(self) -> str:
        return self.ws.config.get("index", {}).get("embedding_model", "none")

    def _embedder(self):
        name = self.model_name()
        if name == "none":
            return None, {"state": "off", "reason": "设置为不使用向量"}
        folder = EMBEDDING_MODELS.get(name)
        path = models_dir(self.ws.config) / (folder or name)
        if not path.is_dir():
            return None, {"state": "missing", "model": name, "reason": f"模型目录不存在：{path}"}
        try:
            return embed_mod.load(path, name), None
        except embed_mod.ModelError as exc:
            return None, {"state": "error", "model": name, "reason": str(exc)}

    def _reranker(self):
        if self.ws.config.get("index", {}).get("rerank", "off") == "off":
            return None, {"state": "off", "reason": "设置为不重排"}
        path = models_dir(self.ws.config) / RERANK_DIR
        if not path.is_dir():
            return None, {"state": "missing", "reason": f"重排模型目录不存在：{path}"}
        try:
            return rerank_mod.load(path), None
        except embed_mod.ModelError as exc:
            return None, {"state": "error", "reason": str(exc)}

    # ---------- 状态与补建 ----------
    def status(self) -> dict:
        model, problem = self._embedder()
        if problem:
            return problem
        done, total = self.ws.index.vector_coverage(model.fingerprint)
        state = "ready" if done >= total else "building"
        out = {"state": state, "model": self.model_name(), "fingerprint": model.fingerprint, "done": done,
               "total": total}
        if model.truncated:
            out["truncated"] = model.truncated
        return out

    def build(self, *, limit: int | None = None, seconds: float | None = None) -> dict:
        """补建缺的向量。limit：最多补几个单元；seconds：最多用多久（后台线程逐批调用）。"""
        model, problem = self._embedder()
        if problem:
            return {**problem, "built": 0}
        started, built = time.monotonic(), 0
        with self.build_lock:
            while True:
                with self.ws.lock:
                    todo = self.ws.index.missing_vector_keys(model.fingerprint, limit=BUILD_BATCH)
                if not todo:
                    break
                vectors = model.embed([f"{ctx}\n{text}" if ctx else text for _, ctx, text in todo])
                with self.ws.lock:
                    self.ws.index.put_vectors(model.fingerprint, model.dim,
                                              [(key, vec.tobytes()) for (key, _, _), vec in zip(todo, vectors,
                                                                                               strict=True)])
                built += len(todo)
                if (limit and built >= limit) or (seconds and time.monotonic() - started > seconds):
                    break
        return {**self.status(), "built": built, "seconds": round(time.monotonic() - started, 1)}

    # ---------- 检索 ----------
    def search(self, query: str, *, layers: list[str] | None = None, limit: int = 100) -> dict:
        model, problem = self._embedder()
        if problem:
            return {"units": [], "status": problem}
        try:
            np = model.np
            rowids, unit_layers, matrix = self._load_matrix(model)
            status = self.status()
            if not rowids:
                return {"units": [], "status": status}
            q = model.embed([query])[0]
            scores = matrix @ q
            if layers:
                mask = np.isin(np.array(unit_layers), layers)
                scores = np.where(mask, scores, -np.inf)
            top = np.argsort(-scores)[:limit]
            chosen = [rowids[i] for i in top if np.isfinite(scores[i])]
            units = self.ws.index.units_by_rowid(chosen)
            score_of = {rowids[i]: float(scores[i]) for i in top}
            return {"units": [_with_score(u, score_of[u.rowid]) for u in units], "status": status}
        except Exception as exc:  # noqa: BLE001 —— 向量通道出错不影响词法检索
            return {"units": [], "status": {"state": "error", "reason": f"{type(exc).__name__}: {exc}"}}

    def neighbors(self, rowid: int, *, limit: int = 10) -> list[tuple[int, float]]:
        """与一个检索单元最相近的单元（联想模式用，设计稿 06 D-17）。"""
        model, problem = self._embedder()
        if problem:
            return []
        rowids, _, matrix = self._load_matrix(model)
        if rowid not in rowids:
            return []
        np = model.np
        scores = matrix @ matrix[rowids.index(rowid)]
        top = np.argsort(-scores)[:limit + 1]
        return [(rowids[i], float(scores[i])) for i in top if rowids[i] != rowid][:limit]

    def _load_matrix(self, model):
        np = model.np
        key = (model.fingerprint, self.ws.index.generation, self.ws.index.data_version())
        if self._matrix and self._matrix[0] == key:
            return self._matrix[1:]
        rows = self.ws.index.all_units()
        cached = self.ws.index.vectors(list({r[3] for r in rows}), model.fingerprint)
        rowids, unit_layers, vecs = [], [], []
        for rowid, _entry, layer, k in rows:
            blob = cached.get(k)
            if blob is not None:
                rowids.append(rowid)
                unit_layers.append(layer)
                vecs.append(np.frombuffer(blob, dtype=np.float32))
        matrix = np.stack(vecs) if vecs else np.zeros((0, model.dim), dtype=np.float32)
        self._matrix = (key, rowids, unit_layers, matrix)
        return rowids, unit_layers, matrix

    # ---------- 重排 ----------
    def rerank_status(self) -> dict:
        model, problem = self._reranker()
        return problem or {"state": "on", "model": model.name}

    def rerank(self, query: str, units: list[UnitHit]) -> dict:
        if not units:
            return {"scores": None, "status": {"state": "skipped", "reason": "没有候选"}}
        model, problem = self._reranker()
        if problem:
            return {"scores": None, "status": problem}
        started = time.monotonic()
        try:
            scores = model.score(query, [f"{u.context}\n{u.text}" if u.context else u.text for u in units])
        except Exception as exc:  # noqa: BLE001 —— 重排出错退回融合顺序
            return {"scores": None, "status": {"state": "error", "reason": f"{type(exc).__name__}: {exc}"}}
        status = {"state": "on", "model": model.name, "candidates": len(units),
                  "ms": round((time.monotonic() - started) * 1000)}
        if model.truncated:
            status["truncated"] = model.truncated
        return {"scores": scores, "status": status}


def _with_score(u: UnitHit, score: float) -> UnitHit:
    u.score = score
    return u
