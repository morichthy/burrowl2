"""坐标的内存图（设计稿 10 G 组 D-30 至 D-37）：由账本与框架库派生的完整图，推出规则（services/coordinates.py）只读它。

- 不落盘、不能修改，账本仍是唯一权威；进程里第一次用到时扫账本建好，丢掉随时重建。
- 账本只追加：之后按各表的 rowid 把新增行合进来（D-33）。发现某表的行数不等于"已读 + 新增"，或已读的最后一行
  ID 变了（彻底删除；SQLite 可能重用最大的 rowid），就从账本整图重建。彻底删除不留记录，只能这样发现。
- 框架库可修改（UPDATE、DELETE）：它有变化时整层重读（D-34）。框架层只给框架页、边、实体的坐标与以后的关系图用，
  不参与判断与原件的坐标（I2）。
- 发现写入：本连接的 total_changes（自己写的）+ PRAGMA data_version（别的连接、别的进程提交的）。
- 字段声明（D-37）：图上每种节点只暴露 NODE_FIELDS 里声明的字段（StrictNode），读未声明的字段直接报错。
  读图的有两处：推出规则（coordinates.READS）与关系图（overview.GRAPH_VIEW_READS，D-38）；测试要求声明的并集
  正好等于这里暴露的。用到新字段时，必须先在这里声明并从账本取到，否则测试失败，而不是悄悄算错。
- 原件的分段（待复核、识别状态要用）来自抽取层的分段缓存（ExtractionService，按指纹失效）；外部文本原件
  每次现查（磁盘文件可能被改而账本不变，D-35）。
"""
import json
import threading
from collections import defaultdict

from ..core.errors import BurrowlError
from ..core.ids import PREFIXES, make_ref
from . import extractors as ex

# 账本表 → 节点种类。版本表的每一行是条目的一个版本
LEDGER_TABLES = ("artifact_versions", "event_versions", "record_versions", "read_versions", "judgment_versions",
                 "relations", "version_states", "reviews", "replacements", "extractions")
VERSION_TABLES = {"artifact_versions": "art", "event_versions": "evt", "record_versions": "rec",
                  "read_versions": "rd", "judgment_versions": "jdg"}

# 图上每种节点暴露的字段（D-37）。"data" 下的键在 DATA_FIELDS 单独声明
_ENTRY_COMPUTED = {"ref", "head_version", "entry_kind", "author"}
# 各种条目都可能被问到、没有就是 None 的字段（推出规则对任何被引条目都会试着取它们）
PROBES = {"artifact_id", "event_id", "session_id"}
NODE_FIELDS: dict[str, set[str]] = {
    "artifact": {"id", "version", "created_at", "source_class", "storage", "sha256", "data", "session_id",
                 "format"} | _ENTRY_COMPUTED | PROBES,
    "event": {"id", "version", "created_at", "session_id", "data"} | _ENTRY_COMPUTED | PROBES,
    "record": {"id", "version", "created_at", "event_id", "artifact_id", "boundary", "data"} | _ENTRY_COMPUTED | PROBES,
    "read": {"id", "version", "created_at", "artifact_id", "artifact_version", "session_id", "data"}
    | _ENTRY_COMPUTED | PROBES,
    "judgment": {"id", "version", "created_at", "kind", "author_kind", "session_id", "data"} | _ENTRY_COMPUTED | PROBES,
    "relation": {"id", "predicate", "label", "subject_id", "subject_version", "object_id", "object_version",
                 "object_anchor", "asserted_by", "session_id", "created_at", "qualifiers", "subject", "object"},
    "version_state": {"id", "entry_id", "version", "action", "created_at", "actor_id", "data"},
    "review": {"id", "target_id", "target_version", "method", "verdict", "created_at", "data"},
    "replacement": {"id", "old_id", "new_id", "created_at"},
    "extraction": {"id", "artifact_id", "artifact_sha256", "kind", "unit", "created_at"},
    "page": {"id", "type", "head_version", "freshness", "review", "subject_id", "updated_at"},
    "page_version": {"page_id", "version", "author_id"},
    "edge": {"id", "rel", "src_id", "dst_id", "origin", "review", "freshness", "created_at"},
    "entity": {"id", "kind", "name", "user_marked"},
}
DATA_FIELDS: dict[str, set[str]] = {
    "artifact": {"external_tier", "path"},
    "event": {"source_class"},
    "record": set(),
    "read": {"anchors", "segment_sha256"},
    "judgment": {"external_author", "conditions", "scope_unclear", "local_observation", "text"},
    "version_state": {"reason", "replaced_by"},
    "review": {"revokes", "revoked_rel_id", "version", "cites", "local_observation", "anchor", "part",
               "extraction_id"},
}
# 不是账本列、由建图算出的字段（核对来源时跳过）
COMPUTED = _ENTRY_COMPUTED | {"format", "subject", "object"}
# 节点种类 → 来源表（核对"声明的字段在表里有列"，D-37）
SOURCE_TABLE = {"artifact": "artifact_versions", "event": "event_versions", "record": "record_versions",
                "read": "read_versions", "judgment": "judgment_versions", "relation": "relations",
                "version_state": "version_states", "review": "reviews", "replacement": "replacements",
                "extraction": "extractions"}
