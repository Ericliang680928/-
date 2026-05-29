"""清單與銷貨紀錄的儲存（純檔案，零外部資料庫）。

檔案：
  data/customers.csv : name[,aliases]   顧客清單（aliases 用 | 分隔，選填）
  data/products.csv  : name,code[,aliases]  產品清單（含產品編號）
  data/sales.json    : 已確認的銷貨紀錄
"""

from __future__ import annotations

import csv
import json
import os
import threading
import uuid
from datetime import datetime
from typing import Optional

_LOCK = threading.Lock()
DATA_DIR = os.environ.get("SALES_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
CUSTOMERS_CSV = os.path.join(DATA_DIR, "customers.csv")
PRODUCTS_CSV = os.path.join(DATA_DIR, "products.csv")
SALES_JSON = os.path.join(DATA_DIR, "sales.json")


def _ensure() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _split_aliases(value: str) -> list[str]:
    return [a.strip() for a in (value or "").replace("、", "|").replace(",", "|").split("|") if a.strip()]


# ---------------------------------------------------------------------------
# 清單
# ---------------------------------------------------------------------------
def load_customers() -> list[dict]:
    _ensure()
    if not os.path.exists(CUSTOMERS_CSV):
        return []
    out = []
    with open(CUSTOMERS_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or row.get("顧客名稱") or "").strip()
            if not name:
                continue
            out.append({"name": name, "aliases": _split_aliases(row.get("aliases") or row.get("別名") or "")})
    return out


def load_products() -> list[dict]:
    _ensure()
    if not os.path.exists(PRODUCTS_CSV):
        return []
    out = []
    with open(PRODUCTS_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or row.get("產品名稱") or "").strip()
            if not name:
                continue
            out.append({
                "name": name,
                "code": (row.get("code") or row.get("產品編號") or "").strip(),
                "aliases": _split_aliases(row.get("aliases") or row.get("別名") or ""),
            })
    return out


def save_customers(items: list[dict]) -> None:
    _ensure()
    with _LOCK, open(CUSTOMERS_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["name", "aliases"])
        for it in items:
            w.writerow([it.get("name", ""), "|".join(it.get("aliases", []) or [])])


def save_products(items: list[dict]) -> None:
    _ensure()
    with _LOCK, open(PRODUCTS_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["name", "code", "aliases"])
        for it in items:
            w.writerow([it.get("name", ""), it.get("code", ""), "|".join(it.get("aliases", []) or [])])


# ---------------------------------------------------------------------------
# 銷貨紀錄
# ---------------------------------------------------------------------------
def load_records() -> list[dict]:
    _ensure()
    if not os.path.exists(SALES_JSON):
        return []
    with open(SALES_JSON, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _write_records(records: list[dict]) -> None:
    with open(SALES_JSON, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def add_records(rows: list[dict]) -> list[dict]:
    """新增多筆銷貨紀錄，回傳含 id 的完整列表。"""
    _ensure()
    with _LOCK:
        records = load_records()
        for r in rows:
            r = dict(r)
            r.setdefault("id", uuid.uuid4().hex[:12])
            r.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
            records.append(r)
        _write_records(records)
        return records


def delete_record(record_id: str) -> bool:
    with _LOCK:
        records = load_records()
        new = [r for r in records if r.get("id") != record_id]
        if len(new) == len(records):
            return False
        _write_records(new)
        return True


def clear_records() -> None:
    with _LOCK:
        _write_records([])
