"""庫存盤點系統 — SQLite 資料結構（程式資料庫為正本，再同步到 Google Sheet）。

資料表對應專屬 Sheet 的工作表：
  products      → 產品主檔
  batches       → 盤點批次
  batch_items   → 盤點明細
  inventory     → 庫存現況
  adjustments   → 結案後的調整紀錄（結案不可改，只能新增調整）
  sync_logs     → 同步日誌
  users         → 帳號與角色（管理員/盤點員/覆核員）
"""

from __future__ import annotations

import os
import sqlite3

DB_PATH = os.environ.get(
    "STOCKTAKE_DB",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "stocktake.db"),
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'counter',   -- admin / counter / reviewer
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    code             TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    category         TEXT DEFAULT '',
    spec             TEXT DEFAULT '',       -- 規格（來源第 4 欄）
    active           INTEGER DEFAULT 1,
    source_updated_at TEXT DEFAULT '',
    synced_at        TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS inventory (
    product_code   TEXT PRIMARY KEY,
    book_qty       REAL DEFAULT 0,        -- 目前帳面庫存
    last_count_date TEXT DEFAULT '',
    last_moved_at  TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS batches (
    id          TEXT PRIMARY KEY,
    count_date  TEXT NOT NULL,            -- 盤點日期（必填）
    title       TEXT DEFAULT '',
    created_by  TEXT DEFAULT '',
    started_at  TEXT DEFAULT '',
    finished_at TEXT DEFAULT '',
    status      TEXT NOT NULL DEFAULT '進行中'  -- 進行中 / 已結案 / 已作廢
);

CREATE TABLE IF NOT EXISTS batch_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id         TEXT NOT NULL,
    count_date       TEXT NOT NULL,
    product_code     TEXT NOT NULL,
    name_snapshot    TEXT DEFAULT '',
    category_snapshot TEXT DEFAULT '',
    spec_snapshot    TEXT DEFAULT '',
    book_qty_snapshot REAL DEFAULT 0,
    actual_qty       REAL,                -- 實盤庫存（null = 未盤）
    diff_qty         REAL,                -- 差異 = 實盤 - 帳面
    diff_reason      TEXT DEFAULT '',
    note             TEXT DEFAULT '',
    counter          TEXT DEFAULT '',
    counted_at       TEXT DEFAULT '',
    reviewer         TEXT DEFAULT '',
    reviewed_at      TEXT DEFAULT '',
    status           TEXT NOT NULL DEFAULT '未盤',   -- 未盤/已盤/差異/已覆核
    version          INTEGER NOT NULL DEFAULT 0,     -- 樂觀鎖：防止多人覆寫
    UNIQUE (batch_id, product_code),
    FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS adjustments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id     TEXT NOT NULL,
    product_code TEXT NOT NULL,
    old_actual   REAL,
    new_actual   REAL,
    reason       TEXT DEFAULT '',
    created_by   TEXT DEFAULT '',
    created_at   TEXT NOT NULL,
    FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sync_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_batch_id TEXT NOT NULL,
    synced_at    TEXT NOT NULL,
    added        INTEGER DEFAULT 0,
    updated      INTEGER DEFAULT 0,
    disabled     INTEGER DEFAULT 0,
    error        TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_items_batch ON batch_items(batch_id);
CREATE INDEX IF NOT EXISTS idx_items_status ON batch_items(batch_id, status);
"""


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _migrate(conn) -> None:
    """既有資料庫補欄位（新增「規格」相關欄位）。"""
    if not _has_column(conn, "products", "spec"):
        conn.execute("ALTER TABLE products ADD COLUMN spec TEXT DEFAULT ''")
    if not _has_column(conn, "batch_items", "spec_snapshot"):
        conn.execute("ALTER TABLE batch_items ADD COLUMN spec_snapshot TEXT DEFAULT ''")


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()
