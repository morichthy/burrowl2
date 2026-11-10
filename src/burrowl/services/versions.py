"""条目版本：底层各版仍用自己的账本 ID，同组版本在界面合并展示。"""
from uuid import uuid4

from ..core.actor import Actor
from ..core.errors import BurrowlError
from ..core.sql import transaction

VERSION_LINK = "entry_version"
STATE_LINK = "entry_version_state"
VERSION_KINDS = {"artifact", "judgment", "record", "event", "read"}
STATE_ACTIONS = {"withdraw", "unwithdraw", "defect", "retire", "restore"}


class VersionService:
    def __init__(self, ws):
        self.ws = ws

    def _entry(self, entry_id: str) -> dict:
        entry = self.ws.ledger.get(entry_id)
        if not entry or entry["entry_kind"] not in VERSION_KINDS:
            raise BurrowlError("NOT_FOUND", "没有可管理版本的账本条目", {"id": entry_id})
        return entry

    def _members(self, entry_id: str) -> list[dict]:
        led = self.ws.ledger
        memberships = led.links_from(entry_id, VERSION_LINK)
        if memberships:
            group = memberships[0]["dst_id"]
            return led.query("SELECT * FROM links WHERE rel = ? AND dst_id = ? "
                             "ORDER BY CAST(json_extract(data, '$.number') AS INTEGER)", (VERSION_LINK, group))
        # 旧版原件和判断本身已有修订关系。读取时解释为版本组，首次更正时再登记成员。
        if not entry_id.startswith(("art_", "jdg_")):
            return []
        table, parent = ("artifacts", "version_of") if entry_id.startswith("art_") else ("judgments", "revises")
        chain = led.query(
            f"WITH RECURSIVE ancestors(id) AS (SELECT ? UNION SELECT t.{parent} FROM {table} t "
            "JOIN ancestors a ON t.id=a.id WHERE "
            f"t.{parent} IS NOT NULL), family(id) AS (SELECT id FROM ancestors UNION "
            f"SELECT t.id FROM {table} t JOIN family f ON t.{parent}=f.id) "
            f"SELECT t.id, t.created_at FROM {table} t JOIN family f ON t.id=f.id ORDER BY t.created_at,t.rowid",
            (entry_id,),
        )
        if len(chain) <= 1:
            return []
        return [{"src_id": e["id"], "data": {"number": n}} for n, e in enumerate(chain, 1)]

    def state(self, entry_id: str) -> dict:
        links = self.ws.ledger.query(
            "SELECT id, created_at, author_id, data, rel, src_id FROM links WHERE dst_id=? "
            "AND rel IN (?, 'retracts', 'defect_of', 'corrects') ORDER BY rowid",
            (entry_id, STATE_LINK),
        )
        flags = {}
        events = []
        # 新旧操作按账本写入顺序回放，同毫秒的撤回与取消撤回也有明确顺序。
        for link in links:
            if link["rel"] == STATE_LINK:
                event = {k: link[k] for k in ("id", "created_at", "author_id", "data")}
            else:
                old = self.ws.ledger.get(link["src_id"])
                if not old:
                    continue
                action = {"retracts": "withdraw", "defect_of": "defect", "corrects": "legacy_correction"}[link["rel"]]
                event = {"id": old["id"], "created_at": old["created_at"], "author_id": old["author_id"],
                         "data": {"action": action, "reason": old["data"].get("text")}}
            events.append(event)
            action = event["data"]["action"]
            if action == "restore":
                flags.pop("retire", None)
            elif action == "unwithdraw":
                flags.pop("withdraw", None)
            else:
                flags[action] = event["id"]
        artifact_retirement = self.ws.judgments.retirement_of(entry_id) if entry_id.startswith("art_") else None
        return {"retired": artifact_retirement or flags.get("retire"), "withdrawn": flags.get("withdraw"),
                "defective": flags.get("defect"), "changes": events}

    def preserve_family_before_destroy(self, entry_id: str) -> None:
        """销毁旧版链的中间成员前，把存续版本归到独立组。销毁后无需保留已删成员。"""
        members = self._members(entry_id)
        if not members or members[0].get("dst_id"):
            return
        group = "version:" + uuid4().hex
        for member in members:
            if member["src_id"] != entry_id:
                self.ws.ledger.link(VERSION_LINK, member["src_id"], group, "system:version", member["data"])

    def history(self, entry_id: str, *, snapshots: bool = False) -> dict | None:
        if entry_id.split("_", 1)[0] not in {"art", "jdg", "evt", "rec", "rd"}:
            return None
        members = self._members(entry_id) or [{"src_id": entry_id, "data": {"number": 1}}]
        versions = []
        for link in members:
            version_id = link["src_id"]
            entry = self.ws.ledger.get(version_id)
            if not entry:
                continue
            item = {"id": version_id, "created_at": entry["created_at"], **link["data"], **self.state(version_id)}
            if snapshots and version_id.startswith("art_"):
                item.update(title=entry["data"].get("title"), sha256=entry["sha256"])
            elif snapshots:
                item["entry"] = entry
                item["cites"] = [r["dst_id"] for r in self.ws.ledger.links_from(version_id)
                                 if r["rel"] in ("used", "documents")]
            versions.append(item)
        if not versions:
            return None
        return {"referenced_id": entry_id, "latest_id": versions[-1]["id"], "versions": versions}

    def hidden_ids(self) -> set[str]:
        """默认视图按组只列最新版。状态不使旧版自动恢复。"""
        led = self.ws.ledger
        older = led.query(
            "SELECT src_id AS id FROM links v WHERE rel=? AND EXISTS (SELECT 1 FROM links n "
            "WHERE n.rel=v.rel AND n.dst_id=v.dst_id AND CAST(json_extract(n.data,'$.number') AS INTEGER) "
            "> CAST(json_extract(v.data,'$.number') AS INTEGER))", (VERSION_LINK,),
        )
        states = led.query("SELECT DISTINCT dst_id AS id FROM links WHERE rel=?", (STATE_LINK,))
        legacy = led.query("SELECT version_of AS id FROM artifacts WHERE version_of IS NOT NULL UNION "
                           "SELECT revises AS id FROM judgments WHERE revises IS NOT NULL")
        return {r["id"] for r in [*older, *legacy]} | {r["id"] for r in states
                                         if any(self.state(r["id"]).get(k) for k in ("retired", "withdrawn"))}

    def successor(self, entry_id: str) -> str | None:
        """给约束检查等调用方报告下一存续版，不替换已有证据引用。"""
        rows = self.ws.ledger.query(
            "SELECT n.src_id FROM links v JOIN links n ON n.dst_id=v.dst_id AND n.rel=v.rel "
            "WHERE v.src_id=? AND v.rel=? AND CAST(json_extract(n.data,'$.number') AS INTEGER) "
            "> CAST(json_extract(v.data,'$.number') AS INTEGER) "
            "ORDER BY CAST(json_extract(n.data,'$.number') AS INTEGER) LIMIT 1",
            (entry_id, VERSION_LINK),
        )
        return rows[0]["src_id"] if rows else None

    def append_existing_successor(self, actor: Actor, previous_id: str, version_id: str, reason: str) -> None:
        """兼容旧的版本登记入口：已管理的版本组继续沿用同一个条目身份。"""
        if not self.ws.ledger.links_from(previous_id, VERSION_LINK):
            return
        with transaction(self.ws.ledger_db):
            members = self._members(previous_id)
            self.ws.ledger.link(VERSION_LINK, version_id, members[0]["dst_id"], actor.id,
                                {"number": members[-1]["data"]["number"] + 1, "reason": reason})

    def change_state(self, actor: Actor, entry_id: str, action: str, reason: str) -> dict:
        actor.require_human("修改版本状态")
        self._entry(entry_id)
        if action not in STATE_ACTIONS or not reason.strip():
            raise BurrowlError("INVALID_ARGUMENT", "请选择版本状态并填写理由")
        with transaction(self.ws.ledger_db):
            current = self.state(entry_id)
            if action == "restore" and not current["retired"]:
                raise BurrowlError("CONFLICT", "该版本尚未退役")
            if action == "retire" and current["retired"]:
                raise BurrowlError("CONFLICT", "该版本已经退役")
            if action == "unwithdraw" and not current["withdrawn"]:
                raise BurrowlError("CONFLICT", "该版本尚未撤回")
            if entry_id.startswith("art_") and action in ("retire", "restore"):
                if action == "retire":
                    return self.ws.judgments.retire(actor, entry_id, reason=reason)
                return self.ws.judgments.restore(actor, entry_id, reason=reason)
            event = self.ws.ledger.link(STATE_LINK, entry_id, entry_id, actor.id,
                                        {"action": action, "reason": reason})
            self.ws.propagation.propagate([entry_id], reason="条目版本状态已变化")
            return event

    def correct(self, actor: Actor, entry_id: str, *, reason: str, text: str | None = None,
                path: str | None = None, cites: list[str] | None = None, inspection_finding: str | None = None) -> dict:
        actor.require_human("更正条目版本")
        if not reason.strip() or not (bool(text and text.strip()) ^ bool(path and path.strip())):
            raise BurrowlError("INVALID_ARGUMENT", "请填写更正理由，并提供新版正文或文件路径")
        with transaction(self.ws.ledger_db):
            old = self._entry(entry_id)
            members = self._members(entry_id)
            if members and members[-1]["src_id"] != entry_id:
                raise BurrowlError("CONFLICT", "请从最新版本发起更正", {"latest_id": members[-1]["src_id"]})
            group = members[0].get("dst_id") if members else None
            if not group:
                group = "version:" + uuid4().hex
                for member in members or [{"src_id": entry_id, "data": {"number": 1}}]:
                    self.ws.ledger.link(VERSION_LINK, member["src_id"], group, actor.id, member["data"])
            new = self._write(actor, old, text=text, path=path, cites=cites, inspection_finding=inspection_finding)
            if new["id"] == entry_id or self.ws.ledger.links_from(new["id"], VERSION_LINK):
                raise BurrowlError("CONFLICT", "更正需要一份独立的新版本")
            number = members[-1]["data"]["number"] + 1 if members else 2
            self.ws.ledger.link(VERSION_LINK, new["id"], group, actor.id, {"number": number, "reason": reason})
            self.ws.propagation.propagate([entry_id], objects=old["objects"], reason="条目已有更正版本")
            return new

    def _write(self, actor: Actor, old: dict, *, text: str | None, path: str | None,
               cites: list[str] | None, inspection_finding: str | None) -> dict:
        kind, data = old["entry_kind"], old["data"]
        if kind == "artifact":
            entry = self.ws.artifacts.register(
                actor, kind=old["kind"], source_class=old["source_class"], text=text, path=path,
                title=data.get("title"), objects=old["objects"], external_tier=data.get("external_tier"),
            )
            if entry.get("existing"):
                raise BurrowlError("CONFLICT", "新版内容已登记；请提供新的原件内容")
            if not self.ws.inspection.outbound(old["id"]):
                self.ws.inspection.set_policy(actor, artifact_id=entry["id"], outbound=False, reason="沿用原件外发限制")
            entry["version_diff"] = self.ws.artifacts._propagate_version(actor, old["id"], entry["id"])
            return entry
        if path:
            raise BurrowlError("INVALID_ARGUMENT", "文件路径只用于原件版本")
        led = self.ws.ledger
        if kind == "judgment":
            if old["kind"] not in ("conclusion", "process", "normative"):
                raise BurrowlError("INVALID_ARGUMENT", "历史处置记录不能更正为正文版本")
            basis = cites if cites is not None else [r["dst_id"] for r in led.links_from(old["id"], "used")]
            return self.ws.judgments.write(actor, kind=old["kind"], text=text, cites=basis,
                                           objects=old["objects"], conditions=data.get("conditions"),
                                           reopen_condition=data.get("reopen_condition"),
                                           inspection_finding=inspection_finding)
        # 保留原始读数和出处。新版对核实后的内容单独标注，避免把事后说明冒充逐字原始输出。
        fields = {k: v for k, v in old.items() if k not in {"id", "entry_kind", "created_at", "objects", "data"}}
        if kind == "event":
            fields.update(session_id=actor.session_id, seq=led.next_seq(actor.session_id),
                          actor_id=actor.id, actor_kind=actor.kind)
        if kind == "record":
            fields["promoted_by"] = actor.id
        if kind == "read":
            fields.update(actor_id=actor.id, session_id=actor.session_id)
        table, prefix = {"event": ("events", "evt"), "record": ("records", "rec"), "read": ("reads", "rd")}[kind]
        new = led.insert(table, prefix, {**fields, "data": {**data, "corrected_text": text}}, objects=old["objects"])
        for rel in led.links_from(old["id"]):
            if rel["rel"] in ("documents", "consumed"):
                led.link(rel["rel"], new["id"], rel["dst_id"], actor.id, rel["data"])
        if kind == "record":
            self.ws.artifacts.index_record(new["id"])
        return new
