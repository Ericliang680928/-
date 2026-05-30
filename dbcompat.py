"""SQLite ↔ PostgreSQL 相容層（讓兩個 App 一套程式碼跑兩種資料庫）。

* 本機開發與測試：用 SQLite（零設定、免安裝伺服器）。
* 雲端部署：設了環境變數 `DATABASE_URL`（如 Neon 免費 Postgres）就改用 Postgres，
  資料才會跨重啟/重新部署永久保存，並更適合多人同時寫入。

設計重點：
  * 兩種後端都讓 `conn.execute(sql, params)` 回傳「可用 row["欄名"] 取值」的列。
  * SQL 一律用 `?` 佔位符；Postgres 後端會自動轉成 `%s`。
  * 建表 DDL 一律用 SQLite 寫法；Postgres 後端會把
    `INTEGER PRIMARY KEY AUTOINCREMENT` 轉成 `SERIAL PRIMARY KEY`。
  * 自增主鍵：取得新 id 請用 `lastid(conn, cur)`（兩種後端皆可）。
  * 結構遷移（PRAGMA/sqlite_master 等）只在 SQLite 上跑；Postgres 永遠是全新建立。
"""

from __future__ import annotations

import os
import re

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))

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
        cur = self._conn.cursor()
        cur.execute(_to_pg_ddl(sql))
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
        if url.startswith("postgres://"):  # SQLAlchemy/psycopg2 慣用 postgresql://
            url = "postgresql://" + url[len("postgres://"):]
        conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
        return _PgConn(conn)

    import sqlite3

    if os.path.dirname(sqlite_path):
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
