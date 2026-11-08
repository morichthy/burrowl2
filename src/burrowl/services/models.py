"""本地模型（设计稿 05）：版面抽取、公式识别、向量模型与 LLM 的槽位、调用与任务队列。

调用边界（§2，用户决定 2026-11-08）：
- 本地模型（版面抽取、公式识别、向量模型，地址是本机）工作台可以自动调用：登记、补抽后排进任务队列；
- LLM（通用大模型）永远不自动调用，只在人显式点击或执行命令时调用（`llm` 槽位没有自动开关）。
burrowl 不打包、不启动模型（D-01）：每个模型是用户自己运行的本地服务，这里只保存地址并通过 HTTP 调用。

结果怎样进抽取层（D-06 至 D-08、D-12）：
- formulas（默认）：内置抽取的段落不动，只给已有的公式块补 LaTeX（按 box 重叠对应），插入内置抽取漏掉的
  行间公式，给段落记下行内公式（inline_math）；
- formulas_only_existing：只补已有公式块，不插入新块（段落编号不变）；
- replace：引擎的分段替换内置抽取（人工、AI、OCR 提交过的单元保留）。
引擎、模型补的内容可信度档记 ocr，`latex_source.method` 记 `tool:<适配器>@<版本>`，需要人确认。
"""
import ipaddress
import json
import threading
import time
from collections import deque
from urllib.parse import urlparse

from ..core.actor import Actor
from ..core.clock import now
from ..core.errors import BurrowlError
from ..core.ids import new_id
from . import model_adapters as ma

SLOTS = ("layout", "formula", "llm")  # 向量模型由检索的 index.embedding_model 负责（设计稿 06 D-07）
LAYOUT_MODES = ("formulas", "formulas_only_existing", "replace")
MODEL_ACTOR = Actor("system:model", "system", "ses_system")
IOU_MATCH = 0.5      # 引擎公式块与内置公式块的重叠度不低于它就算同一块（D-06）
OVERLAP_FREE = 0.15  # 引擎公式与任何内置块重叠都低于它，才算内置抽取漏掉的公式
KEEP_LATEX = ("manual", "ai")  # 人工填写、AI 识别的 LaTeX 不被模型覆盖（D-10）


