"""F4 判断层（草图 §4、§5、§13）。

- 只追加；改写就新增版本（revises），指向旧版本并说明原因。
- 依据只能指向左边两列（原件一列、判断一列），框架永远不能作为依据（规则 ①）。
- 写入时可信度由系统根据依据推出，AI 不能声明（§13 第 1 条）。
- 判断层不复核、不裁决，冲突可以并存；"现在该信什么"由框架回答。
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
        defective = bool(self.ws.ledger.links_to(base, ("defect_of",)))
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
            return {**self.basis_of(entry["artifact_id"])}
        cred = entry["data"]["credibility"]
        return {"source_classes": cred["source_classes"], "external_tiers": cred["external_tiers"],
                "complete": cred["basis_complete"]}

    # ---------- 写判断 ----------
    def write(self, actor: Actor, *, kind: str, text: str, cites: list[str] | None = None,
              objects: list[str] | None = None, conditions: str | None = None,
              relations: list[dict] | None = None, external_author: str | None = None,
              revises: str | None = None, revise_reason: str | None = None, local_observation: bool = False,
              reopen_condition: str | None = None) -> dict:
        """local_observation：人勾选"本地实证"（亲自看到或测到），AI 不能勾选。
        reopen_condition：过程内容中停下的路线在什么条件下值得重新打开。"""
        if kind not in JUDGMENT_KINDS:
            raise BurrowlError("INVALID_ARGUMENT", f"kind 必须是 {', '.join(WRITABLE_KINDS)} 之一", {"kind": kind})
        if kind in HUMAN_ONLY_KINDS:
            actor.require_human(f"写入「{kind}」类系统记录")
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

        credibility = derive_credibility(basis, author_kind=actor.kind, kind=kind,
                                         local_observation=local_observation)
        data = {"text": text, "conditions": conditions, "credibility": credibility}
        notices = []
        for c in cited:
            for code in c.pop("notices"):
                if code == "UNREAD_CITATION" and kind not in ("conclusion", "process"):
                    continue
                notices.append({"code": code, "ref": c["ref"]})
        for ref in cites:  # 引用已退役的原件：写入成功、可信度不变，只提示改引替代它的原件（设计稿 02 D-14）
            base = ref.split("#", 1)[0]
            if base.startswith("art_") and kind not in HUMAN_ONLY_KINDS and self.retirement_of(base):
                notices.append({"code": "RETIRED_CITATION", "ref": ref})
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
        self.index_judgment(jid)
        touched = [*cites, *(r["target"] for r in relations), *([revises] if revises else [])]
        marked = self.ws.propagation.propagate(touched, objects=judgment["objects"], reason=f"新判断 {jid}")
        warnings = []
        if FRAMEWORK_WORDS.search(text):
            warnings.append("判断里出现了框架性措辞（如「显然」「关键在于」「根本原因是」），请只写对象、条件和依据")
        if kind == "conclusion" and not cites and actor.kind == "ai":
            warnings.append("这条结论没有引用任何依据，写入时可信度记为「推断」")
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
            warnings.append(f"LOW_FIDELITY_CITATION：段落 {', '.join(low[:5])} 来自 OCR / AI 识别、未经人确认；"
                            "建议用 artifact_view 对照原件复核")
        self.ws.capture.log(actor, "judgment.write", input={"judgment_id": jid, "kind": kind},
                            objects=judgment["objects"])
        return {**self.ws.ledger.get(jid), "marked": marked, "warnings": warnings,
                "warning_codes": sorted({n["code"] for n in notices})}

    def amend(self, actor: Actor, *, mode: str, target: str, reason: str, cites: list[str] | None = None) -> dict:
        """人工修改入口：更正（原来就错）、撤回（不再主张）、原件有缺陷、原件退役。底层写一条新判断指向原条目（§4）。

        退役（设计稿 02 D-11 至 D-13）：原件内容没错，只是不再需要单独出现（例如旧的派生文本已由原件自己的
        抽取层取代）。撤销退役 = 撤回那条退役记录。"""
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
            if entry["entry_kind"] != "artifact":
                raise BurrowlError("INVALID_ARGUMENT", "退役只针对原件", {"target": target})
            if self.retirement_of(target):
                raise BurrowlError("CONFLICT", "这份原件已经退役", {"target": target,
                                                                  "retirement": self.retirement_of(target)})
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
                "answered_by": by_rel.get("answers", []),
                "corrected": bool(by_rel.get("corrects")), "retracted": bool(by_rel.get("retracts")),
                "opposed_by": by_rel.get("opposes", []), "supported_by": by_rel.get("supports", []),
                "independent_support": self.independent_support(judgment_id)}

    def retirement_of(self, artifact_id: str) -> str | None:
        """原件当前有效的退役记录（没有被撤回的那条），没有退役时为 None（设计稿 02 D-12、D-13）。"""
        for link in self.ws.ledger.links_to(artifact_id, ("retires",)):
            if not self.ws.ledger.links_to(link["src_id"], ("retracts",)):
                return link["src_id"]
        return None

    def retired_ids(self) -> set[str]:
        """全部已退役的原件（一次查询，供列表、检索、门槛过滤）。"""
        return {r["dst_id"] for r in self.ws.ledger.query(
            "SELECT dst_id FROM links WHERE rel = 'retires' AND src_id NOT IN "
            "(SELECT dst_id FROM links WHERE rel = 'retracts')")}

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
        text = j["data"]["text"] + (f"\n条件：{j['data']['conditions']}" if j["data"].get("conditions") else "")
        self.ws.index.replace(judgment_id, 0, "judgment", [(0, j["kind"], sha256_text(text), text)],
                              build_units([{"anchor": j["kind"], "text": text}]))

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
