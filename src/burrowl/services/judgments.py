"""F4 判断层（草图 §4、§5、§13）。

- 只追加；改写就新增版本（revises），指向旧版本并说明原因。
- 依据只能指向左边两列（原件一列、判断一列），框架永远不能作为依据（规则 ①）。
- 写入时可信度由系统根据依据推出，AI 不能声明（§13 第 1 条）。
- 判断层不裁决，冲突可以并存；"现在该信什么"由框架回答。人或 AI 对判断的复核只核对它与依据对不对得上，
  记在复核记录里（services/review.py，设计稿 04 D-18），不改判断本身。
- 原件退役记在 retirements 表，不再写成判断（2.0.0a14）；旧的 retirement 判断照常计入。
  替换记在 replacements 表（设计稿 07 D-03），依赖失效与删除在 services/purge.py。
- 更正、撤回、"原件有缺陷"只能由人通过人工修改入口发起（§4）；AI 只能写"反对"。
- 判断类型只有结论、过程、规定三种可选（D-14）；过程内容不能作为结论的依据（D-15）。
- 依据的主路径是原件段落 `art_…#段落`（设计稿 01 D-02）：写入时检查段落存在，记下被引段落的指纹
  （cited_segments），版本传播与抽取重建据此找出受影响的判断。未读先引、引用未确认的识别文本只提示，不拒绝
  （D-05、D-12）。
"""
import re

from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.hashing import sha256_text
from ..core.ids import kind_of
from ..core.model import (
    EVIDENTIAL_RELS,
    HISTORY_KINDS,
    HUMAN_ONLY_KINDS,
    JUDGMENT_KINDS,
    LAYER_OF_KIND,
    WRITABLE_KINDS,
    derive_credibility,
)
from ..core.refs import extract_refs
from ..index.units import build_units

AI_RELS = ("used", "depends_on", "supports", "opposes", "answers", "targets", "coexists_under")
HUMAN_RELS = ("supersedes", "corrects", "retracts", "defect_of", "retires")
AMEND_MODES = {"correction": "corrects", "retraction": "retracts", "defect": "defect_of", "retirement": "retires"}
# 新写判断以这些关系指向的目标，也检查是否正在待复核（设计稿 04 D-11）
RECHECK_RELS = ("supports", "depends_on")

# 判断里不允许的框架性措辞（草图 §4）；只给警告，不拒绝写入
FRAMEWORK_WORDS = re.compile(r"显然|关键在于|根本原因是|目前有[一二三四五六七八九两\d]+种思路|主线是")


