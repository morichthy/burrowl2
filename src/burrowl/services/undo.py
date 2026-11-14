"""撤销到某个时刻（设计稿 14 D-10 至 D-17）。

人在工作台首页的最新动态里选一条，把账本与框架库回到那个时刻：
- 那之后写入的账本行（所有人、所有会话）和框架行都删掉。删除走 purge_gate，与原件删除同一个通道（设计稿 07 D-05）。
- 删之前把要删的行与只被它们用到的文件存进数据目录的 `undo/<编号>/`（恢复包），可以用 undo.restore 放回去。
- 系统流水里记一条 `undo.apply`（撤销到哪个时刻、删了多少），首页最新动态里能看到。
- 框架页只有版本历史，没有"那个时刻的页面头"：回退到当时最后一版，并标为"输入已变化"，等人重新综合。
  边、待决策只删那之后新建的，之后被改过状态的不还原（框架可再生）。巡检记录、agent 运行记录、设置不动。

这是账本只追加（I1）的第二个例外，只有人能做（effect=user，不出现在 MCP）。
"""
import json
import re
import shutil
from pathlib import Path

from .. import __version__
from ..core.actor import Actor
from ..core.clock import now
from ..core.errors import BurrowlError
from ..core.hashing import sha256_text
from ..core.ids import ulid
from ..core.sql import transaction as _tx
from ..store.ledger import BASE_OF_VIEW

# 带版本的账本表：(表, 条目 ID 列)。entry_objects 按 (entry_id, version) 跟着它们删
_VERSIONED = ("artifact_versions", "event_versions", "record_versions", "read_versions", "judgment_versions")
_OTHER = ("relations", "version_states", "extractions", "reviews", "replacements", "artifact_policies",
          "judgment_titles")
LEDGER_TABLES = (*_VERSIONED, *_OTHER)
# 框架表里按创建时间删的：(表, 主键列)
_FW_CREATED = (("entities", "id"), ("aliases", "alias"), ("pages", "id"), ("edges", "id"), ("decisions", "id"))
_INDEX_KIND = {"art": "artifacts", "jdg": "judgments", "rec": "records"}
_SHA = re.compile(r"\b[0-9a-f]{64}\b")
UNDO_OPS = ("undo.apply", "undo.restore")


