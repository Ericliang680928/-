"""清單、銷貨紀錄與帳號的儲存層（SQLite，依 user_id 隔離）。

對外函式皆以 user_id 為第一參數，確保每個帳號只看得到自己的資料。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash

from .db import connect, init_db

# 新帳號的範例清單（讓使用者一進來就有東西可玩）。
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


def _join(aliases) -> str:
    return "|".join(a for a in (aliases or []) if a)


def _split(value: str) -> list[str]:
    return [a.strip() for a in (value or "").replace("、", "|").replace(",", "|").split("|") if a.strip()]


# ---------------------------------------------------------------------------
# 帳號
# ---------------------------------------------------------------------------
def create_user(email: str, password: str) -> Optional[int]:
    """建立帳號並植入範例清單。email 已存在則回 None。"""
    email = email.strip().lower()
    conn = connect()
    try:
        cur = conn.execute("SELECT id FROM users WHERE email = ?", (email,))
        if cur.fetchone():
            return None
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, generate_password_hash(password), datetime.now().isoformat(timespec="seconds")),
        )
        user_id = cur.lastrowid
        for c in _SEED_CUSTOMERS:
            conn.execute(
                "INSERT INTO customers (user_id, name, aliases) VALUES (?, ?, ?)",
                (user_id, c["name"], _join(c["aliases"])),
            )
        for p in _SEED_PRODUCTS:
            conn.execute(
                "INSERT INTO products (user_id, name, code, aliases) VALUES (?, ?, ?, ?)",
                (user_id, p["name"], p["code"], _join(p["aliases"])),
            )
        conn.commit()
        return user_id
    finally:
        conn.close()


def verify_user(email: str, password: str) -> Optional[int]:
    """驗證帳密，成功回 user_id，否則 None。"""
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
        row = conn.execute("SELECT id, email FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 清單
# ---------------------------------------------------------------------------
def load_customers(user_id: int) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT name, aliases FROM customers WHERE user_id = ? ORDER BY id", (user_id,)
        ).fetchall()
        return [{"name": r["name"], "aliases": _split(r["aliases"])} for r in rows]
    finally:
        conn.close()


def load_products(user_id: int) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT name, code, aliases FROM products WHERE user_id = ? ORDER BY id", (user_id,)
        ).fetchall()
        return [{"name": r["name"], "code": r["code"] or "", "aliases": _split(r["aliases"])} for r in rows]
    finally:
        conn.close()


def save_customers(user_id: int, items: list[dict]) -> None:
    conn = connect()
    try:
        conn.execute("DELETE FROM customers WHERE user_id = ?", (user_id,))
        for it in items:
            if not it.get("name"):
                continue
            conn.execute(
                "INSERT INTO customers (user_id, name, aliases) VALUES (?, ?, ?)",
                (user_id, it["name"], _join(it.get("aliases"))),
            )
        conn.commit()
    finally:
        conn.close()


def save_products(user_id: int, items: list[dict]) -> None:
    conn = connect()
    try:
        conn.execute("DELETE FROM products WHERE user_id = ?", (user_id,))
        for it in items:
            if not it.get("name"):
                continue
            conn.execute(
                "INSERT INTO products (user_id, name, code, aliases) VALUES (?, ?, ?, ?)",
                (user_id, it["name"], it.get("code", ""), _join(it.get("aliases"))),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 銷貨紀錄
# ---------------------------------------------------------------------------
def load_records(user_id: int) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, date, customer_name, product_name, product_code, quantity, unit, raw, created_at "
            "FROM sales WHERE user_id = ? ORDER BY created_at", (user_id,)
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


def add_records(user_id: int, rows: list[dict]) -> int:
    conn = connect()
    try:
        now = datetime.now().isoformat(timespec="seconds")
        for r in rows:
            conn.execute(
                "INSERT INTO sales (id, user_id, date, customer_name, product_name, product_code, "
                "quantity, unit, raw, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex[:12], user_id, r.get("date", ""), r.get("customer_name", ""),
                    r.get("product_name", ""), r.get("product_code", ""), float(r.get("quantity", 0) or 0),
                    r.get("unit", ""), r.get("raw", ""), now,
                ),
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def delete_record(user_id: int, record_id: str) -> bool:
    conn = connect()
    try:
        cur = conn.execute("DELETE FROM sales WHERE user_id = ? AND id = ?", (user_id, record_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def clear_records(user_id: int) -> None:
    conn = connect()
    try:
        conn.execute("DELETE FROM sales WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


# 啟動時確保資料表存在。
init_db()
