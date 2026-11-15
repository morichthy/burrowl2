"""消化外部材料（设计稿 09 D-04 至 D-09）。

- 外部原件（source_class=external）登记后要经过一次"消化"：AI 把材料自己的论断写成要点（框架层，
  point.write，设计稿 15 D-02、D-15），需要与别的来源建立立场关系时另写引用原件段落的判断（D-03），
  再调用 digest.submit 记一条 `digest.submit` 过程日志（系统流水）。要点不设上限（D-15）。
- "待消化"由系统从账本算出，不单独存储（D-06）：外部原件的当前版本没有消化记录、也没被人跳过。
  人跳过（digest.skip）同样记一条过程日志，只能由人做。
- 只在本机按规则计算，不调用大模型（约束 7 / I12）；消化由 AI 会话自己做，或由人点按钮交给 agent（D-04）。
"""
from ..core.actor import Actor
from ..core.errors import BurrowlError

DEFAULTS: dict = {}  # 设计稿 15 D-15：要点不设上限，原来的 max_claims 去掉
DIGEST_OPS = ("digest.submit", "digest.skip")


class DigestService:
    def __init__(self, ws):
        self.ws = ws

    def settings(self) -> dict:
        return {**DEFAULTS, **(self.ws.config.get("digest") or {})}

    # ---------- 状态 ----------
    def records(self, artifact_id: str) -> list[dict]:
        """这份原件的消化记录（消化与跳过），按时间顺序。"""
        rows = self.ws.ledger.query(
            "SELECT id, op, actor_id, actor_kind, session_id, created_at, data FROM events "
            f"WHERE op IN ({','.join('?' * len(DIGEST_OPS))}) "
            "AND json_extract(data, '$.input.artifact_id') = ? ORDER BY created_at",
            (*DIGEST_OPS, artifact_id))
        return [{"id": r["id"], "op": r["op"], "by": r["actor_id"], "actor_kind": r["actor_kind"],
                 "session_id": r["session_id"], "at": r["created_at"],
                 "skipped": r["op"] == "digest.skip", "claims": r["data"]["input"].get("claims", []),
                 "points": r["data"]["input"].get("points", []),
                 "version": r["data"]["input"].get("artifact_version") or 1,
                 "note": r["data"]["input"].get("note", "")} for r in rows]

    def pending(self, limit: int = 200) -> dict:
        """待消化的外部原件（D-06）：当前版没有消化或跳过记录、没有退役（新版本重新进入待消化，设计稿 10 D-01）。"""
        done = {(r["aid"], r["ver"] or 1) for r in self.ws.ledger.query(
            f"SELECT DISTINCT json_extract(data, '$.input.artifact_id') AS aid, "
            f"json_extract(data, '$.input.artifact_version') AS ver FROM events "
            f"WHERE op IN ({','.join('?' * len(DIGEST_OPS))})", DIGEST_OPS)}
        rows = self.ws.ledger.query(
            "SELECT id, version, created_at, data FROM artifacts a WHERE source_class = 'external' "
            "ORDER BY created_at DESC")
        hidden = self.ws.versions.hidden_ids()
        items = []
        for r in rows:
            if (r["id"], r["version"]) in done or r["id"] in hidden or self.ws.judgments.retirement_of(r["id"]):
                continue
            items.append({"id": r["id"], "ref": f"{r['id']}@{r['version']}", "title": r["data"].get("title") or r["id"],
                          "external_tier": r["data"].get("external_tier"), "created_at": r["created_at"],
                          "points": len(self.ws.frameworks.points_citing(r["id"])),
                          "claims": len(self.claims_of(r["id"]))})
        return {"total": len(items), "items": items[:limit]}

    def claims_of(self, artifact_id: str) -> list[str]:
        """从这份原件提取的论断（D-09）：当前版依据它、带原作者（external_author）的判断。"""
        rows = self.ws.ledger.query(
            "SELECT DISTINCT j.id FROM effective_relations r JOIN judgments j ON j.id = r.subject_id "
            "AND j.version = r.subject_version WHERE r.predicate = 'cites' AND r.object_id = ? "
            "AND json_extract(j.data, '$.external_author') IS NOT NULL ORDER BY j.created_at",
            (artifact_id,))
        return [r["id"] for r in rows]

    def view(self, artifact_id: str) -> dict:
        """原件页用：提取的论断、消化记录、是否待消化。"""
        art = self._artifact(artifact_id)
        records = self.records(artifact_id)
        return {"artifact_id": artifact_id, "external": art["source_class"] == "external",
                "points": self.ws.frameworks.points_citing(artifact_id),
                "claims": self.claims_of(artifact_id), "records": records,
                "pending": art["source_class"] == "external" and not records}

    # ---------- 写入 ----------
    def submit(self, actor: Actor, *, artifact_id: str, claims: list[str] | None = None,
               points: list[str] | None = None, note: str = "") -> dict:
        """记下一次消化（D-05；设计稿 15 D-15）。points 是本会话写的、引用了这份原件段落的要点；
        claims 是另写的判断（与别的来源建立关系时，通常为空）；都没有时写明原因。"""
        art = self._artifact(artifact_id)
        claims = list(dict.fromkeys(c.strip() for c in (claims or []) if c and c.strip()))
        points = list(dict.fromkeys(p.strip().split("@", 1)[0] for p in (points or []) if p and p.strip()))
        if not claims and not points and not note.strip():
            raise BurrowlError("INVALID_ARGUMENT", "没有写要点时，请在 note 里写明原因（例如：综述，没有自己的发现）")
        citing = set(self.ws.frameworks.points_citing(artifact_id))
        for pid in points:
            page = self.ws.framework.page(pid)
            if page is None or page["type"] != "point":
                raise BurrowlError("NOT_FOUND", "points 必须是已写入的要点 pg_…", {"ref": pid})
            last = self.ws.framework.page_version(pid, page["head_version"])
            if last["data"].get("session_id") != actor.session_id:
                raise BurrowlError("INVALID_ARGUMENT", "points 只能是本会话写的要点", {"ref": pid})
            if pid not in citing:
                raise BurrowlError("INVALID_ARGUMENT", "points 里的要点要引用这份原件的段落", {"ref": pid})
        cited = set(self._citing(artifact_id))
        for jid in claims:
            j = self.ws.ledger.get(jid)
            if j is None or j.get("entry_kind") != "judgment":
                raise BurrowlError("NOT_FOUND", "claims 必须是已写入的判断 jdg_…", {"ref": jid})
            if j.get("session_id") != actor.session_id:
                raise BurrowlError("INVALID_ARGUMENT", "claims 只能是本会话写的判断", {"ref": jid})
            if jid not in cited:
                raise BurrowlError("INVALID_ARGUMENT", "claims 里的判断要引用这份原件的段落", {"ref": jid})
        warnings = []
        if art["source_class"] != "external":
            warnings.append("这份原件不是外部报告；本地实证与推断类原件按原规则在使用时写判断")
        missing = [j for j in claims if not (self.ws.ledger.get(j)["data"].get("external_author"))]
        if missing:
            warnings.append(f"判断 {', '.join(missing[:5])} 没有填 external_author，说明里不会显示「转述 · 原作者」")
        event = self.ws.capture.log(actor, "digest.submit",
                                    input={"artifact_id": art["id"], "artifact_version": art["version"],
                                           "points": points, "claims": claims, "note": note.strip()})
        return {"event_id": event["id"], "artifact_id": artifact_id, "points": points, "claims": claims,
                "warnings": warnings}

    def skip(self, actor: Actor, *, artifact_id: str, reason: str = "") -> dict:
        """人决定这份外部材料不需要消化（D-06）。"""
        actor.require_human("跳过消化")
        art = self._artifact(artifact_id)
        event = self.ws.capture.log(actor, "digest.skip",
                                    input={"artifact_id": art["id"], "artifact_version": art["version"],
                                           "note": reason.strip()})
        return {"event_id": event["id"], "artifact_id": artifact_id, "skipped": True}

    def prompt(self, artifact_ids: list[str] | None = None) -> str:
        """交给 AI 消化的一句提示（D-04）：原文不进提示词，由 AI 自己用 artifact_read 读。"""
        ids = artifact_ids or [i["id"] for i in self.pending(limit=20)["items"]]
        if not ids:
            raise BurrowlError("INVALID_ARGUMENT", "没有待消化的外部材料")
        return ("用 burrowl 消化这些外部材料：" + "、".join(ids) +
                "。按 Skill burrowl-work 的「消化外部材料」逐份读原件，把会有人回来找的论断写成要点"
                "（point_write：先 search，同一件事并进已有要点；单独读得懂、出处可回溯；一篇通常 3–7 条），"
                "能归纳出经验时写 subkind=lesson 的要点；与本地实证或别的材料一致、冲突时另写判断"
                "（一致写结论，冲突写使用约束），最后对每份调用 digest_submit(points=…)。")

    # ---------- 内部 ----------
    def _artifact(self, artifact_id: str) -> dict:
        art = self.ws.ledger.get(artifact_id)
        if art is None or art.get("entry_kind") != "artifact":
            raise BurrowlError("NOT_FOUND", "原件不存在", {"artifact_id": artifact_id})
        return art

    def _citing(self, artifact_id: str) -> list[str]:
        return [r["src_id"] for r in self.ws.ledger.query(
            "SELECT DISTINCT subject_id AS src_id FROM effective_relations WHERE predicate = 'cites' "
            "AND object_id = ? AND subject_id LIKE 'jdg_%'", (artifact_id,))]
