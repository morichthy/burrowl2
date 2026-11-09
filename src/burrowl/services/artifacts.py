"""F2 原件登记与导入、F3 读取记录与事实记录（草图 §2、§3、§12.1）。

- 原件只保证原文如实：内容寻址保存（managed），或只登记外部路径加 sha256（referenced，适合工业大文件）。
- 抬头只放可核对的元数据，不放 AI 总结。
- 整份原件不预先拆分；可读文本来自抽取层（services/extraction.py，设计稿 01 D-10），分段用于索引、读取与引用。
- 读到时才产生读取记录；读取记录是自动日志，不作为条目显示（设计稿 01 D-03）。
- 新版本登记为新原件并用 version_of 指向旧版本；引用了已变化片段的框架条目标为"输入已变化"（DESIGN §0）。
"""
from pathlib import Path

from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.hashing import sha256_bytes, sha256_file, sha256_text
from ..core.model import ARTIFACT_KINDS, SOURCE_CLASSES
from ..index.units import build_units
from .extractors import TEXT_SUFFIXES, format_of  # noqa: F401  TEXT_SUFFIXES 对外沿用


class ArtifactService:
    def __init__(self, ws):
        self.ws = ws
        self._verified_files: dict[tuple, str] = {}  # (路径, 大小, 修改时间) → 核对过的 sha256

    # ---------- 登记 ----------
    def register(self, actor: Actor, *, kind: str, source_class: str, path: str | None = None,
                 text: str | None = None, title: str | None = None, storage: str = "managed",
                 external_tier: str | None = None, version_of: str | None = None, metadata: dict | None = None,
                 objects: list[str] | None = None) -> dict:
        if kind not in ARTIFACT_KINDS:
            raise BurrowlError("INVALID_ARGUMENT", f"kind 必须是 {', '.join(ARTIFACT_KINDS)} 之一", {"kind": kind})
        if source_class not in SOURCE_CLASSES:
            raise BurrowlError("INVALID_ARGUMENT",
                               "source_class 必须是 local（本地实证）/ external（外部报告）/ inferred（推断）",
                               {"source_class": source_class})
        if (path is None) == (text is None):
            raise BurrowlError("INVALID_ARGUMENT", "path 与 text 必须且只能给一个")
        if version_of and not self.ws.ledger.get(version_of):
            raise BurrowlError("NOT_FOUND", "version_of 指向的原件不存在", {"version_of": version_of})

        data = {"title": title, "metadata": metadata or {}}
        if external_tier:
            data["external_tier"] = external_tier
        if text is not None:
            raw = text.encode("utf-8")
            digest, uri, storage = self.ws.blobs.put(raw), None, "managed"
            data.update(size=len(raw), media_type="text/plain")
        else:
            file = Path(path).expanduser().resolve()
            if not file.is_file():
                raise BurrowlError("NOT_FOUND", "文件不存在", {"path": str(file)})
            uri = file.as_uri()
            if storage == "managed":
                digest = self.ws.blobs.put(file.read_bytes())
            else:
                digest = sha256_file(file)
            data.update(size=file.stat().st_size, filename=file.name, suffix=file.suffix.lower(), path=str(file))
            data["title"] = title or file.name

        # 同内容、同位置的原件幂等：返回已有的那份
        existing = self.ws.ledger.query("SELECT id FROM artifacts WHERE sha256 = ? AND COALESCE(uri,'') = ?",
                                        (digest, uri or ""))
        if existing:
            return {**self.ws.ledger.get(existing[0]["id"]), "existing": True}

        art = self.ws.ledger.insert("artifacts", "art", {
            "kind": kind, "source_class": source_class, "sha256": digest, "storage": storage, "uri": uri,
            "version_of": version_of, "captured_by": actor.id, "session_id": actor.session_id, "data": data,
        }, objects=self.ws.linking.normalize_objects(objects or []))
        self.ws.capture.log(actor, "artifact.register", input={"artifact_id": art["id"], "kind": kind},
                            conditions={"sha256": digest, "uri": uri})
        try:
            extraction = self.ws.extraction.on_register(actor, art)
        except BurrowlError as exc:  # 抽取失败不阻断登记：失败记在单元清单里，状态检查会列出
            extraction = {"error": exc.message}
        self.index_artifact(art["id"])
        self.ws.linking.link_mentions(art["id"])
        if version_of:
            art["version_diff"] = self._propagate_version(actor, version_of, art["id"])
        if extraction:
            art["extraction"] = {k: v for k, v in extraction.items() if k in ("written", "error")}
        return art

    # ---------- 内容与分段 ----------
    def content(self, artifact: dict) -> bytes:
        if artifact["storage"] == "managed":
            return self.ws.blobs.get(artifact["sha256"])
        path = Path(artifact["data"]["path"])
        if not path.exists():
            raise BurrowlError("NOT_FOUND", "外部原件已不在原位置（依据已丢失）", {"uri": artifact["uri"]})
        data = path.read_bytes()
        if sha256_bytes(data) != artifact["sha256"]:
            raise BurrowlError("CONFLICT", "外部原件内容已变化，与登记时的指纹不一致", {"uri": artifact["uri"]})
        return data

    def file_path(self, artifact: dict) -> Path:
        """原件文件在磁盘上的位置（工作台打开原件用，设计稿 01 D-07）：受管原件在 blobs/，外部原件在登记的路径。

        外部原件必须与登记时的指纹一致，否则报 STALE_ARTIFACT（返回的必须是登记的那一版）。
        大小与修改时间没变时沿用上次核对的结果，避免视频拖动进度时反复计算整份文件的指纹。
        """
        if artifact["storage"] == "managed":
            path = self.ws.blobs.path(artifact["sha256"])
            if not path.exists():
                raise BurrowlError("NOT_FOUND", "受管原件的文件不在 blobs/ 里", {"artifact_id": artifact["id"]})
            return path
        path = Path(artifact["data"]["path"])
        if not path.exists():
            raise BurrowlError("NOT_FOUND", "外部原件已不在原位置（依据已丢失）", {"uri": artifact["uri"]})
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        if self._verified_files.get(key) != artifact["sha256"]:
            if sha256_file(path) != artifact["sha256"]:
                raise BurrowlError("STALE_ARTIFACT", "外部原件的内容与登记时不一致；请把新文件登记为新版本",
                                   {"uri": artifact["uri"], "artifact_id": artifact["id"]})
            self._verified_files[key] = artifact["sha256"]
        return path

    def text(self, artifact: dict) -> str | None:
        """文本类原件返回全文；其余格式返回 None，它们的文本在抽取层里（设计稿 01 D-10）。"""
        if format_of(artifact) == "text":
            return self.content(artifact).decode("utf-8", errors="replace")
        return None

    def segments(self, artifact_id: str) -> list[dict]:
        """当前抽取层的全部段落：ordinal、locator、anchor（引用写 art_…#anchor）、单元、文本、指纹、可信度档。"""
        return self.ws.extraction.segments(self._artifact(artifact_id))

    def index_artifact(self, artifact_id: str) -> None:
        """引用段落进 docs；相邻段落合并成检索单元进 units（设计稿 06 D-01 至 D-04）。"""
        try:
            segs = self.segments(artifact_id)
        except BurrowlError:
            segs = []  # 外部原件不可读时不建索引，读取时如实报错
        parts = [(s["ordinal"], s["locator"], s["sha256"], s["text"]) for s in segs]
        art = self.ws.ledger.get(artifact_id)
        title = art["data"].get("title") or ""
        if title:
            parts.insert(0, (-1, "title", sha256_text(title), title))
        # PDF 的页之间、Word 与文本的段落之间不断开；幻灯片、图片、音视频的单元之间断开（D-03）
        opts = self.ws.unit_options()
        units = build_units(segs, title=title, break_units=format_of(art) not in ("text", "pdf", "docx"), **opts)
        if not units and title:  # 没有可读文字（图片、未抽取）：标题本身也要能被找到
            units = build_units([{"anchor": "title", "text": title}], **opts)
        self.ws.index.replace(artifact_id, 0, "original", parts, units)

    def index_record(self, record_id: str) -> None:
        rec = self.ws.ledger.get(record_id)
        d = rec["data"]
        text = "\n".join(str(x) for x in (d.get("method"), d.get("result"), d.get("conditions")) if x)
        self.ws.index.replace(record_id, 0, "original", [(0, "record", sha256_text(text), text)],
                              build_units([{"anchor": "record", "text": text}], **self.ws.unit_options()))

    # ---------- 读取记录 ----------
    def read(self, actor: Actor, artifact_id: str, locator: str | None = None) -> dict:
        """读原件的一段或全部，并留下读取记录（哪份、哪个版本、哪个范围、读到的原文）。

        locator：省略时读全部；`seg:N`、`seg:N-M`；段落 `p3-2` / `seg-3`；单元 `p3`；单元范围 `p3:p5`。
        一次读取只写一条读取记录（D-03：不再另写 artifact.read 过程日志）。
        """
        art = self._artifact(artifact_id)
        self.ws.inspection.guard_artifact(actor, artifact_id)  # 不外发的原件在巡检运行里不能读（设计稿 08 D-31）
        chosen = self.ws.extraction.select(art, locator)
        segs = self.segments(artifact_id)
        excerpt = "\n\n".join(s["text"] for s in chosen)
        locator = locator or (f"seg:0-{len(segs) - 1}" if format_of(art) == "text" else "all")
        rd = self.ws.ledger.insert("reads", "rd", {
            "artifact_id": artifact_id, "artifact_sha256": art["sha256"], "locator": locator,
            "session_id": actor.session_id, "actor_id": actor.id,
            "data": {"excerpt": excerpt, "segments": [s["ordinal"] for s in chosen],
                     "anchors": [s["anchor"] for s in chosen],
                     "segment_sha256": [s["sha256"] for s in chosen], "of_total": len(segs),
                     "fidelity": sorted({s["fidelity"] for s in chosen if s["fidelity"]})},
        })
        out = {"read": rd, "segments": chosen, "artifact": art,
               "cite_as": [f"{artifact_id}#{s['anchor']}" for s in chosen]}
        low = [s["anchor"] for s in chosen if s["fidelity"] in ("ocr", "ai") and not s["verified"]]
        if low:
            out["notice"] = (f"段落 {', '.join(low[:10])} 来自 OCR / AI 识别，尚未经人确认；"
                             "引用前请用 artifact_view 对照原件复核")
        return out

    # ---------- 事实记录（正式条目） ----------
    def promote(self, actor: Actor, *, event_id: str | None = None, artifact_id: str | None = None,
                locator: str | None = None, objects: list[str] | None = None, method: str | None = None,
                result: str | None = None, boundary: str = "complete", gaps: list[str] | None = None,
                conditions: dict | None = None, reason: str = "") -> dict:
        """把日志或原件中的一段升级为事实记录：对象、条件、方法、结果（逐字）、边界（草图 §3）。

        条件只能整理，不能补写：给出的 conditions 每一项都必须已在事件捕获的条件里且取值相同，否则拒绝。
        结果默认取事件输出或原件片段的原文；给出 result 时必须是原文中的一段。
        """
        if (event_id is None) == (artifact_id is None):
            raise BurrowlError("INVALID_ARGUMENT", "event_id 与 artifact_id 必须且只能给一个")
        captured: dict = {}
        if event_id:
            event = self.ws.ledger.get(event_id)
            if not event or event["entry_kind"] != "event":
                raise BurrowlError("NOT_FOUND", "事件不存在", {"event_id": event_id})
            captured = event["data"].get("conditions", {})
            original = self.ws.capture.output_of(event)
            objects = list(dict.fromkeys([*event["objects"], *(objects or [])]))
        else:
            art = self._artifact(artifact_id)
            original = "\n\n".join(s["text"] for s in self.ws.extraction.select(art, locator))
        backfilled = {k: v for k, v in (conditions or {}).items() if captured.get(k) != v}
        if backfilled:
            raise BurrowlError("CONDITION_BACKFILL", "条件必须在发生当下记录，升级时不能补写；缺失的请写进 gaps",
                               {"not_captured": sorted(backfilled)})
        if result is not None and result not in original:
            raise BurrowlError("NOT_VERBATIM", "结果必须逐字取自原文", {"result_head": result[:80]})
        if boundary not in ("complete", "truncated", "partial", "restricted"):
            raise BurrowlError("INVALID_ARGUMENT", "boundary 取值不对", {"boundary": boundary})
        rec = self.ws.ledger.insert("records", "rec", {
            "event_id": event_id, "artifact_id": artifact_id, "boundary": boundary, "promoted_by": actor.id,
            "data": {"conditions": conditions if conditions is not None else captured, "method": method,
                     "result": result if result is not None else original, "gaps": gaps or [],
                     "locator": locator, "reason": reason},
        }, objects=self.ws.linking.normalize_objects(objects or []))
        self.index_record(rec["id"])
        return rec

    # ---------- 内部 ----------
    def _artifact(self, artifact_id: str) -> dict:
        art = self.ws.ledger.get(artifact_id)
        if not art or art["entry_kind"] != "artifact":
            raise BurrowlError("NOT_FOUND", "原件不存在", {"artifact_id": artifact_id})
        return art

    def _propagate_version(self, actor: Actor, old_id: str, new_id: str) -> dict:
        """比较新旧版本的段落指纹；引用了旧版本中已变化或已删除段落的读取记录、判断，
        以及以它们为输入的框架条目，标为"输入已变化"（设计稿 01 D-02：判断里记下的 cited_segments 是依据）。"""
        old = {s["sha256"] for s in self.segments(old_id)} if self._readable(old_id) else set()
        new = {s["sha256"] for s in self.segments(new_id)} if self._readable(new_id) else set()
        removed = old - new
        reads = self.ws.ledger.query("SELECT id, data FROM reads WHERE artifact_id = ?", (old_id,))
        touched_reads = [r["id"] for r in reads if set(r["data"].get("segment_sha256", [])) & removed]
        touched_judgments = []
        if removed:
            ids = {r["id"] for r in self.ws.ledger.query("SELECT id FROM judgments WHERE data LIKE ?",
                                                          (f"%{old_id}#%",))}
            ids |= {r["src_id"] for r in self.ws.ledger.query(
                "SELECT src_id FROM links WHERE rel = 'used' AND dst_id LIKE ?", (f"{old_id}#%",))}
            for jid in sorted(ids):
                cited = self.ws.extraction.cited_hashes(self.ws.ledger.get(jid))
                if any(c["artifact_id"] == old_id and c["sha256"] in removed for c in cited):
                    touched_judgments.append(jid)
        inputs = [*touched_reads, *touched_judgments]
        marked = self.ws.propagation.propagate([old_id, *inputs] if removed else inputs,
                                               reason=f"原件出了新版本 {new_id}")
        return {"removed_segments": len(removed), "added_segments": len(new - old), "marked": marked,
                "affected_judgments": touched_judgments}

    def _readable(self, artifact_id: str) -> bool:
        try:
            return bool(self.segments(artifact_id))
        except BurrowlError:
            return False
