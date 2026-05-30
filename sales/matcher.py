"""中文模糊比對：把口語的講法對應回「顧客清單 / 產品清單」裡最接近的正式名稱。

這是提高口語準確度的核心。原理：
口語常有簡稱、同音字、口誤（例如「可樂」對「可口可樂」、「老王」對「王老闆」）。
有了清單當字典，我們就用字元層級的相似度把講法校正回標準答案，並回傳產品編號。
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Iterable, Optional

# 全形數字 / 標點 → 半形，並統一英數大小寫，降低比對雜訊。
_FULLWIDTH = {ord("　"): " "}
for _i in range(0xFF01, 0xFF5F):
    _FULLWIDTH[_i] = _i - 0xFEE0


def normalize(text: str) -> str:
    """正規化：全形轉半形、去除空白、英文轉小寫。"""
    if not text:
        return ""
    text = text.translate(_FULLWIDTH)
    return "".join(text.split()).lower()


def _bigrams(s: str) -> set[str]:
    if len(s) <= 1:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _bigram_jaccard(a: str, b: str) -> float:
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba or not bb:
        return 0.0
    inter = len(ba & bb)
    union = len(ba | bb)
    return inter / union if union else 0.0


def _lcs_ratio(window: str, candidate: str) -> float:
    """候選字串在視窗文字裡的「最長共同子字串 / 候選長度」。

    例：window=「買了三箱可樂」, candidate=「可樂」→ 共同子字串「可樂」=1.0。
    這能在一整句話裡抓出產品名稱，而不需要完全相等。
    """
    if not candidate or not window:
        return 0.0
    sm = SequenceMatcher(None, window, candidate, autojunk=False)
    m = sm.find_longest_match(0, len(window), 0, len(candidate))
    return m.size / len(candidate)


def score(window: str, candidate: str) -> float:
    """回傳 0~1 的相似度。完全包含時為 1.0。"""
    w, c = normalize(window), normalize(candidate)
    if not w or not c:
        return 0.0
    if c in w:
        return 1.0
    lcs = _lcs_ratio(w, c)
    jac = _bigram_jaccard(w, c)
    # 也比一次「整句對整名」的序列相似度，處理少字/多字的口誤。
    seq = SequenceMatcher(None, w, c, autojunk=False).ratio()
    return max(lcs * 0.7 + jac * 0.3, seq)


def best_match(
    window: str,
    candidates: Iterable[dict],
    name_key: str = "name",
    alias_key: str = "aliases",
    threshold: float = 0.5,
) -> Optional[dict]:
    """在候選清單中找出與 window 最相符的項目。

    candidates 每項為 dict，至少含 name_key；可選 alias_key（list[str] 別名）。
    回傳該 dict 的淺層複本，附加 _score 與 _matched（實際命中的名稱/別名）。
    找不到（皆低於門檻）回傳 None。
    """
    best: Optional[dict] = None
    best_score = 0.0
    best_matched = ""
    for item in candidates:
        names = [item.get(name_key, "")]
        names += list(item.get(alias_key, []) or [])
        for nm in names:
            if not nm:
                continue
            s = score(window, nm)
            if s > best_score:
                best_score, best, best_matched = s, item, nm
    if best is None or best_score < threshold:
        return None
    out = dict(best)
    out["_score"] = round(best_score, 3)
    out["_matched"] = best_matched
    return out
