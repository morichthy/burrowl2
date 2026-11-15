"""阅读会话：人能一眼看到 AI 这次用了 burrowl 的哪些东西、得到了什么认知、为什么在读，以及可交接的 handoff。

不新增表、不新增状态（ARCHITECTURE 的"状态由谁负责"）：
- **读了什么**不另存，读时从读取记录（`reads`）、检索命中记录（`search` 事件）和本会话写的判断算出；
- **目的、认知、handoff** 是 AI 自己维护的笔记，写成会话内只追加的过程事件 `reading.note`（过程笔记，
  不能作为结论的依据，I11）。每次调用只带要更新的字段，各字段取最新一次给出的值；
- handoff：agent 已有自己的 handoff 文件时，AI 提交内容快照并在 `handoff_source` 登记它的绝对路径，人在工作台
  点击阅读时实时读这个文件（`handoff_file`，只读登记的那个路径，读不到退回快照）；没有就由 AI 直接写。
"""
from datetime import UTC, datetime
from pathlib import Path

from ..core.actor import Actor
from ..core.errors import BurrowlError

NOTE_OP = "reading.note"
NUDGE_AFTER = 5       # 上一次笔记之后又检索或读了这么多次，就再提醒一次
MAX_FINDINGS = 30
LIST_LIMIT = 30
LIVE_SUFFIXES = (".md", ".markdown", ".txt")
LIVE_MAX_BYTES = 512 * 1024
HINT = ("请用 reading_note 维护本次阅读会话的笔记：purpose 写目前工作的目的，findings 写已得到的认知"
        "（refs 填依据的条目），handoff 写可交接的进展；agent 已有自己的 handoff 文件时把内容提交进来，"
        "没有就直接写。人在工作台首页的\"阅读会话\"里看。")


def _clip(text: object, limit: int) -> str:
    return str(text or "").strip()[:limit]


