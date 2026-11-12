"""F4 判断层（草图 §4、§5、§13；设计稿 10）。

- 判断只存事实（设计稿 10 D-05）：正文、类型、条件、对象、重开条件、原作者、人勾的本地实证、作者、会话、时间、
  改动理由、巡检来源。依据与其他关系存成关系行（services/relations.py），主语是这一版判断。
  可信度、提示一律读取时推出（services/coordinates.py）；写入时的提示照常返回给写的人，但不落盘。
- 只追加；改写就写新版本（`jdg_…@n`）：AI 改写自己会话写的判断、人更正任何判断（D-02）。新版本沿用上一版的
  原作者、对象、关系，只替换改动的内容。撤回、标缺陷记在版本处置上（services/versions.py）。
- 依据只能指向左边两列（原件一列、判断一列），框架永远不能作为依据（规则 ①）。
- 判断类型只有结论、过程、规定三种（D-14）；过程内容不能作为结论的依据（D-15、I11）。
- 依据的主路径是原件段落 `art_…#段落`（设计稿 01 D-02）：写入时检查段落存在，把被引段落的指纹记在
  cites 关系的限定里，版本传播与抽取重建据此找出受影响的判断。未读先引、引用未确认的识别文本只提示，不拒绝。
- 原件的退役、替换（设计稿 02、07）也在这里：退役是原件那一版的处置，替换记在 replacements 表。
"""
import re

from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.hashing import sha256_text
from ..core.ids import make_ref, parse_ref
from ..core.model import WRITABLE_KINDS
from ..core.refs import extract_refs
from ..core.sql import transaction
from ..index.units import build_units

# 判断里不允许的框架性措辞（草图 §4）；只给警告，不拒绝写入
FRAMEWORK_WORDS = re.compile(r"显然|关键在于|根本原因是|目前有[一二三四五六七八九两\d]+种思路|主线是")
_RECOGNITION_LABEL = {"unchecked": "没有任何复核", "ai_flagged": "AI 核对认为有问题", "ai_unsure": "AI 核对拿不准",
                      "ai_confirmed": "只有 AI 核对一致"}


