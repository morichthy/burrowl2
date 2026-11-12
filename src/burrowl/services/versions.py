"""条目版本（设计稿 10 D-01 至 D-04、D-18、D-20）：一套身份与版本。

- 条目 ID 稳定，版本写 `@n`；当前版 = 最新版。所有关系两端固定到版本。
- 新版本：AI 改写自己会话写的判断、人更正任何条目（D-02）。新版本沿用上一版的原作者、对象、关系，只替换改动的内容；
  关系复制到新版本上，旧版本的关系仍留在旧版本上。界面只显示最终作者。
- 人的处置记在版本上（version_states，D-04）：撤回、取消撤回、标缺陷、取消缺陷、退役、取消退役。
  "重新生效第 n 版"写成一个复制第 n 版内容的新版本。
- 有效性（validity）读时推出：current / replaced / withdrawn / retired / lapsed。
"""
from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.ids import make_ref, parse_ref
from ..core.refs import extract_refs
from ..core.sql import transaction

VERSION_KINDS = {"artifact", "judgment", "record", "event", "read"}
STATE_ACTIONS = {"withdraw", "unwithdraw", "defect", "undefect", "retire", "restore"}
_UNDO = {"unwithdraw": "withdraw", "undefect": "defect", "restore": "retire"}
_FLAG = {"withdraw": "withdrawn", "defect": "defective", "retire": "retired"}


