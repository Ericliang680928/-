"""口語化銷貨單系統 — Flask 網頁後端（多帳號雲端版）。

啟動（本機）：
    python app.py            → http://127.0.0.1:5000
部署（正式）：
    gunicorn app:app
"""

from __future__ import annotations

import io
import os
from datetime import date
from functools import wraps

from flask import (
    Flask, jsonify, request, send_file, render_template,
    session, redirect, url_for,
)

from sales import store, parser, pivot, llm

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # 部署在 https 時設 SECURE=1，cookie 只走加密連線。
    SESSION_COOKIE_SECURE=bool(os.environ.get("COOKIE_SECURE")),
)


# ---------------------------------------------------------------------------
# 驗證
# ---------------------------------------------------------------------------
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "請先登入", "auth": False}), 401
            return redirect(url_for("login_page"))
        return fn(*args, **kwargs)
    return wrapper


def current_user_id() -> int:
    return session["user_id"]


def current_ws() -> int:
    """目前作用中的帳本 id（資料隔離與團隊共享的單位）。"""
    return store.get_active_workspace_id(current_user_id())


@app.get("/login")
def login_page():
    if session.get("user_id"):
        return redirect(url_for("index"))
    return render_template("login.html")


@app.post("/api/auth/register")
def register():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip()
    pw = data.get("password") or ""
    if "@" not in email or len(pw) < 6:
        return jsonify({"error": "請輸入有效 email 與至少 6 碼密碼"}), 400
    user_id = store.create_user(email, pw)
    if not user_id:
        return jsonify({"error": "此 email 已被註冊"}), 409
    session["user_id"] = user_id
    return jsonify({"ok": True, "email": email})


@app.post("/api/auth/login")
def do_login():
    data = request.get_json(force=True)
    user_id = store.verify_user(data.get("email", ""), data.get("password", ""))
    if not user_id:
        return jsonify({"error": "email 或密碼錯誤"}), 401
    session["user_id"] = user_id
    return jsonify({"ok": True})


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/")
@login_required
def index():
    user = store.get_user(current_user_id())
    return render_template("index.html", user_email=user["email"] if user else "")


# ---------------------------------------------------------------------------
# 帳本 / 團隊
# ---------------------------------------------------------------------------
@app.get("/api/workspaces")
@login_required
def get_workspaces():
    uid = current_user_id()
    ws = current_ws()
    return jsonify({
        "workspaces": store.list_workspaces(uid),
        "current": store.workspace_detail(uid, ws),
    })


@app.post("/api/workspaces")
@login_required
def create_workspace():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "請輸入帳本名稱"}), 400
    store.create_workspace(current_user_id(), name)
    return jsonify({"ok": True})


@app.post("/api/workspaces/switch")
@login_required
def switch_workspace():
    data = request.get_json(force=True)
    if not store.switch_workspace(current_user_id(), int(data.get("workspace_id", 0))):
        return jsonify({"error": "你不是該帳本的成員"}), 403
    return jsonify({"ok": True})


@app.post("/api/workspaces/join")
@login_required
def join_workspace():
    data = request.get_json(force=True)
    ws = store.join_workspace(current_user_id(), data.get("invite_code", ""))
    if not ws:
        return jsonify({"error": "邀請碼無效"}), 404
    return jsonify({"ok": True, "name": ws["name"]})


# ---------------------------------------------------------------------------
# 清單管理
# ---------------------------------------------------------------------------
@app.get("/api/lists")
@login_required
def get_lists():
    ws = current_ws()
    return jsonify({
        "customers": store.load_customers(ws),
        "products": store.load_products(ws),
        "llm_available": llm.is_available(),
    })


@app.post("/api/lists/customers")
@login_required
def set_customers():
    data = request.get_json(force=True)
    items = _parse_customer_text(data.get("text", "")) if "text" in data else data.get("items", [])
    ws = current_ws()
    store.save_customers(ws, items)
    return jsonify({"customers": store.load_customers(ws)})


@app.post("/api/lists/products")
@login_required
def set_products():
    data = request.get_json(force=True)
    items = _parse_product_text(data.get("text", "")) if "text" in data else data.get("items", [])
    ws = current_ws()
    store.save_products(ws, items)
    return jsonify({"products": store.load_products(ws)})


