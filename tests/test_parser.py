"""規則解析的核心測試。執行：python -m pytest -q  （或 python tests/test_parser.py）"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sales import parser, matcher, pivot

CUSTOMERS = [
    {"name": "大同公司", "aliases": ["大同"]},
    {"name": "王小明", "aliases": ["老王", "小明"]},
    {"name": "全家便利商店", "aliases": ["全家"]},
]
PRODUCTS = [
    {"name": "可口可樂", "code": "A001", "aliases": ["可樂", "coke"]},
    {"name": "礦泉水", "code": "B001", "aliases": ["水"]},
    {"name": "雪碧", "code": "A003", "aliases": ["sprite"]},
    {"name": "御茶園綠茶", "code": "B002", "aliases": ["綠茶"]},
]
TODAY = date(2026, 5, 29)


def _p(text):
    return parser.parse(text, CUSTOMERS, PRODUCTS, today=TODAY)


def test_cn_to_int():
    assert parser.cn_to_int("三") == 3
    assert parser.cn_to_int("十五") == 15
    assert parser.cn_to_int("二十") == 20
    assert parser.cn_to_int("一百二十") == 120
    assert parser.cn_to_int("兩千") == 2000
    assert parser.cn_to_int("50") == 50


def test_relative_date():
    assert _p("今天王小明買可樂三箱").date == "2026-05-29"
    assert _p("昨天王小明買可樂三箱").date == "2026-05-28"
    assert _p("前天王小明買可樂三箱").date == "2026-05-27"


def test_explicit_date():
    assert _p("5月20號大同公司買可樂50個").date == "2026-05-20"
    assert _p("2026/01/03 大同 可樂 5 箱").date == "2026-01-03"


def test_customer_fuzzy():
    assert _p("今天老王買可樂三箱").customer_name == "王小明"
    assert _p("大同訂可樂50個").customer_name == "大同公司"


def test_single_item_qty_first():
    r = _p("今天王小明買了三箱可口可樂")
    assert len(r.items) == 1
    it = r.items[0]
    assert it.product_name == "可口可樂"
    assert it.product_code == "A001"
    assert it.quantity == 3
    assert it.unit == "箱"


def test_single_item_qty_last():
    r = _p("大同公司可樂三箱")
    assert r.items[0].product_name == "可口可樂"
    assert r.items[0].quantity == 3


def test_multiple_items():
    r = _p("今天王小明買了三箱可口可樂跟兩瓶礦泉水")
    names = {(i.product_name, i.quantity) for i in r.items}
    assert ("可口可樂", 3) in names
    assert ("礦泉水", 2) in names


def test_alias_and_code():
    r = _p("全家訂可樂50個、水12瓶")
    by_code = {i.product_code: i.quantity for i in r.items}
    assert by_code.get("A001") == 50
    assert by_code.get("B001") == 12
    assert r.customer_name == "全家便利商店"


def test_pivot_cross_table():
    records = [
        {"date": "2026-05-20", "product_name": "可口可樂", "product_code": "A001", "quantity": 3},
        {"date": "2026-05-20", "product_name": "可口可樂", "product_code": "A001", "quantity": 2},
        {"date": "2026-05-21", "product_name": "可口可樂", "product_code": "A001", "quantity": 4},
        {"date": "2026-05-20", "product_name": "礦泉水", "product_code": "B001", "quantity": 10},
    ]
    p = pivot.build_pivot(records)
    assert p["dates"] == ["2026-05-20", "2026-05-21"]
    assert p["matrix"]["可口可樂"]["2026-05-20"] == 5  # 3+2 同日加總
    assert p["matrix"]["可口可樂"]["2026-05-21"] == 4
    assert p["row_totals"]["可口可樂"] == 9
    assert p["col_totals"]["2026-05-20"] == 15
    assert p["grand_total"] == 19


def test_pivot_xlsx_bytes():
    records = [{"date": "2026-05-20", "product_name": "可口可樂", "product_code": "A001", "quantity": 3}]
    data = pivot.to_xlsx(records)
    assert data[:2] == b"PK"  # xlsx 是 zip 格式


def test_matcher_threshold():
    assert matcher.best_match("完全不相關的東西xyz", PRODUCTS, threshold=0.5) is None


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
