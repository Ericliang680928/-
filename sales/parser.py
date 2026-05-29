"""離線規則解析：把一句口語銷貨內容拆成「日期 / 顧客 / 多筆(產品+數量)」。

支援的口語型態（範例）：
  「今天王小明買了三箱可樂跟兩瓶礦泉水」
  「5月20號 大同公司 訂 A001 50 個，礦泉水 12」
  「昨天賣給老王可口可樂 3 箱、雪碧兩箱」

設計重點：
  1. 先抽日期、再抽顧客（兩者都用模糊比對校正回清單）。
  2. 產品與數量採「以數量為錨點」配對——不論「三箱可樂」或「可樂三箱」都能對。
  3. 任何低信心的結果都標記 needs_review，交給上層決定是否呼叫 AI 補強。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from typing import Optional

from . import matcher

# ---------------------------------------------------------------------------
# 中文數字
# ---------------------------------------------------------------------------
_CN_DIGIT = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "壹": 1, "貳": 2, "參": 3,
    "肆": 4, "伍": 5, "陸": 6, "柒": 7, "捌": 8, "玖": 9,
}
_CN_UNIT = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000, "萬": 10000, "万": 10000}
_CN_NUM_CHARS = set(_CN_DIGIT) | set(_CN_UNIT)

# 常見計量單位（用來界定數量 token 並可保留單位資訊）。
_UNITS = ["箱", "瓶", "罐", "包", "盒", "打", "個", "顆", "支", "件", "台", "組", "份", "袋", "桶", "條", "把", "張", "本", "杯", "斤", "公斤", "公升", "ml", "g", "kg"]
_UNIT_RE = "|".join(sorted(_UNITS, key=len, reverse=True))


def cn_to_int(s: str) -> Optional[int]:
    """中文數字字串轉整數，支援『十五 / 二十 / 一百二十 / 兩千』等。失敗回 None。"""
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)
    total = 0
    section = 0
    current = 0
    for ch in s:
        if ch in _CN_DIGIT:
            current = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            unit = _CN_UNIT[ch]
            if unit >= 10000:
                section = (section + (current or 0)) * unit
                total += section
                section = 0
            else:
                if current == 0:
                    current = 1  # 「十五」開頭的十
                section += current * unit
            current = 0
        else:
            return None
    return total + section + current


# 數字 token：阿拉伯數字或一串中文數字，後面可帶單位。
_QTY_RE = re.compile(
    r"(?P<num>[0-9]+(?:\.[0-9]+)?|[零〇一二兩两三四五六七八九十拾百佰千仟萬万壹貳參肆伍陸柒捌玖]+)"
    r"\s*(?P<unit>" + _UNIT_RE + r")?"
)


@dataclass
class Item:
    product_name: str = ""
    product_code: str = ""
    quantity: float = 0
    unit: str = ""
    raw: str = ""
    score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParseResult:
    date: str = ""              # ISO yyyy-mm-dd
    date_text: str = ""         # 原句中辨識到的日期講法
    customer_name: str = ""
    customer_score: float = 0.0
    items: list[Item] = field(default_factory=list)
    raw: str = ""
    needs_review: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# 日期
# ---------------------------------------------------------------------------
_REL_DAYS = {
    "今天": 0, "今日": 0, "本日": 0, "當天": 0,
    "明天": 1, "明日": 1, "後天": 2, "后天": 2, "大後天": 3,
    "昨天": -1, "昨日": -1, "前天": -2, "大前天": -3,
}


def _parse_date(text: str, today: date) -> tuple[str, str, str]:
    """回傳 (iso_date, matched_text, remaining_text)。找不到則用 today。"""
    for word, delta in _REL_DAYS.items():
        if word in text:
            d = today + timedelta(days=delta)
            return d.isoformat(), word, text.replace(word, "", 1)

    # yyyy-mm-dd / yyyy/mm/dd
    m = re.search(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", text)
    if m:
        y, mo, da = map(int, m.groups())
        return _safe_date(y, mo, da, today), m.group(0), text.replace(m.group(0), "", 1)

    # X月Y日 / X月Y號
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日號号]?", text)
    if m:
        mo, da = int(m.group(1)), int(m.group(2))
        return _safe_date(today.year, mo, da, today), m.group(0), text.replace(m.group(0), "", 1)

    # m/d（無年份，視為今年）
    m = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", text)
    if m:
        mo, da = int(m.group(1)), int(m.group(2))
        return _safe_date(today.year, mo, da, today), m.group(0), text.replace(m.group(0), "", 1)

    return today.isoformat(), "", text


def _safe_date(y: int, mo: int, da: int, fallback: date) -> str:
    try:
        return date(y, mo, da).isoformat()
    except ValueError:
        return fallback.isoformat()


# ---------------------------------------------------------------------------
# 主解析
# ---------------------------------------------------------------------------
# 切分多筆商品用的連接詞 / 標點。
_SPLIT_RE = re.compile(r"[、，,；;。\n]|還有|另外|加上|以及|和|跟|與|還要|再")
_FILLER = ["買了", "買", "訂了", "訂購", "訂", "賣給", "賣了", "賣", "要了", "要", "拿了", "拿", "出貨", "進貨", "給", "幫", "客戶", "顧客", "公司", "先生", "小姐", "老闆"]


def parse(
    text: str,
    customers: list[dict],
    products: list[dict],
    today: Optional[date] = None,
    cust_threshold: float = 0.45,
    prod_threshold: float = 0.45,
) -> ParseResult:
    today = today or date.today()
    res = ParseResult(raw=text)
    work = matcher.normalize(text)

    # 1) 日期
    iso, dtext, work = _parse_date(work, today)
    res.date, res.date_text = iso, dtext

    # 2) 顧客（用整句殘文做最佳比對）
    if customers:
        cust = matcher.best_match(work, customers, threshold=cust_threshold)
        if cust:
            res.customer_name = cust.get("name", "")
            res.customer_score = cust.get("_score", 0.0)
            # 從工作字串移除命中的顧客講法，避免干擾產品比對。
            work = work.replace(matcher.normalize(cust["_matched"]), " ", 1)
        else:
            res.notes.append("顧客無法對應清單")
            res.needs_review = True

    # 3) 產品 + 數量：以數量 token 為錨點
    res.items = _extract_items(work, products, prod_threshold, res)
    if not res.items:
        res.notes.append("找不到任何產品/數量")
        res.needs_review = True
    return res


def _clean_segment(seg: str) -> str:
    for f in _FILLER:
        seg = seg.replace(f, " ")
    return seg.strip()


def _extract_items(work: str, products: list[dict], threshold: float, res: ParseResult) -> list[Item]:
    matches = list(_QTY_RE.finditer(work))
    items: list[Item] = []
    if not matches:
        return items

    # 數量錨點之間的文字片段（gaps[i] 在 matches[i] 之前；gaps[-1] 在最後）。
    gaps: list[str] = []
    prev_end = 0
    for m in matches:
        gaps.append(work[prev_end : m.start()])
        prev_end = m.end()
    gaps.append(work[prev_end:])

    cands = [
        (matcher.best_match(_clean_segment(g), products, threshold=0) if _clean_segment(g) else None)
        for g in gaps
    ]

    # 判斷整句語序：每個數量配「後方片段」(數量在前，如『三箱可樂』)
    # 還是「前方片段」(產品在前，如『可樂三箱』)。取整體分數較高的方向，
    # 因為同一句通常方向一致，這比逐項各自猜更穩。
    n = len(matches)
    after_score = sum(_s(cands[i + 1]) for i in range(n))   # qty[i] -> gaps[i+1]
    before_score = sum(_s(cands[i]) for i in range(n))      # qty[i] -> gaps[i]
    offset = 1 if after_score >= before_score else 0

    for i, m in enumerate(matches):
        num = m.group("num")
        qty = float(num) if _is_float(num) else cn_to_int(num)
        if qty is None:
            continue
        unit = m.group("unit") or ""
        cand = cands[i + offset]
        seg = _clean_segment(gaps[i + offset])

        item = Item(quantity=qty, unit=unit)
        if cand and cand.get("_score", 0) >= threshold:
            item.product_name = cand.get("name", "")
            item.product_code = cand.get("code", "")
            item.score = cand.get("_score", 0.0)
            item.raw = seg
        else:
            # 低信心：保留原始文字，標記待確認。
            item.product_name = seg
            item.score = cand.get("_score", 0.0) if cand else 0.0
            item.raw = seg
            res.needs_review = True
            res.notes.append(f"產品『{seg or '?'}』信心不足，請確認")
        items.append(item)
    return items


def _s(cand: Optional[dict]) -> float:
    return cand.get("_score", 0.0) if cand else 0.0


def _is_float(num: str) -> bool:
    return bool(re.fullmatch(r"[0-9]+\.[0-9]+", num))
