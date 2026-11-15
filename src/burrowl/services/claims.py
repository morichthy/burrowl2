"""论断的共同底子（设计稿 16）：判断与要点是同一种论断，只是所在的列不同。

一条论断 = 一句话标题 `title` + 正文 `text`（行内引用 [^n]）+ 依据 `cites`（每项 {ref, marker, role, why}）
+ 条件 `conditions`（可带 `scope_unclear`）+ 对象 `objects` + 原作者 `external_author`。
判断（judgments.py）在此之上加类型、标签、立场关系、本地实证、重开条件，存进只追加的账本，可以作为依据；
要点（framework.point_write）只引用原件段落，存成框架页，不能作为依据。

两者共用这里的三件事：
1. `prepare`：整批校验依据与关系，正文的 [^n] 与 marker 一一对上（设计稿 11 D-07）；
2. `notices`：写入时的依据提示（未读先引、已退役、未确认的识别、待复核……），只返回、不落盘；
3. `lint`：写法检查（设计稿 16 D-04）——框架性措辞、没写条件、符号与专有量没有引用定义、依赖上下文的说法。
   只给提示，不拒绝写入；巡检的要点体检用同一套检查。
"""
import re

from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.ids import parse_ref
from ..core.refs import extract_markers, extract_refs, strip_markers
from ..core.vocab import NOTE_KEYS

# 不允许的框架性措辞（草图 §4）；只给警告，不拒绝写入
FRAMEWORK_WORDS = re.compile(r"显然|关键在于|根本原因是|目前有[一二三四五六七八九两\d]+种思路|主线是")
# 依赖上下文的说法（RULES §3 规则 2）：离开写的那一刻、那份材料就读不懂
CONTEXT_WORDS = re.compile(r"如上|同前|上述|前述|本次|刚才|该方法|该算法|该模型|该设备|该方案"
                           r"|本文|文中|作者指出|作者认为")
# 符号与专有量（D-04）：带下标、上标、帽子的记号，或希腊字母；出现时应有一项依据的作用是"定义"
SYMBOLS = re.compile(r"[A-Za-zα-ωΑ-Ω][̂̃̄]?_[\w{(]|[A-Za-zα-ωΑ-Ω][̂̃̄]?\^[\w{(]"
                     r"|[A-Za-z][̂̃̄]|[α-ωΑ-Ω]")
RECOGNITION_LABEL = {"unchecked": "没有任何复核", "ai_flagged": "AI 核对认为有问题", "ai_unsure": "AI 核对拿不准",
                     "ai_confirmed": "只有 AI 核对一致"}


def note_of(source: dict) -> dict:
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


def symbols_in(text: str) -> list[str]:
    """正文里的符号与专有量记号（去掉 [^n] 与引用 ID 后找），最多 5 个，给提示用。"""
    plain = re.sub(r"\b(?:art|jdg|rec|evt|pg)_[0-9A-Za-z]+\S*", " ", strip_markers(text or ""))
    found = []
    for m in SYMBOLS.finditer(plain):
        start = max(0, m.start() - 1)
        token = re.split(r"[\s，。；、（）()：:,;]", plain[start:m.end() + 4].strip())[0] or m.group(0)
        if token not in found:
            found.append(token)
        if len(found) >= 5:
            break
    return found


def has_role(notes: dict[str, dict], word: str) -> bool:
    return any(word in (n.get("role") or "") for n in notes.values())


