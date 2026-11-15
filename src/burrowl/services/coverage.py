"""覆盖图与检索命中记录（设计稿 08 D-09 至 D-13）。

- 检索命中记录（D-12）：AI 调用 search / search.associate 时，在过程日志里记一条 `search` 事件，
  只记查询、模式、返回的条目与命中段落锚点（前 20 个），不记全文；人在工作台里的检索不记。
- 覆盖图（D-10、D-11）：每个原件段落分五档——被引用 cited / 读过未引 read / 命中未读 hit_unread /
  相关未读 related_unread / 冷区 cold。每次从读取记录、判断的引用、检索命中记录与检索单元算出，不单独存储；
  它是框架内容，不能作为依据，也不当作要提高的指标（D-13、原则 4）。已退役的原件不计入。
- 探索样本（D-09）：从"命中未读""相关未读"两档里按"相关度 × 被抽中过几次"挑段落，供巡检包使用。
"""
from datetime import UTC, datetime, timedelta

from ..core.actor import Actor
from ..core.errors import BurrowlError

# pointed：只被要点用到（设计稿 15 D-35）。要点是框架，不算"被引用"，否则消化一次覆盖图就全绿
STATES = ("cited", "pointed", "read", "hit_unread", "related_unread", "cold")
STATE_LABEL = {"cited": "被引用", "pointed": "要点已收", "read": "读过未引", "hit_unread": "命中未读",
               "related_unread": "相关未读", "cold": "冷区"}
HIT_LOG_LIMIT = 20       # 每次检索最多记几个命中条目
RELATED_PER_JUDGMENT = 8  # 每条近期判断取几个最相关的检索单元
FOCUS_DAYS = 30           # 没有给出近期判断时，取最近多少天的判断


def _anchors_of(hit: dict) -> list[str]:
    out: list[str] = []
    for p in hit.get("passages") or []:
        out += p.get("anchors") or []
    if hit.get("anchor"):
        out.append(hit["anchor"])
    return list(dict.fromkeys(out))


