"""SQLite 事务辅助。store 与 index 互不导入，共用的辅助放在 core。"""
import sqlite3
from contextlib import contextmanager


@contextmanager
def transaction(conn: sqlite3.Connection):
    if conn.in_transaction:  # 嵌套调用并入外层事务
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
