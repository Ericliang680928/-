"""帳號、帳本（workspace）、清單與銷貨紀錄的儲存層。

資料隔離單位為 workspace（帳本），可多人共用 → 「團隊共享帳本」。
資料相關函式皆以 workspace_id 為界，確保只存取該帳本的資料。
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash

from .db import connect, init_db

# 新帳本的範例清單（讓使用者一進來就有東西可玩）。
_SEED_CUSTOMERS = [
    {"name": "大同公司", "aliases": ["大同", "大同股份"]},
    {"name": "全家便利商店", "aliases": ["全家", "全家超商"]},
    {"name": "王小明", "aliases": ["小明", "老王", "王老闆"]},
]
_SEED_PRODUCTS = [
    {"name": "可口可樂", "code": "A001", "aliases": ["可樂", "coke"]},
    {"name": "百事可樂", "code": "A002", "aliases": ["百事", "pepsi"]},
    {"name": "雪碧", "code": "A003", "aliases": ["sprite"]},
    {"name": "礦泉水", "code": "B001", "aliases": ["水", "瓶裝水"]},
    {"name": "御茶園綠茶", "code": "B002", "aliases": ["綠茶", "御茶園"]},
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _join(aliases) -> str:
    return "|".join(a for a in (aliases or []) if a)


def _split(value: str) -> list[str]:
    return [a.strip() for a in (value or "").replace("、", "|").replace(",", "|").split("|") if a.strip()]


def _new_invite() -> str:
    return secrets.token_hex(4)  # 8 碼邀請碼


# ---------------------------------------------------------------------------
# 帳號
# ---------------------------------------------------------------------------
def create_user(email: str, password: str) -> Optional[int]:
    """建立帳號 + 個人帳本 + 範例清單。email 已存在則回 None。"""
    email = email.strip().lower()
    conn = connect()
    try:
        if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            return None
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, generate_password_hash(password), _now()),
        )
        user_id = cur.lastrowid
        ws_id = _create_workspace(conn, user_id, "我的帳本", seed=True)
        conn.execute("UPDATE users SET active_workspace_id = ? WHERE id = ?", (ws_id, user_id))
        conn.commit()
        return user_id
    finally:
        conn.close()


def verify_user(email: str, password: str) -> Optional[int]:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            return row["id"]
        return None
    finally:
        conn.close()


def get_user(user_id: int) -> Optional[dict]:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, email, active_workspace_id FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 帳本（workspace）/ 團隊
# ---------------------------------------------------------------------------
def _create_workspace(conn, user_id: int, name: str, seed: bool = False) -> int:
    """在既有連線上建立帳本、設使用者為 owner，並可植入範例清單。"""
    name = (name or "未命名帳本").strip() or "未命名帳本"
    cur = conn.execute(
        "INSERT INTO workspaces (name, invite_code, created_at) VALUES (?, ?, ?)",
        (name, _new_invite(), _now()),
    )
    ws_id = cur.lastrowid
    conn.execute(
        "INSERT INTO memberships (workspace_id, user_id, role, created_at) VALUES (?, ?, 'owner', ?)",
        (ws_id, user_id, _now()),
    )
    if seed:
        for c in _SEED_CUSTOMERS:
            conn.execute(
                "INSERT INTO customers (workspace_id, name, aliases) VALUES (?, ?, ?)",
                (ws_id, c["name"], _join(c["aliases"])),
            )
        for p in _SEED_PRODUCTS:
            conn.execute(
                "INSERT INTO products (workspace_id, name, code, aliases) VALUES (?, ?, ?, ?)",
                (ws_id, p["name"], p["code"], _join(p["aliases"])),
            )
    return ws_id


def is_member(user_id: int, workspace_id: int) -> bool:
    conn = connect()
    try:
        return conn.execute(
            "SELECT 1 FROM memberships WHERE user_id = ? AND workspace_id = ?",
            (user_id, workspace_id),
        ).fetchone() is not None
    finally:
        conn.close()


def get_active_workspace_id(user_id: int) -> int:
    """取得使用者目前作用中的帳本；若無效則自動修正為任一所屬帳本。"""
    conn = connect()
    try:
        u = conn.execute("SELECT active_workspace_id FROM users WHERE id = ?", (user_id,)).fetchone()
        ws_id = u["active_workspace_id"] if u else None
        if ws_id and conn.execute(
            "SELECT 1 FROM memberships WHERE user_id = ? AND workspace_id = ?", (user_id, ws_id)
        ).fetchone():
            return ws_id
        # 後援：取任一所屬帳本；都沒有就建一個個人帳本。
        m = conn.execute(
            "SELECT workspace_id FROM memberships WHERE user_id = ? ORDER BY workspace_id LIMIT 1",
            (user_id,),
        ).fetchone()
        if m:
            ws_id = m["workspace_id"]
        else:
            ws_id = _create_workspace(conn, user_id, "我的帳本", seed=True)
        conn.execute("UPDATE users SET active_workspace_id = ? WHERE id = ?", (ws_id, user_id))
        conn.commit()
        return ws_id
    finally:
        conn.close()


def list_workspaces(user_id: int) -> list[dict]:
    conn = connect()
    try:
        active = get_active_workspace_id(user_id)
        rows = conn.execute(
            "SELECT w.id, w.name, m.role, "
            "(SELECT COUNT(*) FROM memberships mm WHERE mm.workspace_id = w.id) AS members "
            "FROM workspaces w JOIN memberships m ON m.workspace_id = w.id "
            "WHERE m.user_id = ? ORDER BY w.id", (user_id,),
        ).fetchall()
        return [
            {"id": r["id"], "name": r["name"], "role": r["role"],
             "members": r["members"], "is_active": r["id"] == active}
            for r in rows
        ]
    finally:
        conn.close()


def create_workspace(user_id: int, name: str) -> int:
    """建立新帳本（空的），並切換為作用中。"""
    conn = connect()
    try:
        ws_id = _create_workspace(conn, user_id, name, seed=False)
        conn.execute("UPDATE users SET active_workspace_id = ? WHERE id = ?", (ws_id, user_id))
        conn.commit()
        return ws_id
    finally:
        conn.close()


def switch_workspace(user_id: int, workspace_id: int) -> bool:
    conn = connect()
    try:
        if not conn.execute(
            "SELECT 1 FROM memberships WHERE user_id = ? AND workspace_id = ?",
            (user_id, workspace_id),
        ).fetchone():
            return False
        conn.execute("UPDATE users SET active_workspace_id = ? WHERE id = ?", (workspace_id, user_id))
        conn.commit()
        return True
    finally:
        conn.close()


def join_workspace(user_id: int, invite_code: str) -> Optional[dict]:
    """以邀請碼加入帳本並切換為作用中。回傳帳本資訊或 None。"""
    code = (invite_code or "").strip().lower()
    conn = connect()
    try:
        w = conn.execute("SELECT id, name FROM workspaces WHERE invite_code = ?", (code,)).fetchone()
        if not w:
            return None
        if not conn.execute(
            "SELECT 1 FROM memberships WHERE user_id = ? AND workspace_id = ?",
            (user_id, w["id"]),
        ).fetchone():
            conn.execute(
                "INSERT INTO memberships (workspace_id, user_id, role, created_at) VALUES (?, ?, 'member', ?)",
                (w["id"], user_id, _now()),
            )
        conn.execute("UPDATE users SET active_workspace_id = ? WHERE id = ?", (w["id"], user_id))
        conn.commit()
        return {"id": w["id"], "name": w["name"]}
    finally:
        conn.close()


def workspace_detail(user_id: int, workspace_id: int) -> Optional[dict]:
    """目前帳本的詳情：名稱、邀請碼、成員清單、自己的角色。"""
    conn = connect()
    try:
        mine = conn.execute(
            "SELECT role FROM memberships WHERE user_id = ? AND workspace_id = ?",
            (user_id, workspace_id),
        ).fetchone()
        if not mine:
            return None
        w = conn.execute("SELECT id, name, invite_code FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        members = conn.execute(
            "SELECT u.email, m.role FROM memberships m JOIN users u ON u.id = m.user_id "
            "WHERE m.workspace_id = ? ORDER BY m.created_at", (workspace_id,),
        ).fetchall()
        return {
            "id": w["id"], "name": w["name"], "invite_code": w["invite_code"],
            "my_role": mine["role"],
            "members": [{"email": r["email"], "role": r["role"]} for r in members],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 清單（以 workspace 為界）
# ---------------------------------------------------------------------------
def load_customers(workspace_id: int) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT name, aliases FROM customers WHERE workspace_id = ? ORDER BY id", (workspace_id,)
        ).fetchall()
        return [{"name": r["name"], "aliases": _split(r["aliases"])} for r in rows]
    finally:
        conn.close()


def load_products(workspace_id: int) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT name, code, aliases FROM products WHERE workspace_id = ? ORDER BY id", (workspace_id,)
        ).fetchall()
        return [{"name": r["name"], "code": r["code"] or "", "aliases": _split(r["aliases"])} for r in rows]
    finally:
        conn.close()


def save_customers(workspace_id: int, items: list[dict]) -> None:
    conn = connect()
    try:
        conn.execute("DELETE FROM customers WHERE workspace_id = ?", (workspace_id,))
        for it in items:
            if not it.get("name"):
                continue
            conn.execute(
                "INSERT INTO customers (workspace_id, name, aliases) VALUES (?, ?, ?)",
                (workspace_id, it["name"], _join(it.get("aliases"))),
            )
        conn.commit()
    finally:
        conn.close()


def save_products(workspace_id: int, items: list[dict]) -> None:
    conn = connect()
    try:
        conn.execute("DELETE FROM products WHERE workspace_id = ?", (workspace_id,))
        for it in items:
            if not it.get("name"):
                continue
            conn.execute(
                "INSERT INTO products (workspace_id, name, code, aliases) VALUES (?, ?, ?, ?)",
                (workspace_id, it["name"], it.get("code", ""), _join(it.get("aliases"))),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 銷貨紀錄（以 workspace 為界）
# ---------------------------------------------------------------------------
def load_records(workspace_id: int) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT s.id, s.date, s.customer_name, s.product_name, s.product_code, s.quantity, "
            "s.unit, s.raw, s.created_at, u.email AS created_by_email "
            "FROM sales s LEFT JOIN users u ON u.id = s.created_by "
            "WHERE s.workspace_id = ? ORDER BY s.created_at", (workspace_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            q = d["quantity"]
            d["quantity"] = int(q) if isinstance(q, float) and q.is_integer() else q
            out.append(d)
        return out
    finally:
        conn.close()


def add_records(workspace_id: int, rows: list[dict], created_by: Optional[int] = None) -> int:
    conn = connect()
    try:
        now = _now()
        for r in rows:
            conn.execute(
                "INSERT INTO sales (id, workspace_id, date, customer_name, product_name, product_code, "
                "quantity, unit, raw, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex[:12], workspace_id, r.get("date", ""), r.get("customer_name", ""),
                    r.get("product_name", ""), r.get("product_code", ""), float(r.get("quantity", 0) or 0),
                    r.get("unit", ""), r.get("raw", ""), created_by, now,
                ),
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def delete_record(workspace_id: int, record_id: str) -> bool:
    conn = connect()
    try:
        cur = conn.execute(
            "DELETE FROM sales WHERE workspace_id = ? AND id = ?", (workspace_id, record_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def clear_records(workspace_id: int) -> None:
    conn = connect()
    try:
        conn.execute("DELETE FROM sales WHERE workspace_id = ?", (workspace_id,))
        conn.commit()
    finally:
        conn.close()


# 啟動時確保資料表存在（並執行必要遷移）。
init_db()
