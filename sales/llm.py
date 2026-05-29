"""選配：用 Claude 解析較複雜/隨意的口語句子。

僅在「規則解析信心不足」且環境有設定 ANTHROPIC_API_KEY 時才會被呼叫。
把顧客清單與產品清單放進 system 提示並開啟 prompt caching，
這樣多次呼叫時清單部分可重用快取、降低成本與延遲。

回傳格式與規則解析一致（date / customer_name / items），方便上層統一處理。
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Optional

MODEL = os.environ.get("SALES_LLM_MODEL", "claude-sonnet-4-6")


def is_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _system_prompt(customers: list[dict], products: list[dict]) -> list[dict]:
    cust_lines = "\n".join(c.get("name", "") for c in customers) or "(無)"
    prod_lines = "\n".join(
        f"{p.get('code','')}\t{p.get('name','')}" for p in products
    ) or "(無)"
    instructions = (
        "你是銷貨單解析器。使用者會用口語描述一筆或多筆銷貨。\n"
        "請只依據下方提供的『顧客清單』與『產品清單』做對應，將口語講法校正回清單中的正式名稱，"
        "並帶出對應的產品編號。若無法對應，product_code 留空並在 notes 說明。\n"
        "輸出務必是 JSON，格式：\n"
        '{"date":"YYYY-MM-DD","customer_name":"...","items":[{"product_name":"...","product_code":"...","quantity":數字,"unit":"..."}],"notes":["..."]}\n'
        "date 若未提及則用今天。只輸出 JSON，不要多餘文字。"
    )
    # 清單較大且穩定 → 標記 cache_control 以重用快取。
    return [
        {"type": "text", "text": instructions},
        {"type": "text", "text": f"顧客清單：\n{cust_lines}", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"產品清單（編號<tab>名稱）：\n{prod_lines}", "cache_control": {"type": "ephemeral"}},
    ]


def parse(text: str, customers: list[dict], products: list[dict], today: Optional[date] = None) -> Optional[dict]:
    """呼叫 Claude 解析；不可用或失敗時回 None。"""
    if not is_available():
        return None
    try:
        import anthropic
    except ImportError:
        return None

    today = today or date.today()
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=_system_prompt(customers, products),
            messages=[{"role": "user", "content": f"今天是 {today.isoformat()}。請解析：{text}"}],
        )
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        raw = _strip_fence(raw)
        data = json.loads(raw)
        data["_source"] = "llm"
        return data
    except Exception:  # 任何錯誤都安靜降級回規則結果
        return None


def _strip_fence(s: str) -> str:
    if s.startswith("```"):
        s = s.split("\n", 1)[-1]
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
    return s.strip()