def is_local(url: str) -> bool:
    """地址是不是本机：只有本机地址上的模型才会被自动调用（D-03）。"""
    host = (urlparse(url).hostname or "").strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def iou(a: list[float], b: list[float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    w = min(ax + aw, bx + bw) - max(ax, bx)
    h = min(ay + ah, by + bh) - max(ay, by)
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / (aw * ah + bw * bh - inter)


def coverage(inner: list[float], outer: list[float]) -> float:
    """inner 有多少比例落在 outer 里。"""
    ax, ay, aw, ah = inner
    bx, by, bw, bh = outer
    w = min(ax + aw, bx + bw) - max(ax, bx)
    h = min(ay + ah, by + bh) - max(ay, by)
    if w <= 0 or h <= 0 or aw * ah <= 0:
        return 0.0
    return w * h / (aw * ah)


class ModelService:
    def __init__(self, ws):
        self.ws = ws
        self._cv = threading.Condition()
        self._queue: deque[dict] = deque()
        self._jobs: deque[dict] = deque(maxlen=100)  # 最近的任务（含已完成），只在本进程内存里
        self._worker: threading.Thread | None = None

    # ---------- 设置 ----------
    @property
    def cfg(self) -> dict:
        return self.ws.config.get("models", {})

    def adapter(self, slot: str) -> str:
        return self.cfg.get(slot, "none") or "none"

    def url(self, slot: str) -> str:
        if slot == "formula" and self.adapter("formula") == "follow_layout":
            return self.url("layout")
        return (self.cfg.get(f"{slot}_url") or "").rstrip("/")

    def configured(self, slot: str) -> bool:
        if slot == "formula" and self.adapter("formula") == "follow_layout":
            return self.configured("layout")
        return self.adapter(slot) != "none" and bool(self.url(slot))

    def can_auto(self, slot: str) -> bool:
        """自动运行的条件（D-03）：本地模型槽位、已配置、地址是本机、自动开关打开。LLM 永远不自动。"""
        if slot == "llm" or not self.configured(slot):
            return False
        return is_local(self.url(slot)) and self.cfg.get(f"{slot}_auto", "on") == "on"

    def status(self) -> dict:
        slots = {}
        for slot in SLOTS:
            slots[slot] = {"adapter": self.adapter(slot), "url": self.url(slot), "configured": self.configured(slot),
                           "local": bool(self.url(slot)) and is_local(self.url(slot)), "auto": self.can_auto(slot)}
        with self._cv:
            jobs = [dict(j) for j in self._jobs]
        return {"slots": slots, "layout_mode": self.cfg.get("layout_mode", "formulas"), "jobs": jobs[::-1]}

    def check(self, slot: str) -> dict:
        """测试连接（D-05）：调用适配器的健康检查，返回工具版本。"""
        if slot not in SLOTS:
            raise BurrowlError("INVALID_ARGUMENT", f"slot 必须是 {', '.join(SLOTS)} 之一")
        if not self.configured(slot):
            raise BurrowlError("INVALID_ARGUMENT", "这个槽位还没有选择工具或填写地址", {"slot": slot})
        name = "mineru" if slot == "formula" else self.adapter(slot)
        if slot == "llm":
            return ma.llm_health(self.url(slot), self.cfg.get("llm_key") or "", self.cfg.get("llm_model") or "")
        return ma.ADAPTERS[name].health(self.url(slot))

    # ---------- 任务队列（D-04） ----------
    def enqueue(self, kind: str, artifact_id: str, *, by: str, params: dict | None = None) -> dict:
        job = {"id": new_id("run").replace("run_", "job_"), "kind": kind, "artifact_id": artifact_id, "by": by,
               "params": params or {}, "status": "queued", "created_at": now()}
        with self._cv:
            for j in self._queue:  # 同一份原件同一种任务已经在排队：不重复
                if j["kind"] == kind and j["artifact_id"] == artifact_id and j["params"] == job["params"]:
                    return dict(j)
            self._queue.append(job)
            self._jobs.append(job)
            self._cv.notify()
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._loop, name="burrowl-models", daemon=True)
                self._worker.start()
        return dict(job)

    def job(self, job_id: str) -> dict | None:
        with self._cv:
            return next((dict(j) for j in self._jobs if j["id"] == job_id), None)

    def wait(self, job_id: str, timeout: float = 600) -> dict:
        """等一个任务结束（命令行与测试用）。调用方不能持有数据目录的锁。"""
        end = time.monotonic() + timeout
        with self._cv:
            while True:
                j = next((j for j in self._jobs if j["id"] == job_id), None)
                if j is None or j["status"] in ("done", "failed"):
                    return dict(j) if j else {}
                left = end - time.monotonic()
                if left <= 0:
                    return dict(j)
                self._cv.wait(left)

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._queue:
                    if not self._cv.wait(300):
                        self._worker = None
                        return
                job = self._queue.popleft()
                job["status"], job["started_at"] = "running", now()
            try:
                result = self.run(job)
                state = {"status": "done", "result": result}
            except BurrowlError as exc:
                state = {"status": "failed", "error": exc.message}
            except Exception as exc:  # noqa: BLE001 - 模型服务的任何异常都只记在任务上，不影响工作台
                state = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            with self._cv:
                job.update(state, finished_at=now())
                self._cv.notify_all()

    def run(self, job: dict) -> dict:
        """执行一个任务。HTTP 调用期间不持有数据目录的锁；读写账本时持有。"""
        if job["kind"] == "layout":
            return self._run_layout(job)
        if job["kind"] == "formula":
            return self._run_formula(job)
        raise BurrowlError("INVALID_ARGUMENT", "未知的任务类型", {"kind": job["kind"]})

    # ---------- 入口 ----------
    def after_extraction(self, artifact_id: str) -> dict | None:
        """登记、补抽后：版面引擎满足自动条件时，把这份 PDF 排进队列（D-03、D-06）。"""
        art = self.ws.ledger.get(artifact_id)
        if art is None or self.ws.extraction.format(art) != "pdf" or not self.can_auto("layout"):
            return None
        if self._cached(art) is not None and self._applied(art):
            return None
        return self.enqueue("layout", artifact_id, by=MODEL_ACTOR.id)

    def run_layout(self, actor: Actor, artifact_id: str, *, mode: str | None = None) -> dict:
        """人或 AI 显式地用版面引擎处理一份原件（D-07）。"""
        art = self.ws.artifacts._artifact(artifact_id)
        if self.ws.extraction.format(art) != "pdf":
            raise BurrowlError("INVALID_ARGUMENT", "版面引擎目前只处理 PDF", {"artifact_id": artifact_id})
        if not self.configured("layout"):
            raise BurrowlError("INVALID_ARGUMENT", "还没有配置版面抽取引擎（设置 → 模型与引擎）")
        if mode is not None and mode not in LAYOUT_MODES:
            raise BurrowlError("INVALID_ARGUMENT", f"mode 必须是 {', '.join(LAYOUT_MODES)} 之一")
        if mode == "replace":
            actor.require_human("用版面引擎整份替换抽取")
        return self.enqueue("layout", artifact_id, by=actor.id, params={"mode": mode} if mode else {})

    def recognize_formulas(self, actor: Actor, artifact_id: str, *, anchors: list[str], engine: str = "model") -> dict:
        """显式识别公式（D-11）：engine=model 用公式槽位；engine=llm 用 LLM 槽位，只能由人发起。"""
        if engine not in ("model", "llm"):
            raise BurrowlError("INVALID_ARGUMENT", "engine 必须是 model 或 llm")
        slot = "formula" if engine == "model" else "llm"
        if engine == "llm":
            actor.require_human("调用大模型识别公式")
        if not self.configured(slot):
            raise BurrowlError("INVALID_ARGUMENT", "还没有配置这个模型（设置 → 模型与引擎）", {"slot": slot})
        if not anchors:
            raise BurrowlError("INVALID_ARGUMENT", "anchors 不能为空")
        self.ws.artifacts._artifact(artifact_id)
        return self.enqueue("formula", artifact_id, by=actor.id, params={"anchors": list(anchors), "engine": engine})

    # ---------- 版面引擎 ----------
    def _cache_path(self, art: dict):
        return self.ws.root / "cache" / "models" / self.adapter("layout") / f"{art['sha256']}.json"

    def _cached(self, art: dict) -> dict | None:
        path = self._cache_path(art)
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        except (OSError, ValueError):
            return None

    def _applied(self, art: dict) -> bool:
        cached = self._cached(art)
        return bool(cached and cached.get("applied_mode"))

    def _run_layout(self, job: dict) -> dict:
        with self.ws.lock:
            art = self.ws.artifacts._artifact(job["artifact_id"])
            result = self._cached(art)
            data = None if result else self.ws.artifacts.content(art)
            name, url = self.adapter("layout"), self.url("layout")
        if result is None:
            result = ma.ADAPTERS[name].parse(url, data, f"{art['id']}.pdf", tier=self.cfg.get("layout_tier"))
            path = self._cache_path(art)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        mode = job["params"].get("mode") or self.cfg.get("layout_mode", "formulas")
        actor = MODEL_ACTOR if job["by"] == MODEL_ACTOR.id else Actor(job["by"], "human", "ses_system")
        with self.ws.lock:
            out = self.apply_layout(actor, job["artifact_id"], result, mode=mode)
            result["applied_mode"] = mode
            self._cache_path(art).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return out

    def apply_layout(self, actor: Actor, artifact_id: str, result: dict, *, mode: str) -> dict:
        """把版面引擎的结果写进抽取层（D-06、D-07、D-12）。result 是适配器给出的统一格式：
        {tool, version, pages: [{page, blocks: [{type, box, text, latex?, level?, rows?, inline?}]}]}。"""
        ext = self.ws.extraction
        art = self.ws.artifacts._artifact(artifact_id)
        label = f"tool:{result['tool']}@{result.get('version') or '?'}"
        source = {"method": label, "fidelity": "ocr", "actor_id": MODEL_ACTOR.id,
                  **({"requested_by": actor.id} if actor.id != MODEL_ACTOR.id else {})}
        pages = {p["page"]: p["blocks"] for p in result.get("pages", [])}
        current = ext.current(artifact_id)
        units = {u["unit"]: u for u in ext.units(art) if u.get("page")}
        written, stats = [], {"latex": 0, "inserted": 0, "inline": 0, "replaced": 0}
        for unit, u in units.items():
            engine_blocks = pages.get(u["page"])
            row = current.get(unit)
            if not engine_blocks or row is None:
                continue
            d = row["data"]
            if mode == "replace":
                if d.get("fidelity") in ("manual", "ai") or (d.get("fidelity") == "ocr"
                                                             and not str(d.get("method", "")).startswith("tool:")):
                    continue  # 人工、AI、OCR 工具提交过的单元保留
                blocks = [ma.to_block(b, source) for b in engine_blocks]
                blocks = [b for b in blocks if b]
                text = "\n\n".join(t for t in (ex_text(b) for b in blocks) if t)
                if ext._content(actor, art, unit, status="text", text=text, blocks=blocks, meta=d.get("meta") or {},
                                method=label, fidelity="ocr", reason="版面引擎整份替换（设计稿 05 D-07）"):
                    written.append(unit)
                    stats["replaced"] += 1
                continue
            original = d.get("blocks") or []
            blocks = json.loads(json.dumps(original))
            got, inserted = match_formulas(blocks, [eb for eb in engine_blocks if eb["type"] == "formula"],
                                           source, insert=mode == "formulas")
            stats["latex"] += got
            stats["inserted"] += inserted
            for eb in engine_blocks:
                if not eb.get("box"):
                    continue
                if eb.get("inline"):  # 行内公式：记在对应段落的 inline_math，段落文字不变（D-12）
                    # 只对应到同一段：位置重叠，而且去掉公式后的文字长度相近（引擎的一段常覆盖内置抽取的几段）
                    plain = sum(len(r["v"]) for r in eb["inline"] if r["t"] == "text")
                    best = max(((b, iou(b["box"], eb["box"])) for b in blocks
                                if b.get("type") in ("paragraph", "heading") and b.get("box")),
                               key=lambda x: x[1], default=None)
                    similar = best and 0.6 <= len(best[0].get("text", "")) / max(plain, 1) <= 1.6
                    if best and best[1] >= IOU_MATCH and similar:
                        item = {"runs": eb["inline"], "source": label}
                        if best[0].get("inline_math") != item:
                            best[0]["inline_math"] = item
                            changed = True
                            stats["inline"] += sum(1 for r in eb["inline"] if r["t"] == "math")
            changed = blocks != original
            if changed and ext._content(actor, art, unit, status=d["status"], text=d.get("text", ""), blocks=blocks,
                                        meta=d.get("meta") or {}, method=d.get("method") or "",
                                        fidelity=d.get("fidelity"), reason=f"版面引擎补充公式（{label}）"):
                written.append(unit)
        out = ext._after_write(actor, art, written)
        return {**out, "mode": mode, "tool": label, **stats}

    # ---------- 公式识别 ----------
    def _run_formula(self, job: dict) -> dict:
        engine = job["params"]["engine"]
        with self.ws.lock:
            art = self.ws.artifacts._artifact(job["artifact_id"])
            crops = []
            for anchor in job["params"]["anchors"]:
                view = self.ws.extraction._view_block(art, self.ws.extraction.format(art), anchor)
                if view.get("type") != "formula":
                    raise BurrowlError("INVALID_ARGUMENT", "只有公式块可以识别", {"anchor": anchor})
                import base64  # noqa: PLC0415
                crops.append((view["anchor"], base64.b64decode(view["_image"]["base64"])))
            cfg = dict(self.cfg)
        results = []
        for anchor, png in crops:
            if engine == "llm":
                latex = ma.llm_formula(self.url("llm"), cfg.get("llm_key") or "", cfg.get("llm_model") or "", png)
                method = f"llm:{cfg.get('llm_model') or 'unknown'}"
            else:
                latex, version = ma.ADAPTERS["mineru"].formula(self.url("formula"), png,
                                                               tier=cfg.get("layout_tier"))
                method = f"tool:mineru@{version or '?'}"
            results.append({"anchor": anchor, "latex": latex, "method": method})
        with self.ws.lock:
            return self._write_formulas(job, results, engine)

    def _write_formulas(self, job: dict, results: list[dict], engine: str) -> dict:
        ext = self.ws.extraction
        art = self.ws.artifacts._artifact(job["artifact_id"])
        segs = {s["anchor"]: s for s in ext.segments(art)}
        current = ext.current(art["id"])
        actor = Actor(job["by"], "human" if job["by"].startswith("human") else "system", "ses_system")
        changed: dict[str, list] = {}
        done = []
        for r in results:
            seg = segs.get(r["anchor"])
            if seg is None or not r["latex"]:
                continue
            blocks = changed.setdefault(seg["unit"], json.loads(json.dumps(current[seg["unit"]]["data"]["blocks"])))
            b = blocks[seg["block"]]
            if (b.get("latex_source") or {}).get("fidelity") in KEEP_LATEX and job["by"] == MODEL_ACTOR.id:
                continue
            b["latex"] = r["latex"]
            b["latex_source"] = {"method": r["method"], "fidelity": "ai" if engine == "llm" else "ocr",
                                 "actor_id": MODEL_ACTOR.id, "requested_by": job["by"]}
            done.append(r["anchor"])
        written = []
        for unit, blocks in changed.items():
            d = current[unit]["data"]
            if ext._content(actor, art, unit, status=d["status"], text=d.get("text", ""), blocks=blocks,
                            meta=d.get("meta") or {}, method=d.get("method") or "", fidelity=d.get("fidelity"),
                            reason="模型识别公式（设计稿 05 D-11）"):
                written.append(unit)
        return {"artifact_id": art["id"], "recognized": done, "written": written,
                "latex": {r["anchor"]: r["latex"] for r in results}}


def union(boxes: list[list[float]]) -> list[float]:
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]


