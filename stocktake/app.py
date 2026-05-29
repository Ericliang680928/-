"""庫存盤點系統 — Flask 網頁後端（手機優先）。

頁面：登入 / 儀表板 / 建立批次 / 盤點作業 / 差異覆核 / 歷史查詢 / 同步設定
角色：管理員(admin) / 盤點員(counter) / 覆核員(reviewer)
"""

from __future__ import annotations

import os
from datetime import date
from functools import wraps

from flask import (Flask, jsonify, request, render_template, redirect, url_for, session)

from . import store, sheets

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=bool(os.environ.get("COOKIE_SECURE")))


# ---------------------------------------------------------------------------
# 驗證 / 權限
# ---------------------------------------------------------------------------
def login_required(fn):
    @wraps(fn)
    def w(*a, **k):
        if not session.get("uid"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "請先登入"}), 401
            return redirect(url_for("login_page"))
        return fn(*a, **k)
    return w


def require_role(*roles):
    def deco(fn):
        @wraps(fn)
        def w(*a, **k):
            if not session.get("uid"):
                return jsonify({"error": "請先登入"}), 401
            if session.get("role") not in roles and session.get("role") != "admin":
                return jsonify({"error": "權限不足"}), 403
            return fn(*a, **k)
        return w
    return deco


def me() -> dict:
    return {"id": session.get("uid"), "name": session.get("name"),
            "role": session.get("role"), "email": session.get("email")}


# ---------------------------------------------------------------------------
# 登入 / 帳號
# ---------------------------------------------------------------------------
@app.get("/login")
def login_page():
    if session.get("uid"):
        return redirect(url_for("dashboard"))
    return render_template("login.html", first_user=(store.user_count() == 0))


@app.post("/api/auth/login")
def api_login():
    d = request.get_json(force=True)
    u = store.verify_user(d.get("email", ""), d.get("password", ""))
    if not u:
        return jsonify({"error": "email 或密碼錯誤"}), 401
    session.update(uid=u["id"], name=u["name"], role=u["role"], email=u["email"])
    return jsonify({"ok": True})


@app.post("/api/auth/register")
def api_register():
    """只有在系統尚無任何使用者時開放（第一位自動成為管理員）。"""
    if store.user_count() != 0:
        return jsonify({"error": "已有帳號，請由管理員建立新帳號"}), 403
    d = request.get_json(force=True)
    email, pw = (d.get("email") or "").strip(), d.get("password") or ""
    if "@" not in email or len(pw) < 6:
        return jsonify({"error": "請輸入有效 email 與至少 6 碼密碼"}), 400
    uid = store.create_user(email, pw, d.get("name", ""), "admin")
    session.update(uid=uid, name=d.get("name") or email, role="admin", email=email)
    return jsonify({"ok": True})


@app.post("/api/auth/logout")
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/users")
@require_role("admin")
def api_users():
    return jsonify({"users": store.list_users(), "roles": store.ROLE_LABELS})


@app.post("/api/users")
@require_role("admin")
def api_create_user():
    d = request.get_json(force=True)
    email, pw = (d.get("email") or "").strip(), d.get("password") or ""
    if "@" not in email or len(pw) < 6:
        return jsonify({"error": "請輸入有效 email 與至少 6 碼密碼"}), 400
    uid = store.create_user(email, pw, d.get("name", ""), d.get("role", "counter"))
    if not uid:
        return jsonify({"error": "此 email 已存在"}), 409
    return jsonify({"ok": True})


@app.post("/api/users/<int:user_id>/role")
@require_role("admin")
def api_set_role(user_id):
    d = request.get_json(force=True)
    if not store.set_role(user_id, d.get("role", "")):
        return jsonify({"error": "角色無效"}), 400
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# 頁面
# ---------------------------------------------------------------------------
@app.get("/")
@login_required
def dashboard():
    return render_template("dashboard.html", me=me(), stats=store.dashboard_stats(),
                           batches=store.list_batches())


@app.get("/batches/new")
@require_role("admin")
def page_batch_new():
    return render_template("batch_new.html", me=me(), categories=store.categories(),
                           today=date.today().isoformat(),
                           product_count=len(store.load_products()))


@app.get("/batches/<batch_id>/count")
@login_required
def page_count(batch_id):
    b = store.get_batch(batch_id)
    if not b:
        return redirect(url_for("dashboard"))
    return render_template("count.html", me=me(), batch=b)


@app.get("/batches/<batch_id>/review")
@login_required
def page_review(batch_id):
    b = store.get_batch(batch_id)
    if not b:
        return redirect(url_for("dashboard"))
    return render_template("review.html", me=me(), batch=b,
                           adjustments=store.list_adjustments(batch_id))