class UndoService:
    def __init__(self, ws):
        self.ws = ws

    @property
    def root(self) -> Path:
        return self.ws.root / "undo"

    # ---------- 预览 ----------
    def preview(self, at: str, *, include: bool = True) -> dict:
        """撤销到 at 会删掉什么。include=True 时连 at 这一刻写入的也删（"撤销这一条及之后"），
        否则保留它（"回到这一条刚做完时"）。confirm 是执行时要带上的核对值。"""
        plan = self._plan(at, include)
        led = self.ws.ledger
        entries = []
        for entry_id, versions in sorted(plan["entries"].items()):
            if entry_id.startswith(("evt_", "rd_")):  # 过程日志与读取记录只计数（counts）
                continue
            e = led.get(entry_id)
            if e is None:
                continue
            entries.append({"id": entry_id, "versions": sorted(versions), "whole": 1 in versions,
                            "label": self.ws.overview.entry_label(e["ref"]) or entry_id,
                            "by": e.get("author_id") or e.get("captured_by") or e.get("promoted_by")
                            or e.get("actor_id")})
        actors: dict[str, int] = {}
        for table in LEDGER_TABLES:
            for r in plan["ledger"].get(table, []):
                who = r.get("actor_id") or r.get("author_id") or r.get("captured_by") or r.get("promoted_by") \
                    or r.get("asserted_by") or "?"
                actors[who] = actors.get(who, 0) + 1
        return {"at": at, "include": include,
                "counts": {t: len(v) for t, v in {**plan["ledger"], **plan["framework"]}.items() if v},
                "entries": entries, "pages_rolled_back": [p["id"] for p in plan["pages_before"]],
                "by_actor": dict(sorted(actors.items(), key=lambda x: -x[1])), "blobs": len(plan["blobs"]),
                "confirm": plan["confirm"],
                "note": "删掉的内容存进数据目录的 undo/ 下，可以用「恢复」放回；巡检记录、agent 运行记录、设置不动。"
                        "框架页回到那时的最后一版，标为输入已变化，需要重新综合"}

    # ---------- 执行 ----------
    def apply(self, actor: Actor, at: str, *, include: bool = True, confirm: str, reason: str = "") -> dict:
        actor.require_human("撤销到某个时刻")
        plan = self._plan(at, include)
        if confirm != plan["confirm"]:
            raise BurrowlError("CONFLICT", "撤销范围与预览时不同（这期间又有写入），请重新预览后再确认", {"at": at})
        if not plan["ledger"] and not plan["framework"]:
            raise BurrowlError("INVALID_ARGUMENT", "这个时刻之后没有写入，不需要撤销", {"at": at})
        undo_id = f"undo_{ulid()}"  # 恢复包编号，不是账本条目
        package = self.root / undo_id
        self._save(package, plan, at=at, include=include, actor=actor, reason=reason)
        db = self.ws.ledger_db
        gate = sorted({r.get("id") or r.get("entry_id") for rows in plan["ledger"].values() for r in rows})
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("PRAGMA secure_delete=ON")
        try:
            db.execute("BEGIN IMMEDIATE")
            try:
                if self._plan(at, include)["confirm"] != confirm:
                    raise BurrowlError("CONFLICT", "撤销范围已变化，请重新预览")
                db.executemany("INSERT INTO purge_gate VALUES (?)", [(i,) for i in gate])
                for table in reversed(LEDGER_TABLES):
                    for r in plan["ledger"].get(table, []):
                        if table in _VERSIONED:
                            db.execute(f"DELETE FROM {table} WHERE id = ? AND version = ?", (r["id"], r["version"]))
                        else:
                            db.execute(f"DELETE FROM {BASE_OF_VIEW.get(table, table)} WHERE id = ?", (r["id"],))
                for r in plan["ledger"].get("entry_objects", []):
                    db.execute("DELETE FROM entry_objects WHERE entry_id = ? AND version = ? AND object = ?",
                               (r["entry_id"], r["version"], r["object"]))
                db.execute("DELETE FROM purge_gate")
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                shutil.rmtree(package, ignore_errors=True)
                raise
        finally:
            db.execute("PRAGMA foreign_keys=ON")
        self._apply_framework(plan)
        for sha in plan["blobs"]:
            self.ws.blobs.path(sha).unlink(missing_ok=True)
        self._reindex(plan)
        for conn in (db, self.ws.framework_db, self.ws.index.conn):
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.ws.purge._cache = None
        counts = {t: len(v) for t, v in {**plan["ledger"], **plan["framework"]}.items() if v}
        self.ws.capture.log(actor, "undo.apply", input={"undo_id": undo_id, "at": at, "include": include,
                                                        "counts": counts, "reason": reason})
        return {"undo_id": undo_id, "package": str(package), "counts": counts, "blobs": len(plan["blobs"]),
                "pages_rolled_back": [p["id"] for p in plan["pages_before"]]}

    # ---------- 恢复 ----------
    def packages(self) -> list[dict]:
        """数据目录里的恢复包（新的在前）。"""
        if not self.root.exists():
            return []
        out = []
        for d in self.root.iterdir():
            m = d / "manifest.json"
            if m.exists():
                info = json.loads(m.read_text(encoding="utf-8"))
                restored = d / "restored.json"
                info["restored"] = json.loads(restored.read_text(encoding="utf-8")) if restored.exists() else None
                out.append(info)
        return sorted(out, key=lambda i: i["created_at"], reverse=True)

    def restore(self, actor: Actor, undo_id: str) -> dict:
        """把一次撤销删掉的内容放回去。撤销之后又写了同一版本（同一条判断的同一版号、同一框架页的同一版）时拒绝。"""
        actor.require_human("恢复撤销")
        if not re.fullmatch(r"undo_[0-9A-Z]+", undo_id):
            raise BurrowlError("INVALID_ARGUMENT", "恢复包编号不对", {"undo_id": undo_id})
        package = self.root / undo_id
        if not (package / "manifest.json").exists():
            raise BurrowlError("NOT_FOUND", "没有这个恢复包", {"undo_id": undo_id})
        if (package / "restored.json").exists():
            raise BurrowlError("CONFLICT", "这个恢复包已经恢复过", {"undo_id": undo_id})
        ledger = {t: _read_jsonl(package / "ledger" / f"{t}.jsonl") for t in (*LEDGER_TABLES, "entry_objects")}
        framework = {t: _read_jsonl(package / "framework" / f"{t}.jsonl")
                     for t in ("entities", "aliases", "pages", "page_versions", "edges", "decisions",
                               "derivation_inputs", "pages_before")}
        clash = self._clashes(ledger, framework)
        if clash:
            raise BurrowlError("CONFLICT", "撤销之后又写入了同一版本，不能直接恢复", {"clashes": clash[:20]})
        db, fw = self.ws.ledger_db, self.ws.framework_db
        with _tx(db):
            for table in (*LEDGER_TABLES, "entry_objects"):
                for r in sorted(ledger[table], key=lambda x: x.get("created_at") or ""):
                    _insert(db, table, r)
        with _tx(fw):
            for table in ("entities", "aliases", "pages", "page_versions", "edges", "decisions", "derivation_inputs"):
                for r in framework[table]:
                    _insert(fw, table, r)
            for r in framework["pages_before"]:
                cols = [c for c in r if c != "id"]
                fw.execute(f"UPDATE pages SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?",
                           [*(r[c] for c in cols), r["id"]])
        blobs = package / "blobs"
        if blobs.exists():
            shutil.copytree(blobs, self.ws.blobs.root, dirs_exist_ok=True)
        entries: dict[str, set] = {}
        for table in _VERSIONED:
            for r in ledger[table]:
                entries.setdefault(r["id"], set()).add(r["version"])
        pages = {r["id"] for r in framework["pages"]} | {r["page_id"] for r in framework["page_versions"]}
        self._reindex({"entries": entries, "pages": pages})
        self.ws.purge._cache = None
        (package / "restored.json").write_text(json.dumps({"at": now(), "by": actor.id}, ensure_ascii=False),
                                               encoding="utf-8")
        counts = {t: len(v) for t, v in {**ledger, **framework}.items() if v}
        self.ws.capture.log(actor, "undo.restore", input={"undo_id": undo_id, "counts": counts})
        return {"undo_id": undo_id, "restored": counts}

    # ---------- 内部 ----------
    def _plan(self, at: str, include: bool) -> dict:
        if not re.fullmatch(r"\d{4}-\d\d-\d\dT[\d:.]+Z?", at or ""):
            raise BurrowlError("INVALID_ARGUMENT", "at 是一条动态的时间（ISO 格式，如 2026-11-13T01:57:05.489Z）",
                               {"at": at})
        op = ">=" if include else ">"
        db, fw = self.ws.ledger_db, self.ws.framework_db
        ledger: dict[str, list[dict]] = {}
        entries: dict[str, set] = {}
        for table in LEDGER_TABLES:
            rows = [dict(r) for r in db.execute(f"SELECT * FROM {table} WHERE created_at {op} ? ORDER BY rowid",
                                                (at,))]
            if rows:
                ledger[table] = rows
            if table in _VERSIONED:
                for r in rows:
                    entries.setdefault(r["id"], set()).add(r["version"])
        objects = []
        for entry_id, versions in entries.items():
            marks = ",".join("?" * len(versions))
            objects += [dict(r) for r in db.execute(
                f"SELECT * FROM entry_objects WHERE entry_id = ? AND version IN ({marks})", (entry_id, *versions))]
        if objects:
            ledger["entry_objects"] = objects
        framework: dict[str, list[dict]] = {}
        for table, _key in _FW_CREATED:
            rows = [dict(r) for r in fw.execute(f"SELECT * FROM {table} WHERE created_at {op} ?", (at,))]
            if rows:
                framework[table] = rows
        new_pages = {r["id"] for r in framework.get("pages", [])}
        versions = [dict(r) for r in fw.execute(f"SELECT * FROM page_versions WHERE created_at {op} ?", (at,))]
        if versions:
            framework["page_versions"] = versions
        rolled = {v["page_id"] for v in versions} - new_pages
        pages_before = [dict(r) for r in fw.execute(
            f"SELECT * FROM pages WHERE id IN ({','.join('?' * len(rolled))})", sorted(rolled))] if rolled else []
        gone_versions = {(v["page_id"], v["version"]) for v in versions}
        gone_edges = {r["id"] for r in framework.get("edges", [])}
        inputs = [dict(r) for r in fw.execute("SELECT * FROM derivation_inputs")
                  if (r["derived_kind"] == "page" and (r["derived_id"], r["derived_version"]) in gone_versions)
                  or (r["derived_kind"] != "page" and r["derived_id"] in gone_edges)]
        if inputs:
            framework["derivation_inputs"] = inputs
        blobs = self._orphan_blobs(ledger)
        fingerprint = sha256_text(json.dumps(
            {"l": {t: [r.get("id") or r.get("entry_id") for r in v] for t, v in ledger.items()},
             "f": {t: sorted(str(r.get("id") or r.get("alias") or r.get("page_id")) + str(r.get("version", ""))
                             for r in v) for t, v in framework.items()}}, sort_keys=True))
        return {"ledger": ledger, "framework": framework, "entries": entries, "pages_before": pages_before,
                "pages": rolled | new_pages, "blobs": blobs, "confirm": fingerprint[:16]}

    def _orphan_blobs(self, ledger: dict[str, list[dict]]) -> list[str]:
        """只被要删的行用到的文件：原件内容、抽取里的嵌入图片与快照、过程日志的长输出。"""
        candidates = {r["sha256"] for r in ledger.get("artifact_versions", []) if r.get("storage") == "managed"}
        for table in ("extractions", "event_versions"):
            for r in ledger.get(table, []):
                candidates |= set(_SHA.findall(r.get("data") or ""))
        gone = {r["id"] for t in ("extractions", "event_versions") for r in ledger.get(t, [])}
        gone_arts = {(r["id"], r["version"]) for r in ledger.get("artifact_versions", [])}
        db = self.ws.ledger_db
        out = []
        for sha in sorted(candidates):
            if not self.ws.blobs.has(sha):
                continue
            used = any((r[0], r[1]) not in gone_arts for r in db.execute(
                "SELECT id, version FROM artifact_versions WHERE sha256 = ?", (sha,)))
            for table in ("extractions", "event_versions"):
                used = used or any(r[0] not in gone for r in db.execute(
                    f"SELECT id FROM {table} WHERE data LIKE ?", (f"%{sha}%",)))
            if not used:
                out.append(sha)
        return out

    def _save(self, package: Path, plan: dict, *, at: str, include: bool, actor: Actor, reason: str) -> None:
        (package / "ledger").mkdir(parents=True)
        (package / "framework").mkdir()
        for table, rows in plan["ledger"].items():
            _write_jsonl(package / "ledger" / f"{table}.jsonl", rows)
        for table, rows in plan["framework"].items():
            _write_jsonl(package / "framework" / f"{table}.jsonl", rows)
        _write_jsonl(package / "framework" / "pages_before.jsonl", plan["pages_before"])
        for sha in plan["blobs"]:
            target = package / "blobs" / "sha256" / sha[:2] / sha[2:]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.ws.blobs.path(sha), target)
        manifest = {"format": "burrowl-undo", "undo_id": package.name, "at": at, "include": include,
                    "created_at": now(), "by": actor.id, "reason": reason, "program_version": __version__,
                    "counts": {t: len(v) for t, v in {**plan["ledger"], **plan["framework"]}.items() if v},
                    "blobs": len(plan["blobs"])}
        (package / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _apply_framework(self, plan: dict) -> None:
        fw = self.ws.framework_db
        fw.execute("PRAGMA secure_delete=ON")
        with _tx(fw):
            for r in plan["framework"].get("derivation_inputs", []):
                fw.execute("DELETE FROM derivation_inputs WHERE derived_kind = ? AND derived_id = ? "
                           "AND derived_version IS ? AND input_id = ?",
                           (r["derived_kind"], r["derived_id"], r["derived_version"], r["input_id"]))
            for r in plan["framework"].get("page_versions", []):
                fw.execute("DELETE FROM page_versions WHERE page_id = ? AND version = ?", (r["page_id"], r["version"]))
            for table, key in _FW_CREATED:
                for r in plan["framework"].get(table, []):
                    fw.execute(f"DELETE FROM {table} WHERE {key} = ?", (r[key],))
            for p in plan["pages_before"]:  # 回到那时的最后一版，标为输入已变化（D-13）
                last = fw.execute("SELECT version, data FROM page_versions WHERE page_id = ? ORDER BY version DESC "
                                  "LIMIT 1", (p["id"],)).fetchone()
                if last is None:
                    fw.execute("DELETE FROM pages WHERE id = ?", (p["id"],))
                    continue
                title = (json.loads(last[1] or "{}") or {}).get("title") or p["title"]
                fw.execute("UPDATE pages SET head_version = ?, title = ?, freshness = 'inputs_changed', "
                           "updated_at = ? WHERE id = ?", (last[0], title, now(), p["id"]))
            gone = {e for e, versions in plan["entries"].items() if not self._exists(e)}
            for e in gone:  # 主体整条被删的待决策
                fw.execute("DELETE FROM decisions WHERE subject_id = ?", (e,))

    def _exists(self, entry_id: str) -> bool:
        return self.ws.ledger.get(entry_id) is not None

    def _reindex(self, plan: dict) -> None:
        for entry_id in plan["entries"]:
            kind = _INDEX_KIND.get(entry_id.split("_", 1)[0])
            if kind is None:
                continue
            if self._exists(entry_id):
                self.ws._index_one(kind, entry_id)
            else:
                self.ws.index.remove(entry_id)
        for page_id in plan["pages"]:
            if self.ws.framework.page(page_id):
                self.ws._index_one("pages", page_id)
            else:
                self.ws.index.remove(page_id)

    def _clashes(self, ledger: dict, framework: dict) -> list[str]:
        db, fw = self.ws.ledger_db, self.ws.framework_db
        out = []
        for table in _VERSIONED:
            for r in ledger[table]:
                hit = db.execute(f"SELECT 1 FROM {table} WHERE id = ? AND version = ?", (r["id"], r["version"]))
                if hit.fetchone():
                    out.append(f"{r['id']}@{r['version']}")
        for r in framework["page_versions"]:
            if fw.execute("SELECT 1 FROM page_versions WHERE page_id = ? AND version = ?",
                          (r["page_id"], r["version"])).fetchone():
                out.append(f"{r['page_id']}@{r['version']}")
        return out


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _insert(conn, table: str, row: dict) -> None:
    columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    item = {k: v for k, v in row.items() if k in columns}
    conn.execute(f"INSERT OR IGNORE INTO {table} ({','.join(item)}) VALUES ({','.join('?' * len(item))})",
                 list(item.values()))
