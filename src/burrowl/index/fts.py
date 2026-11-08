"""检索索引（index.sqlite，随时可删除重建）。

两张表（设计稿 06 D-01、D-06）：
- `docs`：引用段落，FTS5 trigram（中文可用）。用于短语召回与 `search_exact` 的字面查找。
- `units`：检索单元（相邻段落合并），预先切词（中文双字 + 英文标识符）后进 FTS5 unicode61，
  查询用 OR 连接、bm25 排序：部分命中也能召回，命中越多排得越前。

每行记下来源条目与版本。条目被改写（只有框架页会改写）时先删旧行再写新行，
检索结果还会在服务层与当前版本核对，避免旧索引残留（草图 §12.1）。
向量缓存 `vectors` 按内容指纹存放，`clear` 不删（设计稿 06 D-07）。
"""
import json
import re
import sqlite3
from dataclasses import dataclass

from ..core.clock import now
from ..core.hashing import sha256_text
from ..core.sql import transaction
from .tokenize import fts_document, fts_query
from .units import Unit


@dataclass
class Hit:
    entry_id: str
    version: int
    layer: str
    ordinal: int
    locator: str
    text: str
    score: float


@dataclass
class UnitHit:
    rowid: int
    entry_id: str
    version: int
    layer: str
    ordinal: int
    anchors: list[str]
    scopes: list[str]
    context: str
    text: str
    key: str
    score: float


def unit_key(context: str, text: str) -> str:
    return sha256_text(context + "\n\n" + text)


