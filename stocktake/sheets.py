"""Google Sheets 同步層（服務帳號）。

設計：
  * 部署後用 Google 服務帳號讀「來源產品 Sheet」、寫「專屬盤點 Sheet」。
  * 未設定憑證 / 未安裝 gspread / 連不到 Google 時「優雅退化」：
    來源產品改讀本機 stocktake/data/source_products.csv，其餘同步功能回傳提示。
  * 專屬 Sheet 的 5 個工作表若不存在會自動建立（含表頭）。

環境變數：
  GOOGLE_SERVICE_ACCOUNT_JSON  服務帳號金鑰：檔案路徑或直接貼 JSON 內容
  SOURCE_SHEET_ID              來源產品試算表 ID
  SOURCE_WORKSHEET             來源工作表名稱（預設 產品名單）
  DEDICATED_SHEET_ID           專屬盤點試算表 ID
"""

from __future__ import annotations

import csv
import json
import os
from typing import Optional

SOURCE_SHEET_ID = os.environ.get("SOURCE_SHEET_ID", "1JOpCUfAS3YEHHGUq_NR8twxGzDh7C0_p7bZAdOc0tf0")
SOURCE_WORKSHEET = os.environ.get("SOURCE_WORKSHEET", "產品名單")
DEDICATED_SHEET_ID = os.environ.get("DEDICATED_SHEET_ID", "1-t5dPhduceaVwVk3vtoestXPOKR6_yk9xHKCtiS-Ipc")

_LOCAL_SOURCE = os.path.join(os.path.dirname(__file__), "data", "source_products.csv")

# 專屬 Sheet 各工作表表頭（與需求一致）
TAB_HEADERS = {
    "產品主檔": ["商品編號", "商品名稱", "類別", "啟用狀態", "來源更新時間", "同步時間"],
    "盤點批次": ["批次ID", "盤點日期", "建立人", "開始時間", "完成時間", "狀態"],
    "盤點明細": ["批次ID", "盤點日期", "商品編號", "商品名稱快照", "類別快照", "帳面庫存快照",
               "實盤庫存", "差異數量", "差異原因", "備註", "盤點人員", "盤點時間", "覆核人員", "覆核時間"],
    "庫存現況": ["商品編號", "目前帳面庫存", "最近盤點日期", "最近異動時間"],
    "同步日誌": ["同步批次ID", "同步時間", "新增筆數", "更新筆數", "停用筆數", "錯誤訊息"],
}


def _creds_info() -> Optional[dict]:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return None
    if raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    if os.path.exists(raw):
        with open(raw, encoding="utf-8") as f:
            return json.load(f)
    return None


def is_configured() -> bool:
    """是否具備用服務帳號連 Google 的條件。"""
    if _creds_info() is None:
        return False
    try:
        import gspread  # noqa: F401
    except ImportError:
        return False
    return True


def status() -> dict:
    info = _creds_info()
    try:
        import gspread  # noqa: F401
        has_lib = True
    except ImportError:
        has_lib = False
    return {
        "configured": is_configured(),
        "has_credentials": info is not None,
        "service_account_email": (info or {}).get("client_email", ""),
        "gspread_installed": has_lib,
        "source_sheet_id": SOURCE_SHEET_ID,
        "source_worksheet": SOURCE_WORKSHEET,
        "dedicated_sheet_id": DEDICATED_SHEET_ID,
    }


def _client():
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(_creds_info(), scopes=scopes)
    return gspread.authorize(creds)


# ---------------------------------------------------------------------------
# 讀來源產品
# ---------------------------------------------------------------------------
def read_source_products() -> tuple[list[dict], str]:
    """回傳 (products, source 描述)。未連線 Google 時讀本機 CSV。"""
    if is_configured():
        gc = _client()
        sh = gc.open_by_key(SOURCE_SHEET_ID)
        ws = sh.worksheet(SOURCE_WORKSHEET)
        records = ws.get_all_records()  # 以第一列為表頭
        out = []
        for r in records:
            out.append({
                "code": str(r.get("商品編號", "")).strip(),
                "name": str(r.get("商品名稱", "")).strip(),
                "category": str(r.get("類別", "")).strip(),
            })
        return [r for r in out if r["code"]], f"Google Sheet：{SOURCE_WORKSHEET}"

    # 退化：本機 CSV
    out = []
    if os.path.exists(_LOCAL_SOURCE):
        with open(_LOCAL_SOURCE, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                code = (r.get("商品編號") or "").strip()
                if code:
                    out.append({"code": code, "name": (r.get("商品名稱") or "").strip(),
                                "category": (r.get("類別") or "").strip()})
    return out, "本機 CSV（未設定 Google 憑證）"


# ---------------------------------------------------------------------------
# 寫專屬 Sheet
# ---------------------------------------------------------------------------
def _ensure_tabs(sh):
    existing = {ws.title for ws in sh.worksheets()}
    for title, header in TAB_HEADERS.items():
        if title not in existing:
            ws = sh.add_worksheet(title=title, rows=200, cols=max(len(header), 6))
            ws.update([header], "A1")


def push_to_dedicated(products, batches, items, inventory, sync_logs) -> dict:
    """把 DB 內容覆寫到專屬 Sheet 的對應工作表。未設定則回傳提示。"""
    if not is_configured():
        return {"error": "尚未設定 Google 服務帳號，無法寫入專屬 Sheet"}
    gc = _client()
    sh = gc.open_by_key(DEDICATED_SHEET_ID)
    _ensure_tabs(sh)

    def write(tab, header, rows):
        ws = sh.worksheet(tab)
        ws.clear()
        ws.update([header] + rows, "A1", value_input_option="USER_ENTERED")

    write("產品主檔", TAB_HEADERS["產品主檔"],
          [[p["code"], p["name"], p["category"], "啟用" if p["active"] else "停用",
            p["source_updated_at"], p["synced_at"]] for p in products])
    write("盤點批次", TAB_HEADERS["盤點批次"],
          [[b["id"], b["count_date"], b["created_by"], b["started_at"], b["finished_at"], b["status"]]
           for b in batches])
    write("盤點明細", TAB_HEADERS["盤點明細"],
          [[it["batch_id"], it["count_date"], it["product_code"], it["name_snapshot"],
            it["category_snapshot"], it["book_qty_snapshot"], it["actual_qty"], it["diff_qty"],
            it["diff_reason"], it["note"], it["counter"], it["counted_at"], it["reviewer"], it["reviewed_at"]]
           for it in items])
    write("庫存現況", TAB_HEADERS["庫存現況"],
          [[r["product_code"], r["book_qty"], r["last_count_date"], r["last_moved_at"]] for r in inventory])
    write("同步日誌", TAB_HEADERS["同步日誌"],
          [[s["sync_batch_id"], s["synced_at"], s["added"], s["updated"], s["disabled"], s["error"]]
           for s in sync_logs])
    return {"ok": True}