class VersionService:
    def __init__(self, ws):
        self.ws = ws

    def _entry(self, ref: str) -> dict:
        entry = self.ws.ledger.get(ref.split("#", 1)[0])
        if not entry or entry["entry_kind"] not in VERSION_KINDS:
            raise BurrowlError("NOT_FOUND", "没有可管理版本的账本条目", {"id": ref})
        return entry

    # ---------- 处置与有效性 ----------
    def state(self, ref: str) -> dict:
        """某一版（不带 @n 指当前版）的处置：{withdrawn, defective, retired}（各为生效的处置 ID 或 None）、
        replaced_by（退役时指定的替代原件）、changes（处置历史）。"""
        entry_id, version, _ = parse_ref(ref)
        version = version or self.ws.ledger.head_version(entry_id)
        flags: dict[str, str | None] = {"withdrawn": None, "defective": None, "retired": None}
        replaced_by = None
        changes = []
        for r in self.ws.ledger.version_states(entry_id, version):
            changes.append({"id": r["id"], "created_at": r["created_at"], "actor_id": r["actor_id"],
                            "action": r["action"], "reason": r["data"].get("reason", ""),
                            **({"replaced_by": r["data"]["replaced_by"]} if r["data"].get("replaced_by") else {})})
            if r["action"] in _FLAG:
                flags[_FLAG[r["action"]]] = r["id"]
                if r["action"] == "retire":
                    replaced_by = r["data"].get("replaced_by")
            else:
                flags[_FLAG[_UNDO[r["action"]]]] = None
                if r["action"] == "restore":
                    replaced_by = None
        return {**flags, "replaced_by": replaced_by, "changes": changes}

    def validity(self, ref: str) -> str:
        """有效性（D-12）：retired / withdrawn（本版的处置）> replaced（有更新的版本，或被人确认的 supersedes 替代，
        或退役原件有替代原件）> lapsed（依据全部失效）> current。"""
        entry_id, version, _ = parse_ref(ref)
        head = self.ws.ledger.head_version(entry_id)
        if head is None:
            return "lapsed" if entry_id.startswith(("art_", "evt_", "rec_", "rd_", "jdg_")) else "current"
        version = version or head
        st = self.state(make_ref(entry_id, version))
        if st["retired"]:
            return "retired"
        if st["withdrawn"]:
            return "withdrawn"
        if version < head or self.superseded_by(entry_id):
            return "replaced"
        lapse = self.ws.purge.coordinates(entry_id)
        if lapse and lapse.get("hidden"):
            return "lapsed"
        return "current"

    def superseded_by(self, entry_id: str) -> list[str]:
        """人确认的 supersedes 入边（替代者引用）。"""
        return [r["subject"] for r in self.ws.ledger.relations_to(entry_id, "supersedes")]

    def hidden_ids(self) -> set[str]:
        """当前版已撤回或已退役的条目（列表、检索默认不返回，D-19）。"""
        out = set()
        for r in self.ws.ledger.query("SELECT DISTINCT entry_id, version FROM version_states"):
            if r["version"] == self.ws.ledger.head_version(r["entry_id"]):
                st = self.state(make_ref(r["entry_id"], r["version"]))
                if st["withdrawn"] or st["retired"]:
                    out.add(r["entry_id"])
        return out

    def retired_ids(self) -> set[str]:
        """当前版已退役的原件。"""
        out = set()
        for r in self.ws.ledger.query("SELECT DISTINCT entry_id, version FROM version_states WHERE action='retire'"):
            if r["version"] == self.ws.ledger.head_version(r["entry_id"]) and self.state(r["entry_id"])["retired"]:
                out.add(r["entry_id"])
        return out

    def successor(self, ref: str) -> str | None:
        """下一版的引用；已是最新版时为 None。"""
        entry_id, version, _ = parse_ref(ref)
        head = self.ws.ledger.head_version(entry_id)
        if head is None or not version or version >= head:
            return None
        return make_ref(entry_id, version + 1)

    # ---------- 历史（D-18） ----------
    def history(self, ref: str, *, snapshots: bool = False) -> dict | None:
        """每一版：作者、改动理由、处置、相对上一版的关系变化；snapshots=True 时附上那一版的内容。"""
        entry_id = parse_ref(ref)[0]
        rows = self.ws.ledger.versions(entry_id)
        if not rows:
            return None
        versions, previous = [], set()
        for e in rows:
            rels = {(r["predicate"], r.get("label") or "", r["object"])
                    for r in self.ws.ledger.relations_from(entry_id, version=e["version"])}
            item = {"ref": e["ref"], "version": e["version"], "created_at": e["created_at"],
                    "author": _author(e), "author_kind": _author_kind(e),
                    "change_reason": e["data"].get("change_reason"),
                    "validity": self.validity(e["ref"]), **{k: v for k, v in self.state(e["ref"]).items()},
                    "relations_added": [{"predicate": p, "label": lb or None, "object": o}
                                        for p, lb, o in sorted(rels - previous)],
                    "relations_removed": [{"predicate": p, "label": lb or None, "object": o}
                                          for p, lb, o in sorted(previous - rels)] if e["version"] > 1 else []}
            if snapshots:
                item["entry"] = e
            versions.append(item)
            previous = rels
        head = rows[-1]
        return {"entry_id": entry_id, "head_version": head["version"], "current_ref": head["ref"],
                "versions": versions}

    # ---------- 人的处置（D-04） ----------
    def change_state(self, actor: Actor, ref: str, action: str, reason: str, *,
                     replaced_by: str | None = None) -> dict:
        actor.require_human("修改版本状态")
        if action == "reactivate":
            return self.reactivate(actor, ref, reason)
        entry = self._entry(ref)
        if action not in STATE_ACTIONS or not (reason or "").strip():
            raise BurrowlError("INVALID_ARGUMENT", "请选择处置并填写理由")
        if action in ("retire", "restore") and entry["entry_kind"] != "artifact":
            raise BurrowlError("INVALID_ARGUMENT", "退役只针对原件", {"target": ref})
        if action in ("withdraw", "unwithdraw") and entry["entry_kind"] != "judgment":
            raise BurrowlError("INVALID_ARGUMENT", "撤回只针对判断；原件一列出错请标缺陷", {"target": ref})
        if action in ("defect", "undefect") and entry["entry_kind"] == "judgment":
            raise BurrowlError("INVALID_ARGUMENT", "缺陷只针对原件一列的条目；判断请更正或撤回", {"target": ref})
        current = self.state(entry["ref"])
        flag = _FLAG.get(action) or _FLAG[_UNDO[action]]
        if action in _FLAG and current[flag]:
            raise BurrowlError("CONFLICT", {"withdrawn": "该版本已经撤回", "defective": "该版本已标缺陷",
                                            "retired": "这份原件已经退役"}[flag], {"target": entry["ref"]})
        if action in _UNDO and not current[flag]:
            raise BurrowlError("CONFLICT", {"withdrawn": "该版本尚未撤回", "defective": "该版本没有待取消的缺陷标记",
                                            "retired": "这份原件没有退役"}[flag], {"target": entry["ref"]})
        data = {"reason": reason}
        if replaced_by:
            other = self.ws.ledger.get(replaced_by.split("#", 1)[0])
            if action != "retire" or other is None or other["entry_kind"] != "artifact" \
                    or other["id"] == entry["id"]:
                raise BurrowlError("INVALID_ARGUMENT", "replaced_by 必须是另一份原件，且只用于退役",
                                   {"replaced_by": replaced_by})
            data["replaced_by"] = replaced_by.split("#", 1)[0]
        with transaction(self.ws.ledger_db):
            rec = self.ws.ledger.insert("version_states", "vst", {
                "entry_id": entry["id"], "version": entry["version"], "action": action, "actor_id": actor.id,
                "session_id": actor.session_id, "data": data})
            marked = self.ws.propagation.propagate([entry["id"]], reason=f"{entry['ref']} 的处置：{action}")
        self.ws.capture.log(actor, f"record.{action}", input={"target": entry["ref"], "state": rec["id"]})
        return {**rec, "marked": marked}

    def reactivate(self, actor: Actor, ref: str, reason: str) -> dict:
        """重新生效第 n 版：复制那一版的内容写成新版本（版本只往前走）。"""
        actor.require_human("让历史版本重新生效")
        entry = self._entry(ref)
        if entry["version"] == entry["head_version"]:
            raise BurrowlError("CONFLICT", "该版本已是当前版")
        if not (reason or "").strip():
            raise BurrowlError("INVALID_ARGUMENT", "请填写理由")
        st = self.state(entry["ref"])
        if st["withdrawn"] or st["retired"]:
            raise BurrowlError("CONFLICT", "只有未撤回、未退役的历史版本可重新生效")
        keep = {k: entry[k] for k in entry if k not in ("id", "version", "created_at", "data", "entry_kind", "ref",
                                                         "head_version", "objects")}
        with transaction(self.ws.ledger_db):
            new = self.ws.ledger.new_version(entry["id"], {**keep, **_author_fields(entry, actor)},
                                             data={**entry["data"],
                                                   "change_reason": f"重新生效第 {entry['version']} 版：{reason}"},
                                             objects=entry["objects"])
            self._copy_relations(actor, entry["ref"], new["ref"])
            self._after_new_version(actor, new)
        return new

    # ---------- 新版本（D-02） ----------
    def correct(self, actor: Actor, ref: str, *, reason: str, text: str | None = None, path: str | None = None,
                cites: list[str] | None = None, inspection_finding: str | None = None) -> dict:
        """人更正任何条目：写一个新版本。判断改正文与依据；原件登记新内容；日志、事实记录、读取记录改正文。"""
        actor.require_human("更正条目")
        if not (reason or "").strip() or not (bool(text and text.strip()) ^ bool(path and path.strip())):
            raise BurrowlError("INVALID_ARGUMENT", "请填写更正理由，并提供新版正文或文件路径")
        entry = self._entry(ref)
        if entry["version"] != entry["head_version"]:
            raise BurrowlError("CONFLICT", "请从当前版发起更正", {"current_ref": make_ref(entry["id"],
                                                                                    entry["head_version"])})
        kind = entry["entry_kind"]
        if kind == "judgment":
            return self.ws.judgments.revise(actor, entry["id"], text=text, cites=cites, reason=reason,
                                            inspection_finding=inspection_finding)
        if kind == "artifact":
            return self.ws.artifacts.register_version(actor, entry["id"], text=text, path=path, reason=reason)
        if path:
            raise BurrowlError("INVALID_ARGUMENT", "文件路径只用于原件版本")
        body = {"event": "output", "record": "result", "read": "excerpt"}[kind]
        with transaction(self.ws.ledger_db):
            new = self.ws.ledger.new_version(entry["id"], _author_fields(entry, actor),
                                             data={body: text, "change_reason": reason})
            self._copy_relations(actor, entry["ref"], new["ref"])
            if kind == "record":
                self.ws.artifacts.index_record(new["id"])
            self._after_new_version(actor, new)
        return new

    def change_relations(self, actor: Actor, ref: str, *, reason: str, add: list[dict] | None = None,
                         remove: list[str] | None = None) -> dict:
        """人增删判断的关系（含依据 cites 与只有人能写的 supersedes）：写成判断的新版本，正文不变。
        remove 是当前版出边的关系 ID（rel_…）；add 每项 {predicate, target, label?, condition?, reason?}。
        关系固定在版本上，所以改关系 = 新版本（D-01、D-02）；旧版本的关系原样保留。"""
        actor.require_human("修改关系")
        entry = self._entry(ref)
        if entry["entry_kind"] != "judgment":
            raise BurrowlError("INVALID_ARGUMENT", "关系写在判断上；要让别的条目指向它，请在那条判断上加关系",
                               {"target": ref})
        if entry["version"] != entry["head_version"]:
            raise BurrowlError("CONFLICT", "请从当前版修改关系", {"current_ref": make_ref(entry["id"],
                                                                                    entry["head_version"])})
        add, remove = list(add or []), list(remove or [])
        if not (reason or "").strip() or not (add or remove):
            raise BurrowlError("INVALID_ARGUMENT", "请填写理由，并至少增加或移除一条关系")
        current = {r["id"]: r for r in self.ws.ledger.relations_from(entry["id"], version=entry["version"])}
        for rid in remove:
            if rid not in current:
                raise BurrowlError("NOT_FOUND", "当前版没有这条关系", {"relation": rid})
        dropped = set(remove)
        embedded = {parse_ref(x)[0] for x in extract_refs(entry["data"].get("text", ""))}
        for rid in dropped:
            r = current[rid]
            if r["predicate"] == "cites" and parse_ref(r["object"])[0] in embedded:
                raise BurrowlError("INVALID_ARGUMENT", "这条依据是正文里写的 [[…]] 引用，要去掉请更正正文",
                                   {"relation": rid, "object": r["object"]})
        kept = {(r["predicate"], (r.get("label") or ""), parse_ref(r["object"])[0])
                for rid, r in current.items() if rid not in dropped}
        rels = []
        for a in add:
            name = a.get("predicate") or a.get("rel")
            target = a.get("target") or a.get("object")
            key = (name, (a.get("label") or "").strip(), parse_ref(target or "")[0])
            if key in kept:
                raise BurrowlError("CONFLICT", "这条关系已经存在", {"predicate": name, "target": target})
            kept.add(key)
            rels.append({k: v for k, v in a.items() if k in ("predicate", "rel", "target", "object", "label",
                                                              "condition", "reason") and v})
        new_cites = [r["object"] for rid, r in current.items() if r["predicate"] == "cites" and rid not in dropped]
        new_cites += [r.get("target") or r.get("object") for r in rels
                      if (r.get("predicate") or r.get("rel")) == "cites"]
        others = [r for r in rels if (r.get("predicate") or r.get("rel")) != "cites"]
        return self.ws.judgments.revise(actor, entry["id"], cites=new_cites, relations=others, reason=reason,
                                        drop_relations=dropped)

    def _copy_relations(self, actor: Actor, old_ref: str, new_ref: str, *, skip: tuple[str, ...] = (),
                        drop: set[str] | None = None) -> None:
        """新版本沿用上一版的关系（D-02）：把上一版的出边复制到新版本上（写的人保持原样）。"""
        old_id, old_version, _ = parse_ref(old_ref)
        for r in self.ws.ledger.relations_from(old_id, version=old_version):
            if r["predicate"] in skip or r["id"] in (drop or ()):
                continue
            self.ws.ledger.relate(r["predicate"], new_ref, r["object"], r["asserted_by"],
                                  session_id=actor.session_id, label=r.get("label"), qualifiers=r["qualifiers"],
                                  args=r.get("args"))

    def _after_new_version(self, actor: Actor, new: dict) -> None:
        self.ws.propagation.propagate([new["id"]], objects=new.get("objects") or [],
                                      reason=f"{new['ref']} 是新版本")
        self.ws.capture.log(actor, "record.new_version", input={"ref": new["ref"]})


def _author(entry: dict) -> str:
    return entry.get("author_id") or entry.get("captured_by") or entry.get("actor_id") or entry.get("promoted_by") \
        or ""


def _author_kind(entry: dict) -> str:
    if entry.get("author_kind") or entry.get("actor_kind"):
        return entry.get("author_kind") or entry.get("actor_kind")
    who = _author(entry)
    return "human" if who.startswith("human") else "system" if who.startswith("system") else "ai"


def _author_fields(entry: dict, actor: Actor) -> dict:
    """新版本的作者列：各类条目的作者列名不同。"""
    kind = entry["entry_kind"]
    if kind == "judgment":
        return {"author_id": actor.id, "author_kind": actor.kind, "session_id": actor.session_id}
    if kind == "artifact":
        return {"captured_by": actor.id, "session_id": actor.session_id}
    if kind == "event":
        return {"actor_id": actor.id, "actor_kind": actor.kind}
    if kind == "record":
        return {"promoted_by": actor.id}
    return {"actor_id": actor.id}
