"""SQLite ↔ PostgreSQL 相容層（讓兩個 App 一套程式碼跑兩種資料庫）。

* 本機開發與測試：用 SQLite（零設定、免安裝伺服器）。
* 雲端部署：設了 `DATABASE_URL` 就改用 Postgres（如 Supabase）；
  設了 `DB_SCHEMA` 就把所有表放進那個 schema（多 App 共用同一個 Postgres 實例）。
  資料才會跨重啟/重新部署永久保存，並更適合多人同時寫入。

環境變數：
  DATABASE_URL   postgresql://user:pass@host:port/dbname   （不設 → 用 SQLite）
  DB_SCHEMA      salesapp | stocktake                      （不設 → 用 public schema）
"""

from __future__ import annotations

import os
import re

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB_SCHEMA    = os.environ.get("DB_SCHEMA", "").strip()
IS_PG        = DATABASE_URL.startswith(("postgres://", "postgresql://"))

_AUTOINC = re.compile(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", re.IGNORECASE)


def _to_pg_ddl(sql: str) -> str:
    """把 SQLite 建表語法轉成 Postgres 可用的語法。"""
    return _AUTOINC.sub("SERIAL PRIMARY KEY", sql)


class _PgCursor:
    """包一層 psycopg2 cursor，對齊 sqlite3.Cursor 常用介面。"""

    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def lastrowid(self):
        # 僅作防呆；正常情況請用 lastid() helper
        return None

    def __iter__(self):
        return iter(self._cur.fetchall())


class _PgConn:
    """包一層 psycopg2 connection，對齊 sqlite3.Connection 常用介面。"""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params=()):
        cur = self._conn.cursor()
        cur.execute(sql.replace("?", "%s"), params)
        return _PgCursor(cur)

    def executescript(self, sql: str):
        """逐條執行；Postgres 不支援 SQLite 的 executescript，拆開更可靠。"""
        cur = self._conn.cursor()
        for stmt in _to_pg_ddl(sql).split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
        return _PgCursor(cur)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def connect(sqlite_path: str):
    """依環境取得資料庫連線（Postgres 或 SQLite）。"""
    if IS_PG:
        import psycopg2
        import psycopg2.extras

        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]

        # 用 options 在協定層設定 search_path，相容 pgBouncer / Supavisor 各種模式
        opts = f"-c search_path={DB_SCHEMA}" if DB_SCHEMA else ""
        conn = psycopg2.connect(url, options=opts,
                                cursor_factory=psycopg2.extras.RealDictCursor)
        return _PgConn(conn)

    import sqlite3

    if sqlite_path and os.path.dirname(sqlite_path):
        os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)
    conn = sqlite3.connect(sqlite_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def lastid(conn, cur):
    """取得剛插入列的自增 id（兩種後端皆可用）。"""
    if IS_PG:
        return conn.execute("SELECT lastval() AS id").fetchone()["id"]
    return cur.lastrowid