class ClaimService:
    def __init__(self, ws):
        self.ws = ws

    # ---------- 1. 依据与关系 ----------
    def prepare(self, actor: Actor, kind: str, text: str, cites: list | None, relations: list[dict] | None,
                *, kept_markers: set[str] | frozenset = frozenset(), layer: str = "judgment"
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
                put(c["ref"], note_of(c))
            else:
                raise BurrowlError("INVALID_ARGUMENT", "cites 的每一项是引用字符串，或 {ref, why?, role?, marker?}",
                                   {"item": str(c)[:80]})
        for ref in extract_refs(text):
            put(ref, {})
        cites = list(notes)
        subject = {"entry_kind": "judgment", "kind": kind}
        for ref in cites:
            if layer == "framework":  # 要点（设计稿 17 D-03）：原件、事实记录、判断、别的要点都可以；不作依据
                self._check_point_source(ref)
            else:
                self.ws.relations.check(actor, "cites", subject, ref)
        cited = {c["ref"]: c for c in (self.ws.extraction.citation(actor, ref) for ref in cites) if c}
        rels = []
        for rel in relations or []:
            name = rel.get("rel") or rel.get("predicate")
            target = rel.get("target") or rel.get("object")
            if not target:
                raise BurrowlError("INVALID_ARGUMENT", "关系缺少 target")
            note = note_of(rel)
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

    def _check_point_source(self, ref: str) -> None:
        base, _, _ = parse_ref(ref)
        if not base.startswith(("art_", "rec_", "jdg_", "pg_")) or self.ws.get(base) is None:
            raise BurrowlError("INVALID_REFERENCE", "要点的来源要是已有的原件（段落）、事实记录、判断或要点",
                               {"ref": ref})
        if base.startswith("pg_") and (self.ws.framework.page(base) or {}).get("type") != "point":
            raise BurrowlError("INVALID_REFERENCE", "要点只能引用别的要点，不能引用综合页等框架页", {"ref": ref})

    # ---------- 2. 依据提示 ----------
    def notices(self, cites: list[str], cited: dict[str, dict], rels: list[dict]) -> list[dict]:
        """写入时的提示（只返回给写的人，不落盘）。"""
        notices = []
        judgments = self.ws.judgments
        for ref in cites:
            st = self.ws.versions.state(ref.split("#", 1)[0])
            for flag, code in (("withdrawn", "WITHDRAWN_CITATION"), ("defective", "DEFECTIVE_CITATION")):
                if st[flag]:
                    notices.append({"code": code, "ref": ref})
            c = cited.get(ref)
            for code in (c or {}).get("notices", []):
                notices.append({"code": code, "ref": ref, **({"state": c.get("recognition")}
                                                             if code == "LOW_FIDELITY_CITATION" else {})})
            source = judgments._artifact_behind(ref)  # 经读取记录、事实记录的间接引用同样提示（设计稿 07 D-06）
            if source and self.ws.versions.state(source)["retired"]:
                notices.append({"code": "RETIRED_CITATION", "ref": ref})
        leaning = [*cites, *(r["target"] for r in rels if r["predicate"] == "supports")]
        for ref in dict.fromkeys(leaning):
            base = parse_ref(ref)[0]
            if base.startswith("jdg_") and self.ws.extraction.pending_recheck(base):
                notices.append({"code": "RECHECK_CITATION", "ref": ref})
        return notices

    @staticmethod
    def notice_warnings(notices: list[dict], *, unread: bool = True) -> tuple[list[str], set[str]]:
        """依据提示写成给写的人看的话。unread=False 时不报未读先引（约束不要求先读）。"""
        warnings: list[str] = []
        for code, label in (("WITHDRAWN_CITATION", "已撤回"), ("DEFECTIVE_CITATION", "有缺陷")):
            affected = [n["ref"] for n in notices if n["code"] == code]
            if affected:
                warnings.append(f"{code}：所引版本{label}：{', '.join(affected[:5])}；请重新核对依据")
        refs = [n["ref"] for n in notices if n["code"] == "UNREAD_CITATION"] if unread else []
        if refs:
            warnings.append(f"UNREAD_CITATION：引用的段落 {', '.join(refs[:5])} 你还没有读过（没有你的读取记录）；"
                            "写入已成功，状态检查会列出，建议先用 artifact_read 读过再引用")
        retired = [n["ref"] for n in notices if n["code"] == "RETIRED_CITATION"]
        if retired:
            warnings.append(f"RETIRED_CITATION：原件 {', '.join(retired[:5])} 已由人退役；写入已成功、依据来源不变，"
                            "建议改引替代它的原件（见原件页顶部的退役说明）")
        low = [n for n in notices if n["code"] == "LOW_FIDELITY_CITATION"]
        if low:
            detail = "；".join(f"{n['ref']}（{RECOGNITION_LABEL.get(n.get('state'), '未确认')}）" for n in low[:5])
            warnings.append(f"LOW_FIDELITY_CITATION：段落 {detail} 来自 OCR / AI 识别（含 AI 补的公式 LaTeX）、"
                            "人还没确认；写入已成功，说明里会标「依据含未确认的识别」。"
                            "如果这处公式或文字很关键，请现在用 artifact_view 对照原图再检查一次"
                            "（有误用 artifact_extract 更正，再用 revises 改写）；不关键可以不处理")
        recheck = [n["ref"] for n in notices if n["code"] == "RECHECK_CITATION"]
        if recheck:
            warnings.append(f"RECHECK_CITATION：判断 {', '.join(recheck[:5])} 引用的原件段落已变化，尚未复核；"
                            "写入已成功，它的依据可能已不成立")
        codes = {n["code"] for n in notices if n["code"] != "UNREAD_CITATION" or unread}
        return warnings, codes

    # ---------- 3. 写法检查（D-04） ----------
    @staticmethod
    def lint(*, text: str, title: str | None, conditions: str | None, scope_unclear: bool,
             notes: dict[str, dict], needs_conditions: bool, quoted: bool) -> list[tuple[str, str]]:
        """论断的写法检查，返回 [(code, 给写的人看的话)]。判断与要点、写入与巡检共用。
        needs_conditions：这一类论断要写条件（结论、要点）；quoted：转述外部材料（有原作者，或是要点）。"""
        out: list[tuple[str, str]] = []
        whole = f"{title or ''}\n{text or ''}"
        if FRAMEWORK_WORDS.search(whole):
            out.append(("FRAMEWORK_WORDING", "出现了框架性措辞（如「显然」「关键在于」「根本原因是」），"
                                             "请只写对象、条件和依据"))
        if needs_conditions and not (conditions or "").strip() and not scope_unclear:
            if quoted:
                out.append(("CONDITIONS_UNSTATED",
                            "CONDITIONS_UNSTATED：转述外部材料却没有写条件；写入已成功。请在 conditions 里写原文给出的"
                            "条件，原文没说明的写成「原文未说明：……」，并写明读过的范围，"
                            "不要补或猜（可用 revises 改写）"))
            else:
                out.append(("CONDITIONS_UNSTATED",
                            "CONDITIONS_UNSTATED：这条结论没有写条件；写入已成功。条件（对象、工况、版本、参数、样本量）"
                            "要在发生的当下写下；范围还不清楚时写明哪些清楚、哪些不清楚并设 scope_unclear"))
        symbols = symbols_in(text)
        if notes and symbols and not has_role(notes, "定义"):
            out.append(("DEFINITION_UNCITED", f"DEFINITION_UNCITED：正文用了符号或专有量（{'、'.join(symbols)}），"
                                              "却没有一项依据的作用（role）是「定义」；写入已成功。请在第一次出现处"
                                              "用文字说明它是什么，并引用定义它的段落（role=\"定义\"）"))
        found = sorted(set(CONTEXT_WORDS.findall(whole)))
        if found:
            out.append(("CONTEXT_DEPENDENT", f"CONTEXT_DEPENDENT：出现了依赖上下文的说法（{'、'.join(found)}）；"
                                             "写入已成功。读的人只看到这一条：请写出对象全称、哪篇材料或哪次实验"
                                             "（日期、版本、文件），不要写「该方法」「本文」「如上」"))
        return out
