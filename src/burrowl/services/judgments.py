"""F4 判断层（草图 §4、§5、§13；设计稿 10）。

- 判断只存事实（设计稿 10 D-05）：正文、类型、条件、对象、重开条件、原作者、人勾的本地实证、作者、会话、时间、
  改动理由、巡检来源。依据与其他关系存成关系行（services/relations.py），主语是这一版判断。
  可信度、提示一律读取时推出（services/coordinates.py）；写入时的提示照常返回给写的人，但不落盘。
- 只追加；改写就写新版本（`jdg_…@n`）：AI 改写自己会话写的判断、人更正任何判断（D-02）。新版本沿用上一版的
  原作者、对象、关系，只替换改动的内容。撤回、标缺陷记在版本处置上（services/versions.py）。
- 依据只能指向左边两列（原件一列、判断一列），框架永远不能作为依据（规则 ①）。
- 判断类型只有结论、思路、约束三种（D-14）；思路不能作为结论的依据（D-15、I11）。
- 依据的主路径是原件段落 `art_…#段落`（设计稿 01 D-02）：写入时检查段落存在，把被引段落的指纹记在
  cites 关系的限定里，版本传播与抽取重建据此找出受影响的判断。未读先引、引用未确认的识别文本只提示，不拒绝；
  未读先引只查 AI 的引用（设计稿 14）。
- 原件的退役、替换（设计稿 02、07）也在这里：退役是原件那一版的处置，替换记在 replacements 表。
"""
import re

from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.hashing import sha256_text
from ..core.ids import make_ref, parse_ref
from ..core.model import SUBKINDS, WRITABLE_KINDS
from ..core.refs import extract_markers, extract_refs, strip_markers
from ..core.sql import transaction
from ..core.vocab import NOTE_KEYS
from ..index.units import build_units

# 判断里不允许的框架性措辞（草图 §4）；只给警告，不拒绝写入
FRAMEWORK_WORDS = re.compile(r"显然|关键在于|根本原因是|目前有[一二三四五六七八九两\d]+种思路|主线是")
_RECOGNITION_LABEL = {"unchecked": "没有任何复核", "ai_flagged": "AI 核对认为有问题", "ai_unsure": "AI 核对拿不准",
                      "ai_confirmed": "只有 AI 核对一致"}


def _note_of(source: dict) -> dict:
    """关系的说明（设计稿 11 D-01）：从 cites 项、relations 项或关系的 qualifiers 里取 why、role、marker。
    marker 接受 1、"1"、"[^1]"，规范成 "1"；空值不要。"""
    note = {}
    for key in NOTE_KEYS:
        value = source.get(key)
        if value is None:
            continue
        value = str(value).strip()
        if key == "marker":
            m = re.fullmatch(r"(?:\[\^)?(\d{1,3})\]?", value)
            if not m:
                raise BurrowlError("INVALID_ARGUMENT", "marker 是 1–3 位数字，对应正文里的 [^n]", {"marker": value})
            value = m[1]
        if value:
            note[key] = value
    return note


TITLE_MAX = 60


def clean_title(title: str | None) -> str | None:
    """判断的标题：一句话概括，去掉多余空白；空串得到 None（清掉标题）。"""
    title = " ".join((title or "").split())
    if len(title) > TITLE_MAX:
        raise BurrowlError("INVALID_ARGUMENT", f"标题最多 {TITLE_MAX} 字，请概括成一句话", {"length": len(title)})
    return title or None