FRAMEWORK_TABLE = {"page": "pages", "page_version": "page_versions", "edge": "edges", "entity": "entities"}


def author_of(entry: dict) -> str:
    """一版条目的最终作者：人 / AI / 系统（判断有 author_kind，过程日志有 actor_kind，其余按写入者 ID 的前缀）。"""
    if entry.get("author_kind") or entry.get("actor_kind"):
        return entry.get("author_kind") or entry.get("actor_kind")
    who = entry.get("captured_by") or entry.get("actor_id") or entry.get("promoted_by") or ""
    return kind_of_actor(who)


def kind_of_actor(who: str) -> str:
    if who.startswith("human"):
        return "human"
    if who.startswith("ai"):
        return "ai"
    return "system"


class StrictNode(dict):
    """只暴露声明过的字段：读未声明的键报错（D-37）。值缺失时 get 照常给默认值。"""
    __slots__ = ("_kind", "_allowed")

    def __init__(self, kind: str, allowed: set[str], values: dict):
        super().__init__(values)
        self._kind, self._allowed = kind, allowed

    def _check(self, key):
        if key not in self._allowed:
            raise KeyError(f"图上的 {self._kind} 节点没有声明字段 {key!r}：先在 services/graph.py 的 NODE_FIELDS / "
                           "DATA_FIELDS 声明并从账本取到（设计稿 10 D-37）")

    def __getitem__(self, key):
        self._check(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._check(key)
        return super().get(key, default)

    def __contains__(self, key):
        self._check(key)
        return super().__contains__(key)

    def __reduce__(self):
        return (dict, (dict(self),))


def _node(kind: str, raw: dict) -> StrictNode:
    allowed = NODE_FIELDS[kind]
    values = {k: v for k, v in raw.items() if k in allowed}
    if "data" in allowed:
        data = raw.get("data") or {}
        if isinstance(data, str):
            data = json.loads(data)
        dkind = kind
        values["data"] = StrictNode(f"{dkind}.data", DATA_FIELDS.get(dkind, set()),
                                    {k: v for k, v in data.items() if k in DATA_FIELDS.get(dkind, set())})
    return StrictNode(kind, allowed, values)


class _TableCursor:
    __slots__ = ("count", "last_rowid", "last_id")

    def __init__(self):
        self.count, self.last_rowid, self.last_id = 0, 0, None


class LedgerGraph:
    """见模块说明。读接口给推出规则用；节点是只读的 StrictNode。"""

    def __init__(self, ws):
        self.ws = ws
        self.lock = threading.RLock()
        self.generation = 0          # 每次图有变化（合并了新行、整图重建、框架层重读）加一
        self.rebuilds = 0            # 整图重建的次数（测试与统计用）
        self._stamp: tuple | None = None
        self._built = False
        self._fw_stamp: tuple | None = None
        self._segments: dict[tuple, tuple] = {}
        self._reset()

    # ---------- 同步 ----------
    def _reset(self) -> None:
        self._cursors = {t: _TableCursor() for t in LEDGER_TABLES}
        self.versions: dict[str, list[StrictNode]] = {}          # 条目 → 各版本（下标 = 版本 - 1）
        self.rel_by_subject: dict[str, list[StrictNode]] = defaultdict(list)
        self.rel_by_object: dict[str, list[StrictNode]] = defaultdict(list)
        self.relations: dict[str, StrictNode] = {}
        self.revoked_rels: set[str] = set()                     # 复核撤销的 opposes / supersedes
        self.states: dict[str, list[StrictNode]] = defaultdict(list)   # 条目 → 处置（按写入顺序）
        self.reviews: dict[str, list[tuple]] = defaultdict(list)        # 对象 → [(created_at, rowid, 节点)]
        self.replacements: dict[str, list[StrictNode]] = defaultdict(list)
        self.extractions: dict[str, list[tuple]] = defaultdict(list)    # 原件 → [(created_at, id, 节点)]
        self._segments = {}

    def sync(self) -> int:
        """把账本与框架库的新变化合进图，返回当前代数。没有变化时只读两个计数。"""
        led, fw = self.ws.ledger_db, self.ws.framework_db
        with self.lock:
            stamp = (led.total_changes, led.execute("PRAGMA data_version").fetchone()[0])
            if stamp != self._stamp:
                if not self._built or not self._merge():
                    self._rebuild()
                    self._built = True
                # 在事务里合进来的行可能被回滚：下一次照样核对（回滚的行不在了，最后一行 ID 对不上，整图重建）
                self._stamp = ("recheck",) if led.in_transaction else \
                    (led.total_changes, led.execute("PRAGMA data_version").fetchone()[0])
            fw_stamp = (fw.total_changes, fw.execute("PRAGMA data_version").fetchone()[0])
            if fw_stamp != self._fw_stamp:
                self._load_framework()
                self._fw_stamp = (fw.total_changes, fw.execute("PRAGMA data_version").fetchone()[0])
                self.generation += 1
            return self.generation

    def _rebuild(self) -> None:
        self._reset()
        self.rebuilds += 1
        if not self._merge():
            raise RuntimeError("账本在整图重建时又被删除了行")  # 不会发生：重建从空图开始

    def _merge(self) -> bool:
        """读各表新增的行；发现删除时返回 False（调用方整图重建）。在一个读事务里读，各表互相一致。"""
        conn = self.ws.ledger_db
        own = not conn.in_transaction
        if own:
            conn.execute("BEGIN")
        try:
            fresh: dict[str, list[dict]] = {}
            for table in LEDGER_TABLES:
                cur = self._cursors[table]
                if cur.last_id is not None:
                    at = conn.execute(f"SELECT id FROM {table} WHERE rowid = ?", (cur.last_rowid,)).fetchone()
                    if at is None or at[0] != cur.last_id:
                        return False
                cols = "rowid AS _rowid, *"
                rows = [dict(r) for r in conn.execute(
                    f"SELECT {cols} FROM {table} WHERE rowid > ? ORDER BY rowid", (cur.last_rowid,))]
                total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if total != cur.count + len(rows):
                    return False
                fresh[table] = rows
        finally:
            if own:
                conn.execute("COMMIT")
        changed = False
        for table in LEDGER_TABLES:  # 版本表在前：关系、处置引用的条目已经在图上
            for r in fresh[table]:
                self._add(table, r)
                changed = True
            if fresh[table]:
                cur = self._cursors[table]
                cur.count += len(fresh[table])
                cur.last_rowid, cur.last_id = fresh[table][-1]["_rowid"], fresh[table][-1]["id"]
        if changed:
            self.generation += 1
            self._segments = {}
        return True

    def _add(self, table: str, r: dict) -> None:
        if table in VERSION_TABLES:
            prefix = VERSION_TABLES[table]
            kind = PREFIXES[prefix]
            raw = {**r, "entry_kind": kind, "ref": make_ref(r["id"], r["version"]), "author": author_of(r)}
            if kind == "artifact":
                data = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
                raw["format"] = ex.format_of({"data": data})
            versions = self.versions.setdefault(r["id"], [])
            while len(versions) < r["version"]:
                versions.append(None)
            versions[r["version"] - 1] = _node(kind, raw)
        elif table == "relations":
            raw = {**r, "qualifiers": json.loads(r["qualifiers"]) if isinstance(r["qualifiers"], str)
                   else r["qualifiers"],
                   "subject": make_ref(r["subject_id"], r["subject_version"]),
                   "object": make_ref(r["object_id"], r["object_version"], r["object_anchor"] or "")}
            rel = _node("relation", raw)
            self.relations[rel["id"]] = rel
            self.rel_by_subject[rel["subject_id"]].append(rel)
            self.rel_by_object[rel["object_id"]].append(rel)
        elif table == "version_states":
            self.states[r["entry_id"]].append(_node("version_state", r))
        elif table == "reviews":
            node = _node("review", r)
            if node["data"].get("revoked_rel_id"):
                self.revoked_rels.add(node["data"]["revoked_rel_id"])
            rows = self.reviews[r["target_id"]]
            key = (r["created_at"], r["_rowid"])
            if rows and rows[-1][:2] > key:  # 时间早于已有的（时钟回拨）：按 (created_at, rowid) 插入
                import bisect  # noqa: PLC0415
                bisect.insort(rows, (*key, node), key=lambda x: x[:2])
            else:
                rows.append((*key, node))
        elif table == "replacements":
            self.replacements[r["old_id"]].append(_node("replacement", r))
        elif table == "extractions":
            rows = self.extractions[r["artifact_id"]]
            node = _node("extraction", r)
            key = (r["created_at"], r["id"])
            if rows and rows[-1][:2] > key:
                import bisect  # noqa: PLC0415
                bisect.insort(rows, (*key, node), key=lambda x: x[:2])
            else:
                rows.append((*key, node))

    def _load_framework(self) -> None:
        fw = self.ws.framework_db
        self.pages = {r["id"]: _node("page", dict(r)) for r in fw.execute(  # 顺序同 Framework.pages()
            "SELECT id, type, head_version, freshness, review, subject_id, updated_at FROM pages "
            "ORDER BY updated_at DESC")}
        self.page_versions = {(r["page_id"], r["version"]): _node("page_version", dict(r)) for r in fw.execute(
            "SELECT page_id, version, author_id FROM page_versions")}
        self.edges = {r["id"]: _node("edge", dict(r)) for r in fw.execute(  # 顺序同 Framework.edges()
            "SELECT id, rel, src_id, dst_id, origin, review, freshness, created_at FROM edges ORDER BY created_at")}
        self.entities = {r["id"]: _node("entity", dict(r)) for r in fw.execute(
            "SELECT id, kind, name, user_marked FROM entities")}
        self.inputs: dict[tuple[str, str, int], list[str]] = defaultdict(list)
        for r in fw.execute("SELECT * FROM derivation_inputs"):  # 顺序同 Framework.inputs_of()（不排序）
            self.inputs[(r["derived_kind"], r["derived_id"], r["derived_version"])].append(r["input_id"])

    # ---------- 读：条目 ----------
    def entry(self, entry_id: str, version: int | None = None) -> StrictNode | None:
        """条目某一版（不给版本取当前版），带 head_version；没有时为 None。"""
        versions = self.versions.get(entry_id)
        if not versions:
            return None
        head = len(versions)
        node = versions[(version or head) - 1] if (version or head) <= head else None
        if node is None:
            return None
        if node.get("head_version") != head:  # 当前版号随新版本变化：读时补上
            dict.__setitem__(node, "head_version", head)
        return node

    def head_version(self, entry_id: str) -> int | None:
        versions = self.versions.get(entry_id)
        return len(versions) if versions else None

    def ids(self, prefix: str) -> list[str]:
        return [i for i in self.versions if i.startswith(prefix + "_")]

    # ---------- 读：关系与处置 ----------
    def _effective(self, rel: StrictNode) -> bool:
        return rel["predicate"] not in ("opposes", "supersedes") or rel["id"] not in self.revoked_rels

    def relations_from(self, subject_id: str, predicate: str | None = None, *,
                       version: int | None = None) -> list[StrictNode]:
        return [r for r in self.rel_by_subject.get(subject_id, ())
                if (predicate is None or r["predicate"] == predicate)
                and (version is None or r["subject_version"] == version) and self._effective(r)]

    def relations_to(self, object_id: str, predicate: str | None = None) -> list[StrictNode]:
        return [r for r in self.rel_by_object.get(object_id, ())
                if (predicate is None or r["predicate"] == predicate) and self._effective(r)]

    def all_relations(self, predicate: str | None = None) -> list[StrictNode]:
        return [r for r in self.relations.values()
                if (predicate is None or r["predicate"] == predicate) and self._effective(r)]

    def version_states(self, entry_id: str, version: int) -> list[StrictNode]:
        return [s for s in self.states.get(entry_id, ()) if s["version"] == version]

    def state_entries(self) -> list[str]:
        return list(self.states)

    def review_rows(self, target_id: str) -> list[StrictNode]:
        return [x[2] for x in self.reviews.get(target_id, ())]

    def last_replacement(self, old_id: str) -> StrictNode | None:
        rows = self.replacements.get(old_id)
        return rows[-1] if rows else None

    def extraction_rows(self, artifact_id: str, kind: str, sha: str, unit: str | None = None) -> list[StrictNode]:
        return [x[2] for x in self.extractions.get(artifact_id, ())
                if x[2]["kind"] == kind and x[2]["artifact_sha256"] == sha and (unit is None or x[2]["unit"] == unit)]

    # ---------- 读：原件分段（来自抽取层的分段缓存） ----------
    def segment_info(self, artifact_id: str) -> tuple[frozenset, dict, frozenset] | None:
        """原件当前版的 (段落指纹集合, 锚点 → 段落, 带 AI LaTeX 的块)；读不出时三项为空。原件不存在时为 None。
        每一代只取一次；外部文本原件每次现查（D-35）。"""
        node = self.entry(artifact_id)
        if node is None:
            return None
        external_text = node["format"] == "text" and node["storage"] != "managed"
        key = (artifact_id, node["version"])
        if not external_text and key in self._segments:
            return self._segments[key]
        raw = self.ws.ledger.get(artifact_id)  # 抽取层要原件的完整一行（路径、指纹）
        try:
            ext = self.ws.extraction
            with ext.pinned(raw):
                entry = ext._entry(raw)
            info = (frozenset(s["sha256"] for s in entry.segments), entry.by_anchor, entry.low_latex)
        except BurrowlError:
            info = (frozenset(), {}, frozenset())
        if not external_text:
            self._segments[key] = info
        return info

    # ---------- 统计 ----------
    def stats(self) -> dict:
        return {"generation": self.generation, "rebuilds": self.rebuilds,
                "entries": len(self.versions), "versions": sum(len(v) for v in self.versions.values()),
                "relations": len(self.relations),
                "rows": {t: c.count for t, c in self._cursors.items()},
                "framework": {"pages": len(getattr(self, "pages", {})), "edges": len(getattr(self, "edges", {})),
                              "entities": len(getattr(self, "entities", {}))}}
