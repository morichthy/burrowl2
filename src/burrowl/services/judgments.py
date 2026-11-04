"""F4 判断层（草图 §4、§5、§13）。

- 只追加；改写就新增版本（revises），指向旧版本并说明原因。
- 依据只能指向左边两列（原件一列、判断一列），框架永远不能作为依据（规则 ①）。
- 写入时可信度由系统根据依据推出，AI 不能声明（§13 第 1 条）。
- 判断层不复核、不裁决，冲突可以并存；"现在该信什么"由框架回答。
- 更正、撤回、"原件有缺陷"只能由人通过人工修改入口发起（§4）；AI 只能写"反对"。
"""
import re

from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.hashing import sha256_text
from ..core.ids import kind_of
from ..core.model import HUMAN_ONLY_KINDS, JUDGMENT_KINDS, LAYER_OF_KIND, derive_credibility
from ..core.refs import extract_refs

AI_RELS = ("used", "depends_on", "supports", "opposes", "answers", "targets", "coexists_under")
HUMAN_RELS = ("supersedes", "corrects", "retracts", "defect_of")
AMEND_MODES = {"correction": "corrects", "retraction": "retracts", "defect": "defect_of"}

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
        if kind not in ("artifact", "event", "record", "read", "judgment"):
            raise BurrowlError("INVALID_REFERENCE", "这类条目不能作为依据", {"ref": ref, "kind": kind})
        entry = self.ws.ledger.get(base)
        if entry is None:
            raise BurrowlError("NOT_FOUND", "依据不存在", {"ref": ref})
        defective = bool(self.ws.ledger.links_to(base, ("defect_of",)))
        if kind == "artifact":
            tier = entry["data"].get("external_tier")
            return {"source_classes": [entry["source_class"]], "external_tiers": [tier] if tier else [],
                    "complete": not defective}
        if kind == "event":
            return {"source_classes": [entry["data"].get("source_class", "executed")], "external_tiers": [],
                    "complete": not defective}
        if kind == "record":
            origin = self.basis_of(entry["event_id"] or entry["artifact_id"])
            return {**origin, "complete": origin["complete"] and entry["boundary"] == "complete" and not defective}
        if kind == "read":
            return {**self.basis_of(entry["artifact_id"])}
        cred = entry["data"]["credibility"]
        return {"source_classes": cred["source_classes"], "external_tiers": cred["external_tiers"],
                "complete": cred["basis_complete"]}

    # ---------- 写判断 ----------
    def write(self, actor: Actor, *, kind: str, text: str, cites: list[str] | None = None,
              objects: list[str] | None = None, conditions: str | None = None,
              relations: list[dict] | None = None, external_author: str | None = None,
              revises: str | None = None, revise_reason: str | None = None) -> dict:
        if kind not in JUDGMENT_KINDS:
            raise BurrowlError("INVALID_ARGUMENT", f"kind 必须是 {', '.join(JUDGMENT_KINDS)} 之一", {"kind": kind})
        if kind in HUMAN_ONLY_KINDS:
            actor.require_human(f"写入「{kind}」类判断")
        if not text.strip():
            raise BurrowlError("INVALID_ARGUMENT", "判断正文不能为空")
        cites = list(dict.fromkeys([*(cites or []), *extract_refs(text)]))
        basis = [self.basis_of(c) for c in cites]
        relations = relations or []
        for rel in relations:
            self._check_relation(actor, rel)
        if revises:
            self._check_revision(actor, revises, revise_reason)

        credibility = derive_credibility(basis, author_kind=actor.kind, kind=kind)
        data = {"text": text, "conditions": conditions, "credibility": credibility}
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
        self.index_judgment(jid)
        touched = [*cites, *(r["target"] for r in relations), *([revises] if revises else [])]
        marked = self.ws.propagation.propagate(touched, objects=judgment["objects"], reason=f"新判断 {jid}")
        warnings = []
        if FRAMEWORK_WORDS.search(text):
            warnings.append("判断里出现了框架性措辞（如「显然」「关键在于」「根本原因是」），请只写对象、条件和依据")
        if kind not in ("question", "constraint", "decision", "instruction", "purpose") and not cites \
                and actor.kind == "ai":
            warnings.append("这条判断没有引用任何依据，写入时可信度记为「推断或讨论」")
        self.ws.capture.log(actor, "judgment.write", input={"judgment_id": jid, "kind": kind},
                            objects=judgment["objects"])
        return {**self.ws.ledger.get(jid), "marked": marked, "warnings": warnings}

    def amend(self, actor: Actor, *, mode: str, target: str, reason: str, cites: list[str] | None = None) -> dict:
        """人工修改入口：更正（原来就错）、撤回（不再主张）、原件有缺陷。底层写一条新判断指向原条目（§4）。"""
        actor.require_human("更正、撤回和标记原件缺陷")
        if mode not in AMEND_MODES:
            raise BurrowlError("INVALID_ARGUMENT", "mode 必须是 correction / retraction / defect", {"mode": mode})
        entry = self.ws.ledger.get(target)
        if entry is None:
            raise BurrowlError("NOT_FOUND", "目标条目不存在", {"target": target})
        if mode in ("correction", "retraction") and entry["entry_kind"] != "judgment":
            raise BurrowlError("INVALID_ARGUMENT", "更正和撤回只针对判断；原件出错请用 defect", {"target": target})
        if mode == "defect" and LAYER_OF_KIND[entry["entry_kind"]] != "original":
            raise BurrowlError("INVALID_ARGUMENT", "defect 只针对原件一列的条目", {"target": target})
        return self.write(actor, kind=mode, text=reason, cites=cites,
                          objects=entry.get("objects") or [], relations=[{"rel": AMEND_MODES[mode], "target": target}])

    # ---------- 查询 ----------
    def status(self, judgment_id: str) -> dict:
        """当前主张状态（框架层计算，不写回判断）：是否被替代、更正、撤回，是否有反对。"""
        incoming = self.ws.ledger.links_to(judgment_id)
        by_rel: dict[str, list[str]] = {}
        for link in incoming:
            by_rel.setdefault(link["rel"], []).append(link["src_id"])
        superseded_by = [*by_rel.get("supersedes", []), *by_rel.get("corrects", []), *by_rel.get("retracts", []),
                         *by_rel.get("wasRevisionOf", [])]
        return {"superseded": bool(superseded_by), "superseded_by": superseded_by,
                "corrected": bool(by_rel.get("corrects")), "retracted": bool(by_rel.get("retracts")),
                "opposed_by": by_rel.get("opposes", []), "supported_by": by_rel.get("supports", []),
                "independent_support": self.independent_support(judgment_id)}

    def independent_support(self, judgment_id: str) -> int:
        """独立支持数（DESIGN §0）：亲自执行类依据中，原件互不相同、会话也互不相同的，各算一次。"""
        seen_roots, seen_sessions = set(), set()
        count = 0
        for link in self.ws.ledger.links_from(judgment_id, "used"):
            ref = link["dst_id"].split("#", 1)[0]
            entry = self.ws.ledger.get(ref)
            if not entry or "executed" not in self.basis_of(ref)["source_classes"]:
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
        text = j["data"]["text"] + (f"\n条件：{j['data']['conditions']}" if j["data"].get("conditions") else "")
        self.ws.index.replace(judgment_id, 0, "judgment", [(0, j["kind"], sha256_text(text), text)])

    # ---------- 内部 ----------
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
