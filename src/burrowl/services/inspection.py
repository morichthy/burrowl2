"""定期巡检（设计稿 08）：规则检查、巡检包、巡检发现、复核员的 AI 复核与人的处理。

- 定时只准备、人点开跑（D-01、D-02）：到期时系统（system:inspection）在本机做规则检查与抽样，生成巡检包；
  不调用任何大模型（I12）。巡检员、复核员都由人点按钮经 agent.start 启动，或复制领取提示交给 AI 客户端。
- 规则检查只说明"这里可疑"（D-05 至 D-08）：疑似冲突、相邻段落未读、与规则不符、依据变化后仍被引用；
  另按覆盖图抽探索样本（D-09，services/coverage.py）。
- 巡检发现就是一项待决策（kind=finding，设计稿 08 §9）：说明、依据、针对的条目、建议、指纹、复核员意见都在
  这一项的数据里；不能被引用，不写回判断层，也不另开"请人复核"或可能矛盾边（人处理时从这一项打开针对的条目）。
- 提交与复核都要先读（D-17、D-21）；不能针对本会话写的条目，复核员不能复核本会话提交的发现。
- 人采纳（关闭为已处理）、驳回或忽略（关闭为已关闭）；有过发现的指纹下一期不再生成任务（D-19）。
- 不外发（D-30、D-31）：标为不外发的原件，原文不进巡检包；巡检会话里读它被拒绝，检索结果里去掉它。
"""
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta

from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.sql import transaction
from ..index.tokenize import tokens

SYSTEM_INSPECTION = Actor("system:inspection", "system", "ses_system")

DEFAULTS = {
    "interval_days": 7,        # 0 关闭定时准备（D-03）
    "max_segments": 60,        # 一期巡检包的阅读预算（段落数，D-09）
    "explore_ratio": 0.3,      # 预算中用于探索样本的比例
    "window_days": 90,         # 检索命中记录的统计窗口（D-11）
    "hit_min": 3,              # 窗口内被检索返回不少于这么多次、从没被读，记为"命中未读"
    "related_min": 0.5,        # 向量相似度不低于这个值，记为"相关未读"
    "first_days": 30,          # 第一期的范围：最近多少天（D-04）
    "inspector": "",           # 巡检员 agent（辅），config.json 的 agents 里的名称
    "reviewer": "",            # 复核员 agent（主）
    "framework_words": "显然,关键在于,根本原因是,主线是,毫无疑问,众所周知",  # D-07 的评价性措辞，逗号分隔
    "guidelines": "",          # 巡检原则（设计稿 08 D-36）：人在设置里改；空表示用 DEFAULT_GUIDELINES
}
# 巡检原则的默认文本（D-36）：是给巡检员、复核员的工作原则，随领取结果、离线包交给 AI；
# 系统强制的规则（先读后报、依据只能是原件层与判断层、不复核本会话提交的……）在 instructions() 与代码里，不随这里改
DEFAULT_GUIDELINES = "\n".join([
    "1. 只对照原件层和判断层：原件原文、事实记录、判断。框架页、综合页、关系图只能帮你找线索，"
    "不能作为发现的依据。",
    "2. 先读后报：发现引用的段落必须是你在这次巡检里读过的；没读到原文的地方不下结论。",
    "3. 分清冲突和条件不同：两条判断对象相同、条件（时间、设备、样本、参数）不同，不算冲突。"
    "写发现时说明你核对了哪些条件。",
    "4. 写清楚：对象、条件、哪一句与哪一段不一致，或者遗漏了什么；不写“可能有问题”这样的空话。",
    "5. 拿不准就说拿不准：suggestion 选 review（请人复核），不要为了交差硬交 clear 或 issue。",
    "6. 判断层只收录对工程、科研或其他重要、经常性工作有价值的经验与判断。"
    "看过程判断是否有助于后续工作；例行流水留在日志里，过程判断不能用作结论依据。",
    "7. 探索样本：读完说明它和近期结论的关系（支持、补充、矛盾、无关）；无关就交 clear。",
    "8. 巡检会话不能写判断。巡检员提交发现，复核员可提出修改意见，由人确认后写入。",
    "9. 复核员只看发现本身是否成立：确认前自己读过它引用的段落；认为不成立时写明你读到的原文。",
])
GUIDELINES_MAX = 4000
CHECKS = ("conflict", "stale_basis", "unread_neighbor", "rule", "explore")
CHECK_LABEL = {"conflict": "疑似冲突", "stale_basis": "依据变化后仍被引用", "unread_neighbor": "相邻段落未读",
               "rule": "与规则不符", "explore": "探索样本"}
SUGGESTIONS = {"oppose": "写一条反对判断", "amend": "请人更正或撤回", "read_more": "补读某段",
               "contradict_edge": "建可能矛盾边", "review": "请人复核", "none": "无需处理"}
HUMAN_ACTIONS = {"adopt": "resolved", "reject": "dismissed", "ignore": "dismissed"}
AI_REVIEW_STATE = {"confirm": "ai_reviewed", "reject": "ai_flagged", "unsure": "ai_unsure"}
AI_REVIEW_IMPACT = {"confirm": 3, "unsure": 1, "reject": 0}
LINKED_RELS = ("opposes", "supersedes", "coexists_under", "corrects", "retracts", "wasRevisionOf")
NEGATION = re.compile(r"不|没有|未|无法|并非|非")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
ANTONYMS = (("升高", "降低"), ("增加", "减少"), ("上升", "下降"), ("增大", "减小"), ("大于", "小于"), ("高于", "低于"),
            ("提高", "下降"), ("成功", "失败"), ("有效", "无效"), ("正常", "异常"), ("合格", "不合格"),
            ("稳定", "不稳定"), ("通过", "未通过"), ("可行", "不可行"), ("一致", "不一致"), ("存在", "不存在"))
STALE_CODES = {"RECHECK_CITATION": "引用了依据已变化、尚未复核的判断", "RETIRED_CITATION": "引用了已退役的原件",
               "LOW_FIDELITY_CITATION": "引用了未经人确认的 OCR / AI 识别段落"}
SECTION_SPAN = 6  # 同一小节最多往前后看几段；没有标题时只看前后各 2 段


def _iso(t: datetime) -> str:
    """与账本的 created_at 同一格式（core/clock.now：毫秒、Z 结尾），按字符串比较先后才对。"""
    return t.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _now() -> str:
    return _iso(datetime.now(UTC))


def _ago(days: float) -> str:
    return _iso(datetime.now(UTC) - timedelta(days=days))


def fingerprint(check: str, *parts: str) -> str:
    return hashlib.sha256(json.dumps([check, *sorted(parts)], ensure_ascii=False).encode()).hexdigest()[:24]


def _run_of(actor_id: str) -> str | None:
    tail = actor_id.rsplit(":", 1)[-1]
    return tail if tail.startswith("run_") else None


