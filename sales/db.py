"""SQLite 連線與資料表結構（零外部資料庫依賴）。

預設檔案：data/app.db，可用環境變數 SALES_DB 覆寫（部署時指向持久磁碟）。
所有業務資料都帶 user_id，達成多帳號資料隔離。
"""

from __future__ import annotations

import os
import sqlite3

DB_PATH = os.environ.get(
    "SALES_DB",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "app.db"),
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name    TEXT NOT NULL,
    aliases TEXT DEFAULT '',
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS products (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name    TEXT NOT NULL,
    code    TEXT DEFAULT '',
    aliases TEXT DEFAULT '',
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS sales (
    id           TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    date         TEXT NOT NULL,
    customer_name TEXT DEFAULT '',
    product_name TEXT NOT NULL,
    product_code TEXT DEFAULT '',
    quantity     REAL DEFAULT 0,
    unit         TEXT DEFAULT '',
    raw          TEXT DEFAULT '',
    created_at   TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sales_user ON sales(user_id);
CREATE INDEX IF NOT EXISTS idx_cust_user ON customers(user_id);
CREATE INDEX IF NOT EXISTS idx_prod_user ON products(user_id);
"""


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()