class ReadingService:
    def __init__(self, ws):
        self.ws = ws

    # ---------- AI 写笔记 ----------
    def note(self, actor: Actor, *, purpose: str | None = None, findings: list[dict] | None = None,
             handoff: str | None = None, handoff_source: str | None = None) -> dict:
        if actor.kind != "ai":
            raise BurrowlError("FORBIDDEN", "阅读会话笔记由 AI 维护；人想记录请写判断或登记原件", {"actor": actor.id})
        purpose = _clip(purpose, 500) or None
        handoff = (handoff or "").strip() or None
        if purpose is None and findings is None and handoff is None:
            raise BurrowlError("INVALID_ARGUMENT", "purpose、findings、handoff 至少给一个")
        clean = None
        if findings is not None:
            if len(findings) > MAX_FINDINGS:
                raise BurrowlError("INVALID_ARGUMENT", f"findings 最多 {MAX_FINDINGS} 条，请合并后再提交")
            clean = []
            for f in findings:
                text = _clip(f.get("text") if isinstance(f, dict) else f, 800)
                if not text:
                    continue
                refs = [str(r) for r in ((f.get("refs") if isinstance(f, dict) else None) or [])][:10]
                bad = [r for r in refs if not self.ws.get(r)]
                if bad:
                    raise BurrowlError("NOT_FOUND", "refs 里有不存在的条目", {"refs": bad})
                clean.append({"text": text, "refs": refs})
        data: dict = {}
        if purpose is not None:
            data["purpose"] = purpose
        if clean is not None:
            data["findings"] = clean
        if handoff_source:
            data["handoff_source"] = _clip(handoff_source, 500)
        event = self.ws.capture.log(actor, NOTE_OP, input=data, output=handoff, source_class="inferred")
        updated = sorted({*data, *(["handoff"] if handoff else [])})
        return {"id": event["id"], "session_id": actor.session_id, "updated": updated}

    # ---------- 提醒 ----------
    def hint(self, actor: Actor) -> str | None:
        """检索结果里催 AI 维护笔记：还没写过，或写过之后又用了 NUDGE_AFTER 次。"""
        if actor.kind != "ai":
            return None
        ledger = self.ws.ledger
        last = ledger.query("SELECT created_at FROM events WHERE session_id = ? AND op = ? "
                            "ORDER BY seq DESC LIMIT 1", (actor.session_id, NOTE_OP))
        since = last[0]["created_at"] if last else ""
        used = ledger.query("SELECT COUNT(*) AS n FROM events WHERE session_id = ? AND op = 'search' "
                            "AND created_at > ?", (actor.session_id, since))[0]["n"]
        used += ledger.query("SELECT COUNT(*) AS n FROM reads WHERE session_id = ? AND created_at > ?",
                             (actor.session_id, since))[0]["n"]
        if (not last and used >= 1) or used >= NUDGE_AFTER:
            return HINT
        return None

    # ---------- 工作台读 ----------
    def sessions(self, limit: int = LIST_LIMIT) -> list[dict]:
        """最近的 AI 会话（用过检索、读过原件或写过笔记的）：目的、用了多少、最后活跃时间、有没有 handoff。"""
        q = self.ws.ledger.query
        seen: dict[str, dict] = {}

        def merge(rows: list[dict], field: str | None) -> None:
            for r in rows:
                s = seen.setdefault(r["session_id"], {"session_id": r["session_id"], "actor": r["actor_id"],
                                                       "first_at": r["first"], "last_at": r["last"],
                                                       "searches": 0, "artifacts_read": 0, "notes": 0})
                s["first_at"], s["last_at"] = min(s["first_at"], r["first"]), max(s["last_at"], r["last"])
                if field:
                    s[field] = r["n"]

        merge(q("SELECT session_id, actor_id, MIN(created_at) AS first, MAX(created_at) AS last, COUNT(*) AS n "
                "FROM events WHERE actor_kind = 'ai' AND op = 'search' GROUP BY session_id "
                "ORDER BY last DESC LIMIT ?", (limit,)), "searches")
        merge(q("SELECT session_id, actor_id, MIN(created_at) AS first, MAX(created_at) AS last, COUNT(*) AS n "
                "FROM events WHERE actor_kind = 'ai' AND op = ? GROUP BY session_id ORDER BY last DESC LIMIT ?",
                (NOTE_OP, limit)), "notes")
        merge(q("SELECT session_id, actor_id, MIN(created_at) AS first, MAX(created_at) AS last, "
                "COUNT(DISTINCT artifact_id) AS n FROM reads WHERE actor_id LIKE 'ai:%' AND session_id IS NOT NULL "
                "GROUP BY session_id ORDER BY last DESC LIMIT ?", (limit,)), "artifacts_read")
        out = sorted(seen.values(), key=lambda s: s["last_at"], reverse=True)[:limit]
        for s in out:
            view = self._notes(s["session_id"])
            s.update(purpose=view["purpose"], findings=len(view["findings"]), has_handoff=bool(view["handoff"]))
        return out

    def _notes(self, session_id: str) -> dict:
        """各字段取最新一次给出的值。"""
        view: dict = {"purpose": None, "findings": [], "handoff": None, "handoff_source": None, "handoff_at": None,
                      "notes": []}
        for e in self.ws.capture.session(session_id):
            if e["op"] != NOTE_OP:
                continue
            d = (e["data"] or {}).get("input") or {}
            if "purpose" in d:
                view["purpose"] = d["purpose"]
            if "findings" in d:
                view["findings"] = d["findings"]
            if d.get("handoff_source"):
                view["handoff_source"] = d["handoff_source"]
            handoff = self.ws.capture.output_of(e)
            if handoff:
                view["handoff"], view["handoff_at"] = handoff, e["created_at"]
            view["notes"].append({"id": e["id"], "at": e["created_at"], "fields": [
                k for k in ("purpose", "findings") if k in d] + (["handoff"] if handoff else [])})
        return view

    def get(self, session_id: str) -> dict:
        """一个阅读会话：笔记 + 这次读了什么（读过的原件段落、检索命中的条目、写下的判断）。"""
        ledger = self.ws.ledger
        events = self.ws.capture.session(session_id)
        reads_rows = ledger.query("SELECT * FROM reads WHERE session_id = ? ORDER BY created_at", (session_id,))
        if not events and not reads_rows:
            raise BurrowlError("NOT_FOUND", "没有这个会话的记录", {"session_id": session_id})
        view = self._notes(session_id)

        read: dict[str, dict] = {}
        for r in reads_rows:
            d = r["data"] or {}
            anchors = d.get("anchors") or [f"seg-{n}" for n in d.get("segments", [])]
            slot = read.setdefault(r["artifact_id"], {"id": r["artifact_id"], "anchors": [], "times": 0,
                                                       "first_at": r["created_at"], "last_at": r["created_at"]})
            slot["anchors"] = list(dict.fromkeys([*slot["anchors"], *anchors]))
            slot["times"] += 1
            slot["last_at"] = r["created_at"]

        searches, hit_ids = [], {}
        for e in events:
            if e["op"] != "search":
                continue
            d = (e["data"] or {}).get("input") or {}
            hits = d.get("hits") or []
            searches.append({"at": e["created_at"], "query": d.get("query", ""), "mode": d.get("mode", ""),
                             "via": d.get("via", "search"), "hits": [h["id"] for h in hits]})
            for h in hits:
                hit_ids.setdefault(h["id"], e["created_at"])
        # 命中过但没读原文的：参考过，但不要让人误以为读过
        returned = [{"id": i, "at": at, "read": i in read} for i, at in hit_ids.items()]

        written = [{"id": j["id"], "version": j["version"], "kind": j["kind"], "at": j["created_at"]}
                   for j in ledger.query("SELECT id, version, kind, created_at FROM judgments WHERE session_id = ? "
                                         "ORDER BY created_at", (session_id,))]
        started = min([e["created_at"] for e in events] + [r["created_at"] for r in reads_rows])
        last = max([e["created_at"] for e in events] + [r["created_at"] for r in reads_rows])
        actor = (events or reads_rows)[0].get("actor_id")
        return {"session_id": session_id, "actor": actor, "started_at": started, "last_at": last,
                **{k: view[k] for k in ("purpose", "findings", "handoff", "handoff_source", "handoff_at", "notes")},
                "read": list(read.values()), "returned": returned, "searches": searches, "written": written,
                "refs_in_findings": sorted({r for f in view["findings"] for r in f.get("refs", [])})}

    def handoff_file(self, session_id: str) -> dict:
        """实时读 AI 登记的 handoff 文件（只在人在工作台点击时调用）。只读这个会话最近一次登记的 `handoff_source`，
        且须是已存在的绝对路径、文本或 Markdown 后缀、不超过 512 KB；否则不读，工作台退回显示最近提交的快照。"""
        source = self._notes(session_id)["handoff_source"]
        if not source:
            return {"available": False, "reason": "AI 没有登记 handoff 文件的路径"}
        path = Path(source).expanduser()
        if not path.is_absolute():
            return {"available": False, "path": source, "reason": "登记的不是绝对路径，工作台不读"}
        try:
            path = path.resolve(strict=True)
        except OSError:
            return {"available": False, "path": source, "reason": "文件不存在或不可访问"}
        if not path.is_file() or path.suffix.lower() not in LIVE_SUFFIXES:
            return {"available": False, "path": source, "reason": "只读 .md、.markdown、.txt 文件"}
        try:
            stat = path.stat()
            if stat.st_size > LIVE_MAX_BYTES:
                return {"available": False, "path": source, "reason": "文件超过 512 KB，不实时读取"}
            text = path.read_bytes().decode("utf-8", errors="replace")
        except OSError as exc:
            return {"available": False, "path": source, "reason": f"读取失败：{exc.strerror or exc}"}
        modified = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        return {"available": True, "path": str(path), "text": text, "modified_at": modified, "size": stat.st_size}