class Index:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.generation = 0  # 本进程内的写入计数：向量矩阵的缓存用它判断是否过期

    # ---------- 写入 ----------
    def replace(self, entry_id: str, version: int, layer: str, parts: list[tuple[int, str, str, str]],
                units: list[Unit] | None = None) -> None:
        """parts：(序号, 定位, sha256, 文本) 的引用段落；units：检索单元。替换该条目已有的全部索引行。"""
        with transaction(self.conn):
            self.conn.execute("DELETE FROM docs WHERE entry_id = ?", (entry_id,))
            self.conn.execute("DELETE FROM units WHERE entry_id = ?", (entry_id,))
            self.conn.executemany(
                "INSERT INTO docs (entry_id, version, layer, ordinal, locator, sha256, text) VALUES (?,?,?,?,?,?,?)",
                [(entry_id, version, layer, o, loc, sha, text) for o, loc, sha, text in parts if text.strip()],
            )
            self.conn.executemany(
                "INSERT INTO units (entry_id, version, layer, ordinal, anchors, scopes, context, text, tokens, key) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(entry_id, version, layer, u.ordinal, json.dumps(u.anchors), json.dumps(u.units), u.context, u.text,
                  fts_document(u.context + "\n" + u.text), unit_key(u.context, u.text)) for u in units or []],
            )
        self.generation += 1

    def remove(self, entry_id: str) -> None:
        with transaction(self.conn):
            self.conn.execute("DELETE FROM docs WHERE entry_id = ?", (entry_id,))
            self.conn.execute("DELETE FROM units WHERE entry_id = ?", (entry_id,))
        self.generation += 1

    def clear(self) -> None:
        with transaction(self.conn):
            self.conn.execute("DELETE FROM docs")
            self.conn.execute("DELETE FROM units")
        self.generation += 1

    # ---------- 检索单元：词法主路 ----------
    def search_units(self, query: str, *, layers: list[str] | None = None, limit: int = 100) -> list[UnitHit]:
        match = fts_query(query)
        if not match:
            return []
        layer_sql, params = _layers(layers, "u")
        sql = ("SELECT u.*, bm25(units_fts) AS score FROM units_fts JOIN units u ON u.rowid = units_fts.rowid "
               f"WHERE units_fts MATCH ?{layer_sql} ORDER BY score LIMIT ?")
        return [_unit(r) for r in self.conn.execute(sql, [match, *params, limit])]

    def units_by_rowid(self, rowids: list[int]) -> list[UnitHit]:
        if not rowids:
            return []
        rs = self.conn.execute(f"SELECT u.*, 0.0 AS score FROM units u WHERE rowid IN ({','.join('?' * len(rowids))})",
                               rowids)
        by = {r["rowid"]: _unit(r) for r in rs}
        return [by[i] for i in rowids if i in by]

    def units_of(self, entry_id: str) -> list[UnitHit]:
        rs = self.conn.execute("SELECT u.*, 0.0 AS score FROM units u WHERE entry_id = ? ORDER BY ordinal", (entry_id,))
        return [_unit(r) for r in rs]

    def unit_of_anchor(self, entry_id: str, anchor: str) -> UnitHit | None:
        r = self.conn.execute("SELECT u.*, 0.0 AS score FROM units u WHERE entry_id = ? AND anchors LIKE ? "
                              "ORDER BY ordinal LIMIT 1", (entry_id, f'%"{anchor}"%')).fetchone()
        return _unit(r) if r else None

    def unit_counts(self, entry_ids: list[str]) -> dict[str, int]:
        if not entry_ids:
            return {}
        rs = self.conn.execute(f"SELECT entry_id, COUNT(*) FROM units WHERE entry_id IN "
                               f"({','.join('?' * len(entry_ids))}) GROUP BY entry_id", entry_ids)
        return {r[0]: r[1] for r in rs}

    def all_units(self, layers: list[str] | None = None) -> list[tuple[int, str, str, str]]:
        """(rowid, entry_id, layer, key)，给向量矩阵用。"""
        layer_sql, params = _layers(layers, "units", where=True)
        return [tuple(r) for r in self.conn.execute(f"SELECT rowid, entry_id, layer, key FROM units{layer_sql}",
                                                    params)]

    # ---------- 引用段落：短语路与字面查找 ----------
    def search_phrase(self, phrase: str, *, layers: list[str] | None = None, limit: int = 50) -> list[Hit]:
        """整个查询作为一个短语出现的段落（至少 3 个字，trigram 才能匹配）。"""
        phrase = phrase.strip()
        if len(phrase) < 3:
            return []
        layer_sql, params = _layers(layers, "d")
        sql = ("SELECT d.*, bm25(docs_fts) AS score FROM docs_fts JOIN docs d ON d.rowid = docs_fts.rowid "
               f"WHERE docs_fts MATCH ?{layer_sql} ORDER BY score LIMIT ?")
        return [_hit(r) for r in self.conn.execute(sql, ['"' + phrase.replace('"', '""') + '"', *params, limit])]

    def exact(self, text: str, *, layers: list[str] | None = None, limit: int = 200) -> list[Hit]:
        """字面查找（不分词、不排序，按条目与段落顺序）。不区分大小写；不足 3 个字时用 LIKE。"""
        text = text.strip()
        if not text:
            return []
        layer_sql, params = _layers(layers, "d")
        if len(text) >= 3:
            sql = ("SELECT d.*, 0.0 AS score FROM docs_fts JOIN docs d ON d.rowid = docs_fts.rowid "
                   f"WHERE docs_fts MATCH ? AND instr(lower(d.text), lower(?)) > 0{layer_sql} "
                   "ORDER BY d.entry_id, d.ordinal LIMIT ?")
            args = ['"' + text.replace('"', '""') + '"', text, *params, limit]
        else:
            sql = (f"SELECT d.*, 0.0 AS score FROM docs d WHERE d.text LIKE ?{layer_sql} "
                   "ORDER BY d.entry_id, d.ordinal LIMIT ?")
            args = [f"%{text}%", *params, limit]
        return [_hit(r) for r in self.conn.execute(sql, args)]

    def segments(self, entry_id: str) -> list[dict]:
        rs = self.conn.execute("SELECT ordinal, locator, sha256, text FROM docs WHERE entry_id = ? ORDER BY ordinal",
                               (entry_id,)).fetchall()
        return [dict(r) for r in rs]

    def search(self, query: str, *, layers: list[str] | None = None, limit: int = 50) -> list[Hit]:
        """旧接口（2.0.0a12 及以前）：段落级 trigram，全部词都要命中。检索服务已改用 search_units。"""
        terms = [t for t in re.split(r"\s+", query.strip()) if t]
        if not terms:
            return []
        layer_sql, params = _layers(layers, "d")
        if all(len(t) >= 3 for t in terms):
            match = " AND ".join('"' + t.replace('"', '""') + '"' for t in terms)
            sql = ("SELECT d.*, bm25(docs_fts) AS score FROM docs_fts JOIN docs d ON d.rowid = docs_fts.rowid "
                   f"WHERE docs_fts MATCH ?{layer_sql} ORDER BY score LIMIT ?")
            rs = self.conn.execute(sql, [match, *params, limit]).fetchall()
        else:
            like = " AND ".join("d.text LIKE ?" for _ in terms)
            sql = f"SELECT d.*, 0.0 AS score FROM docs d WHERE {like}{layer_sql} LIMIT ?"
            rs = self.conn.execute(sql, [*(f"%{t}%" for t in terms), *params, limit]).fetchall()
        return [_hit(r) for r in rs]

    # ---------- 向量缓存 ----------
    def vectors(self, keys: list[str], model: str) -> dict[str, bytes]:
        out: dict[str, bytes] = {}
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            rs = self.conn.execute(f"SELECT key, vec FROM vectors WHERE model = ? AND key IN "
                                   f"({','.join('?' * len(chunk))})", [model, *chunk])
            out.update({r[0]: r[1] for r in rs})
        return out

    def put_vectors(self, model: str, dim: int, items: list[tuple[str, bytes]]) -> None:
        with transaction(self.conn):
            self.conn.executemany(
                "INSERT OR REPLACE INTO vectors (key, model, dim, vec, created_at) VALUES (?,?,?,?,?)",
                [(k, model, dim, v, now()) for k, v in items])
        self.generation += 1

    def missing_vector_keys(self, model: str, limit: int | None = None) -> list[tuple[str, str, str]]:
        """还没有向量的检索单元：(key, context, text)，同一内容只出现一次。"""
        sql = ("SELECT u.key, MIN(u.context), MIN(u.text) FROM units u LEFT JOIN vectors v "
               "ON v.key = u.key AND v.model = ? WHERE v.key IS NULL GROUP BY u.key")
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [tuple(r) for r in self.conn.execute(sql, (model,))]

    def vector_coverage(self, model: str) -> tuple[int, int]:
        total = self.conn.execute("SELECT COUNT(DISTINCT key) FROM units").fetchone()[0]
        done = self.conn.execute("SELECT COUNT(DISTINCT u.key) FROM units u JOIN vectors v ON v.key = u.key "
                                 "AND v.model = ?", (model,)).fetchone()[0]
        return done, total

    def data_version(self) -> int:
        """其他连接（例如另一个进程）提交后会变；与 generation 一起判断向量矩阵是否过期。"""
        return self.conn.execute("PRAGMA data_version").fetchone()[0]


def _layers(layers: list[str] | None, alias: str, *, where: bool = False) -> tuple[str, list]:
    if not layers:
        return "", []
    col = f"{alias}.layer" if not where else "layer"
    return f"{' WHERE' if where else ' AND'} {col} IN ({','.join('?' * len(layers))})", list(layers)


def _unit(r) -> UnitHit:
    return UnitHit(r["rowid"], r["entry_id"], r["version"], r["layer"], r["ordinal"], json.loads(r["anchors"]),
                   json.loads(r["scopes"]), r["context"], r["text"], r["key"], r["score"])


def _hit(r) -> Hit:
    return Hit(r["entry_id"], r["version"], r["layer"], r["ordinal"], r["locator"], r["text"], r["score"])
