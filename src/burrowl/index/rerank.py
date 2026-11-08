"""离线 ONNX Cross-encoder 重排（设计稿 06 D-08）。沿用旧版 burrowl 的 `index/rerank.py` 做法。

- 只从本地模型目录加载；目录必须有 `model-manifest.json`（model、onnx_file、max_length、
  files 的 sha256），加载前逐个核对。
- 分数是相关性 logit，不是校准过的"正确概率"，也不是复核状态。
- 查询加单元超过 max_length 时只截断单元一侧，并计数报告（检索单元按 400 token 切分，正常不会触发）。
"""
import threading
from pathlib import Path

from .embed import ModelError, find_onnx, verify_manifest

_CACHE: dict[str, "CrossEncoder"] = {}
_LOCK = threading.Lock()
BATCH = 16


class CrossEncoder:
    def __init__(self, model_dir: Path):
        try:
            import numpy as np  # noqa: PLC0415
            import onnxruntime as ort  # noqa: PLC0415
            from tokenizers import Tokenizer  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise ModelError(f"缺少运行库：{exc.name}") from exc
        manifest = verify_manifest(model_dir)
        if manifest is None:
            raise ModelError(f"重排模型目录缺少 model-manifest.json：{model_dir}")
        self.np = np
        self.name = manifest["model"]
        self.max_length = int(manifest.get("max_length", 512))
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.no_padding()
        self.tokenizer.enable_truncation(self.max_length, strategy="only_second")
        options = ort.SessionOptions()
        self.session = ort.InferenceSession(str(find_onnx(model_dir, manifest)), options,
                                            providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.truncated = 0

    def score(self, query: str, texts: list[str]) -> list[float]:
        np = self.np
        out: list[float] = []
        for start in range(0, len(texts), BATCH):
            chunk = texts[start:start + BATCH]
            encs = [self.tokenizer.encode(query, t) for t in chunk]
            self.truncated += sum(1 for e in encs if e.overflowing)
            width = max(len(e.ids) for e in encs)
            ids = np.ones((len(encs), width), dtype=np.int64)  # XLM-R 的 pad id 是 1
            mask = np.zeros_like(ids)
            for row, e in enumerate(encs):
                ids[row, :len(e.ids)] = e.ids
                mask[row, :len(e.ids)] = 1
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            logits = self.session.run(None, feed)[0]
            out.extend(float(x) for x in logits.reshape(len(encs), -1)[:, 0])
        return out


def load(model_dir: Path) -> CrossEncoder:
    key = str(model_dir.resolve())
    with _LOCK:
        if key not in _CACHE:
            _CACHE[key] = CrossEncoder(model_dir)
        return _CACHE[key]
