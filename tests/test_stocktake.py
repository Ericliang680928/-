"""庫存盤點核心邏輯測試（不需 Google）。

執行：STOCKTAKE_DB=/tmp/st_test.db python tests/test_stocktake.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["STOCKTAKE_DB"] = tempfile.mktemp(suffix=".db")

from stocktake import store  # noqa: E402


def fresh():
    # 每次測試用乾淨 DB
    for ext in ("", "-wal", "-shm"):
        p = os.environ["STOCKTAKE_DB"] + ext
        if os.path.exists(p):
            os.remove(p)
    store.init_db()


def seed_products():
    store.import_products([
        {"code": "A001", "name": "可樂", "category": "飲料"},
        {"code": "B001", "name": "礦泉水", "category": "飲料"},
        {"code": "C001", "name": "白米", "category": "米類"},
    ], source_updated_at="2026-05-29")
    store.set_book_qty("A001", 10)
    store.set_book_qty("B001", 5)
    store.set_book_qty("C001", 20)


def test_import_and_disable():
    fresh()
    r = store.import_products([{"code": "A001", "name": "可樂", "category": "飲料"}])
    assert r["added"] == 1
    r = store.import_products([{"code": "A001", "name": "可口可樂", "category": "飲料"}])
    assert r["updated"] == 1
    # 來源不再有 A001 → 停用
    r = store.import_products([{"code": "Z999", "name": "新品", "category": "其他"}])
    assert r["disabled"] == 1
    assert len(store.load_products(active_only=True)) == 1  # 只剩 Z999


def test_create_batch_snapshot():
    fresh(); seed_products()
    bid = store.create_batch("2026-05-29", "管理員")
    items = store.list_items(bid)
    assert len(items) == 3
    assert all(i["status"] == "未盤" for i in items)
    a = next(i for i in items if i["product_code"] == "A001")
    assert a["book_qty_snapshot"] == 10


def test_count_status_and_diff():
    fresh(); seed_products()
    bid = store.create_batch("2026-05-29", "員工")
    # 實盤=帳面 → 已盤
    res, code = store.update_count(bid, "A001", 10, 0, "員工")
    assert code == 200 and res["item"]["status"] == "已盤" and res["item"]["diff_qty"] == 0
    # 實盤≠帳面 → 差異
    res, code = store.update_count(bid, "B001", 3, 0, "員工")
    assert res["item"]["status"] == "差異" and res["item"]["diff_qty"] == -2


def test_optimistic_lock_conflict():
    fresh(); seed_products()
    bid = store.create_batch("2026-05-29", "員工")
    # 甲讀到 version 0 並寫入 → version 變 1
    res, code = store.update_count(bid, "A001", 9, 0, "甲")
    assert code == 200
    # 乙仍拿著舊 version 0 寫入 → 衝突
    res, code = store.update_count(bid, "A001", 8, 0, "乙")
    assert code == 409 and res.get("conflict") is True
    # 乙拿正確 version 1 → 成功
    res, code = store.update_count(bid, "A001", 8, 1, "乙")
    assert code == 200 and res["item"]["actual_qty"] == 8


def test_review_then_recount_resets():
    fresh(); seed_products()
    bid = store.create_batch("2026-05-29", "員工")
    store.update_count(bid, "B001", 3, 0, "員工")
    store.review_items(bid, ["B001"], "覆核員")
    items = store.list_items(bid, status="已覆核")
    assert len(items) == 1
    # 覆核後再被改 → 退回需重新覆核
    v = items[0]["version"]
    res, code = store.update_count(bid, "B001", 4, v, "員工")
    assert res["item"]["status"] == "差異" and res["item"]["reviewer"] == ""


def test_close_applies_to_inventory_and_freezes():
    fresh(); seed_products()
    bid = store.create_batch("2026-05-29", "員工")
    store.update_count(bid, "A001", 7, 0, "員工")
    r = store.close_batch(bid)
    assert r["ok"] and r["applied"] == 1
    inv = {x["product_code"]: x for x in store.inventory_snapshot()}
    assert inv["A001"]["book_qty"] == 7  # 實盤套用到帳面
    # 結案後不可再盤點
    res, code = store.update_count(bid, "A001", 6, 0, "員工")
    assert code == 409


def test_adjustment_after_close():
    fresh(); seed_products()
    bid = store.create_batch("2026-05-29", "員工")
    store.update_count(bid, "A001", 7, 0, "員工")
    store.close_batch(bid)
    # 進行中不能調整；結案後可以
    r = store.add_adjustment(bid, "A001", 6, "重數", "覆核員")
    assert r["ok"]
    adj = store.list_adjustments(bid)
    assert len(adj) == 1 and adj[0]["new_actual"] == 6 and adj[0]["old_actual"] == 7
    inv = {x["product_code"]: x for x in store.inventory_snapshot()}
    assert inv["A001"]["book_qty"] == 6


def test_spec_carried_through():
    fresh()
    store.import_products([
        {"code": "A001", "name": "白米", "category": "米類", "spec": "整件"},
    ], source_updated_at="2026-05-29")
    p = store.load_products()[0]
    assert p["spec"] == "整件"
    bid = store.create_batch("2026-05-29", "管理員")
    it = store.list_items(bid)[0]
    assert it["spec_snapshot"] == "整件"


def test_diff_report():
    from stocktake import report
    fresh(); seed_products()
    bid = store.create_batch("2026-05-29", "員工")
    store.update_count(bid, "A001", 10, 0, "員工")   # 無差異
    store.update_count(bid, "B001", 3, 0, "員工")    # -2 盤虧
    store.update_count(bid, "C001", 25, 0, "員工")   # +5 盤盈
    items = store.list_items(bid)
    rows = report.select_rows(items, only_diff=True, sort="diff")
    assert [r["product_code"] for r in rows] == ["C001", "B001"]  # 依差異絕對值大→小
    s = report.summarize(rows)
    assert s["count"] == 2 and s["over"] == 1 and s["short"] == 1 and s["abs_sum"] == 7
    xlsx = report.to_xlsx(store.get_batch(bid), items, [], only_diff=True, sort="category")
    assert xlsx[:2] == b"PK" and len(xlsx) > 0  # 合法 .xlsx
    csv_txt = report.to_csv(store.get_batch(bid), items, [])
    assert "差異報表" in csv_txt and "B001" in csv_txt


def test_roles_and_users():
    fresh()
    uid = store.create_user("a@t.com", "secret1", "管理員", "admin")
    assert uid
    assert store.create_user("a@t.com", "x", "dup", "admin") is None  # 重複
    assert store.verify_user("a@t.com", "secret1")["role"] == "admin"
    assert store.verify_user("a@t.com", "wrong") is None
    store.create_user("b@t.com", "secret2", "盤點員", "counter")
    store.set_role(2, "reviewer")
    assert store.get_user(2)["role"] == "reviewer"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn(); passed += 1; print(f"  ✓ {fn.__name__}")
        except Exception:
            print(f"  ✗ {fn.__name__}"); traceback.print_exc()
    print(f"\n{passed}/{len(fns)} 通過")
    sys.exit(0 if passed == len(fns) else 1)
