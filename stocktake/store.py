"""庫存盤點 — 資料存取與商業邏輯（程式資料庫為唯一正本）。

重點規則：
  * 多人同時盤點：盤點明細以 version 做樂觀鎖，偵測覆寫衝突回 409 提示。
  * 結案後不可改：批次結案後 batch_items 凍結，只能新增 adjustments 調整紀錄。
  * 狀態：未盤 / 已盤(差異0) / 差異(差異≠0) / 已覆核。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash

from .db import connect, init_db

ROLES = ("admin", "counter", "reviewer")
ROLE_LABELS = {"admin": "管理員", "counter": "盤點員", "reviewer": "覆核員"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 帳號 / 角色
# ---------------------------------------------------------------------------
def user_count() -> int:
    conn = connect()
    try:
        return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    finally:
        conn.close()


def create_user(email: str, password: str, name: str, role: str) -> Optional[int]:
    if role not in ROLES:
        role = "counter"
    email = email.strip().lower()
    conn = connect()
    try:
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            return None
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, name, role, created_at) VALUES (?,?,?,?,?)",
            (email, generate_password_hash(password), name or email, role, _now()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def verify_user(email: str, password: str) -> Optional[dict]:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            return {"id": row["id"], "email": row["email"], "name": row["name"], "role": row["role"]}
        return None
    finally:
        conn.close()


def get_user(user_id: int) -> Optional[dict]:
    conn = connect()
    try:
        row = conn.execute("SELECT id,email,name,role FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_users() -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id,email,name,role,created_at FROM users ORDER BY id").fetchall()]
    finally:
        conn.close()


def set_role(user_id: int, role: str) -> bool:
    if role not in ROLES:
        return False
    conn = connect()
    try:
        conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
        conn.commit()
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 產品主檔 / 庫存現況
# ---------------------------------------------------------------------------
def import_products(rows: list[dict], source_updated_at: str = "") -> dict:
    """以 商品編號 為唯一鍵 upsert 產品；來源沒有的標記停用。回傳統計。"""
    now = _now()
    conn = connect()
    try:
        existing = {r["code"]: r for r in conn.execute("SELECT * FROM products").fetchall()}
        seen = set()
        added = updated = 0
        for r in rows:
            code = (r.get("code") or "").strip()
            if not code:
                continue
            seen.add(code)
            name = (r.get("name") or "").strip()
            cat = (r.get("category") or "").strip()
            if code in existing:
                conn.execute(
                    "UPDATE products SET name=?,category=?,active=1,source_updated_at=?,synced_at=? WHERE code=?",
                    (name, cat, source_updated_at, now, code))
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO products (code,name,category,active,source_updated_at,synced_at) VALUES (?,?,?,1,?,?)",
                    (code, name, cat, source_updated_at, now))
                conn.execute(
                    "INSERT OR IGNORE INTO inventory (product_code,book_qty,last_count_date,last_moved_at) VALUES (?,0,'','')",
                    (code,))
                added += 1
        # 來源已不存在的 → 停用（不刪，保留歷史）
        disabled = 0
        for code in existing:
            if code not in seen and existing[code]["active"]:
                conn.execute("UPDATE products SET active=0,synced_at=? WHERE code=?", (now, code))
                disabled += 1
        conn.commit()
        return {"added": added, "updated": updated, "disabled": disabled}
    finally:
        conn.close()


def load_products(active_only: bool = True) -> list[dict]:
    conn = connect()
    try:
        q = "SELECT * FROM products"
        if active_only:
            q += " WHERE active=1"
        q += " ORDER BY category, code"
        return [dict(r) for r in conn.execute(q).fetchall()]
    finally:
        conn.close()


def categories() -> list[str]:
    conn = connect()
    try:
        return [r["category"] for r in conn.execute(
            "SELECT DISTINCT category FROM products WHERE active=1 AND category<>'' ORDER BY category").fetchall()]
    finally:
        conn.close()


def set_book_qty(product_code: str, qty: float) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO inventory (product_code,book_qty,last_moved_at) VALUES (?,?,?) "
            "ON CONFLICT(product_code) DO UPDATE SET book_qty=excluded.book_qty,last_moved_at=excluded.last_moved_at",
            (product_code, qty, _now()))
        conn.commit()
    finally:
        conn.close()


def inventory_snapshot() -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT i.product_code, p.name, p.category, i.book_qty, i.last_count_date, i.last_moved_at "
            "FROM inventory i LEFT JOIN products p ON p.code=i.product_code ORDER BY p.category, i.product_code"
        ).fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 盤點批次
# ---------------------------------------------------------------------------
def create_batch(count_date: str, created_by: str, title: str = "",
                 category: str = "", only_codes: Optional[list[str]] = None) -> str:
    """建立批次，並依目前產品/庫存快照產生盤點明細（每個產品一列）。"""
    if not count_date:
        raise ValueError("盤點日期為必填")
    batch_id = "B" + datetime.now().strftime("%Y%m%d%H%M%S")
    now = _now()
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO batches (id,count_date,title,created_by,started_at,status) VALUES (?,?,?,?,?, '進行中')",
            (batch_id, count_date, title, created_by, now))
        q = "SELECT p.code,p.name,p.category,COALESCE(i.book_qty,0) book FROM products p " \
            "LEFT JOIN inventory i ON i.product_code=p.code WHERE p.active=1"
        params: list = []
        if category:
            q += " AND p.category=?"
            params.append(category)
        rows = conn.execute(q, params).fetchall()
        codes = set(only_codes) if only_codes else None
        for r in rows:
            if codes is not None and r["code"] not in codes:
                continue
            conn.execute(
                "INSERT INTO batch_items (batch_id,count_date,product_code,name_snapshot,"
                "category_snapshot,book_qty_snapshot,status,version) VALUES (?,?,?,?,?,?, '未盤',0)",
                (batch_id, count_date, r["code"], r["name"], r["category"], r["book"]))
        conn.commit()
        return batch_id
    finally:
        conn.close()


def list_batches() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM batches ORDER BY started_at DESC").fetchall()
        out = []
        for b in rows:
            d = dict(b)
            d.update(_batch_progress(conn, b["id"]))
            out.append(d)
        return out
    finally:
        conn.close()


def get_batch(batch_id: str) -> Optional[dict]:
    conn = connect()
    try:
        b = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        if not b:
            return None
        d = dict(b)
        d.update(_batch_progress(conn, batch_id))
        return d
    finally:
        conn.close()


def _batch_progress(conn, batch_id: str) -> dict:
    rows = conn.execute(
        "SELECT status, COUNT(*) c FROM batch_items WHERE batch_id=? GROUP BY status", (batch_id,)).fetchall()
    counts = {"未盤": 0, "已盤": 0, "差異": 0, "已覆核": 0}
    for r in rows:
        counts[r["status"]] = r["c"]
    total = sum(counts.values())
    done = total - counts["未盤"]
    return {"counts": counts, "total": total, "done": done,
            "progress": round(done / total * 100) if total else 0}


def close_batch(batch_id: str) -> dict:
    """結案：套用實盤數到庫存現況，批次狀態改已結案（之後明細凍結）。"""
    now = _now()
    conn = connect()
    try:
        b = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        if not b:
            return {"error": "批次不存在"}
        if b["status"] != "進行中":
            return {"error": "只有進行中的批次可結案"}
        un = conn.execute(
            "SELECT COUNT(*) c FROM batch_items WHERE batch_id=? AND status='未盤'", (batch_id,)).fetchone()["c"]
        items = conn.execute(
            "SELECT product_code,actual_qty FROM batch_items WHERE batch_id=? AND actual_qty IS NOT NULL",
            (batch_id,)).fetchall()
        for it in items:
            conn.execute(
                "UPDATE inventory SET book_qty=?,last_count_date=?,last_moved_at=? WHERE product_code=?",
                (it["actual_qty"], b["count_date"], now, it["product_code"]))
        conn.execute("UPDATE batches SET status='已結案',finished_at=? WHERE id=?", (now, batch_id))
        conn.commit()
        return {"ok": True, "uncounted": un, "applied": len(items)}
    finally:
        conn.close()


def void_batch(batch_id: str) -> dict:
    conn = connect()
    try:
        b = conn.execute("SELECT status FROM batches WHERE id=?", (batch_id,)).fetchone()
        if not b:
            return {"error": "批次不存在"}
        if b["status"] == "已結案":
            return {"error": "已結案批次不可作廢"}
        conn.execute("UPDATE batches SET status='已作廢',finished_at=? WHERE id=?", (_now(), batch_id))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 盤點明細
# ---------------------------------------------------------------------------
def list_items(batch_id: str, status: str = "", search: str = "") -> list[dict]:
    conn = connect()
    try:
        q = "SELECT * FROM batch_items WHERE batch_id=?"
        params: list = [batch_id]
        if status:
            q += " AND status=?"
            params.append(status)
        if search:
            q += " AND (product_code LIKE ? OR name_snapshot LIKE ? OR category_snapshot LIKE ?)"
            like = f"%{search}%"
            params += [like, like, like]
        q += " ORDER BY category_snapshot, product_code"
        return [dict(r) for r in conn.execute(q, params).fetchall()]
    finally:
        conn.close()


def _status_for(actual: Optional[float], diff: Optional[float], reviewed_at: str) -> str:
    if reviewed_at:
        return "已覆核"
    if actual is None:
        return "未盤"
    return "已盤" if (diff or 0) == 0 else "差異"


def update_count(batch_id: str, product_code: str, actual_qty, base_version: int,
                 user: str, note: str = "", diff_reason: str = "") -> dict:
    """盤點員輸入實盤數。樂觀鎖：版本不符回 conflict；批次非進行中拒絕（改用調整）。"""
    conn = connect()
    try:
        b = conn.execute("SELECT status FROM batches WHERE id=?", (batch_id,)).fetchone()
        if not b:
            return {"error": "批次不存在"}, 404
        if b["status"] != "進行中":
            return {"error": "批次已結案，請改用「調整紀錄」"}, 409
        row = conn.execute(
            "SELECT * FROM batch_items WHERE batch_id=? AND product_code=?", (batch_id, product_code)).fetchone()
        if not row:
            return {"error": "找不到此品項"}, 404
        if base_version is not None and int(base_version) != row["version"]:
            return {"conflict": True, "current": dict(row),
                    "message": f"此品項已被 {row['counter'] or '他人'} 更新，請確認後再存"}, 409

        actual = None if actual_qty in ("", None) else float(actual_qty)
        diff = None if actual is None else actual - (row["book_qty_snapshot"] or 0)
        # 覆核後又被改動 → 退回需重新覆核
        new_status = _status_for(actual, diff, "")
        conn.execute(
            "UPDATE batch_items SET actual_qty=?,diff_qty=?,note=?,diff_reason=?,counter=?,counted_at=?,"
            "reviewer='',reviewed_at='',status=?,version=version+1 WHERE id=?",
            (actual, diff, note, diff_reason, user, _now(), new_status, row["id"]))
        conn.commit()
        updated = conn.execute("SELECT * FROM batch_items WHERE id=?", (row["id"],)).fetchone()
        return {"ok": True, "item": dict(updated)}, 200
    finally:
        conn.close()


def review_items(batch_id: str, product_codes: list[str], reviewer: str) -> dict:
    """覆核員把指定品項標記為已覆核（需已盤/差異狀態）。"""
    conn = connect()
    try:
        b = conn.execute("SELECT status FROM batches WHERE id=?", (batch_id,)).fetchone()
        if not b:
            return {"error": "批次不存在"}
        n = 0
        for code in product_codes:
            r = conn.execute(
                "SELECT * FROM batch_items WHERE batch_id=? AND product_code=?", (batch_id, code)).fetchone()
            if not r or r["actual_qty"] is None:
                continue
            conn.execute(
                "UPDATE batch_items SET reviewer=?,reviewed_at=?,status='已覆核',version=version+1 WHERE id=?",
                (reviewer, _now(), r["id"]))
            n += 1
        conn.commit()
        return {"ok": True, "reviewed": n}
    finally:
        conn.close()


def add_adjustment(batch_id: str, product_code: str, new_actual: float,
                   reason: str, user: str) -> dict:
    """結案後唯一可做的修改：新增調整紀錄（不改動凍結的盤點明細）。"""
    conn = connect()
    try:
        b = conn.execute("SELECT status,count_date FROM batches WHERE id=?", (batch_id,)).fetchone()
        if not b:
            return {"error": "批次不存在"}
        if b["status"] != "已結案":
            return {"error": "只有已結案批次需用調整紀錄；進行中請直接盤點"}
        old = conn.execute(
            "SELECT actual_qty FROM batch_items WHERE batch_id=? AND product_code=?",
            (batch_id, product_code)).fetchone()
        old_actual = old["actual_qty"] if old else None
        conn.execute(
            "INSERT INTO adjustments (batch_id,product_code,old_actual,new_actual,reason,created_by,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (batch_id, product_code, old_actual, float(new_actual), reason, user, _now()))
        # 調整也反映到庫存現況
        conn.execute(
            "UPDATE inventory SET book_qty=?,last_count_date=?,last_moved_at=? WHERE product_code=?",
            (float(new_actual), b["count_date"], _now(), product_code))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def list_adjustments(batch_id: str) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM adjustments WHERE batch_id=? ORDER BY created_at", (batch_id,)).fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 同步日誌 / 儀表板
# ---------------------------------------------------------------------------
def log_sync(sync_batch_id: str, added: int, updated: int, disabled: int, error: str = "") -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO sync_logs (sync_batch_id,synced_at,added,updated,disabled,error) VALUES (?,?,?,?,?,?)",
            (sync_batch_id, _now(), added, updated, disabled, error))
        conn.commit()
    finally:
        conn.close()


def list_sync_logs(limit: int = 20) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM sync_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    finally:
        conn.close()


def dashboard_stats() -> dict:
    conn = connect()
    try:
        active = conn.execute("SELECT COUNT(*) c FROM products WHERE active=1").fetchone()["c"]
        open_b = conn.execute("SELECT COUNT(*) c FROM batches WHERE status='進行中'").fetchone()["c"]
        closed_b = conn.execute("SELECT COUNT(*) c FROM batches WHERE status='已結案'").fetchone()["c"]
        return {"active_products": active, "open_batches": open_b, "closed_batches": closed_b}
    finally:
        conn.close()


init_db()