class InspectionService:
    def __init__(self, ws):
        self.ws = ws

    # ---------- 设置 ----------
    def settings(self) -> dict:
        return {**DEFAULTS, **(self.ws.config.get("inspection") or {})}

    def guidelines(self) -> dict:
        """当前生效的巡检原则（D-36）：设置为空时用默认文本。工作台与 MCP 进程读同一份 config.json。"""
        custom = (self.settings().get("guidelines") or "").strip()
        text = custom or DEFAULT_GUIDELINES
        return {"text": text, "default": DEFAULT_GUIDELINES, "is_default": not custom,
                "sha": hashlib.sha256(text.encode()).hexdigest()[:12],
                "fixed": {"inspector": instructions("inspector"), "reviewer": instructions("reviewer")}}

    def words(self) -> list[str]:
        return [w.strip() for w in re.split(r"[,，、\s]+", self.settings()["framework_words"] or "") if w.strip()]

    # ---------- 不外发（D-30、D-31） ----------
    def policy_history(self, artifact_id: str) -> list[dict]:
        return self.ws.ledger.query("SELECT * FROM artifact_policies WHERE artifact_id = ? ORDER BY created_at, rowid",
                                    (artifact_id,))

    def outbound(self, artifact_id: str) -> bool:
        rows = self.policy_history(artifact_id)
        return not rows or rows[-1]["policy"] != "no_outbound"

    def no_outbound_ids(self) -> set[str]:
        last: dict[str, str] = {}
        for r in self.ws.ledger.query("SELECT artifact_id, policy FROM artifact_policies ORDER BY created_at, rowid"):
            last[r["artifact_id"]] = r["policy"]
        return {k for k, v in last.items() if v == "no_outbound"}

    def set_policy(self, actor: Actor, *, artifact_id: str, outbound: bool, reason: str) -> dict:
        actor.require_human("设置原件是否外发")
        art = self.ws.ledger.get(artifact_id)
        if art is None or art["entry_kind"] != "artifact":
            raise BurrowlError("NOT_FOUND", "原件不存在", {"artifact_id": artifact_id})
        if outbound == self.outbound(artifact_id):
            return {"artifact_id": artifact_id, "outbound": outbound, "changed": False}
        policy = "outbound" if outbound else "no_outbound"
        row = self.ws.ledger.insert("artifact_policies", "pol", {
            "artifact_id": artifact_id, "policy": policy, "actor_id": actor.id, "session_id": actor.session_id,
            "data": {"reason": reason}})
        self.ws.capture.log(actor, "artifact.policy", input={"artifact_id": artifact_id, "policy": policy})
        return {"artifact_id": artifact_id, "outbound": outbound, "changed": True, "policy_id": row["id"]}

    def inspection_sessions(self) -> set[str]:
        """巡检运行与领取过巡检包的会话（未关闭的各期）：D-31 只在这些会话里生效。"""
        out: set[str] = set()
        for insp in self.ws.framework.inspections(limit=10):
            if insp["status"] == "closed":
                continue
            d = insp["data"]
            out |= {r["session_id"] for r in d.get("runs", []) if r.get("session_id")}
            out |= {c["session_id"] for c in d.get("claims", []) if c.get("session_id")}
        return out

    def in_inspection(self, actor: Actor) -> bool:
        return actor.kind == "ai" and actor.session_id in self.inspection_sessions()

    def guard_original_write(self, actor: Actor) -> None:
        """巡检的运行日志和内部审计照常保留，AI 不另写原件或事实记录。"""
        if actor.kind == "ai" and self.ws.framework.inspection_session(actor.session_id):
            raise BurrowlError("FORBIDDEN", "巡检过程留在运行日志，请提交发现或复核意见")

    def guard_artifact(self, actor: Actor, artifact_id: str) -> None:
        base = artifact_id.split("#", 1)[0]
        if base.startswith("art_") and self.in_inspection(actor) and not self.outbound(base):
            raise BurrowlError("NOT_OUTBOUND", "这份原件由人标为不外发，巡检运行里不能读取原文；涉及它的任务只能由人看",
                               {"artifact_id": base})

    def filter_result(self, actor: Actor, result: dict) -> dict:
        """巡检会话里，检索、联想结果去掉不外发原件的命中（D-31）。"""
        if not self.in_inspection(actor):
            return result
        blocked = self.no_outbound_ids()
        if not blocked:
            return result
        for key in ("hits", "items", "results"):
            if isinstance(result.get(key), list):
                kept = [h for h in result[key]
                        if not (isinstance(h, dict) and str(h.get("id", "")).split("#", 1)[0] in blocked)]
                for hit in kept:
                    if isinstance(hit, dict):
                        for basis in hit.get("basis", []):
                            basis.pop("version_history", None)
                if len(kept) != len(result[key]):
                    result[key] = kept
                    result.setdefault("hints", []).append("巡检运行里不返回标为不外发的原件")
        return result

    # ---------- 状态与调度（D-01、D-03） ----------
    def latest(self) -> dict | None:
        items = self.ws.framework.inspections(limit=1)
        return items[0] if items else None

    def due(self, now: datetime | None = None) -> bool:
        days = float(self.settings()["interval_days"])
        if days <= 0:
            return False
        latest = self.latest()
        if latest is None:
            return True
        if latest["status"] in ("running", "done"):  # 上一期还在处理：不另起一期
            return False
        now = now or datetime.now(UTC)
        stamp = latest["data"].get("prepared_at") or latest["updated_at"]
        made = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if made.tzinfo is None:
            made = made.replace(tzinfo=UTC)
        return now - made >= timedelta(days=days)

    def run_due(self, now: datetime | None = None) -> dict | None:
        if not self.due(now):
            return None
        return self.prepare(SYSTEM_INSPECTION, trigger="schedule")

    def status(self) -> dict:
        """首页与设置页用：最近一期巡检包、是否到期、巡检员与复核员 agent 是否可用。"""
        s = self.settings()
        latest = self.latest()
        agents = {a["name"]: a for a in self.ws.agents.agents()}
        summary = None
        if latest:
            summary = self.summary(latest)
        return {"latest": summary, "due": self.due(), "interval_days": s["interval_days"],
                "inspector": {"agent": s["inspector"], "available": bool(agents.get(s["inspector"], {})
                                                                         .get("available"))},
                "reviewer": {"agent": s["reviewer"], "available": bool(agents.get(s["reviewer"], {})
                                                                       .get("available"))},
                "same_agent": bool(s["inspector"]) and s["inspector"] == s["reviewer"],
                "review_ai": self.ws.config.get("review", {}).get("ai", "framework")}

    def summary(self, insp: dict) -> dict:
        d = insp["data"]
        findings = self.findings(insp["id"])
        tasks = d.get("tasks", [])
        return {"id": insp["id"], "period": insp["period"], "status": insp["status"],
                "created_at": insp["created_at"], "prepared_at": d.get("prepared_at"), "trigger": d.get("trigger"),
                "scope": {k: v for k, v in d.get("scope", {}).items() if k != "judgments"},
                "judgments": len(d.get("scope", {}).get("judgments", [])),
                "tasks": len(tasks), "explore": len([t for t in tasks if t["check"] == "explore"]),
                "suspicious": len([t for t in tasks if t["check"] != "explore"]),
                "human_only": len([t for t in tasks if t.get("human_only")]),
                "checked": len([t for t in tasks if t.get("results")]),
                "counts": d.get("counts", {}), "runs": d.get("runs", []),
                "findings": len(findings), "open": len([f for f in findings if f["status"] == "open"]),
                "unreviewed": len([f for f in findings if f["status"] == "open"
                                   and f["data"].get("review") == "ai_generated"])}

    def summaries(self, limit: int = 20) -> list[dict]:
        return [self.summary(i) for i in self.ws.framework.inspections(limit)]

    # ---------- 准备巡检包（D-03 至 D-09、D-14、D-19） ----------
    def prepare(self, actor: Actor, *, trigger: str = "manual") -> dict:
        if trigger == "manual":
            actor.require_human("准备巡检包")
        fw = self.ws.framework
        latest = self.latest()
        if latest and latest["status"] in ("running", "done"):
            raise BurrowlError("CONFLICT", "上一期巡检还没有关闭；处理完或关闭后再准备新的一期",
                               {"inspection_id": latest["id"], "status": latest["status"]})
        refresh = latest if latest and latest["status"] == "ready" else None
        if refresh:
            since = refresh["data"]["scope"]["since"]
        else:
            closed = [i for i in fw.inspections(limit=50) if i["status"] == "closed"]
            since = closed[0]["data"]["scope"]["until"] if closed else _ago(float(self.settings()["first_days"]))
        until = _now()
        data = self._build(since, until, exclude=refresh["id"] if refresh else None)
        data.update(trigger=trigger, prepared_at=until, prepared_by=actor.id)
        if refresh:
            keep = {k: refresh["data"].get(k, []) for k in ("runs", "claims")}
            insp = fw.update_inspection(refresh["id"], data={**data, **keep})
        else:
            period = (latest["period"] + 1) if latest else 1
            insp = fw.add_inspection(period, {**data, "runs": [], "claims": []})
        self.ws.capture.log(actor, "inspection.prepare", input={"inspection_id": insp["id"], "trigger": trigger,
                                                                "tasks": len(data["tasks"])})
        return self.summary(insp)

    def _build(self, since: str, until: str, *, exclude: str | None) -> dict:
        s = self.settings()
        scope = self.ws.ledger.query(
            "SELECT * FROM judgments WHERE created_at >= ? AND created_at <= ? "
            "AND kind IN ('conclusion', 'normative', 'process') ORDER BY created_at", (since, until))
        known = {f["data"].get("fingerprint") for f in self.findings()}  # 已经有发现的（含驳回、忽略过的，D-19）
        blocked = self.no_outbound_ids()
        reads = self._read_anchors()
        candidates = (self._conflicts(scope) + self._stale(scope) + self._unread_neighbors(scope, reads)
                      + self._rules(scope))
        tasks, skipped, budget = [], {"known": 0, "over_budget": 0}, int(s["max_segments"])
        explore_budget = round(budget * float(s["explore_ratio"]))
        main_budget, used = budget - explore_budget, 0
        for t in candidates:
            if t["fingerprint"] in known:
                skipped["known"] += 1
                continue
            hidden = [r for r in t["read"] if r.split("#", 1)[0] in blocked]
            if hidden:
                t["read"] = [r for r in t["read"] if r not in hidden]
                t["human_only"] = True
                t["hidden"] = len(hidden)
            if t["read"] and used + len(t["read"]) > main_budget:
                skipped["over_budget"] += 1
                continue
            used += len(t["read"])
            tasks.append(t)
        sampled = self._sampled_before(exclude)
        samples = []
        for c in self.ws.coverage.explore_candidates(scope, sampled, blocked)[:max(0, explore_budget)]:
            fp = fingerprint("explore", c["ref"], c["sha256"])
            if fp in known:
                continue
            samples.append(c["ref"])
            state = "命中未读" if c["state"] == "hit_unread" else "相关未读"
            tasks.append({"check": "explore", "title": f"探索：{c['ref']}（{state}）",
                          "question": "这一段里有没有本期结论应当考虑却没有考虑的内容"
                                      "（限制条件、反例、例外、不同的测量结果）？",
                          "targets": [], "read": [c["ref"]], "fingerprint": fp,
                          "detail": {"state": c["state"], "hits": c["hits"], "relevance": c["relevance"],
                                     "head": c["head"]}})
        for i, t in enumerate(tasks, 1):
            t["id"] = f"t{i}"
            t.setdefault("results", [])
        counts = {c: len([t for t in tasks if t["check"] == c]) for c in CHECKS}
        return {"scope": {"since": since, "until": until, "judgments": [j["id"] for j in scope]},
                "tasks": tasks, "samples": samples, "counts": counts, "skipped": skipped,
                "budget": {"max_segments": budget, "explore": explore_budget, "used": used + len(samples)}}

    def _sampled_before(self, exclude: str | None) -> dict[str, int]:
        out: dict[str, int] = {}
        for insp in self.ws.framework.inspections(limit=50):
            if insp["id"] == exclude:
                continue
            for ref in insp["data"].get("samples", []):
                out[ref] = out.get(ref, 0) + 1
        return out

    def _read_anchors(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for r in self.ws.ledger.query("SELECT artifact_id, data FROM reads"):
            d = r["data"] or {}
            out.setdefault(r["artifact_id"], set()).update(d.get("anchors") or [])
        return out

    # D-05 疑似冲突
    def _conflicts(self, scope: list[dict]) -> list[dict]:
        tasks, seen = [], set()
        conclusions = [j for j in scope if j["kind"] == "conclusion"]
        for j in conclusions:
            objects = self.ws.ledger.objects_of(j["id"])
            if not objects:
                continue
            for other_id in self.ws.ledger.entries_with_objects(objects):
                if not other_id.startswith("jdg_") or other_id == j["id"]:
                    continue
                pair = tuple(sorted((j["id"], other_id)))
                if pair in seen:
                    continue
                seen.add(pair)
                other = self.ws.ledger.get(other_id)
                if other is None or other["kind"] != "conclusion" or self._linked(*pair):
                    continue
                if self.ws.judgments.status(other_id)["superseded"] or self.ws.judgments.status(j["id"])["superseded"]:
                    continue
                c1, c2 = (j["data"].get("conditions") or "").strip(), (other["data"].get("conditions") or "").strip()
                if c1 and c2 and c1 != c2:
                    continue  # 条件不同：可以并存，不算冲突
                reason = opposite(j["data"]["text"], other["data"]["text"])
                if not reason:
                    continue
                reads = list(dict.fromkeys(r for jj in (j, other) for r in self._cited_refs(jj)))[:6]
                tasks.append({"check": "conflict", "title": f"疑似冲突：{pair[0]} 与 {pair[1]}",
                              "question": "这两条结论是真的冲突，还是条件不同、可以并存，或只是表述不同？"
                                          "请读两边引用的原文后判断。",
                              "targets": list(pair), "read": reads, "fingerprint": fingerprint("conflict", *pair),
                              "detail": {"reason": reason, "objects": sorted(set(objects)
                                                                              & set(other["objects"]))}})
        return tasks

    def _linked(self, a: str, b: str) -> bool:
        for src, dst in ((a, b), (b, a)):
            if any(lk["dst_id"] == dst and lk["rel"] in LINKED_RELS for lk in self.ws.ledger.links_from(src)):
                return True
        for e in self.ws.framework.edges_of(a):
            if {e["src_id"], e["dst_id"]} == {a, b} and e["rel"] in ("may_contradict", "may_supersede"):
                return True
        return False

    def _cited_refs(self, judgment: dict) -> list[str]:
        return [lk["dst_id"] for lk in self.ws.ledger.links_from(judgment["id"], "used")
                if lk["dst_id"].startswith("art_") and "#" in lk["dst_id"]]

    # D-08 依据变化后仍被引用
    def _stale(self, scope: list[dict]) -> list[dict]:
        tasks = []
        retired = self.ws.judgments.retired_ids()
        for j in scope:
            if j["kind"] != "conclusion":
                continue
            problems, refs = {}, []
            for n in j["data"].get("citation_notices") or []:
                if n["code"] in STALE_CODES:
                    problems.setdefault(n["code"], []).append(n["ref"])
            for lk in self.ws.ledger.links_from(j["id"], "used"):
                ref, base = lk["dst_id"], lk["dst_id"].split("#", 1)[0]
                if base in retired and ref not in problems.get("RETIRED_CITATION", []):
                    problems.setdefault("RETIRED_CITATION", []).append(ref)
                if base.startswith("jdg_") and self.ws.extraction.pending_recheck(base) \
                        and ref not in problems.get("RECHECK_CITATION", []):
                    problems.setdefault("RECHECK_CITATION", []).append(ref)
            if self.ws.extraction.pending_recheck(j["id"]):
                problems.setdefault("SELF_RECHECK", [j["id"]])
            if not problems:
                continue
            for code, items in problems.items():
                if code in ("LOW_FIDELITY_CITATION",):
                    refs += [r for r in items if r.startswith("art_") and "#" in r]
            parts = [f"{code}:{','.join(sorted(v))}" for code, v in problems.items()]
            tasks.append({"check": "stale_basis", "title": f"依据有变化：{j['id']}",
                          "question": "这条结论的依据已变化或可靠性较低；请核对它现在是否仍然成立、是否需要请人复核。",
                          "targets": [j["id"]], "read": refs[:4],
                          "fingerprint": fingerprint("stale_basis", j["id"], *parts),
                          "detail": {"problems": {k: v for k, v in problems.items()},
                                     "labels": {k: STALE_CODES.get(k, "这条结论自己正在待复核")
                                                for k in problems}}})
        return tasks

    # D-06 相邻段落未读
    def _unread_neighbors(self, scope: list[dict], reads: dict[str, set[str]]) -> list[dict]:
        tasks, seg_cache = [], {}
        retired = self.ws.judgments.retired_ids()
        for j in scope:
            if j["kind"] != "conclusion":
                continue
            groups: dict[str, list[str]] = {}
            for c in self.ws.extraction.cited_hashes(j):
                art_id = c["artifact_id"]
                if art_id in retired:
                    continue
                if art_id not in seg_cache:
                    art = self.ws.ledger.get(art_id)
                    try:
                        seg_cache[art_id] = self.ws.extraction.segments(art) if art else []
                    except BurrowlError:
                        seg_cache[art_id] = []
                segs = seg_cache[art_id]
                idx = next((i for i, s in enumerate(segs) if s["anchor"] == c["anchor"]), None)
                if idx is None:
                    continue
                for s in section(segs, idx):
                    if s["anchor"] not in reads.get(art_id, set()) and s["anchor"] != c["anchor"]:
                        groups.setdefault(art_id, [])
                        if s["anchor"] not in groups[art_id]:
                            groups[art_id].append(s["anchor"])
            for art_id, anchors in groups.items():
                anchors = anchors[:6]
                shas = [s["sha256"] for s in seg_cache[art_id] if s["anchor"] in anchors]
                tasks.append({"check": "unread_neighbor", "title": f"相邻段落未读：{j['id']} 引用的 {art_id}",
                              "question": "这条结论引用的段落附近有从没被读过的段落；请读这些段落，看有没有限制条件、"
                                          "反例或例外没有写进结论。",
                              "targets": [j["id"]], "read": [f"{art_id}#{a}" for a in anchors],
                              "fingerprint": fingerprint("unread_neighbor", j["id"], art_id, *shas),
                              "detail": {"cited": [c["ref"] for c in self.ws.extraction.cited_hashes(j)
                                                   if c["artifact_id"] == art_id]}})
            cred = j["data"].get("credibility") or {}
            if cred.get("basis_complete") is False:
                tasks.append({"check": "unread_neighbor", "title": f"依据不完整：{j['id']}",
                              "question": "这条结论的依据边界是截断、只读了一部分或权限受限；"
                                          "请核对缺的部分会不会改变结论。",
                              "targets": [j["id"]], "read": [],
                              "fingerprint": fingerprint("unread_neighbor", j["id"], "incomplete"),
                              "detail": {"basis_complete": False}})
        return tasks

    # D-07 与规则不符
    def _rules(self, scope: list[dict]) -> list[dict]:
        tasks = []
        words = self.words()
        unchecked = {}
        for d in self.ws.framework.decisions("open", "constraint_unchecked"):
            for c in d["data"].get("constraints", []):
                unchecked.setdefault(c["id"], []).append(d["subject_id"])
        for j in scope:
            text = j["data"].get("text") or ""
            problems = []
            found = []
            if j["kind"] != "process":  # 过程判断记录思路与尝试，可以有评价（D-38）
                found = [w for w in words if w in text]
                if re.search(r"目前有[一二三四五六七八九两几\d]+种思路", text):
                    found.append("目前有几种思路")
            if found:
                problems.append(f"含评价性或框架性措辞：{'、'.join(found)}")
            if j["kind"] in ("conclusion", "normative") and not self.ws.ledger.objects_of(j["id"]):
                problems.append("没有写对象")
            if j["kind"] == "conclusion" and not (j["data"].get("conditions") or "").strip():
                problems.append("没有写条件")
            cred = j["data"].get("credibility") or {}
            if j["kind"] == "conclusion" and cred.get("source_classes") == ["inferred"]:
                problems.append("依据只有推断一类来源")
            if j["kind"] == "normative" and unchecked.get(j["id"]):
                problems.append(f"这条规定生效后有 {len(unchecked[j['id']])} 次相关操作没有先检查约束")
            if not problems:
                continue
            tasks.append({"check": "rule", "title": f"与规则不符：{j['id']}",
                          "question": "这条判断有以下不符合记录规则的地方；请判断是否需要请人更正，或者另写一条"
                                      "写全对象和条件的判断。",
                          "targets": [j["id"]], "read": [],
                          "fingerprint": fingerprint("rule", j["id"], *problems),
                          "detail": {"problems": problems, "author_kind": j["author_kind"]}})
        return tasks

    # ---------- 领取（D-15） ----------
    def get(self, actor: Actor, *, inspection_id: str, role: str = "inspector",
            finding_ids: list[str] | None = None) -> dict:
        insp = self._inspection(inspection_id)
        if role not in ("inspector", "reviewer"):
            raise BurrowlError("INVALID_ARGUMENT", "role 必须是 inspector（巡检员）或 reviewer（复核员）")
        if insp["status"] == "closed":
            raise BurrowlError("CONFLICT", "这一期巡检已经关闭", {"inspection_id": inspection_id})
        data = insp["data"]
        # 已绑定的会话只能领取原角色的任务；外部客户端需要为两个角色使用不同会话。
        if actor.kind == "ai" and self.ws.framework.inspection_session(actor.session_id, inspection_id=inspection_id):
            if not self.ws.framework.inspection_session(actor.session_id, inspection_id=inspection_id, role=role):
                raise BurrowlError("FORBIDDEN", "同一巡检会话不能切换角色，请另开会话")
        claims = data.get("claims", [])
        claim = next((c for c in claims if c["session_id"] == actor.session_id and c["role"] == role), None)
        previous = (claim or {}).get("finding_ids", [])
        selected = list(dict.fromkeys([*previous, *(finding_ids or [])])) if role == "reviewer" else []
        if actor.kind == "ai" and (claim is None or selected != previous):
            updated = {**(claim or {"session_id": actor.session_id, "actor_id": actor.id, "role": role, "at": _now(),
                                   "guidelines_sha": self.guidelines()["sha"]}),
                       **({"finding_ids": selected} if selected else {})}
            data["claims"] = [c for c in claims if c is not claim] + [updated]
            status = "running" if role == "inspector" and insp["status"] == "ready" else insp["status"]
            insp = self.ws.framework.update_inspection(inspection_id, status=status, data=data)
        blocked = self.no_outbound_ids()
        g = self.guidelines()
        out = {"inspection": self.summary(insp), "role": role, "instructions": instructions(role),
               "guidelines": g["text"], "suggestions": SUGGESTIONS}
        if role == "inspector":
            out["tasks"] = self._task_views(data)
            return out
        items = []
        for f in self.findings(inspection_id, status="open"):
            d = f["data"]
            if finding_ids and f["id"] not in finding_ids:
                continue
            if (not finding_ids and d.get("review") != "ai_generated") or d.get("session_id") == actor.session_id:
                continue
            refs = [r for r in d.get("cites", []) if r.split("#", 1)[0] not in blocked]
            items.append({"id": f["id"], "check": d.get("check"), "check_label": d.get("check_label"),
                          "summary": d.get("summary"), "targets": d.get("targets", []), "cites": refs,
                          "suggestion": d.get("suggestion"), "method": d.get("method"),
                          "human_only": len(refs) != len(d.get("cites", []))})
        out["findings"] = items
        return out

    @staticmethod
    def _task_views(data: dict) -> list[dict]:
        return [{**{k: v for k, v in t.items() if k not in ("fingerprint", "results")},
                 "check_label": CHECK_LABEL[t["check"]], "done": len(t.get("results", []))}
                for t in data.get("tasks", [])]

    def tasks(self, *, inspection_id: str) -> dict:
        """工作台用（D-37）：本期任务清单，只读，不记领取。"""
        insp = self._inspection(inspection_id)
        return {"inspection": self.summary(insp), "tasks": self._task_views(insp["data"])}

    # ---------- 巡检员提交（D-16 至 D-18） ----------
    def submit(self, actor: Actor, *, inspection_id: str, task_id: str, outcome: str, summary: str = "",
               cites: list[str] | None = None, targets: list[str] | None = None, suggestion: str = "review",
               model: str = "") -> dict:
        if actor.kind != "ai":
            raise BurrowlError("FORBIDDEN", "巡检发现由 AI 提交；人请在待决策页处理，离线结果用 inspection.import 贴回")
        insp = self._inspection(inspection_id)
        if insp["status"] == "closed":
            raise BurrowlError("CONFLICT", "这一期巡检已经关闭", {"inspection_id": inspection_id})
        data = insp["data"]
        task = next((t for t in data.get("tasks", []) if t["id"] == task_id), None)
        if task is None:
            raise BurrowlError("NOT_FOUND", "巡检包里没有这个任务", {"task_id": task_id})
        if outcome not in ("issue", "clear"):
            raise BurrowlError("INVALID_ARGUMENT", "outcome 必须是 issue（有问题）或 clear（检查过，没有问题）")
        if not (model or "").strip():
            raise BurrowlError("INVALID_ARGUMENT", "请在 model 里写明模型（如 claude-sonnet-5-5）")
        cites = list(dict.fromkeys(c.strip() for c in (cites or []) if c and c.strip()))
        self._check_cites(actor, cites)
        result = {"session_id": actor.session_id, "actor_id": actor.id, "outcome": outcome, "at": _now(),
                  "model": model}
        finding = None
        if outcome == "issue":
            if not summary.strip():
                raise BurrowlError("INVALID_ARGUMENT", "请写明发现了什么（summary）")
            if not cites:
                raise BurrowlError("INVALID_ARGUMENT", "发现至少要一条依据（原件段落、事实记录或判断），并且先读过")
            if suggestion not in SUGGESTIONS:
                raise BurrowlError("INVALID_ARGUMENT", f"suggestion 必须是 {', '.join(SUGGESTIONS)} 之一")
            targets = list(dict.fromkeys(targets or task.get("targets") or []))
            self._check_targets(actor, targets)
            finding = self._create(actor, insp, task, summary=summary, cites=cites, targets=targets,
                                   suggestion=suggestion, model=model, method="ai")
            result["decision_id"] = finding["id"]
        task["results"] = [*task.get("results", []), result]
        status = insp["status"]
        if all(t.get("results") for t in data["tasks"]):
            status = "done"
        elif status == "ready":
            status = "running"
        self.ws.framework.update_inspection(inspection_id, status=status, data=data)
        self.ws.capture.log(actor, "inspection.submit", input={"inspection_id": inspection_id, "task_id": task_id,
                                                               "outcome": outcome,
                                                               "decision_id": finding["id"] if finding else None})
        return {"task_id": task_id, "outcome": outcome, "finding": finding, "inspection": self.summary(
            self.ws.framework.inspection(inspection_id))}

    def _create(self, actor: Actor, insp: dict, task: dict, *, summary: str, cites: list[str], targets: list[str],
                suggestion: str, model: str, method: str, relayed_by: str | None = None) -> dict:
        """一条巡检发现 = 一项待决策（kind=finding）。subject 取第一个针对的条目，便于从待决策直接打开。"""
        return self.ws.framework.add_decision("finding", targets[0] if targets else None, 1, {
            "inspection_id": insp["id"], "period": insp["period"], "task_id": task["id"], "check": task["check"],
            "check_label": CHECK_LABEL[task["check"]], "title": task["title"], "question": task["question"],
            "summary": summary, "cites": cites, "targets": targets, "suggestion": suggestion, "model": model,
            "fingerprint": task["fingerprint"], "method": method, "by": actor.id, "run_id": _run_of(actor.id),
            "session_id": actor.session_id if method == "ai" else None, "review": "ai_generated",
            **({"relayed_by": relayed_by} if relayed_by else {})})

    def _check_cites(self, actor: Actor, cites: list[str]) -> None:
        """依据只能是原件层与判断层（I2），原件段落必须本会话读过（D-17）。"""
        for ref in cites:
            self.ws.judgments.basis_of(ref)
            if ref.startswith("art_"):
                self.guard_artifact(actor, ref)
                if "#" in ref:
                    c = self.ws.extraction.citation(actor, ref)
                    if "UNREAD_CITATION" in c["notices"]:
                        raise BurrowlError("UNREAD_FINDING", "提交前要先用 artifact_read 读过引用的段落", {"ref": ref})
                elif not self.ws.ledger.query("SELECT id FROM reads WHERE artifact_id = ? AND actor_id = ? AND "
                                              "(session_id = ? OR session_id IS NULL) LIMIT 1",
                                              (ref, actor.id, actor.session_id)):
                    raise BurrowlError("UNREAD_FINDING", "提交前要先用 artifact_read 读过引用的原件", {"ref": ref})

    def _check_targets(self, actor: Actor, targets: list[str]) -> None:
        for ref in targets:
            entry = self.ws.get(ref)
            if entry is None:
                raise BurrowlError("NOT_FOUND", "发现针对的条目不存在", {"ref": ref})
            if ref.startswith("dec_"):
                raise BurrowlError("INVALID_ARGUMENT", "发现不能针对待决策项", {"ref": ref})
            if entry.get("session_id") and entry.get("session_id") == actor.session_id and ref.startswith("jdg_"):
                raise BurrowlError("SAME_SESSION", "不能针对本会话自己写的条目提交发现", {"ref": ref})

    # ---------- 复核员（D-20、D-21） ----------
    def is_finding(self, item_id: str) -> bool:
        if not item_id.startswith("dec_"):
            return False
        d = self.ws.framework.decision(item_id)
        return bool(d and d["kind"] == "finding")

    def ai_review(self, actor: Actor, *, decision_id: str, verdict: str, reason: str, model: str,
                  cites: list[str] | None = None, proposed_change: str = "") -> dict:
        if actor.kind != "ai":
            raise BurrowlError("FORBIDDEN", "AI 复核只给 AI 用；人请在待决策页处理发现")
        if self.ws.config.get("review", {}).get("ai", "framework") == "off":
            raise BurrowlError("REVIEW_DISABLED", "这个数据目录关闭了 AI 复核（设置 review.ai）")
        if verdict not in AI_REVIEW_STATE:
            raise BurrowlError("INVALID_ARGUMENT", "verdict 必须是 confirm / reject / unsure")
        if not reason.strip():
            raise BurrowlError("INVALID_ARGUMENT", "请写明理由")
        if not (model or "").strip():
            raise BurrowlError("INVALID_ARGUMENT", "请在 model 里写明模型（如 claude-opus-5-5）")
        f = self._finding(decision_id)
        d = f["data"]
        insp = self._inspection(d["inspection_id"])
        if f["status"] != "open" or insp["status"] == "closed":
            raise BurrowlError("REVIEW_NOT_ALLOWED", "只有尚未由人处理、所在巡检仍开放的发现可以由 AI 复核",
                               {"status": f["status"], "review": d.get("review")})
        if d.get("review") != "ai_generated" and not any(
            c["role"] == "reviewer" and c["session_id"] == actor.session_id and decision_id in c.get("finding_ids", [])
            for c in insp["data"].get("claims", [])
        ):
            raise BurrowlError("REVIEW_NOT_ALLOWED",
                               "再次复核前，请用 inspection_get 的 finding_ids 指定并领取这条发现")
        if d.get("session_id") and d["session_id"] == actor.session_id:
            raise BurrowlError("SAME_SESSION", "不能复核本会话提交的发现；请换一个会话复核")
        if verdict == "confirm" and d.get("method") == "relayed":
            raise BurrowlError("REVIEW_NOT_ALLOWED",
                               "经人转交的发现没有读取记录，复核员不能确认；请交 unsure 或 reject")
        cites = list(dict.fromkeys(c.strip() for c in (cites or []) if c and c.strip()))
        self._check_cites(actor, cites)
        if verdict == "confirm":  # D-21：发现引用的段落，复核员自己也要读过
            self._check_cites(actor, [r for r in d.get("cites", []) if r.startswith("art_")])
        if verdict == "reject" and not cites:
            raise BurrowlError("INVALID_ARGUMENT", "认为发现不成立时至少要一条依据，并且先读过；拿不准时交 unsure")
        proposed_change = proposed_change.strip()
        if proposed_change:
            if verdict != "confirm" or not cites:
                raise BurrowlError("INVALID_ARGUMENT", "修改意见须确认发现成立，并提供本会话核对过的依据")
            if not self.ws.framework.inspection_session(actor.session_id, inspection_id=d["inspection_id"],
                                                        role="reviewer"):
                raise BurrowlError("FORBIDDEN", "只有本期复核员可以提出修改意见")
        reviewer = {"verdict": verdict, "reason": reason, "cites": cites, "model": model, "by": actor.id,
                    "session_id": actor.session_id, "run_id": _run_of(actor.id), "at": _now()}
        if proposed_change:
            reviewer["proposed_change"] = proposed_change
        history = d.get("reviewer_history", [])
        if d.get("reviewer"):
            history = [*history, d["reviewer"]]
        self.ws.framework.update_decision(decision_id, impact=AI_REVIEW_IMPACT[verdict],
                                          data={**d, "review": AI_REVIEW_STATE[verdict], "reviewer": reviewer,
                                                "reviewer_history": history})
        self.ws.capture.log(actor, "inspection.ai_review", input={"decision_id": decision_id, "verdict": verdict,
                                                                  "model": model})
        return {"decision_id": decision_id, "verdict": verdict, "review": AI_REVIEW_STATE[verdict]}

    # ---------- 人的处理（D-23、D-24） ----------
    def resolve(self, actor: Actor, *, decision_id: str, action: str, reason: str = "",
                apply_change: bool = False, target: str | None = None) -> dict:
        actor.require_human("处理巡检发现")
        if action not in HUMAN_ACTIONS:
            raise BurrowlError("INVALID_ARGUMENT", "action 必须是 adopt（采纳）/ reject（驳回）/ ignore（忽略）")
        f = self._finding(decision_id)
        if f["status"] != "open":
            if apply_change and f["data"].get("resolution", {}).get("judgment_id"):
                return self.finding_view(decision_id)
            raise BurrowlError("CONFLICT", "这条发现已经处理过", {"status": f["status"]})
        resolution = {"action": action, "reason": reason, "by": actor.id}
        if apply_change:
            if action != "adopt":
                raise BurrowlError("INVALID_ARGUMENT", "只有采纳时可以写入复核意见")
            resolution["judgment_id"] = self._apply_review_change(actor, f, target)
        fw = self.ws.framework
        fw.close_decision(decision_id, HUMAN_ACTIONS[action], resolution)
        insp = fw.inspection(f["data"].get("inspection_id", ""))
        if insp and insp["status"] == "done" and not self.findings(insp["id"], status="open"):
            fw.update_inspection(insp["id"], status="closed")
        self.ws.capture.log(actor, "inspection.resolve", input={"decision_id": decision_id, "action": action})
        return self.finding_view(decision_id)

    def _apply_review_change(self, actor: Actor, finding: dict, target: str | None) -> str:
        data, decision_id = finding["data"], finding["id"]
        reviewer = data.get("reviewer") or {}
        proposal, cites = reviewer.get("proposed_change"), reviewer.get("cites")
        if reviewer.get("verdict") != "confirm" or not proposal or not cites:
            raise BurrowlError("INVALID_ARGUMENT", "只有复核员确认并附依据的修改意见可以写入判断层")
        if target and target not in data.get("targets", []):
            raise BurrowlError("INVALID_ARGUMENT", "只能更正这条发现针对的判断", {"target": target})
        # 账本和待决策在两个库中。用账本里的来源编号去重，写完账本后可安全重试关闭待决策。
        with transaction(self.ws.ledger_db):
            existing = self.ws.ledger.query(
                "SELECT id FROM judgments WHERE json_extract(data, '$.inspection_finding') = ? LIMIT 1",
                (decision_id,),
            )
            if existing:
                return existing[0]["id"]
            if target:
                written = self.ws.versions.correct(actor, target, reason="采纳巡检复核意见", text=proposal,
                                                   cites=cites, inspection_finding=decision_id)
            else:
                written = self.ws.judgments.write(actor, kind="conclusion", text=proposal, cites=cites,
                                                  objects=list(dict.fromkeys(
                                                      obj for ref in data.get("targets", [])
                                                      for obj in self.ws.ledger.objects_of(ref))),
                                                  inspection_finding=decision_id)
            return written["id"]

    def close(self, actor: Actor, *, inspection_id: str) -> dict:
        actor.require_human("关闭一期巡检")
        self._inspection(inspection_id)
        insp = self.ws.framework.update_inspection(inspection_id, status="closed")
        self.ws.capture.log(actor, "inspection.close", input={"inspection_id": inspection_id})
        return self.summary(insp)

    def forget(self, entries: list[str]) -> dict:
        """删除原件时调用（设计稿 07 D-05：删除不留记录）：去掉提到被删条目的巡检发现，
        以及巡检包里涉及它们的任务与探索样本。由 PurgeService.delete 在账本删除之后调用。"""
        if not entries:
            return {"findings": 0, "tasks": 0}
        mentions = lambda value: any(x in json.dumps(value, ensure_ascii=False) for x in entries)  # noqa: E731
        fw = self.ws.framework
        gone = [d["id"] for status in ("open", "resolved", "dismissed")
                for d in fw.decisions(status=status, kind="finding") if mentions(d["data"])]
        for decision_id in gone:
            fw.conn.execute("DELETE FROM decisions WHERE id = ?", (decision_id,))
        dropped = 0
        for insp in fw.inspections(limit=1_000_000):
            data = insp["data"]
            tasks = [t for t in data.get("tasks", []) if not mentions(t)]
            samples = [s for s in data.get("samples", []) if not mentions(s)]
            if len(tasks) != len(data.get("tasks", [])) or len(samples) != len(data.get("samples", [])):
                dropped += len(data.get("tasks", [])) - len(tasks)
                fw.update_inspection(insp["id"], data={**data, "tasks": tasks, "samples": samples})
        return {"findings": len(gone), "tasks": dropped}

    def finding_view(self, decision_id: str) -> dict:
        """一条发现与它的经过：巡检员提交、复核员意见、人的处理（都记在这一项待决策上，过程日志另有记录）。"""
        f = self._finding(decision_id)
        d = f["data"]
        history = [{"type": "submit", "at": f["created_at"], "by": d.get("by"), "model": d.get("model"),
                    "method": d.get("method")}]
        history.extend({"type": "ai_review", **r} for r in d.get("reviewer_history", []))
        if d.get("reviewer"):
            history.append({"type": "ai_review", **d["reviewer"]})
        if d.get("resolution"):
            history.append({"type": "resolve", "at": f["updated_at"], **d["resolution"]})
        return {**f, "history": history}

    def findings(self, inspection_id: str | None = None, status: str | None = None) -> list[dict]:
        """巡检发现（kind=finding 的待决策项），按时间。status：open / resolved / dismissed。"""
        rows = self.ws.framework.decisions(status, "finding")
        if inspection_id:
            rows = [r for r in rows if r["data"].get("inspection_id") == inspection_id]
        return sorted(rows, key=lambda r: (r["created_at"], r["id"]))

    # ---------- 启动与提示（D-01、D-02、D-27） ----------
    def prompt(self, *, inspection_id: str, role: str = "inspector", finding_ids: list[str] | None = None) -> str:
        self._inspection(inspection_id)
        if role == "inspector":
            return (f"请用 burrowl 的 inspection_get 领取巡检包 {inspection_id}（role=inspector），按返回的说明逐个任务"
                    "阅读原件并用 inspection_submit 提交；每个任务都要提交，有问题交 outcome=issue，没有问题交 clear。")
        ids = f"，finding_ids={json.dumps(finding_ids, ensure_ascii=False)}" if finding_ids else ""
        return (f"请用 burrowl 的 inspection_get 领取巡检包 {inspection_id} 的复核任务（role=reviewer{ids}），"
                "对每条发现自己用 artifact_read 读它引用的原文，再用 review_ai_submit"
                "（item_id 写发现的待决策编号 dec_…）"
            "交 confirm / reject / unsure；确认后如有值得写入的修改，用 proposed_change 提出，并附自己核对过的依据。")

    def start(self, actor: Actor, *, inspection_id: str, role: str = "inspector",
              finding_ids: list[str] | None = None) -> dict:
        actor.require_human("启动巡检员或复核员")
        insp = self._inspection(inspection_id)
        if insp["status"] == "closed":
            raise BurrowlError("CONFLICT", "这一期巡检已经关闭", {"inspection_id": inspection_id})
        agent = self.settings()["inspector" if role == "inspector" else "reviewer"]
        if not agent:
            raise BurrowlError("INVALID_ARGUMENT", "请先在设置页的“巡检”里选择" + ("巡检员" if role == "inspector"
                                                                          else "复核员") + " agent")
        if role == "reviewer" and self.ws.config.get("review", {}).get("ai", "framework") == "off":
            raise BurrowlError("REVIEW_DISABLED", "这个数据目录关闭了 AI 复核（设置 review.ai）")
        run = self.ws.agents.start(actor, agent=agent, prompt=self.prompt(inspection_id=inspection_id, role=role,
                                                                          finding_ids=finding_ids),
                                   preamble=False, inspection_id=inspection_id, inspection_role=role)
        data = self.ws.framework.inspection(inspection_id)["data"]
        data["runs"] = [*data.get("runs", []), {"run_id": run["id"], "role": role, "agent": agent,
                                                "guidelines_sha": self.guidelines()["sha"],
                                                "session_id": run["session_id"], "started_at": run["created_at"],
                                                "started_by": actor.id, "finding_ids": finding_ids or []}]
        status = "running" if role == "inspector" and insp["status"] == "ready" else insp["status"]
        self.ws.framework.update_inspection(inspection_id, status=status, data=data)
        return run

    # ---------- 离线包（D-29） ----------
    def export(self, *, inspection_id: str) -> dict:
        insp = self._inspection(inspection_id)
        blocked = self.no_outbound_ids()
        lines = [f"# burrowl 巡检包 {inspection_id}（第 {insp['period']} 期）", "",
                 "请逐个任务阅读下面的原文段落，按要求判断。最后只输出一个 JSON 数组，每个元素：",
                 '`{"task_id": "t1", "outcome": "issue 或 clear", "summary": "发现了什么", '
                 '"cites": ["art_…#p3-2"], "suggestion": "' + "/".join(SUGGESTIONS) + '"}`。',
                 "cites 只能写下面给出的段落编号或判断编号。", "", "## 巡检原则", "", self.guidelines()["text"], ""]
        for t in insp["data"].get("tasks", []):
            lines += [f"## {t['id']} {CHECK_LABEL[t['check']]}：{t['title']}", "", t["question"], ""]
            for ref in t.get("targets", []):
                entry = self.ws.get(ref) or {}
                text = (entry.get("data") or {}).get("text")
                if text:
                    lines += [f"- 判断 {ref}：{text}"]
            for ref in t["read"]:
                art_id, _, anchor = ref.partition("#")
                if art_id in blocked:
                    lines += [f"- {ref}：（不外发，原文不在此包中）"]
                    continue
                art = self.ws.ledger.get(art_id)
                seg = self.ws.extraction.find(art, anchor) if art else None
                lines += [f"- {ref}：{seg['text'] if seg else '（段落不存在）'}"]
            if t.get("human_only"):
                lines += ["- （有段落标为不外发，只能由人看）"]
            lines.append("")
        return {"inspection_id": inspection_id, "markdown": "\n".join(lines)}

    def import_result(self, actor: Actor, *, inspection_id: str, text: str, model: str) -> dict:
        actor.require_human("贴回离线巡检结果")
        insp = self._inspection(inspection_id)
        if not (model or "").strip():
            raise BurrowlError("INVALID_ARGUMENT", "请写明给出结果的模型")
        m = re.search(r"\[.*\]", text, re.S)
        try:
            items = json.loads(m.group(0) if m else text)
        except (ValueError, AttributeError) as exc:
            raise BurrowlError("INVALID_ARGUMENT", "没有找到 JSON 数组；请贴回 AI 输出的结果") from exc
        if not isinstance(items, list):
            raise BurrowlError("INVALID_ARGUMENT", "结果应是 JSON 数组")
        relay = Actor(f"ai:relayed:{model.strip()}", "ai", actor.session_id)
        data, created, skipped = insp["data"], [], []
        tasks = {t["id"]: t for t in data.get("tasks", [])}
        for item in items:
            task = tasks.get(str(item.get("task_id")))
            if task is None or not isinstance(item, dict):
                skipped.append(item.get("task_id") if isinstance(item, dict) else None)
                continue
            outcome = item.get("outcome", "issue")
            result = {"session_id": None, "actor_id": relay.id, "outcome": outcome, "at": _now(), "model": model,
                      "relayed_by": actor.id}
            if outcome == "issue":
                cites = [c for c in item.get("cites") or [] if isinstance(c, str)]
                for ref in cites:
                    self.ws.judgments.basis_of(ref)
                suggestion = item.get("suggestion") if item.get("suggestion") in SUGGESTIONS else "review"
                f = self._create(relay, insp, task, summary=str(item.get("summary") or "")[:2000], cites=cites,
                                 targets=list(task.get("targets") or []), suggestion=suggestion, model=model,
                                 method="relayed", relayed_by=actor.id)
                created.append(f["id"])
                result["decision_id"] = f["id"]
            task["results"] = [*task.get("results", []), result]
        status = "done" if all(t.get("results") for t in data.get("tasks", [])) else insp["status"]
        self.ws.framework.update_inspection(inspection_id, status=status, data=data)
        self.ws.capture.log(actor, "inspection.import", input={"inspection_id": inspection_id, "created": created})
        return {"created": created, "skipped": skipped}

    # ---------- 内部 ----------
    def _inspection(self, inspection_id: str) -> dict:
        insp = self.ws.framework.inspection(inspection_id)
        if insp is None:
            raise BurrowlError("NOT_FOUND", "没有这一期巡检", {"inspection_id": inspection_id})
        return insp

    def _finding(self, decision_id: str) -> dict:
        f = self.ws.framework.decision(decision_id)
        if f is None or f["kind"] != "finding":
            raise BurrowlError("NOT_FOUND", "没有这条巡检发现", {"decision_id": decision_id})
        return f


def section(segs: list[dict], idx: int) -> list[dict]:
    """引用段落所在的小节：同一单元里，往前到最近的标题、往后到下一个标题（各最多 SECTION_SPAN 段）；
    没有标题时取前后各 2 段。"""
    unit = segs[idx]["unit"]
    same = [i for i, s in enumerate(segs) if s["unit"] == unit]
    pos = same.index(idx)
    has_heading = any(segs[i].get("heading") for i in same)
    if not has_heading:
        return [segs[i] for i in same[max(0, pos - 2):pos + 3]]
    start = pos
    while start > 0 and pos - start < SECTION_SPAN and not segs[same[start]].get("heading"):
        start -= 1
    end = pos + 1
    while end < len(same) and end - pos <= SECTION_SPAN and not segs[same[end]].get("heading"):
        end += 1
    return [segs[i] for i in same[start:end]]


def opposite(a: str, b: str) -> str | None:
    """两段结论文字是否有相反的表述（D-05）：只按字面比较，不调用模型。返回原因，没有时返回 None。"""
    ta, tb = set(tokens(NUMBER.sub(" ", a))), set(tokens(NUMBER.sub(" ", b)))
    if not ta or not tb:
        return None
    overlap = len(ta & tb) / min(len(ta), len(tb))
    if overlap < 0.3:
        return None
    for x, y in ANTONYMS:
        ax, bx = x in a.replace(y, ""), x in b.replace(y, "")
        ay, by = y in a, y in b
        if (ax and by and not ay and not bx) or (bx and ay and not by and not ax):
            return f"相反的表述：「{x}」与「{y}」"
    if overlap >= 0.5:
        na, nb = sorted(NUMBER.findall(a)), sorted(NUMBER.findall(b))
        if na and nb and na != nb:
            return f"数值不同：{'、'.join(na[:4])} 与 {'、'.join(nb[:4])}"
        if (len(NEGATION.findall(a)) % 2) != (len(NEGATION.findall(b)) % 2):
            return "一条含否定表述、另一条没有"
    return None


def instructions(role: str) -> str:
    if role == "inspector":
        return ("你是巡检员。逐个任务：先读 read 里列出的原件段落（artifact_read，locator 写段落锚点），需要时用 "
                "entry_get 看 targets 里的判断；再用 inspection_submit 提交。有问题交 outcome=issue，写清 summary"
                "（对象、条件、哪里不一致或遗漏）、cites（只能是你读过的原件段落、事实记录或判断，不能是框架页）、"
                "suggestion；没有问题交 outcome=clear。你不能更正或撤回判断，也不要写判断；每条巡检发现是一项待决策，"
                "由复核员和人处理。巡检输出留在运行日志，不登记为原件。"
                "human_only 的任务里有不外发的原件，只看能看到的部分。"
                "另按 guidelines 里的巡检原则工作。")
    return ("你是复核员。对每条发现：自己用 artifact_read 读它 cites 里的原件段落（必须读过才能确认），"
            "需要时读更多上下文；然后用 review_ai_submit（item_id 写发现的待决策编号 dec_…、"
            "model 写你的模型）交 confirm"
            "（发现成立）/ reject（不成立，附你读过的依据）/ unsure（拿不准）。你不能复核本会话提交的发现，"
            "也不直接写判断。确认后如确有值得收录的修改，填写 proposed_change 并附自己核对过的依据，由人确认写入。"
            "巡检输出留在运行日志，不登记为原件。另按 guidelines 里的巡检原则工作。")