def _parse_customer_text(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.replace("\t", ",").split(",")]
        out.append({"name": parts[0], "aliases": parts[1:] if len(parts) > 1 else []})
    return out


def _parse_product_text(text: str) -> list[dict]:
    """每行：產品名稱[,編號][,別名...]  或  編號<tab>名稱。"""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.replace("\t", ",").split(",")]
        name, code, aliases = parts[0], "", []
        if len(parts) > 1:
            code = parts[1]
            aliases = parts[2:]
        out.append({"name": name, "code": code, "aliases": aliases})
    return out


# ---------------------------------------------------------------------------
# 解析（預覽，不存檔）
# ---------------------------------------------------------------------------
@app.post("/api/parse")
@login_required
def api_parse():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    use_llm = data.get("use_llm", True)
    today = _today(data.get("today"))
    ws = current_ws()
    customers = store.load_customers(ws)
    products = store.load_products(ws)

    if not text:
        return jsonify({"error": "請輸入內容"}), 400

    res = parser.parse(text, customers, products, today=today)
    out = res.to_dict()
    out["source"] = "rule"

    if use_llm and res.needs_review and llm.is_available():
        llm_res = llm.parse(text, customers, products, today=today)
        if llm_res:
            out = _merge_llm(out, llm_res)
            out["source"] = "llm"
    return jsonify(out)


def _merge_llm(rule_out: dict, llm_res: dict) -> dict:
    merged = dict(rule_out)
    merged["date"] = llm_res.get("date") or rule_out.get("date")
    merged["customer_name"] = llm_res.get("customer_name") or rule_out.get("customer_name")
    items = []
    for it in llm_res.get("items", []):
        items.append({
            "product_name": it.get("product_name", ""),
            "product_code": it.get("product_code", ""),
            "quantity": it.get("quantity", 0),
            "unit": it.get("unit", ""),
            "score": 1.0,
            "raw": "",
        })
    if items:
        merged["items"] = items
    merged["notes"] = (rule_out.get("notes") or []) + (llm_res.get("notes") or [])
    merged["needs_review"] = False
    return merged


# ---------------------------------------------------------------------------
# 銷貨紀錄
# ---------------------------------------------------------------------------
@app.get("/api/records")
@login_required
def get_records():
    return jsonify({"records": store.load_records(current_ws())})


@app.post("/api/records")
@login_required
def add_records():
    data = request.get_json(force=True)
    d = data.get("date") or date.today().isoformat()
    customer = data.get("customer_name", "")
    rows = []
    for it in data.get("items", []):
        if not (it.get("product_name") or it.get("product_code")):
            continue
        rows.append({
            "date": d,
            "customer_name": customer,
            "product_name": it.get("product_name", ""),
            "product_code": it.get("product_code", ""),
            "quantity": it.get("quantity", 0),
            "unit": it.get("unit", ""),
            "raw": data.get("raw", ""),
        })
    if not rows:
        return jsonify({"error": "沒有可儲存的品項"}), 400
    n = store.add_records(current_ws(), rows, created_by=current_user_id())
    return jsonify({"ok": True, "added": n})


@app.delete("/api/records/<record_id>")
@login_required
def del_record(record_id):
    return jsonify({"ok": store.delete_record(current_ws(), record_id)})


@app.post("/api/records/clear")
@login_required
def clear_records():
    store.clear_records(current_ws())
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# 統計 / 匯出
# ---------------------------------------------------------------------------
@app.get("/api/pivot")
@login_required
def api_pivot():
    return jsonify(pivot.build_pivot(store.load_records(current_ws())))


@app.get("/api/export/xlsx")
@login_required
def export_xlsx():
    content = pivot.to_xlsx(store.load_records(current_ws()))
    return send_file(
        io.BytesIO(content),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="銷售統計表.xlsx",
    )


@app.get("/api/export/csv")
@login_required
def export_csv():
    content = pivot.to_csv(store.load_records(current_ws()))
    return send_file(
        io.BytesIO(content.encode("utf-8")),
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name="銷售統計表.csv",
    )


def _today(value):
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return date.today()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("DEBUG")))