class JudgmentService:
    def __init__(self, ws):
        self.ws = ws

    # ---------- 写判断 ----------
    def write(self, actor: Actor, *, kind: str, text: str, cites: list | None = None, subkind: str | None = None,
              objects: list[str] | None = None, conditions: str | None = None,
              relations: list[dict] | None = None, external_author: str | None = None,
              revises: str | None = None, revise_reason: str | None = None, local_observation: bool = False,
              reopen_condition: str | None = None, inspection_finding: str | None = None,
              scope_unclear: bool | None = None, title: str | None = None) -> dict:
        """写一条判断（第 1 版）。title：一句话标题（工作台各处用它代替正文显示，可省略，省略时用正文第一句）。
        revises：改写已有判断，等同 revise（写新版本）。
        cites 每项是引用字符串，或 {ref, why?, role?, marker?}（设计稿 11 D-03）；正文里的 [^n] 要有 marker 相同的关系。
        local_observation：人勾选"本地实证"（亲自看到或测到），AI 不能勾选。
        scope_unclear：写的人声明"适用范围尚不清晰"（条件里写明哪些清楚、哪些不清楚），说明里显示"适用范围未明"。
        reopen_condition：思路中停下的路线在什么条件下值得重新打开。"""
        if revises:
            return self.revise(actor, revises, text=text, cites=cites, reason=revise_reason, kind=kind, subkind=subkind,
                               conditions=conditions, relations=relations, objects=objects,
                               external_author=external_author, reopen_condition=reopen_condition,
                               local_observation=True if local_observation else None,
                               inspection_finding=inspection_finding, scope_unclear=scope_unclear, title=title)
        title = clean_title(title)
        self._guard(actor, kind=kind, text=text, local_observation=local_observation,
                    reopen_condition=reopen_condition, inspection_finding=inspection_finding, subkind=subkind)
        cites, cited, rels, notes = self._prepare(actor, kind, text, cites, relations)
        self._check_subkind_links(kind, subkind, cites, [(r["predicate"], r["target"]) for r in rels])
        data = {"text": text, "conditions": conditions}
        for key, value in (("title", title), ("subkind", subkind), ("reopen_condition", reopen_condition),
                           ("external_author", external_author),
                           ("local_observation", bool(local_observation) or None),
                           ("scope_unclear", bool(scope_unclear) or None),
                           ("inspection_finding", inspection_finding)):
            if value:
                data[key] = value
        with transaction(self.ws.ledger_db):
            judgment = self.ws.ledger.insert("judgments", "jdg", {
                "kind": kind, "author_id": actor.id, "author_kind": actor.kind, "session_id": actor.session_id,
                "data": data}, objects=self.ws.linking.normalize_objects(objects or []))
            self._write_relations(actor, judgment["ref"], cites, cited, rels, notes)
        return self._finish(actor, judgment, kind=kind, text=text, cites=cites, cited=cited, rels=rels, notes=notes,
                            external_author=external_author, conditions=conditions)

    def revise(self, actor: Actor, judgment_id: str, *, text: str | None = None, cites: list | None = None,
               reason: str | None = None, kind: str | None = None, conditions: str | None = None,
               relations: list[dict] | None = None, objects: list[str] | None = None, subkind: str | None = None,
               external_author: str | None = None, reopen_condition: str | None = None,
               local_observation: bool | None = None, inspection_finding: str | None = None,
               drop_relations: set[str] | None = None, scope_unclear: bool | None = None,
               add_cites: list | None = None, title: str | None = None) -> dict:
        """写判断的新版本（D-02）。title 给出时替换标题（空字符串清掉），没给沿用上一版。
        AI 只能改写自己（同一作者或同一会话）写的判断；人可以更正任何判断。
        没给的字段沿用上一版；给了空字符串的 external_author、reopen_condition 清掉它们；
        local_observation 只有人能改（给 False 取消）；scope_unclear 给 False 取消。
        cites 给出时替换上一版的依据（要保留说明就在新值里再写），其他关系照旧沿用，relations 追加；
        沿用的依据与关系带着它们的说明（why、role、marker），正文里已经没有的 [^n] 会从沿用的关系上去掉标记。
        drop_relations 是上一版要去掉的关系 ID，add_cites 是追加的依据（人改关系用，见 VersionService.correct）。"""
        old =self.ws.ledger.get(parse_ref(judgment_id)[0])
        if not old or old["entry_kind"] != "judgment":
            raise BurrowlError("NOT_FOUND", "要改写的判断不存在", {"revises": judgment_id})
        if not (reason or "").strip():
            raise BurrowlError("INVALID_ARGUMENT", "改写判断必须说明原因（revise_reason）")
        if actor.kind != "human" and not (old["author_id"] == actor.id or (
                old["session_id"] and old["session_id"] == actor.session_id and old["author_kind"] == actor.kind)):
            raise BurrowlError("FORBIDDEN", "AI 只能改写自己会话写的判断；对别人的判断请写反驳（opposes）或由人更正",
                               {"author": old["author_id"]})
        kind = kind or old["kind"]
        if subkind is None and kind == old["kind"]:
            subkind = old["data"].get("subkind")
        if kind == "conclusion":
            subkind = None
        text = text if (text or "").strip() else old["data"]["text"]
        reopen = old["data"].get("reopen_condition") if reopen_condition is None else reopen_condition
        self._guard(actor, kind=kind, text=text, local_observation=bool(local_observation),
                    reopen_condition=reopen_condition, inspection_finding=inspection_finding, subkind=subkind,
                    effective_reopen=reopen if kind == "thought" else None)
        drop = drop_relations or set()
        self._check_kind_change(old, kind, drop)
        in_text = set(extract_markers(text))
        if cites is None:  # 沿用上一版的依据，连同说明；正文里已经没有的标记去掉
            base_cites = []
            for r in self.ws.ledger.relations_from(old["id"], "cites", version=old["version"]):
                if r["id"] not in drop:
                    note = _note_of(r.get("qualifiers") or {})
                    if note.get("marker") and note["marker"] not in in_text:
                        note.pop("marker")
                    base_cites.append({"ref": r["object"], **note})
        else:
            base_cites = list(cites)
        base_cites += add_cites or []  # 在沿用或新给的依据之外追加（人改关系用）
        kept_markers = {m for r in self.ws.ledger.relations_from(old["id"], version=old["version"])
                        if r["predicate"] != "cites" and r["id"] not in drop
                        for m in [(r.get("qualifiers") or {}).get("marker")] if m and m in in_text}
        cites, cited, rels, notes = self._prepare(actor, kind, text, base_cites, relations, kept_markers=kept_markers)
        kept = [(r["predicate"], r["object"]) for r in self.ws.ledger.relations_from(old["id"], version=old["version"])
                if r["predicate"] != "cites" and r["id"] not in drop]
        self._check_subkind_links(kind, subkind, cites, kept + [(r["predicate"], r["target"]) for r in rels])
        data = {"text": text, "change_reason": reason, "inspection_finding": inspection_finding, "subkind": subkind}
        if conditions is not None:
            data["conditions"] = conditions
        for key, value in (("reopen_condition", reopen_condition), ("external_author", external_author)):
            if value is not None:
                data[key] = value or None
        if scope_unclear is not None:
            data["scope_unclear"] = bool(scope_unclear) or None
        if title is not None:
            data["title"] = clean_title(title)
        if actor.kind == "human" and local_observation is not None:
            data["local_observation"] = bool(local_observation) or None
        changes = {"kind": kind, "author_id": actor.id, "author_kind": actor.kind, "session_id": actor.session_id}
        with transaction(self.ws.ledger_db):
            new = self.ws.ledger.new_version(old["id"], changes, data=data,
                                             objects=self.ws.linking.normalize_objects(objects)
                                             if objects is not None else None)
            self.ws.versions._copy_relations(actor, old["ref"], new["ref"], skip=("cites",), drop=drop,
                                             keep_markers=in_text)
            self._write_relations(actor, new["ref"], cites, cited, rels, notes)
        return self._finish(actor, new, kind=kind, text=text, cites=cites, cited=cited, rels=rels, notes=notes,
                            external_author=new["data"].get("external_author"),
                            conditions=new["data"].get("conditions"), revised_from=old["ref"])

    # ---------- 内部：校验、写关系、收尾 ----------
    def _guard(self, actor: Actor, *, kind: str, text: str, local_observation: bool, reopen_condition: str | None,
               inspection_finding: str | None, subkind: str | None = None,
               effective_reopen: str | None | bool = False) -> None:
        if actor.kind == "ai" and self.ws.framework.inspection_session(actor.session_id):
            raise BurrowlError("FORBIDDEN", "巡检会话不能写判断；请提交发现或复核意见，由人处理")
        if kind not in WRITABLE_KINDS:
            raise BurrowlError("INVALID_ARGUMENT", f"kind 必须是 {', '.join(WRITABLE_KINDS)} 之一", {"kind": kind})
        if local_observation and actor.kind != "human":
            raise BurrowlError("FORBIDDEN", "只有人能标记本地实证；AI 的执行请用过程日志和事实记录留痕",
                               {"actor": actor.id})
        if reopen_condition and kind != "thought":
            raise BurrowlError("INVALID_ARGUMENT", "reopen_condition 只用于思路（kind=thought）")
        allowed = SUBKINDS.get(kind)
        if allowed and subkind not in allowed:
            names = {"thought": "思路", "constraint": "约束"}[kind]
            raise BurrowlError("INVALID_ARGUMENT", f"{names}必须给 subkind：{' / '.join(allowed)}",
                               {"kind": kind, "subkind": subkind})
        if not allowed and subkind:
            raise BurrowlError("INVALID_ARGUMENT", "结论不带 subkind；只有思路与约束有标签", {"subkind": subkind})
        reopen = reopen_condition if effective_reopen is False else effective_reopen
        if subkind == "stopped" and not (reopen or "").strip():
            raise BurrowlError("INVALID_ARGUMENT",
                               "停下的路线（subkind=stopped）必须写 reopen_condition：在什么条件下值得重开")
        if not (text or "").strip():
            raise BurrowlError("INVALID_ARGUMENT", "判断正文不能为空")
        if inspection_finding:
            actor.require_human("采纳巡检复核意见")

    @staticmethod
    def _check_subkind_links(kind: str, subkind: str | None, cites: list[str], links: list[tuple[str, str]]) -> None:
        """使用约束要指向被限制的条目；联想要连两个以上条目（设计稿 15 D-25、D-38）。"""
        if kind == "constraint" and subkind == "usage" and not any(p == "targets" for p, _ in links):
            raise BurrowlError("INVALID_ARGUMENT", "使用约束（subkind=usage）必须用 relations 的 targets 指向它限制的"
                               "条目或原件段落，检索命中那一条时才会随附")
        if kind == "thought" and subkind == "association":
            ends = {parse_ref(t)[0] for t in [*cites, *(t for _, t in links)]}
            if len(ends) < 2:
                raise BurrowlError("INVALID_ARGUMENT", "联想（subkind=association）至少连两个条目"
                                   "（cites 或 relations），"
                                   "并在 why 里写明哪一点相似")

    def _check_kind_change(self, old: dict, kind: str, drop: set[str]) -> None:
        """类型改成思路时，不能已有结论把它当依据、也不能它自己佐证别人（I11）。"""
        if kind == old["kind"] or kind != "thought":
            return
        led = self.ws.ledger
        bad = []
        for r in led.relations_to(old["id"], ("cites", "supports")):
            subject = led.get(parse_ref(r["subject"])[0]) or {}
            if r["predicate"] == "cites" and subject.get("kind") != "conclusion":
                continue
            if self.ws.versions.validity(r["subject"]) in ("withdrawn", "retired"):
                continue
            bad.append(r["subject"])
        bad += [r["object"] for r in led.relations_from(old["id"], "supports", version=old["version"])
                if r["id"] not in drop]
        if bad:
            raise BurrowlError("THOUGHT_NOT_EVIDENCE",
                               "这条判断已被结论当作依据（或佐证关系里有它），不能改成思路；请先处理这些关系",
                               {"refs": list(dict.fromkeys(bad))[:10]})

    def _prepare(self, actor: Actor, kind: str, text: str, cites: list | None, relations: list[dict] | None,
                 *, kept_markers: set[str] | frozenset = frozenset()
                 ) -> tuple[list[str], dict[str, dict], list[dict], dict[str, dict]]:
        """整批校验依据与关系（先校验、再写入）。返回去重后的依据、段落引用的指纹、规范化的关系、
        每条依据的说明（why、role、marker）。正文里的 [^n] 与关系的 marker 必须一一对得上（设计稿 11 D-07）。"""
        notes: dict[str, dict] = {}

        def put(ref: str, note: dict) -> None:
            cur = notes.setdefault(ref, {})
            for k, v in note.items():
                if k == "marker" and cur.get("marker") and cur["marker"] != v:
                    raise BurrowlError("INVALID_ARGUMENT", "同一条依据只能带一个标记（同一个编号可以在正文里出现多次）",
                                       {"ref": ref, "markers": [cur["marker"], v]})
                cur.setdefault(k, v)

        for c in cites or []:
            if isinstance(c, str):
                put(c, {})
            elif isinstance(c, dict) and c.get("ref"):
                put(c["ref"], _note_of(c))
            else:
                raise BurrowlError("INVALID_ARGUMENT", "cites 的每一项是引用字符串，或 {ref, why?, role?, marker?}",
                                   {"item": str(c)[:80]})
        for ref in extract_refs(text):
            put(ref, {})
        cites = list(notes)
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
            note = _note_of(rel)
            if rel.get("reason") and "why" not in note:  # 旧写法 reason 并入 why
                note["why"] = str(rel["reason"]).strip()
            qualifiers = {**({"condition": rel["condition"]} if rel.get("condition") else {}), **note}
            self.ws.relations.check(actor, name, subject, target, label=rel.get("label"), qualifiers=qualifiers)
            rels.append({"predicate": name, "target": target, "label": rel.get("label"), "qualifiers": qualifiers})
        in_rel = {n["marker"] for n in notes.values() if n.get("marker")} | set(kept_markers) | {
            r["qualifiers"]["marker"] for r in rels if r["qualifiers"].get("marker")}
        in_text = set(extract_markers(text))
        if in_text - in_rel:
            missing = "、".join(f"[^{m}]" for m in sorted(in_text - in_rel, key=int))
            raise BurrowlError("INVALID_ARGUMENT",
                               f"正文里的 {missing} 没有对应的关系：请在 cites 项或 relations 项里写 "
                               "marker（如 {ref, marker: \"1\"}），或删去这个标记",
                               {"markers": sorted(in_text - in_rel)})
        if in_rel - in_text:
            extra = "、".join(f"[^{m}]" for m in sorted(in_rel - in_text, key=int))
            raise BurrowlError("INVALID_ARGUMENT",
                               f"关系带了 marker，但正文里没有对应的 {extra}：请在正文相应的句子后面写上标记，"
                               "或去掉 marker", {"markers": sorted(in_rel - in_text)})
        return cites, cited, rels, notes

    def _write_relations(self, actor: Actor, subject: str, cites: list[str], cited: dict[str, dict],
                         rels: list[dict], notes: dict[str, dict] | None = None) -> None:
        for ref in cites:
            c = cited.get(ref)
            qualifiers = {"sha256": c["sha256"], "unit": c["unit"]} if c else {}
            qualifiers.update((notes or {}).get(ref, {}))
            self.ws.relations.add(actor, "cites", subject, ref, qualifiers=qualifiers, checked=True)
        for r in rels:
            self.ws.relations.add(actor, r["predicate"], subject, r["target"], label=r["label"],
                                  qualifiers=r["qualifiers"], checked=True)

    def _finish(self, actor: Actor, judgment: dict, *, kind: str, text: str, cites: list[str],
                cited: dict[str, dict], rels: list[dict], external_author: str | None, conditions: str | None,
                revised_from: str | None = None, notes: dict[str, dict] | None = None) -> dict:
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
        unread = [n["ref"] for n in notices if n["code"] == "UNREAD_CITATION" and kind in ("conclusion", "thought")]
        if unread:
            warnings.append(f"UNREAD_CITATION：引用的段落 {', '.join(unread[:5])} 你还没有读过（没有你的读取记录）；"
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
        codes = {n["code"] for n in notices if n["code"] != "UNREAD_CITATION" or kind in ("conclusion", "thought")}
        if external_author and kind == "conclusion" and not (conditions or "").strip():  # 设计稿 09 D-08
            codes.add("CONDITIONS_UNSTATED")
            warnings.append("CONDITIONS_UNSTATED：这条转述外部材料的结论没有写条件；写入已成功。"
                            "请在 conditions 里写原文给出的条件，原文没说明的写成「原文未说明：……」，"
                            "不要补或猜（可用 revises 改写）")
        elif kind == "conclusion" and not (conditions or "").strip() \
                and not judgment["data"].get("scope_unclear"):  # 设计稿 15 D-19
            codes.add("CONDITIONS_UNSTATED")
            warnings.append("CONDITIONS_UNSTATED：这条结论没有写条件；写入已成功。条件（对象、工况、版本、参数、样本量）"
                            "要在发生的当下写下；范围还不清楚时写明哪些清楚、哪些不清楚并设 scope_unclear")
        stance = ("supports", "opposes", "coexists_under", "answers", "targets", "assumes")
        sources = self.ws.coordinates.sources(judgment["ref"]) if kind == "conclusion" else []
        if sources and all(x.startswith("external") for x in sources) and not any(
                r["predicate"] in stance for r in self.ws.ledger.relations_from(jid, version=judgment["version"])):
            codes.add("EXTERNAL_ONLY")  # 设计稿 15 D-17
            warnings.append("EXTERNAL_ONLY：这条结论只转述外部材料，也没有和别的来源建立关系；写入已成功。"
                            "只是为了好找、好整理的话请写成要点（point_write）；判断层只收与本地实证或别的材料"
                            "一致、冲突的结论，以及读的人加的判断")
        self.ws.capture.log(actor, "judgment.write", input={"judgment": judgment["ref"], "kind": kind},
                            objects=judgment["objects"])
        markers: dict[str, int] = {}
        for m in [*(n.get("marker") for n in (notes or {}).values()),
                  *(r["qualifiers"].get("marker") for r in rels)]:
            if m:
                markers[m] = markers.get(m, 0) + 1
        return {**self.ws.ledger.get(judgment["ref"]), "marked": marked, "warnings": warnings,
                "warning_codes": sorted(codes), **({"markers": dict(sorted(markers.items(), key=lambda x: int(x[0])))}
                                                  if markers else {})}

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

    # ---------- 判断的标题（D-101）：标签，不是内容 ----------
    def set_title(self, actor: Actor, judgment_id: str, title: str | None) -> dict:
        """人给判断定标题（空或 None 清掉标题）。只追加一行标题记录：不产生新版本，也不让引用它的框架页过期。"""
        actor.require_human("修改判断的标题")
        entry = self.ws.ledger.get(judgment_id)
        if entry is None or entry["entry_kind"] != "judgment":
            raise BurrowlError("NOT_FOUND", "标题只属于判断", {"id": judgment_id})
        clean = clean_title(title) or ""
        if clean == (entry["data"].get("title") or ""):
            return {"id": entry["id"], "title": clean or None, "changed": False}
        row = self.ws.ledger.insert("judgment_titles", "ttl", {
            "judgment_id": entry["id"], "title": clean, "actor_id": actor.id, "session_id": actor.session_id,
            "data": {"previous": entry["data"].get("title")}})
        self.ws.capture.log(actor, "judgment.title", input={"id": entry["id"], "title": clean})
        return {"id": entry["id"], "title": clean or None, "changed": True, "title_id": row["id"]}

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
                                               reason=f"原件 {artifact_id} 由 {new['id']} 替代",
                                               changed_artifacts=[artifact_id])
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
            text = strip_markers(j["data"]["text"]) + (
                f"\n条件：{j['data']['conditions']}" if j["data"].get("conditions") else "")
            self.ws.index.replace(judgment_id, j["version"], "judgment", [(0, j["kind"], sha256_text(text), text)],
                                  build_units([{"anchor": j["kind"], "text": text}], **self.ws.unit_options()))

    def ref_of(self, judgment_id: str) -> str:
        return make_ref(judgment_id, self.ws.ledger.head_version(judgment_id))