def _since(days: float) -> str:
    """与账本的 created_at 同一格式（毫秒、Z 结尾）。"""
    t = datetime.now(UTC) - timedelta(days=days)
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class CoverageService:
    def __init__(self, ws):
        self.ws = ws

    # ---------- 检索命中记录（D-12） ----------
    def log_search(self, actor: Actor, op: str, query: str | None, mode: str, result: dict) -> None:
        if actor.kind != "ai":
            return
        hits = []
        for h in (result.get("hits") or [])[:HIT_LOG_LIMIT]:
            hid = h.get("id")
            if not hid:
                continue
            base = hid.split("#", 1)[0]
            anchors = _anchors_of(h)
            if "#" in hid:
                anchors.append(hid.split("#", 1)[1])
            hits.append({"id": base, **({"anchors": list(dict.fromkeys(anchors))} if anchors else {})})
        self.ws.capture.log(actor, "search", input={"via": op, "query": (query or "")[:200], "mode": mode,
                                                    "hits": hits}, source_class="inferred")

    # ---------- 原始数据 ----------
    def _segments(self, art: dict) -> list[dict]:
        try:
            return self.ws.extraction.segments(art)
        except BurrowlError:
            return []

    def _reads(self) -> dict[str, dict[str, str]]:
        """{原件: {段落锚点: 最后一次读取时间}}。人和 AI 的读取都算。"""
        out: dict[str, dict[str, str]] = {}
        for r in self.ws.ledger.query("SELECT artifact_id, created_at, data FROM reads ORDER BY created_at"):
            d = r["data"] or {}
            anchors = d.get("anchors") or [f"seg-{n}" for n in d.get("segments", [])]
            slot = out.setdefault(r["artifact_id"], {})
            for a in anchors:
                slot[a] = r["created_at"]
        return out

    def _cited(self) -> dict[str, dict[str, list[str]]]:
        """{原件: {段落锚点: [依据它的判断]}}：判断以 cites 关系引用的原件段落（设计稿 10 D-08）。"""
        out: dict[str, dict[str, list[str]]] = {}
        for r in self.ws.ledger.query("SELECT subject_id, object_id, object_anchor FROM effective_relations "
                                      "WHERE predicate = 'cites' AND object_id LIKE 'art_%' AND object_anchor != '' "
                                      "AND subject_id LIKE 'jdg_%'"):
            out.setdefault(r["object_id"], {}).setdefault(r["object_anchor"], []).append(r["subject_id"])
        return out

    def _pointed(self) -> dict[str, dict[str, list[str]]]:
        """{原件: {段落锚点: [用到它的要点]}}：要点当前版的输入清单里的原件段落。"""
        out: dict[str, dict[str, list[str]]] = {}
        for r in self.ws.framework_db.execute(
                "SELECT di.derived_id, di.input_id FROM derivation_inputs di JOIN pages p ON p.id = di.derived_id "
                "AND di.derived_version = p.head_version WHERE di.derived_kind = 'page' AND p.type = 'point' "
                "AND p.review != 'rejected' AND di.input_id LIKE 'art_%#%'"):
            ref = r["input_id"]
            base, anchor = ref.split("#", 1)
            out.setdefault(base.split("@", 1)[0], {}).setdefault(anchor, []).append(r["derived_id"])
        return out

    def _hits(self, window_days: float) -> dict[str, dict[str, int]]:
        """{原件: {段落锚点: 窗口内被检索返回的次数}}。"""
        out: dict[str, dict[str, int]] = {}
        for ev in self.ws.ledger.query("SELECT data FROM events WHERE op = 'search' AND created_at >= ?",
                                       (_since(window_days),)):
            for h in ((ev["data"] or {}).get("input") or {}).get("hits") or []:
                if not h.get("id", "").startswith("art_"):
                    continue
                slot = out.setdefault(h["id"], {})
                for a in h.get("anchors") or []:
                    slot[a] = slot.get(a, 0) + 1
        return out

    def focus_judgments(self, since: str | None = None, limit: int = 30) -> list[dict]:
        since = since or _since(FOCUS_DAYS)
        return self.ws.ledger.query(
            "SELECT * FROM judgments WHERE created_at >= ? AND kind IN ('conclusion', 'constraint', 'thought') "
            "ORDER BY created_at DESC LIMIT ?", (since, limit))

    def _related(self, judgments: list[dict]) -> dict[str, dict[str, float]]:
        """{原件: {段落锚点: 相关度}}：与近期判断最相关的原件检索单元。有向量模型时用向量相似度
        （不低于 inspection.related_min），没有时用词法检索的名次。"""
        out: dict[str, dict[str, float]] = {}
        threshold = float(self.settings()["related_min"])
        for j in judgments:
            text = (j["data"] or {}).get("text") or ""
            if not text.strip():
                continue
            dense = self.ws.vectors.search(text, layers=["original"], limit=RELATED_PER_JUDGMENT)
            scored: list[tuple[object, float]] = []
            if dense["units"]:
                scored = [(u, float(getattr(u, "score", 0.0))) for u in dense["units"]]
                scored = [(u, s) for u, s in scored if s >= threshold]
            else:
                lexical = self.ws.index.search_units(text, layers=["original"], limit=RELATED_PER_JUDGMENT)
                scored = [(u, 1.0 / (1 + i)) for i, u in enumerate(lexical)]
            for u, score in scored:
                if not u.entry_id.startswith("art_"):
                    continue
                slot = out.setdefault(u.entry_id, {})
                for a in u.anchors:
                    if a != "title":
                        slot[a] = max(slot.get(a, 0.0), score)
        return out

    def settings(self) -> dict:
        return self.ws.inspection.settings()

    # ---------- 覆盖图（D-10、D-11） ----------
    def compute(self, *, focus: list[dict] | None = None, artifact_ids: list[str] | None = None) -> dict:
        """逐段分档。返回 {原件: {"artifact": …, "segments": [{anchor, unit, state, …}]}}。"""
        s = self.settings()
        retired = self.ws.judgments.retired_ids()
        reads, cited, hits = self._reads(), self._cited(), self._hits(float(s["window_days"]))
        pointed = self._pointed()
        related = self._related(focus if focus is not None else self.focus_judgments())
        hit_min = int(s["hit_min"])
        if artifact_ids is None:
            arts = self.ws.ledger.query("SELECT * FROM artifacts ORDER BY created_at")
        else:
            arts = [a for a in (self.ws.ledger.get(i) for i in artifact_ids) if a]
        out: dict[str, dict] = {}
        for art in arts:
            if art["id"] in retired:
                continue
            segs = self._segments(art)
            if not segs:
                continue
            r, c, h, rel = (reads.get(art["id"], {}), cited.get(art["id"], {}), hits.get(art["id"], {}),
                            related.get(art["id"], {}))
            rows = []
            for seg in segs:
                a = seg["anchor"]
                if a in c:
                    state = "cited"
                elif a in pointed.get(art["id"], {}):
                    state = "pointed"
                elif a in r:
                    state = "read"
                elif h.get(a, 0) >= hit_min:
                    state = "hit_unread"
                elif a in rel:
                    state = "related_unread"
                else:
                    state = "cold"
                rows.append({"anchor": a, "unit": seg["unit"], "ordinal": seg["ordinal"], "sha256": seg["sha256"],
                             "state": state, "hits": h.get(a, 0), "last_read": r.get(a),
                             "related": round(rel[a], 3) if a in rel else None, "cited_by": c.get(a, []),
                             "points": pointed.get(art["id"], {}).get(a, []),
                             "head": seg["text"][:80]})
            out[art["id"]] = {"artifact": art, "segments": rows}
        return out

    def view(self, artifact_id: str | None = None) -> dict:
        """覆盖图：不给 artifact_id 时按原件和对象汇总各档段落数；给出时列出这份原件每一段的档位、
        命中次数、最后读取时间、引用它的判断。"""
        if artifact_id:
            data = self.compute(artifact_ids=[artifact_id]).get(artifact_id)
            if data is None:
                raise BurrowlError("NOT_FOUND", "原件不存在、已退役或没有可读段落", {"artifact_id": artifact_id})
            art = data["artifact"]
            readers = {}
            for r in self.ws.ledger.query("SELECT data, session_id FROM reads WHERE artifact_id = ?", (artifact_id,)):
                for a in (r["data"] or {}).get("anchors") or []:
                    readers.setdefault(a, set()).add(r["session_id"])
            for row in data["segments"]:
                row["sessions"] = len(readers.get(row["anchor"], ()))
            return {"artifact": {"id": art["id"], "title": art["data"].get("title"), "kind": art["kind"],
                                 "outbound": self.ws.inspection.outbound(art["id"])},
                    "counts": _counts(data["segments"]), "segments": data["segments"],
                    "states": STATE_LABEL, "settings": self._shown_settings()}
        computed = self.compute()
        artifacts, objects = [], {}
        totals = dict.fromkeys(STATES, 0)
        for art_id, data in computed.items():
            counts = _counts(data["segments"])
            for k, v in counts.items():
                totals[k] += v
            art = data["artifact"]
            artifacts.append({"id": art_id, "title": art["data"].get("title"), "kind": art["kind"],
                              "counts": counts, "total": len(data["segments"]),
                              "cells": [row["state"] for row in data["segments"]],
                              "outbound": self.ws.inspection.outbound(art_id)})
            for obj in self.ws.ledger.objects_of(art_id):
                slot = objects.setdefault(obj, dict.fromkeys(STATES, 0))
                for k, v in counts.items():
                    slot[k] += v
        artifacts.sort(key=lambda a: (-(a["counts"]["hit_unread"] + a["counts"]["related_unread"]), a["id"]))
        return {"totals": totals, "artifacts": artifacts,
                "objects": [{"object": k, "counts": v} for k, v in sorted(objects.items())],
                "states": STATE_LABEL, "settings": self._shown_settings()}

    def _shown_settings(self) -> dict:
        s = self.settings()
        return {"window_days": s["window_days"], "hit_min": s["hit_min"], "related_min": s["related_min"]}

    # ---------- 探索样本（D-09） ----------
    def explore_candidates(self, focus: list[dict], sampled_before: dict[str, int],
                           exclude_artifacts: set[str]) -> list[dict]:
        """命中未读、相关未读的段落，按"相关度 × 0.3^被抽中次数"从高到低。"""
        out = []
        for art_id, data in self.compute(focus=focus).items():
            if art_id in exclude_artifacts:
                continue
            for row in data["segments"]:
                if row["state"] not in ("hit_unread", "related_unread"):
                    continue
                ref = f"{art_id}#{row['anchor']}"
                if row["state"] == "hit_unread":
                    relevance = 0.5 + row["hits"] / (row["hits"] + 2)
                else:
                    relevance = row["related"] or 0.0
                weight = relevance * (0.3 ** sampled_before.get(ref, 0))
                out.append({"ref": ref, "artifact_id": art_id, "anchor": row["anchor"], "state": row["state"],
                            "sha256": row["sha256"], "hits": row["hits"], "relevance": round(relevance, 3),
                            "weight": round(weight, 4), "head": row["head"]})
        out.sort(key=lambda c: (-c["weight"], c["ref"]))
        return out


def _counts(rows: list[dict]) -> dict[str, int]:
    counts = dict.fromkeys(STATES, 0)
    for row in rows:
        counts[row["state"]] += 1
    return counts
