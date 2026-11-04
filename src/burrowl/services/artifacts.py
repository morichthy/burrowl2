"""F2 原件登记与导入、F3 读取记录与事实记录（草图 §2、§3、§12.1）。

- 原件只保证原文如实：内容寻址保存（managed），或只登记外部路径加 sha256（referenced，适合工业大文件）。
- 抬头只放可核对的元数据，不放 AI 总结。
- 整份原件不预先拆分；分段只用于索引。读到时才产生读取记录。
- 新版本登记为新原件并用 version_of 指向旧版本；引用了已变化片段的框架条目标为"输入已变化"（DESIGN §0）。
"""
from pathlib import Path

from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.hashing import sha256_bytes, sha256_file, sha256_text
from ..core.model import ARTIFACT_KINDS, SOURCE_CLASSES
from ..index.segment import segment_text

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".log", ".py", ".yaml", ".yml",
                 ".xml", ".html", ".htm", ".ini", ".cfg", ".toml", ".sql", ".rst", ".tex"}


class ArtifactService:
    def __init__(self, ws):
        self.ws = ws

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
        self.index_artifact(art["id"])
        self.ws.linking.link_mentions(art["id"])
        if version_of:
            art["version_diff"] = self._propagate_version(actor, version_of, art["id"])
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

    def text(self, artifact: dict) -> str | None:
        """可抽取文本的原件返回文本；图片、二进制等返回 None（它们需要框架层的描述，草图 §11.1）。"""
        suffix = artifact["data"].get("suffix")
        if artifact["storage"] == "managed" and suffix is None:
            return self.content(artifact).decode("utf-8", errors="replace")
        if suffix in TEXT_SUFFIXES:
            return self.content(artifact).decode("utf-8", errors="replace")
        return None

    def segments(self, artifact_id: str) -> list[dict]:
        art = self._artifact(artifact_id)
        text = self.text(art)
        if text is None:
            return []
        return [{"ordinal": s.ordinal, "locator": s.locator, "text": s.text, "lines": [s.line_start, s.line_end],
                 "sha256": sha256_text(s.text)} for s in segment_text(text)]

    def index_artifact(self, artifact_id: str) -> None:
        try:
            parts = [(s["ordinal"], s["locator"], s["sha256"], s["text"]) for s in self.segments(artifact_id)]
        except BurrowlError:
            parts = []  # 外部原件不可读时不建索引，读取时如实报错
        art = self.ws.ledger.get(artifact_id)
        title = art["data"].get("title") or ""
        if title:
            parts.insert(0, (-1, "title", sha256_text(title), title))
        self.ws.index.replace(artifact_id, 0, "original", parts)

    def index_record(self, record_id: str) -> None:
        rec = self.ws.ledger.get(record_id)
        d = rec["data"]
        text = "\n".join(str(x) for x in (d.get("method"), d.get("result"), d.get("conditions")) if x)
        self.ws.index.replace(record_id, 0, "original", [(0, "record", sha256_text(text), text)])

    # ---------- 读取记录 ----------
    def read(self, actor: Actor, artifact_id: str, locator: str | None = None) -> dict:
        """读原件的一段或全部，并留下读取记录（哪份、哪个版本、哪个范围、读到的原文）。

        locator：`seg:N`、`seg:N-M`，省略时读全部分段。
        """
        art = self._artifact(artifact_id)
        segs = self.segments(artifact_id)
        if not segs:
            raise BurrowlError("UNREADABLE", "这份原件没有可读的文本（图片或二进制），请看它的描述页",
                               {"artifact_id": artifact_id})
        chosen = _select(segs, locator)
        excerpt = "\n\n".join(s["text"] for s in chosen)
        locator = locator or f"seg:0-{len(segs) - 1}"
        rd = self.ws.ledger.insert("reads", "rd", {
            "artifact_id": artifact_id, "artifact_sha256": art["sha256"], "locator": locator,
            "session_id": actor.session_id, "actor_id": actor.id,
            "data": {"excerpt": excerpt, "segments": [s["ordinal"] for s in chosen],
                     "segment_sha256": [s["sha256"] for s in chosen], "of_total": len(segs)},
        })
        self.ws.capture.log(actor, "artifact.read", input={"artifact_id": artifact_id, "locator": locator},
                            conditions={"read_id": rd["id"]})
        return {"read": rd, "segments": chosen, "artifact": art}

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
            self._artifact(artifact_id)
            original = "\n\n".join(s["text"] for s in _select(self.segments(artifact_id), locator))
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
        """比较新旧版本的片段哈希；引用了旧版本中已变化或已删除片段的框架条目标为"输入已变化"。"""
        old = {s["sha256"] for s in self.segments(old_id)} if self._readable(old_id) else set()
        new = {s["sha256"] for s in self.segments(new_id)} if self._readable(new_id) else set()
        removed = old - new
        reads = self.ws.ledger.query("SELECT id, data FROM reads WHERE artifact_id = ?", (old_id,))
        touched_reads = [r["id"] for r in reads if set(r["data"].get("segment_sha256", [])) & removed]
        marked = self.ws.propagation.propagate([old_id, *touched_reads] if removed else touched_reads,
                                               reason=f"原件出了新版本 {new_id}")
        return {"removed_segments": len(removed), "added_segments": len(new - old), "marked": marked}

    def _readable(self, artifact_id: str) -> bool:
        try:
            return bool(self.segments(artifact_id))
        except BurrowlError:
            return False


def _select(segs: list[dict], locator: str | None) -> list[dict]:
    if not locator:
        return segs
    if not locator.startswith("seg:"):
        raise BurrowlError("INVALID_ARGUMENT", "locator 应为 seg:N 或 seg:N-M", {"locator": locator})
    span = locator[4:]
    start, _, end = span.partition("-")
    try:
        a, b = int(start), int(end or start)
    except ValueError as exc:
        raise BurrowlError("INVALID_ARGUMENT", "locator 应为 seg:N 或 seg:N-M", {"locator": locator}) from exc
    chosen = [s for s in segs if a <= s["ordinal"] <= b]
    if not chosen:
        raise BurrowlError("INVALID_ARGUMENT", "locator 超出范围", {"locator": locator, "segments": len(segs)})
    return chosen

