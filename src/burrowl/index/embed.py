"""文本嵌入（设计稿 06 D-07）：离线加载本地 ONNX 模型，平均池化后归一化。

- 只从本地模型目录加载，不下载、不执行模型仓库里的代码。
- 目录里有 `model-manifest.json`（`files: {文件名: sha256}`）时逐个核对；没有时用 onnx 文件的 sha256 作指纹。
  指纹写进向量缓存的 model 字段：换模型或模型文件变了，旧向量自然不再被用到。
- 不静默截断：超过 MAX_TOKENS 的输入照样截断编码，但会计数并报告（旧版的教训：MiniLM 在 128 token 处
  静默截断，58%–71% 的正文从未进入向量）。检索单元按 400 token 估计切分，正常不会触发。
"""
import hashlib
import json
import os
import threading
from pathlib import Path

MAX_TOKENS = 2048
BATCH_TOKENS = 16384  # 每批编码的 token 总量：长序列按批内最长补齐，注意力内存随长度平方增长

_CACHE: dict[str, "Embedder"] = {}
_LOCK = threading.Lock()


class ModelError(Exception):
    pass


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_manifest(model_dir: Path) -> dict | None:
    """有清单就逐个文件核对，返回清单；不一致抛 ModelError。没有清单返回 None。"""
    path = model_dir / "model-manifest.json"
    if not path.is_file():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for name, digest in manifest.get("files", {}).items():
        if not (model_dir / name).is_file() or file_sha256(model_dir / name) != digest:
            raise ModelError(f"模型文件与清单不一致：{name}")
    return manifest


def find_onnx(model_dir: Path, manifest: dict | None) -> Path:
    if manifest and manifest.get("onnx_file"):
        return model_dir / manifest["onnx_file"]
    for candidate in (model_dir / "onnx" / "model.onnx", model_dir / "model.onnx"):
        if candidate.is_file():
            return candidate
    found = sorted(model_dir.glob("**/*.onnx"))
    if not found:
        raise ModelError(f"模型目录里没有 onnx 文件：{model_dir}")
    return found[0]


class Embedder:
    def __init__(self, model_dir: Path, name: str):
        try:
            import numpy as np  # noqa: PLC0415 - 只有启用向量通道时才需要
            import onnxruntime as ort  # noqa: PLC0415
            from tokenizers import Tokenizer  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - 依赖随安装包提供
            raise ModelError(f"缺少运行库：{exc.name}") from exc
        self.np = np
        manifest = verify_manifest(model_dir)
        onnx = find_onnx(model_dir, manifest)
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest() if manifest \
            else file_sha256(onnx)
        self.fingerprint = f"{name}:{digest[:16]}"
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
        self.max_tokens = min(MAX_TOKENS, int(config.get("max_position_embeddings", 512)))
        self.dim = int(config.get("hidden_size", 768))
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, (os.cpu_count() or 2) - 1)
        self.session = ort.InferenceSession(str(onnx), options, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.truncated = 0

    def embed(self, texts: list[str]):
        """返回 float32 矩阵（每行已归一化）。按 token 总量分批。"""
        np = self.np
        encoded = [self.tokenizer.encode(t).ids for t in texts]
        out = [None] * len(texts)
        order = sorted(range(len(texts)), key=lambda i: len(encoded[i]))
        batch: list[int] = []

        def run(idx: list[int]):
            seqs = []
            for i in idx:
                ids = encoded[i]
                if len(ids) > self.max_tokens:
                    self.truncated += 1
                    ids = ids[:self.max_tokens - 1] + ids[-1:]
                seqs.append(ids)
            width = max(len(s) for s in seqs)
            ids = np.zeros((len(seqs), width), dtype=np.int64)
            mask = np.zeros_like(ids)
            for row, s in enumerate(seqs):
                ids[row, :len(s)] = s
                mask[row, :len(s)] = 1
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self.session.run(None, feed)[0]
            pooled = (hidden * mask[..., None]).sum(1) / np.maximum(mask.sum(1, keepdims=True), 1)
            pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
            for row, i in enumerate(idx):
                out[i] = pooled[row].astype(np.float32)

        for i in order:
            width = min(len(encoded[i]), self.max_tokens)
            if batch and width * (len(batch) + 1) > BATCH_TOKENS:
                run(batch)
                batch = []
            batch.append(i)
        if batch:
            run(batch)
        return np.stack(out) if out else np.zeros((0, self.dim), dtype=np.float32)


def load(model_dir: Path, name: str) -> Embedder:
    key = str(model_dir.resolve())
    with _LOCK:
        if key not in _CACHE:
            _CACHE[key] = Embedder(model_dir, name)
        return _CACHE[key]
