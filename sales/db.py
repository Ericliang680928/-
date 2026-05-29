"""SQLite 連線與資料表結構（零外部資料庫依賴）。

預設檔案：data/app.db，可用環境變數 SALES_DB 覆寫（部署時指向持久磁碟）。

資料隔離單位為 workspace（帳本）：
  users        使用者帳號（active_workspace_id = 目前作用中的帳本）
  workspaces   帳本（含邀請碼）
  memberships  使用者 ↔ 帳本 的成員關係（owner / member）
  customers / products / sales 皆以 workspace_id 隔離，達成「團隊共享帳本」。

含 v1→v2 自動遷移：舊版以 user_id 隔離的資料，會為每位使用者建立個人帳本後搬移。
"""

from __future__ import annotations

import os

import dbcompat

DB_PATH = os.environ.get(
    "SALES_DB",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "app.db"),
)

SCHEMA_VERSION = 2

_CORE = """
CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    email               TEXT UNIQUE NOT NULL,
    password_hash       TEXT NOT NULL,
    active_workspace_id INTEGER,
    created_at          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspaces (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    invite_code TEXT UNIQUE NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
    workspace_id INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    role         TEXT NOT NULL DEFAULT 'member',
    created_at   TEXT NOT NULL,
    PRIMARY KEY (workspace_id, user_id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

_DATA = """
CREATE TABLE IF NOT EXISTS customers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    name         TEXT NOT NULL,
    aliases      TEXT DEFAULT '',
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS products (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    name         TEXT NOT NULL,
    code         TEXT DEFAULT '',
    aliases      TEXT DEFAULT '',
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS sales (
    id            TEXT PRIMARY KEY,
    workspace_id  INTEGER NOT NULL,
    date          TEXT NOT NULL,
    customer_name TEXT DEFAULT '',
    product_name  TEXT NOT NULL,
    product_code  TEXT DEFAULT '',
    quantity      REAL DEFAULT 0,
    unit          TEXT DEFAULT '',
    raw           TEXT DEFAULT '',
    created_by    INTEGER,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_sales_ws ON sales(workspace_id);
CREATE INDEX IF NOT EXISTS idx_cust_ws ON customers(workspace_id);
CREATE INDEX IF NOT EXISTS idx_prod_ws ON products(workspace_id);
CREATE INDEX IF NOT EXISTS idx_mem_user ON memberships(user_id);
"""


def connect():
    return dbcompat.connect(DB_PATH)


def _has_table(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _has_column(conn, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == col for r in rows)


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(_CORE)
        # 結構遷移只在 SQLite 上跑；Postgres 一律全新建立（無舊資料可遷移）。
        if not dbcompat.IS_PG:
            # 舊版 users 可能沒有 active_workspace_id 欄位。
            if _has_table(conn, "users") and not _has_column(conn, "users", "active_workspace_id"):
                conn.execute("ALTER TABLE users ADD COLUMN active_workspace_id INTEGER")

            # v1（以 user_id 隔離）→ v2（以 workspace_id 隔離）遷移。
            if _has_table(conn, "customers") and _has_column(conn, "customers", "user_id") \
                    and not _has_column(conn, "customers", "workspace_id"):
                _migrate_v1_to_v2(conn)

        conn.executescript(_DATA)
        conn.executescript(_INDEXES)
        if not dbcompat.IS_PG:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    finally:
        conn.close()


def _migrate_v1_to_v2(conn) -> None:
    """為每位舊使用者建立個人帳本，並把其資料搬到該帳本。"""
    import secrets
    from datetime import datetime

    now = datetime.now().isoformat(timespec="seconds")
    user_ws: dict[int, int] = {}
    for u in conn.execute("SELECT id FROM users").fetchall():
        cur = conn.execute(
            "INSERT INTO workspaces (name, invite_code, created_at) VALUES (?, ?, ?)",
            ("我的帳本", secrets.token_hex(4), now),
        )
        ws_id = cur.lastrowid
        conn.execute(
            "INSERT INTO memberships (workspace_id, user_id, role, created_at) VALUES (?, ?, 'owner', ?)",
            (ws_id, u["id"], now),
        )
        conn.execute("UPDATE users SET active_workspace_id = ? WHERE id = ?", (ws_id, u["id"]))
        user_ws[u["id"]] = ws_id

    for table in ("customers", "products", "sales"):
        if _has_table(conn, table) and not _has_column(conn, table, "workspace_id"):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN workspace_id INTEGER")
            for uid, ws_id in user_ws.items():
                conn.execute(f"UPDATE {table} SET workspace_id = ? WHERE user_id = ?", (ws_id, uid))

    # 新版 sales 多了 created_by 欄位；用舊的 user_id 回填為輸入者。
    if _has_table(conn, "sales") and not _has_column(conn, "sales", "created_by"):
        conn.execute("ALTER TABLE sales ADD COLUMN created_by INTEGER")
        if _has_column(conn, "sales", "user_id"):
            conn.execute("UPDATE sales SET created_by = user_id")