def match_formulas(blocks: list[dict], engine: list[dict], source: dict, *, insert: bool) -> tuple[int, int]:
    """把引擎的行间公式对应到内置抽取的公式块上（设计稿 05 D-06，按 Adam 论文实测修订）：
    - 内置抽取常把一条公式切成几块：落在同一条引擎公式范围里的几块成一组（latex_group），第一块带整条 LaTeX
      与整组的范围 latex_box，其余几块只标组号，显示时并入第一块；段落文字与锚点都不变；
    - 一个内置块包含几条引擎公式时，几条 LaTeX 依次记在 latex_parts；
    - 与任何内置块都不重叠的引擎公式，insert=True 时作为新的公式块插入（会改变后面的段落编号）。
    人工填写、AI 识别的 LaTeX 不覆盖。返回（补上 LaTeX 的块数，插入的块数）。"""
    for b in blocks:  # 上一次引擎补的分组与附加字段先清掉，按这一次的结果重算
        if (b.get("latex_source") or {}).get("method", "").startswith("tool:") or "latex_group" in b:
            for key in ("latex_group", "latex_parts", "latex_box"):
                b.pop(key, None)
        if str((b.get("inline_math") or {}).get("source", "")).startswith("tool:"):
            b.pop("inline_math")
    fidx = [i for i, b in enumerate(blocks) if b.get("type") == "formula" and b.get("box")]
    heads: dict[int, dict] = {}
    member_of: dict[int, int] = {}
    pending = []
    for eb in engine:
        if not eb.get("latex") or not eb.get("box"):
            continue
        inside = [i for i in fidx if coverage(blocks[i]["box"], eb["box"]) >= 0.6]
        if not inside:
            around = [i for i in fidx if coverage(eb["box"], blocks[i]["box"]) >= 0.6
                      or iou(eb["box"], blocks[i]["box"]) >= IOU_MATCH]
            inside = [max(around, key=lambda i: iou(eb["box"], blocks[i]["box"]))] if around else []
        if not inside:
            if insert and all(iou(b["box"], eb["box"]) < OVERLAP_FREE and coverage(eb["box"], b["box"]) < 0.5
                              for b in blocks if b.get("box")):
                pending.append(eb)
            continue
        head = min(member_of.get(i, i) for i in inside)
        entry = heads.setdefault(head, {"latex": [], "boxes": [], "members": set()})
        entry["latex"].append(eb["latex"])
        entry["boxes"].append(eb["box"])
        for i in inside:
            if i != head and i not in heads:
                entry["members"].add(i)
                member_of[i] = head
    got = 0
    for group, (head, e) in enumerate(sorted(heads.items()), start=1):
        b = blocks[head]
        if (b.get("latex_source") or {}).get("fidelity") in KEEP_LATEX:
            continue
        b["latex"], b["latex_source"] = e["latex"][0], source
        if len(e["latex"]) > 1:
            b["latex_parts"] = e["latex"]
        if e["members"] or len(e["boxes"]) > 1:
            b["latex_box"] = union([b["box"], *e["boxes"], *(blocks[m]["box"] for m in e["members"])])
        if e["members"]:
            b["latex_group"] = group
            for m in e["members"]:
                blocks[m]["latex_group"] = group
        got += 1
    for eb in pending:
        new = {"type": "formula", "text": eb.get("text") or eb["latex"], "box": eb["box"], "latex": eb["latex"],
               "latex_source": source, "inserted_by": source["method"]}
        at = next((i for i, b in enumerate(blocks) if b.get("box") and b.get("type") != "furniture"
                   and b["box"][1] > eb["box"][1]), len(blocks))
        blocks.insert(at, new)
    return got, len(pending)


def ex_text(block: dict) -> str:
    from . import extractors  # noqa: PLC0415
    return extractors.block_text(block)