class JudgmentService:
    def __init__(self, ws):
        self.ws = ws

    # ---------- 依据 ----------
    def basis_of(self, ref: str) -> dict:
        """把一个依据引用归纳为 {source_classes, external_tiers, complete}；框架条目直接拒绝。"""
        base = ref.split("@", 1)[0].split("#", 1)[0]
        kind = kind_of(base)
        if kind is None:
            raise BurrowlError("INVALID_REFERENCE", "不是合法的条目 ID", {"ref": ref})
        if LAYER_OF_KIND.get(kind) == "framework":
            raise BurrowlError("FRAMEWORK_NOT_EVIDENCE", "框架条目不能作为依据，请引用它所依据的原件或判断",
                               {"ref": ref})
        if kind == "extraction":
            raise BurrowlError("INVALID_REFERENCE", "抽取记录不能作为依据，请引用原件段落（art_…#p3-2）", {"ref": ref})
        if kind not in ("artifact", "event", "record", "read", "judgment"):
            raise BurrowlError("INVALID_REFERENCE", "这类条目不能作为依据", {"ref": ref, "kind": kind})
        entry = self.ws.ledger.get(base)
        if entry is None:
            raise BurrowlError("NOT_FOUND", "依据不存在", {"ref": ref})
        defective = bool(self.ws.versions.state(base)["defective"])
        if kind == "artifact":
            tier = entry["data"].get("external_tier")
            return {"source_classes": [entry["source_class"]], "external_tiers": [tier] if tier else [],
                    "complete": not defective}
        if kind == "event":
            return {"source_classes": [entry["data"].get("source_class", "local")], "external_tiers": [],
                    "complete": not defective}
        if kind == "record":
            origin = self.basis_of(entry["event_id"] or entry["artifact_id"])
            return {**origin, "complete": origin["complete"] and entry["boundary"] == "complete" and not defective}
        if kind == "read":
            origin = self.basis_of(entry["artifact_id"])
            return {**origin, "complete": origin["complete"] and not defective}
        cred = entry["data"]["credibility"]
        return {"source_classes": cred["source_classes"], "external_tiers": cred["external_tiers"],
                "complete": cred["basis_complete"] and not defective,
                "recognition_unverified": cred.get("recognition_unverified", [])}

    # ---------- 写判断 ----------
    def write(self, actor: Actor, *, kind: str, text: str, cites: list[str] | None = None,
              objects: list[str] | None = None, conditions: str | None = None,
              relations: list[dict] | None = None, external_author: str | None = None,
              revises: str | None = None, revise_reason: str | None = None, local_observation: bool = False,
              reopen_condition: str | None = None, inspection_finding: str | None = None) -> dict:
        """local_observation：人勾选"本地实证"（亲自看到或测到），AI 不能勾选。
        reopen_condition：过程内容中停下的路线在什么条件下值得重新打开。"""
        if actor.kind == "ai" and self.ws.framework.inspection_session(actor.session_id):
            raise BurrowlError("FORBIDDEN", "巡检会话不能写判断；请提交发现或复核意见，由人处理")
        if kind not in JUDGMENT_KINDS:
            raise BurrowlError("INVALID_ARGUMENT", f"kind 必须是 {', '.join(WRITABLE_KINDS)} 之一", {"kind": kind})
        if kind in HUMAN_ONLY_KINDS:
            actor.require_human(f"写入「{kind}」类系统记录")
        if kind in HISTORY_KINDS:
            raise BurrowlError("INVALID_ARGUMENT", "复核和原件退役不再写成判断：复核用 review.submit，"
                               "退役用 artifact.retire", {"kind": kind})
        if local_observation and actor.kind != "human":
            raise BurrowlError("FORBIDDEN", "只有人能标记本地实证；AI 的执行请用过程日志和事实记录留痕",
                               {"actor": actor.id})
        if reopen_condition and kind != "process":
            raise BurrowlError("INVALID_ARGUMENT", "reopen_condition 只用于过程内容（kind=process）")
        if not text.strip():
            raise BurrowlError("INVALID_ARGUMENT", "判断正文不能为空")
        cites = list(dict.fromkeys([*(cites or []), *extract_refs(text)]))
        basis = [self.basis_of(c) for c in cites]
        cited = [c for c in (self.ws.extraction.citation(actor, ref) for ref in cites) if c]
        relations = relations or []
        for rel in relations:
            self._check_relation(actor, rel)
        if kind == "conclusion":
            self._reject_process_evidence([*cites, *(r["target"] for r in relations if r["rel"] in EVIDENTIAL_RELS)])
        if revises:
            self._check_revision(actor, revises, revise_reason)

        # AI 引用了人还没确认的识别（未复核，或只有 AI 复核）：不挡写入，只在可信度里记下（设计稿 04 D-26）
        recognition = [{"ref": c["ref"], "state": c["recognition"]} for c in cited
                       if actor.kind == "ai" and c.get("recognition")]
        credibility = derive_credibility(basis, author_kind=actor.kind, kind=kind,
                                         local_observation=local_observation, recognition=recognition)
        data = {"text": text, "conditions": conditions, "credibility": credibility}
        if inspection_finding:
            actor.require_human("采纳巡检复核意见")
            # 只作来源追踪与重试去重，待决策编号不属于判断依据。
            data["inspection_finding"] = inspection_finding
        notices = []
        for ref in cites:
            base = ref.split("#", 1)[0].split("@", 1)[0]
            version_state = self.ws.versions.state(base)
            for flag, code in (("withdrawn", "WITHDRAWN_CITATION"), ("defective", "DEFECTIVE_CITATION")):
                if version_state[flag]:
                    notices.append({"code": code, "ref": ref})
        for c in cited:
            for code in c.pop("notices"):
                if code == "UNREAD_CITATION" and kind not in ("conclusion", "process"):
                    continue
                notices.append({"code": code, "ref": c["ref"]})
        for ref in cites:  # 引用已退役的原件：写入成功、可信度不变，只提示改引替代它的原件（设计稿 02 D-14）
            source = self._artifact_behind(ref)  # 经读取记录、事实记录的间接引用同样提示（设计稿 07 D-06）
            if source and kind not in HUMAN_ONLY_KINDS and self.retirement_of(source):
                notices.append({"code": "RETIRED_CITATION", "ref": ref})
        # 引用或支持一条正在待复核的判断（依据已变、还没有人复核）：写入成功，只提示（设计稿 04 D-11）
        leaning = [*cites, *(r["target"] for r in relations if r["rel"] in RECHECK_RELS)]
        for ref in dict.fromkeys(leaning):
            base = ref.split("#", 1)[0]
            if base.startswith("jdg_") and self.ws.extraction.pending_recheck(base):
                notices.append({"code": "RECHECK_CITATION", "ref": ref})
        if cited:
            data["cited_segments"] = cited
        if notices:
            data["citation_notices"] = notices
        if reopen_condition:
            data["reopen_condition"] = reopen_condition
        if external_author:  # 文献中的论断：作者记为原作者，同时记下提取者（草图 §1）
            data.update(external_author=external_author, extracted_by=actor.id)
        if revise_reason:
            data["revise_reason"] = revise_reason
        judgment = self.ws.ledger.insert("judgments", "jdg", {
            "kind": kind, "author_id": actor.id, "author_kind": actor.kind, "revises": revises,
            "session_id": actor.session_id, "data": data,
        }, objects=self.ws.linking.normalize_objects(objects or []))
        jid = judgment["id"]
        for c in cites:
            self.ws.ledger.link("used", jid, c, actor.id)
        for rel in relations:
            self.ws.ledger.link(rel["rel"], jid, rel["target"], actor.id,
                                {k: v for k, v in rel.items() if k not in ("rel", "target")})
        if revises:
            self.ws.ledger.link("wasRevisionOf", jid, revises, actor.id, {"reason": revise_reason})
            self.ws.versions.append_existing_successor(actor, revises, jid, revise_reason or "")
        self.index_judgment(jid)
        touched = [*cites, *(r["target"] for r in relations), *([revises] if revises else [])]
        marked = self.ws.propagation.propagate(touched, objects=judgment["objects"], reason=f"新判断 {jid}")
        warnings = []
        if FRAMEWORK_WORDS.search(text):
            warnings.append("判断里出现了框架性措辞（如「显然」「关键在于」「根本原因是」），请只写对象、条件和依据")
        if kind == "conclusion" and not cites and actor.kind == "ai":
            warnings.append("这条结论没有引用任何依据，写入时可信度记为「推断」")
        for code, label in (("WITHDRAWN_CITATION", "已撤回"), ("DEFECTIVE_CITATION", "有缺陷")):
            affected = [n["ref"] for n in notices if n["code"] == code]
            if affected:
                warnings.append(f"{code}：所引版本{label}：{', '.join(affected[:5])}；请重新核对依据")
        unread = [n["ref"] for n in notices if n["code"] == "UNREAD_CITATION"]
        low = [n["ref"] for n in notices if n["code"] == "LOW_FIDELITY_CITATION"]
        if unread:
            warnings.append(f"UNREAD_CITATION：引用的段落 {', '.join(unread[:5])} 在本会话中没有读取记录；"
                            "写入已成功，状态检查会列出，建议先用 artifact_read 读过再引用")
        retired = [n["ref"] for n in notices if n["code"] == "RETIRED_CITATION"]
        if retired:
            warnings.append(f"RETIRED_CITATION：原件 {', '.join(retired[:5])} 已由人退役；写入已成功、可信度不变，"
                            "建议改引替代它的原件（见原件页顶部的退役说明）")
        if low:
            states = {c["ref"]: c.get("recognition") for c in cited}
            label = {"unchecked": "没有任何复核", "ai_flagged": "AI 核对认为有问题", "ai_unsure": "AI 核对拿不准",
                     "ai_confirmed": "只有 AI 核对一致"}
            detail = "；".join(f"{r}（{label.get(states.get(r), '未确认')}）" for r in low[:5])
            warnings.append(f"LOW_FIDELITY_CITATION：段落 {detail} 来自 OCR / AI 识别（含 AI 补的公式 LaTeX）、"
                            "人还没确认；写入已成功，这条判断的可信度已记为「依据含未确认的识别」。"
                            "如果这处公式或文字对结论很关键，请现在用 artifact_view 对照原图再检查一次"
                            "（有误用 artifact_extract 更正，再用 revises 改写这条判断）；不关键可以不处理")
        recheck = [n["ref"] for n in notices if n["code"] == "RECHECK_CITATION"]
        if recheck:
            warnings.append(f"RECHECK_CITATION：判断 {', '.join(recheck[:5])} 引用的原件段落已变化，尚未复核；"
                            "写入已成功，状态检查会列出，它的依据可能已不成立")
        self.ws.capture.log(actor, "judgment.write", input={"judgment_id": jid, "kind": kind},
                            objects=judgment["objects"])
        return {**self.ws.ledger.get(jid), "marked": marked, "warnings": warnings,
                "warning_codes": sorted({n["code"] for n in notices})}

    def amend(self, actor: Actor, *, mode: str, target: str, reason: str, cites: list[str] | None = None,
              inspection_finding: str | None = None) -> dict:
        """人工修改入口：更正（原来就错）、撤回（不再主张）、原件有缺陷。底层写一条新判断指向原条目（§4）。

        mode=retirement 保留给旧的调用：转为 retire()，写退役记录而不是判断；对旧的 retirement 判断做撤回，
        转为 restore()。"""
        actor.require_human("更正、撤回、标记原件缺陷和退役原件")
        if mode not in AMEND_MODES:
            raise BurrowlError("INVALID_ARGUMENT", "mode 必须是 correction / retraction / defect / retirement",
                               {"mode": mode})
        entry = self.ws.ledger.get(target)
        if entry is None:
            raise BurrowlError("NOT_FOUND", "目标条目不存在", {"target": target})
        if mode in ("correction", "retraction") and entry["entry_kind"] != "judgment":
            raise BurrowlError("INVALID_ARGUMENT", "更正和撤回只针对判断；原件出错请用 defect", {"target": target})
        if mode == "defect" and LAYER_OF_KIND[entry["entry_kind"]] != "original":
            raise BurrowlError("INVALID_ARGUMENT", "defect 只针对原件一列的条目", {"target": target})
        if mode == "retirement":
            return self.retire(actor, target, reason=reason)
        if mode == "retraction" and entry.get("kind") == "retirement":  # 撤回旧的退役判断 = 恢复原件
            artifact = next((lk["dst_id"] for lk in self.ws.ledger.links_from(target, "retires")), None)
            if artifact is None or self.retirement_of(artifact) != target:
                raise BurrowlError("CONFLICT", "这条退役记录已经不再有效", {"target": target})
            return self.restore(actor, artifact, reason=reason)
        if mode in ("correction", "retraction") and entry.get("kind") in HISTORY_KINDS:
            raise BurrowlError("INVALID_ARGUMENT", "复核记录不能更正或撤回；请重新复核", {"target": target})
        return self.write(actor, kind=mode, text=reason, cites=cites,
                          objects=entry.get("objects") or [], relations=[{"rel": AMEND_MODES[mode], "target": target}],
                          inspection_finding=inspection_finding)

    # ---------- 查询 ----------
    def status(self, judgment_id: str) -> dict:
        """当前主张状态（框架层计算，不写回判断）：是否被替代、更正、撤回，是否有反对。"""
        incoming = self.ws.ledger.links_to(judgment_id)
        by_rel: dict[str, list[str]] = {}
        for link in incoming:
            by_rel.setdefault(link["rel"], []).append(link["src_id"])
        reactivated = self.ws.versions.is_reactivated_current(judgment_id)
        superseded_by = [*by_rel.get("supersedes", []), *by_rel.get("corrects", [])]
        if not reactivated:
            superseded_by.extend(by_rel.get("wasRevisionOf", []))
        successor = self.ws.versions.successor(judgment_id) if not reactivated else None
        if successor and successor not in superseded_by:
            superseded_by.append(successor)
        version_state = self.ws.versions.state(judgment_id)
        withdrawn = version_state["withdrawn"]
        return {"superseded": bool(superseded_by or withdrawn or version_state["retired"]),
                "superseded_by": superseded_by, "replaced": bool(superseded_by), "retired": version_state["retired"],
                "defective": bool(version_state["defective"]),
                "answered_by": by_rel.get("answers", []),
                "corrected": bool(by_rel.get("corrects")), "retracted": bool(withdrawn),
                "opposed_by": by_rel.get("opposes", []), "supported_by": by_rel.get("supports", []),
                "independent_support": self.independent_support(judgment_id)}

    # ---------- 原件退役（设计稿 02 D-11 至 D-15；2.0.0a14 起不再写成判断） ----------
    def retire(self, actor: Actor, artifact_id: str, *, reason: str, replaced_by: str | None = None) -> dict:
        """人退役一份原件：内容没错，只是不再需要单独出现。记在 retirements 表，是原件的状态历史，不是判断。"""
        actor.require_human("退役原件")
        art = self.ws.ledger.get(artifact_id)
        if art is None or art["entry_kind"] != "artifact":
            raise BurrowlError("INVALID_ARGUMENT", "退役只针对原件", {"target": artifact_id})
        if not reason.strip():
            raise BurrowlError("INVALID_ARGUMENT", "请写明退役的理由")
        if self.retirement_of(artifact_id):
            raise BurrowlError("CONFLICT", "这份原件已经退役", {"target": artifact_id,
                                                              "retirement": self.retirement_of(artifact_id)})
        if replaced_by:
            other = self.ws.ledger.get(replaced_by.split("#", 1)[0])
            if other is None or other["entry_kind"] != "artifact" or other["id"] == artifact_id:
                raise BurrowlError("INVALID_ARGUMENT", "replaced_by 必须是另一份原件", {"replaced_by": replaced_by})
        rec = self.ws.ledger.insert("retirements", "ret", {
            "artifact_id": artifact_id, "action": "retire", "actor_id": actor.id, "session_id": actor.session_id,
            "data": {"reason": reason, **({"replaced_by": replaced_by} if replaced_by else {})}})
        marked = self.ws.propagation.propagate([artifact_id], reason=f"原件 {artifact_id} 已退役")  # D-14
        self.ws.capture.log(actor, "artifact.retire", input={"artifact_id": artifact_id, "retirement": rec["id"]})
        return {**rec, "kind": "retirement", "marked": marked}

    def restore(self, actor: Actor, artifact_id: str, *, reason: str) -> dict:
        """撤销退役：原件恢复显示。"""
        actor.require_human("撤销原件退役")
        if not self.retirement_of(artifact_id):
            raise BurrowlError("CONFLICT", "这份原件没有退役", {"target": artifact_id})
        rec = self.ws.ledger.insert("retirements", "ret", {
            "artifact_id": artifact_id, "action": "restore", "actor_id": actor.id, "session_id": actor.session_id,
            "data": {"reason": reason}})
        marked = self.ws.propagation.propagate([artifact_id], reason=f"原件 {artifact_id} 已撤销退役")
        self.ws.capture.log(actor, "artifact.restore", input={"artifact_id": artifact_id, "record": rec["id"]})
        return {**rec, "kind": "restore", "marked": marked}

    # ---------- 原件替换（设计稿 07 D-03） ----------
    def replace(self, actor: Actor, artifact_id: str, *, replacement: str, reason: str) -> dict:
        """人给已退役或已删除的原件指定替代原件。引用旧原件段落的判断按段落指纹在替代原件里比对，
        对不上的进入待复核；以旧原件和这些判断为输入的框架页标为"输入已变化"。"""
        actor.require_human("替换原件")
        if not reason.strip():
            raise BurrowlError("INVALID_ARGUMENT", "请写明替换的理由")
        old = self.ws.ledger.get(artifact_id)
        if old is not None and (old["entry_kind"] != "artifact" or not self.retirement_of(artifact_id)):
            raise BurrowlError("NOT_RETIRED", "只能替换已退役或已删除的原件；请先退役它", {"target": artifact_id})
        if old is None and not (artifact_id.startswith("art_") and self.ws.ledger.query(
                "SELECT 1 FROM links WHERE dst_id = ? OR dst_id LIKE ? LIMIT 1", (artifact_id, f"{artifact_id}#%"))):
            raise BurrowlError("NOT_FOUND", "没有这份原件，也没有条目引用过它", {"target": artifact_id})
        new = self.ws.ledger.get(replacement.split("#", 1)[0])
        if new is None or new["entry_kind"] != "artifact" or new["id"] == artifact_id:
            raise BurrowlError("INVALID_ARGUMENT", "replacement 必须是另一份已登记的原件", {"replacement": replacement})
        if self.retirement_of(new["id"]):
            raise BurrowlError("INVALID_ARGUMENT", "替代原件本身已退役", {"replacement": new["id"]})
        rec = self.ws.ledger.insert("replacements", "rpl", {
            "old_id": artifact_id, "new_id": new["id"], "actor_id": actor.id, "session_id": actor.session_id,
            "data": {"reason": reason}})
        affected = self.citing(artifact_id)
        marked = self.ws.propagation.propagate([artifact_id, *affected],
                                               reason=f"原件 {artifact_id} 由 {new['id']} 替代")
        self.ws.capture.log(actor, "artifact.replace", input={"artifact_id": artifact_id, "replacement": new["id"],
                                                              "record": rec["id"]})
        recheck = [jid for jid in affected if self.ws.extraction.recheck_entry(jid)]
        return {**rec, "kind": "replacement", "affected_judgments": affected, "needs_recheck": recheck,
                "marked": marked}

    def replacement_of(self, artifact_id: str) -> str | None:
        """替代这份原件的原件（设计稿 07 D-03）；没有时为 None。"""
        info = self.replacement_info(artifact_id)
        return info["new_id"] if info else None

    def replacement_info(self, artifact_id: str) -> dict | None:
        """最近一条替换记录，否则当前退役记录里写的 replaced_by：{new_id, at, record}。
        只对已退役或已删除的原件有意义；撤销退役后，退役记录里的 replaced_by 不再生效。"""
        rows = self.ws.ledger.query("SELECT id, new_id, created_at FROM replacements WHERE old_id = ? "
                                    "ORDER BY rowid DESC LIMIT 1", (artifact_id,))
        if rows:
            return {"new_id": rows[0]["new_id"], "at": rows[0]["created_at"], "record": rows[0]["id"]}
        current = self.retirement_of(artifact_id)
        if current and current.startswith("ret_"):
            r = self.ws.ledger.get(current) or {}
            new_id = (r.get("data", {}).get("replaced_by") or "").split("#", 1)[0]
            if new_id:
                return {"new_id": new_id, "at": r["created_at"], "record": current}
        return None

    def citing(self, artifact_id: str) -> list[str]:
        """直接或经读取记录、事实记录引用这份原件的判断。"""
        ids = {r["src_id"] for r in self.ws.ledger.query(
            "SELECT src_id FROM links WHERE rel IN ('used', 'depends_on') AND (dst_id = ? OR dst_id LIKE ? "
            "OR dst_id IN (SELECT id FROM reads WHERE artifact_id = ?) "
            "OR dst_id IN (SELECT id FROM records WHERE artifact_id = ?))",
            (artifact_id, f"{artifact_id}#%", artifact_id, artifact_id))}
        ids |= {r["id"] for r in self.ws.ledger.query("SELECT id FROM judgments WHERE data LIKE ?",
                                                      (f"%{artifact_id}#%",))}
        return sorted(i for i in ids if i.startswith("jdg_"))

    def _artifact_behind(self, ref: str) -> str | None:
        """引用背后的原件：原件段落、原件、读过它的读取记录、从它升级的事实记录。"""
        base = ref.split("@", 1)[0].split("#", 1)[0]
        if base.startswith("art_"):
            return base
        if base.startswith(("rd_", "rec_")):
            entry = self.ws.ledger.get(base)
            return (entry or {}).get("artifact_id")
        return None

    def retirement_history(self, artifact_id: str | None = None) -> list[dict]:
        """退役与恢复的历史（按时间）：retirements 表，加上旧版写成判断的退役与对它的撤回。"""
        sql, p = "SELECT * FROM links WHERE rel = 'retires'", []
        if artifact_id:
            sql, p = sql + " AND dst_id = ?", [artifact_id]
        out = []
        for lk in self.ws.ledger.query(sql + " ORDER BY created_at", p):
            j = self.ws.ledger.get(lk["src_id"])
            out.append({"id": lk["src_id"], "created_at": lk["created_at"], "artifact_id": lk["dst_id"],
                        "action": "retire", "actor_id": j["author_id"] if j else lk["author_id"],
                        "reason": j["data"]["text"] if j else "", "legacy": True})
            for rt in self.ws.ledger.links_to(lk["src_id"], ("retracts",)):
                rj = self.ws.ledger.get(rt["src_id"])
                out.append({"id": rt["src_id"], "created_at": rt["created_at"], "artifact_id": lk["dst_id"],
                            "action": "restore", "actor_id": rt["author_id"],
                            "reason": rj["data"]["text"] if rj else "", "legacy": True})
        sql, p = "SELECT * FROM retirements", []
        if artifact_id:
            sql, p = sql + " WHERE artifact_id = ?", [artifact_id]
        for r in self.ws.ledger.query(sql + " ORDER BY rowid", p):  # 同一毫秒内的退役与恢复按写入顺序
            out.append({"id": r["id"], "created_at": r["created_at"], "artifact_id": r["artifact_id"],
                        "action": r["action"], "actor_id": r["actor_id"], "reason": r["data"].get("reason", ""),
                        "replaced_by": r["data"].get("replaced_by")})
        out.sort(key=lambda x: x["created_at"])  # 稳定排序：同一时刻的记录保持写入顺序（ULID 同一毫秒内的先后是随机的）
        return out

    def retirement_of(self, artifact_id: str) -> str | None:
        """原件当前有效的退役记录 ID（ret_… 或旧版的 jdg_…），没有退役时为 None（设计稿 02 D-12、D-13）。"""
        current = None
        for h in self.retirement_history(artifact_id):
            current = h["id"] if h["action"] == "retire" else None
        return current

    def retired_ids(self) -> set[str]:
        """全部已退役的原件（供列表、检索、门槛过滤）。"""
        state: dict[str, bool] = {}
        for h in self.retirement_history():
            state[h["artifact_id"]] = h["action"] == "retire"
        return {k for k, v in state.items() if v}

    def independent_support(self, judgment_id: str) -> int:
        """独立支持数（DESIGN §0）：本地实证类依据中，原件互不相同、会话也互不相同的，各算一次。"""
        seen_roots, seen_sessions = set(), set()
        count = 0
        for link in self.ws.ledger.links_from(judgment_id, "used"):
            ref = link["dst_id"].split("#", 1)[0]
            entry = self.ws.ledger.get(ref)
            if not entry or "local" not in self.basis_of(ref)["source_classes"]:
                continue
            root = entry.get("artifact_id") or entry.get("event_id") or entry["id"]
            session = entry.get("session_id")
            if root in seen_roots or (session and session in seen_sessions):
                continue
            seen_roots.add(root)
            if session:
                seen_sessions.add(session)
            count += 1
        return count

    def index_judgment(self, judgment_id: str) -> None:
        j = self.ws.ledger.get(judgment_id)
        if j["kind"] in HISTORY_KINDS:  # 旧版的复核、退役记录是变更历史，不进检索
            self.ws.index.remove(judgment_id)
            return
        text = j["data"]["text"] + (f"\n条件：{j['data']['conditions']}" if j["data"].get("conditions") else "")
        self.ws.index.replace(judgment_id, 0, "judgment", [(0, j["kind"], sha256_text(text), text)],
                              build_units([{"anchor": j["kind"], "text": text}], **self.ws.unit_options()))

    # ---------- 内部 ----------
    def _reject_process_evidence(self, refs: list[str]) -> None:
        """结论的依据只能是原件或结论；过程内容是思路，进证据链会造成框架污染（D-15）。"""
        bad = []
        for ref in refs:
            base = ref.split("@", 1)[0].split("#", 1)[0]
            if base.startswith("jdg_"):
                entry = self.ws.ledger.get(base)
                if entry and entry["kind"] == "process":
                    bad.append(ref)
        if bad:
            raise BurrowlError("PROCESS_NOT_EVIDENCE", "过程内容（提问、尝试、停止）不能作为结论的依据，"
                               "请引用它背后的原件或结论；如果只是记下思路，请把这条写成过程内容", {"refs": bad})

    def _check_relation(self, actor: Actor, rel: dict) -> None:
        name, target = rel.get("rel"), rel.get("target")
        if name in HUMAN_RELS:
            actor.require_human(f"写入「{name}」关系")
        elif name not in AI_RELS:
            raise BurrowlError("INVALID_ARGUMENT", f"关系必须是 {', '.join(AI_RELS + HUMAN_RELS)} 之一", {"rel": name})
        if not target:
            raise BurrowlError("INVALID_ARGUMENT", "关系缺少 target")
        if name == "coexists_under" and not rel.get("condition"):
            raise BurrowlError("INVALID_ARGUMENT", "「在某条件下并存」必须写明条件 condition")
        self.basis_of(target)  # 目标必须存在且不是框架条目

    def _check_revision(self, actor: Actor, revises: str, reason: str | None) -> None:
        old = self.ws.ledger.get(revises)
        if not old or old["entry_kind"] != "judgment":
            raise BurrowlError("NOT_FOUND", "revises 指向的判断不存在", {"revises": revises})
        if not reason:
            raise BurrowlError("INVALID_ARGUMENT", "改写判断必须说明原因 revise_reason")
        if old["author_kind"] != actor.kind or (actor.kind == "human" and old["author_id"] != actor.id):
            raise BurrowlError("FORBIDDEN", "只能改写自己写的判断；对别人的判断请写「反对」或由人更正",
                               {"author": old["author_id"]})