@app.get("/history")
@login_required
def page_history():
    return render_template("history.html", me=me(), batches=store.list_batches())


@app.get("/sync")
@require_role("admin")
def page_sync():
    return render_template("sync.html", me=me(), status=sheets.status(),
                           logs=store.list_sync_logs())


# ---------------------------------------------------------------------------
# 批次 API
# ---------------------------------------------------------------------------
@app.get("/api/batches")
@login_required
def api_batches():
    return jsonify({"batches": store.list_batches()})


@app.get("/api/batches/<batch_id>")
@login_required
def api_batch(batch_id):
    b = store.get_batch(batch_id)
    if not b:
        return jsonify({"error": "批次不存在"}), 404
    return jsonify({"batch": b, "adjustments": store.list_adjustments(batch_id)})


@app.post("/api/batches")
@require_role("admin")
def api_create_batch():
    d = request.get_json(force=True)
    count_date = (d.get("count_date") or "").strip()
    if not count_date:
        return jsonify({"error": "盤點日期為必填"}), 400
    try:
        bid = store.create_batch(count_date, me()["name"], d.get("title", ""),
                                 d.get("category", ""), d.get("only_codes") or None)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "batch_id": bid})


@app.get("/api/batches/<batch_id>/items")
@login_required
def api_items(batch_id):
    return jsonify({"items": store.list_items(
        batch_id, request.args.get("status", ""), request.args.get("q", ""))})


@app.post("/api/batches/<batch_id>/count")
@require_role("counter", "admin")
def api_count(batch_id):
    d = request.get_json(force=True)
    res, code = store.update_count(
        batch_id, d.get("product_code", ""), d.get("actual_qty"),
        d.get("version"), me()["name"], d.get("note", ""), d.get("diff_reason", ""))
    return jsonify(res), code


@app.post("/api/batches/<batch_id>/review")
@require_role("reviewer", "admin")
def api_review(batch_id):
    d = request.get_json(force=True)
    return jsonify(store.review_items(batch_id, d.get("product_codes", []), me()["name"]))


@app.post("/api/batches/<batch_id>/close")
@require_role("reviewer", "admin")
def api_close(batch_id):
    res = store.close_batch(batch_id)
    return (jsonify(res), 400) if res.get("error") else jsonify(res)


@app.post("/api/batches/<batch_id>/void")
@require_role("admin")
def api_void(batch_id):
    res = store.void_batch(batch_id)
    return (jsonify(res), 400) if res.get("error") else jsonify(res)


@app.post("/api/batches/<batch_id>/adjust")
@require_role("reviewer", "admin")
def api_adjust(batch_id):
    d = request.get_json(force=True)
    if d.get("new_actual") in (None, ""):
        return jsonify({"error": "請輸入調整後數量"}), 400
    res = store.add_adjustment(batch_id, d.get("product_code", ""),
                               d.get("new_actual"), d.get("reason", ""), me()["name"])
    return (jsonify(res), 400) if res.get("error") else jsonify(res)


# ---------------------------------------------------------------------------
# 同步 API
# ---------------------------------------------------------------------------
@app.get("/api/sync/status")
@require_role("admin")
def api_sync_status():
    return jsonify({"status": sheets.status(), "logs": store.list_sync_logs()})


@app.post("/api/sync/source")
@require_role("admin")
def api_sync_source():
    """從來源 Sheet（或本機 CSV）匯入產品到產品主檔。"""
    import datetime
    sync_id = "S" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    try:
        products, src = sheets.read_source_products()
        res = store.import_products(products, source_updated_at=datetime.date.today().isoformat())
        store.log_sync(sync_id, res["added"], res["updated"], res["disabled"], "")
        return jsonify({"ok": True, "source": src, **res})
    except Exception as e:
        store.log_sync(sync_id, 0, 0, 0, str(e))
        return jsonify({"error": f"同步失敗：{e}"}), 500


@app.post("/api/sync/push")
@require_role("admin")
def api_sync_push():
    """把 DB 內容寫回專屬 Sheet 的 5 個工作表（需服務帳號）。"""
    if not sheets.is_configured():
        return jsonify({"error": "尚未設定 Google 服務帳號，無法寫入專屬 Sheet"}), 400
    products = store.load_products(active_only=False)
    batches = store.list_batches()
    items = []
    for b in batches:
        items += store.list_items(b["id"])
    inv = store.inventory_snapshot()
    logs = store.list_sync_logs(500)
    res = sheets.push_to_dedicated(products, batches, items, inv, logs)
    return (jsonify(res), 400) if res.get("error") else jsonify(res)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("DEBUG")))
