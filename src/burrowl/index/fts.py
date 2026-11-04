"""全文索引：FTS5 trigram 分词（中文可用）。查询不足 3 个字时 trigram 无法匹配，退回 LIKE。

每行记下来源条目与版本。条目被改写（只有框架页会改写）时先删旧行再写新行，
检索结果还会在服务层与当前版本核对，避免旧索引残留（草图 §12.1）。
"""
import re
import sqlite3
from dataclasses import dataclass

from ..core.sql import transaction


@dataclass
class Hit:
    entry_id: str
    version: int
    layer: str
    ordinal: int
    locator: str
    text: str
    score: float


class Index:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def replace(self, entry_id: str, version: int, layer: str, parts: list[tuple[int, str, str, str]]) -> None:
        """parts: (序号, 定位, sha256, 文本)。替换该条目已有的全部索引行。"""
        with transaction(self.conn):
            self.conn.execute("DELETE FROM docs WHERE entry_id = ?", (entry_id,))
            self.conn.executemany(
                "INSERT INTO docs (entry_id, version, layer, ordinal, locator, sha256, text) VALUES (?,?,?,?,?,?,?)",
                [(entry_id, version, layer, o, loc, sha, text) for o, loc, sha, text in parts if text.strip()],
            )

    def remove(self, entry_id: str) -> None:
        with transaction(self.conn):
            self.conn.execute("DELETE FROM docs WHERE entry_id = ?", (entry_id,))

    def search(self, query: str, *, layers: list[str] | None = None, limit: int = 50) -> list[Hit]:
        terms = [t for t in re.split(r"\s+", query.strip()) if t]
        if not terms:
            return []
        layer_sql, params = "", []
        if layers:
            layer_sql = f" AND d.layer IN ({','.join('?' * len(layers))})"
            params = list(layers)
        if all(len(t) >= 3 for t in terms):
            match = " AND ".join('"' + t.replace('"', '""') + '"' for t in terms)
            sql = ("SELECT d.*, bm25(docs_fts) AS score FROM docs_fts JOIN docs d ON d.rowid = docs_fts.rowid "
                   f"WHERE docs_fts MATCH ?{layer_sql} ORDER BY score LIMIT ?")
            rs = self.conn.execute(sql, [match, *params, limit]).fetchall()
        else:
            like = " AND ".join("d.text LIKE ?" for _ in terms)
            sql = f"SELECT d.*, 0.0 AS score FROM docs d WHERE {like}{layer_sql} LIMIT ?"
            rs = self.conn.execute(sql, [*(f"%{t}%" for t in terms), *params, limit]).fetchall()
        return [Hit(r["entry_id"], r["version"], r["layer"], r["ordinal"], r["locator"], r["text"], r["score"])
                for r in rs]

    def segments(self, entry_id: str) -> list[dict]:
        rs = self.conn.execute("SELECT ordinal, locator, sha256, text FROM docs WHERE entry_id = ? ORDER BY ordinal",
                               (entry_id,)).fetchall()
        return [dict(r) for r in rs]

    def clear(self) -> None:
        with transaction(self.conn):
            self.conn.execute("DELETE FROM docs")
