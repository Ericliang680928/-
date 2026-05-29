"""口語化銷貨單系統 — Flask 網頁後端。

啟動：
    python app.py
    然後瀏覽器開 http://127.0.0.1:5000

流程：輸入口語 → /api/parse 預覽（可手動修正）→ /api/records 確認存檔
      → /api/pivot 看統計表 → /api/export 匯出 Excel / CSV
"""

from __future__ import annotations

from datetime import date

from flask import Flask, jsonify, request, send_file, render_template
import io

from sales import store, parser, pivot, llm

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# 清單管理
# ---------------------------------------------------------------------------
@app.get("/api/lists")
def get_lists():
    return jsonify({
        "customers": store.load_customers(),
        "products": store.load_products(),
        "llm_available": llm.is_available(),
    })


@app.post("/api/lists/customers")
def set_customers():
    data = request.get_json(force=True)
    items = _parse_customer_text(data.get("text", "")) if "text" in data else data.get("items", [])
    store.save_customers(items)
    return jsonify({"customers": store.load_customers()})


@app.post("/api/lists/products")
def set_products():
    data = request.get_json(force=True)
    items = _parse_product_text(data.get("text", "")) if "text" in data else data.get("items", [])
    store.save_products(items)
    return jsonify({"products": store.load_products()})


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
def api_parse():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    use_llm = data.get("use_llm", True)
    today = _today(data.get("today"))
    customers = store.load_customers()
    products = store.load_products()

    if not text:
        return jsonify({"error": "請輸入內容"}), 400

    res = parser.parse(text, customers, products, today=today)
    out = res.to_dict()
    out["source"] = "rule"

    # 規則信心不足 → 嘗試 AI 補強
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
def get_records():
    return jsonify({"records": store.load_records()})


@app.post("/api/records")
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
    store.add_records(rows)
    return jsonify({"ok": True, "added": len(rows)})


@app.delete("/api/records/<record_id>")
def del_record(record_id):
    return jsonify({"ok": store.delete_record(record_id)})


@app.post("/api/records/clear")
def clear_records():
    store.clear_records()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# 統計 / 匯出
# ---------------------------------------------------------------------------
@app.get("/api/pivot")
def api_pivot():
    return jsonify(pivot.build_pivot(store.load_records()))


@app.get("/api/export/xlsx")
def export_xlsx():
    content = pivot.to_xlsx(store.load_records())
    return send_file(
        io.BytesIO(content),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="銷售統計表.xlsx",
    )


@app.get("/api/export/csv")
def export_csv():
    content = pivot.to_csv(store.load_records())
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
    import os
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("DEBUG")))