class JudgmentService:
    def __init__(self, ws):
        self.ws = ws

    # ---------- 写判断 ----------
    def write(self, actor: Actor, *, kind: str, text: str, cites: list[str] | None = None,
              objects: list[str] | None = None, conditions: str | None = None,
              relations: list[dict] | None = None, external_author: str | None = None,
              revises: str | None = None, revise_reason: str | None = None, local_observation: bool = False,
              reopen_condition: str | None = None, inspection_finding: str | None = None) -> dict:
        """写一条判断（第 1 版）。revises：改写已有判断，等同 revise（写新版本）。
        local_observation：人勾选"本地实证"（亲自看到或测到），AI 不能勾选。
        reopen_condition：过程内容中停下的路线在什么条件下值得重新打开。"""
        if revises:
            return self.revise(actor, revises, text=text, cites=cites, reason=revise_reason, kind=kind,
                               conditions=conditions, relations=relations, objects=objects,
                               external_author=external_author, reopen_condition=reopen_condition,
                               local_observation=local_observation, inspection_finding=inspection_finding)
        self._guard(actor, kind=kind, text=text, local_observation=local_observation,
                    reopen_condition=reopen_condition, inspection_finding=inspection_finding)
        cites, cited, rels = self._prepare(actor, kind, text, cites, relations)
        data = {"text": text, "conditions": conditions}
        for key, value in (("reopen_condition", reopen_condition), ("external_author", external_author),
                           ("local_observation", bool(local_observation) or None),
                           ("inspection_finding", inspection_finding)):
            if value:
                data[key] = value
        with transaction(self.ws.ledger_db):
            judgment = self.ws.ledger.insert("judgments", "jdg", {
                "kind": kind, "author_id": actor.id, "author_kind": actor.kind, "session_id": actor.session_id,
                "data": data}, objects=self.ws.linking.normalize_objects(objects or []))
            self._write_relations(actor, judgment["ref"], cites, cited, rels)
        return self._finish(actor, judgment, kind=kind, text=text, cites=cites, cited=cited, rels=rels,
                            external_author=external_author, conditions=conditions)

    def revise(self, actor: Actor, judgment_id: str, *, text: str | None = None, cites: list[str] | None = None,
               reason: str | None = None, kind: str | None = None, conditions: str | None = None,
               relations: list[dict] | None = None, objects: list[str] | None = None,
               external_author: str | None = None, reopen_condition: str | None = None,
               local_observation: bool = False, inspection_finding: str | None = None,
               drop_relations: set[str] | None = None) -> dict:
        """写判断的新版本（D-02）。AI 只能改写自己（同一作者或同一会话）写的判断；人可以更正任何判断。
        没给的字段沿用上一版；cites 给出时替换上一版的依据，其他关系照旧沿用，relations 追加。
        drop_relations 是上一版要去掉的关系 ID（人改关系用，见 VersionService.change_relations）。"""
        old = self.ws.ledger.get(parse_ref(judgment_id)[0])
        if not old or old["entry_kind"] != "judgment":
            raise BurrowlError("NOT_FOUND", "要改写的判断不存在", {"revises": judgment_id})
        if not (reason or "").strip():
            raise BurrowlError("INVALID_ARGUMENT", "改写判断必须说明原因（revise_reason）")
        if actor.kind != "human" and not (old["author_id"] == actor.id or (
                old["session_id"] and old["session_id"] == actor.session_id and old["author_kind"] == actor.kind)):
            raise BurrowlError("FORBIDDEN", "AI 只能改写自己会话写的判断；对别人的判断请写反驳（opposes）或由人更正",
                               {"author": old["author_id"]})
        kind = kind or old["kind"]
        text = text if (text or "").strip() else old["data"]["text"]
        self._guard(actor, kind=kind, text=text, local_observation=local_observation,
                    reopen_condition=reopen_condition, inspection_finding=inspection_finding)
        drop = drop_relations or set()
        base_cites = cites if cites is not None else [
            r["object"] for r in self.ws.ledger.relations_from(old["id"], "cites", version=old["version"])
            if r["id"] not in drop]
        cites, cited, rels = self._prepare(actor, kind, text, base_cites, relations)
        data = {"text": text, "change_reason": reason, "inspection_finding": inspection_finding}
        if conditions is not None:
            data["conditions"] = conditions
        for key, value in (("reopen_condition", reopen_condition), ("external_author", external_author)):
            if value:
                data[key] = value
        if actor.kind == "human" and local_observation:
            data["local_observation"] = True
        changes = {"kind": kind, "author_id": actor.id, "author_kind": actor.kind, "session_id": actor.session_id}
        with transaction(self.ws.ledger_db):
            new = self.ws.ledger.new_version(old["id"], changes, data=data,
                                             objects=self.ws.linking.normalize_objects(objects)
                                             if objects is not None else None)
            self.ws.versions._copy_relations(actor, old["ref"], new["ref"], skip=("cites",), drop=drop)
            self._write_relations(actor, new["ref"], cites, cited, rels)
        return self._finish(actor, new, kind=kind, text=text, cites=cites, cited=cited, rels=rels,
                            external_author=new["data"].get("external_author"),
                            conditions=new["data"].get("conditions"), revised_from=old["ref"])

    # ---------- 内部：校验、写关系、收尾 ----------
    def _guard(self, actor: Actor, *, kind: str, text: str, local_observation: bool, reopen_condition: str | None,
               inspection_finding: str | None) -> None:
        if actor.kind == "ai" and self.ws.framework.inspection_session(actor.session_id):
            raise BurrowlError("FORBIDDEN", "巡检会话不能写判断；请提交发现或复核意见，由人处理")
        if kind not in WRITABLE_KINDS:
            raise BurrowlError("INVALID_ARGUMENT", f"kind 必须是 {', '.join(WRITABLE_KINDS)} 之一", {"kind": kind})
        if local_observation and actor.kind != "human":
            raise BurrowlError("FORBIDDEN", "只有人能标记本地实证；AI 的执行请用过程日志和事实记录留痕",
                               {"actor": actor.id})
        if reopen_condition and kind != "process":
            raise BurrowlError("INVALID_ARGUMENT", "reopen_condition 只用于过程内容（kind=process）")
        if not (text or "").strip():
            raise BurrowlError("INVALID_ARGUMENT", "判断正文不能为空")
        if inspection_finding:
            actor.require_human("采纳巡检复核意见")

    def _prepare(self, actor: Actor, kind: str, text: str, cites: list[str] | None,
                 relations: list[dict] | None) -> tuple[list[str], dict[str, dict], list[dict]]:
        """整批校验依据与关系（先校验、再写入）。返回去重后的依据、段落引用的指纹、规范化的关系。"""
        cites = list(dict.fromkeys([*(cites or []), *extract_refs(text)]))
        subject = {"entry_kind": "judgment", "kind": kind}
        for ref in cites:
            self.ws.relations.check(actor, "cites", subject, ref)
        cited = {c["ref"]: c for c in (self.ws.extraction.citation(actor, ref) for ref in cites) if c}
        rels = []
        for rel in relations or []:
            name = rel.get("rel") or rel.get("predicate")
            target = rel.get("target") or rel.get("object")
            if not target:
                raise BurrowlError("INVALID_ARGUMENT", "关系缺少 target")
            qualifiers = {k: rel[k] for k in ("condition", "reason") if rel.get(k)}
            self.ws.relations.check(actor, name, subject, target, label=rel.get("label"), qualifiers=qualifiers)
            rels.append({"predicate": name, "target": target, "label": rel.get("label"), "qualifiers": qualifiers})
        return cites, cited, rels

    def _write_relations(self, actor: Actor, subject: str, cites: list[str], cited: dict[str, dict],
                         rels: list[dict]) -> None:
        for ref in cites:
            c = cited.get(ref)
            qualifiers = {"sha256": c["sha256"], "unit": c["unit"]} if c else {}
            self.ws.relations.add(actor, "cites", subject, ref, qualifiers=qualifiers, checked=True)
        for r in rels:
            self.ws.relations.add(actor, r["predicate"], subject, r["target"], label=r["label"],
                                  qualifiers=r["qualifiers"], checked=True)

    def _finish(self, actor: Actor, judgment: dict, *, kind: str, text: str, cites: list[str],
                cited: dict[str, dict], rels: list[dict], external_author: str | None, conditions: str | None,
                revised_from: str | None = None) -> dict:
        jid = judgment["id"]
        self.index_judgment(jid)
        touched = [*cites, *(r["target"] for r in rels), *([revised_from] if revised_from else [])]
        marked = self.ws.propagation.propagate([jid, *touched], objects=judgment["objects"],
                                               reason=f"新判断 {judgment['ref']}")
        notices = self._notices(cites, cited, rels)
        warnings = []
        if FRAMEWORK_WORDS.search(text):
            warnings.append("判断里出现了框架性措辞（如「显然」「关键在于」「根本原因是」），请只写对象、条件和依据")
        if kind == "conclusion" and not cites and actor.kind == "ai":
            warnings.append("这条结论没有引用任何依据，依据来源记为「推断」")
        for code, label in (("WITHDRAWN_CITATION", "已撤回"), ("DEFECTIVE_CITATION", "有缺陷")):
            affected = [n["ref"] for n in notices if n["code"] == code]
            if affected:
                warnings.append(f"{code}：所引版本{label}：{', '.join(affected[:5])}；请重新核对依据")
        unread = [n["ref"] for n in notices if n["code"] == "UNREAD_CITATION" and kind in ("conclusion", "process")]
        if unread:
            warnings.append(f"UNREAD_CITATION：引用的段落 {', '.join(unread[:5])} 在本会话中没有读取记录；"
                            "写入已成功，状态检查会列出，建议先用 artifact_read 读过再引用")
        retired = [n["ref"] for n in notices if n["code"] == "RETIRED_CITATION"]
        if retired:
            warnings.append(f"RETIRED_CITATION：原件 {', '.join(retired[:5])} 已由人退役；写入已成功、依据来源不变，"
                            "建议改引替代它的原件（见原件页顶部的退役说明）")
        low = [n for n in notices if n["code"] == "LOW_FIDELITY_CITATION"]
        if low:
            detail = "；".join(f"{n['ref']}（{_RECOGNITION_LABEL.get(n.get('state'), '未确认')}）" for n in low[:5])
            warnings.append(f"LOW_FIDELITY_CITATION：段落 {detail} 来自 OCR / AI 识别（含 AI 补的公式 LaTeX）、"
                            "人还没确认；写入已成功，这条判断的说明里会标「依据含未确认的识别」。"
                            "如果这处公式或文字对结论很关键，请现在用 artifact_view 对照原图再检查一次"
                            "（有误用 artifact_extract 更正，再用 revises 改写这条判断）；不关键可以不处理")
        recheck = [n["ref"] for n in notices if n["code"] == "RECHECK_CITATION"]
        if recheck:
            warnings.append(f"RECHECK_CITATION：判断 {', '.join(recheck[:5])} 引用的原件段落已变化，尚未复核；"
                            "写入已成功，它的依据可能已不成立")
        codes = {n["code"] for n in notices if n["code"] != "UNREAD_CITATION" or kind in ("conclusion", "process")}
        if external_author and kind == "conclusion" and not (conditions or "").strip():  # 设计稿 09 D-08
            codes.add("CONDITIONS_UNSTATED")
            warnings.append("CONDITIONS_UNSTATED：这条转述外部材料的结论没有写条件；写入已成功。"
                            "请在 conditions 里写原文给出的条件，原文没说明的写成「原文未说明：……」，"
                            "不要补或猜（可用 revises 改写）")
        self.ws.capture.log(actor, "judgment.write", input={"judgment": judgment["ref"], "kind": kind},
                            objects=judgment["objects"])
        return {**self.ws.ledger.get(judgment["ref"]), "marked": marked, "warnings": warnings,
                "warning_codes": sorted(codes)}

    def _notices(self, cites: list[str], cited: dict[str, dict], rels: list[dict]) -> list[dict]:
        """写入时的提示（只返回给写的人，不落盘）。"""
        notices = []
        for ref in cites:
            st = self.ws.versions.state(ref.split("#", 1)[0])
            for flag, code in (("withdrawn", "WITHDRAWN_CITATION"), ("defective", "DEFECTIVE_CITATION")):
                if st[flag]:
                    notices.append({"code": code, "ref": ref})
            c = cited.get(ref)
            for code in (c or {}).get("notices", []):
                notices.append({"code": code, "ref": ref, **({"state": c.get("recognition")}
                                                             if code == "LOW_FIDELITY_CITATION" else {})})
            source = self._artifact_behind(ref)  # 经读取记录、事实记录的间接引用同样提示（设计稿 07 D-06）
            if source and self.ws.versions.state(source)["retired"]:
                notices.append({"code": "RETIRED_CITATION", "ref": ref})
        leaning = [*cites, *(r["target"] for r in rels if r["predicate"] == "supports")]
        for ref in dict.fromkeys(leaning):
            base = parse_ref(ref)[0]
            if base.startswith("jdg_") and self.ws.extraction.pending_recheck(base):
                notices.append({"code": "RECHECK_CITATION", "ref": ref})
        return notices

    # ---------- 原件退役（设计稿 02 D-11 至 D-15）：原件那一版的处置 ----------
    def retire(self, actor: Actor, artifact_id: str, *, reason: str, replaced_by: str | None = None) -> dict:
        art = self.ws.ledger.get(artifact_id)
        if art is None or art["entry_kind"] != "artifact":
            raise BurrowlError("INVALID_ARGUMENT", "退役只针对原件", {"target": artifact_id})
        if not (reason or "").strip():
            raise BurrowlError("INVALID_ARGUMENT", "请写明退役的理由")
        return {**self.ws.versions.change_state(actor, artifact_id, "retire", reason, replaced_by=replaced_by),
                "kind": "retirement"}

    def restore(self, actor: Actor, artifact_id: str, *, reason: str) -> dict:
        return {**self.ws.versions.change_state(actor, artifact_id, "restore", reason), "kind": "restore"}

    def retirement_of(self, artifact_id: str) -> str | None:
        """原件当前版生效的退役处置 ID；没有退役时为 None。"""
        if not artifact_id.startswith("art_") or self.ws.ledger.head_version(artifact_id) is None:
            return None
        return self.ws.versions.state(artifact_id)["retired"]

    def retired_ids(self) -> set[str]:
        return self.ws.versions.retired_ids()

    def retirement_history(self, artifact_id: str | None = None) -> list[dict]:
        """退役与恢复的历史（按时间）。"""
        q, p = "SELECT * FROM version_states WHERE action IN ('retire', 'restore')", []
        if artifact_id:
            q, p = q + " AND entry_id = ?", [artifact_id]
        return [{"id": r["id"], "created_at": r["created_at"], "artifact_id": r["entry_id"],
                 "version": r["version"], "action": r["action"], "actor_id": r["actor_id"],
                 "reason": r["data"].get("reason", ""), "replaced_by": r["data"].get("replaced_by")}
                for r in self.ws.ledger.query(q + " ORDER BY rowid", p)]

    # ---------- 原件替换（设计稿 07 D-03） ----------
    def replace(self, actor: Actor, artifact_id: str, *, replacement: str, reason: str) -> dict:
        """人给已退役或已删除的原件指定替代原件。引用旧原件段落的判断按段落指纹在替代原件里比对，
        对不上的进入待复核；以旧原件和这些判断为输入的框架页标为"输入已变化"。"""
        actor.require_human("替换原件")
        if not (reason or "").strip():
            raise BurrowlError("INVALID_ARGUMENT", "请写明替换的理由")
        old = self.ws.ledger.get(artifact_id)
        if old is not None and (old["entry_kind"] != "artifact" or not self.retirement_of(artifact_id)):
            raise BurrowlError("NOT_RETIRED", "只能替换已退役或已删除的原件；请先退役它", {"target": artifact_id})
        if old is None and not (artifact_id.startswith("art_") and self.ws.ledger.query(
                "SELECT 1 FROM relations WHERE object_id = ? LIMIT 1", (artifact_id,))):
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
        info = self.replacement_info(artifact_id)
        return info["new_id"] if info else None

    def replacement_info(self, artifact_id: str) -> dict | None:
        """最近一条替换记录，否则当前退役处置里写的 replaced_by：{new_id, at, record}。"""
        rows = self.ws.ledger.query("SELECT id, new_id, created_at FROM replacements WHERE old_id = ? "
                                    "ORDER BY rowid DESC LIMIT 1", (artifact_id,))
        if rows:
            return {"new_id": rows[0]["new_id"], "at": rows[0]["created_at"], "record": rows[0]["id"]}
        current = self.retirement_of(artifact_id)
        if current:
            r = self.ws.ledger.get(current) or {}
            new_id = r.get("data", {}).get("replaced_by")
            if new_id:
                return {"new_id": new_id, "at": r["created_at"], "record": current}
        return None

    def citing(self, artifact_id: str) -> list[str]:
        """直接或经读取记录、事实记录依据这份原件的判断（任一版）。"""
        ids = {r["subject_id"] for r in self.ws.ledger.query(
            "SELECT subject_id FROM effective_relations WHERE predicate = 'cites' AND (object_id = ? "
            "OR object_id IN (SELECT id FROM read_versions WHERE artifact_id = ?) "
            "OR object_id IN (SELECT id FROM record_versions WHERE artifact_id = ?))",
            (artifact_id, artifact_id, artifact_id))}
        return sorted(i for i in ids if i.startswith("jdg_"))

    def _artifact_behind(self, ref: str) -> str | None:
        """引用背后的原件：原件段落、原件、读过它的读取记录、从它升级的事实记录。"""
        base = parse_ref(ref)[0]
        if base.startswith("art_"):
            return base
        if base.startswith(("rd_", "rec_")):
            return (self.ws.ledger.get(base) or {}).get("artifact_id")
        return None

    # ---------- 索引 ----------
    def index_judgment(self, judgment_id: str) -> None:
        """全部版本进索引（设计稿 10 D-19），检索时按条目折叠。"""
        for j in self.ws.ledger.versions(judgment_id):
            text = j["data"]["text"] + (f"\n条件：{j['data']['conditions']}" if j["data"].get("conditions") else "")
            self.ws.index.replace(judgment_id, j["version"], "judgment", [(0, j["kind"], sha256_text(text), text)],
                                  build_units([{"anchor": j["kind"], "text": text}], **self.ws.unit_options()))

    def ref_of(self, judgment_id: str) -> str:
        return make_ref(judgment_id, self.ws.ledger.head_version(judgment_id))
