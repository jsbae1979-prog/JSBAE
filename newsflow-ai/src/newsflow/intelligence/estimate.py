"""Conservative token and cost estimates for external AI calls; pure functions, no I/O.

The estimate is a planning aid shown before a paid call. It is not a tokenizer and it
never gates a call: the enforced gate stays the monthly token limit. Korean text is
counted conservatively (about one token per Hangul syllable) so the shown maximum is
more likely to be above than below the provider's real count. The observed ratio is
recorded after a real call so the user can compare "예상" with "실제".

Cost uses only unit prices the user typed in (per one million tokens). The app has no
vendor price table, never bills, and labels every amount as an estimate.
"""

from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

HANGUL_CHARS_PER_TOKEN = 1.2
ASCII_CHARS_PER_TOKEN = 4.0
OTHER_CHARS_PER_TOKEN = 2.0
SAFETY_FACTOR = 1.15
MILLION = Decimal(1_000_000)
_HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
_ASCII = re.compile(r"[\x20-\x7e]")


def estimate_tokens(text: str) -> int:
    """Upper-leaning token count for mixed Korean/ASCII text; 0 for empty input."""
    if not text:
        return 0
    hangul = len(_HANGUL.findall(text))
    ascii_chars = len(_ASCII.findall(text))
    other = max(0, len(text) - hangul - ascii_chars)
    units = hangul / HANGUL_CHARS_PER_TOKEN + ascii_chars / ASCII_CHARS_PER_TOKEN + other / OTHER_CHARS_PER_TOKEN
    return max(1, math.ceil(units * SAFETY_FACTOR))


def estimate_call(instruction: str, payload: dict, max_tokens: int) -> dict:
    """Estimate for one chat completion built from the exact strings the provider sends."""
    from .provider import user_message

    prompt = instruction + user_message(payload)
    prompt_tokens = estimate_tokens(prompt)
    return {
        "prompt_chars": len(prompt),
        "prompt_tokens": prompt_tokens,
        "output_tokens_max": int(max_tokens),
        "total_max": prompt_tokens + int(max_tokens),
    }


def estimate_job(evidence: dict, duration: int, script_max_tokens: int, analysis_max_tokens: int | None) -> dict:
    """Estimate for one real-content job: an analysis call (optional) plus the script call."""
    from .provider import ANALYSIS_INSTRUCTION, SCRIPT_INSTRUCTION

    calls = []
    if analysis_max_tokens is not None:
        calls.append({"kind": "analysis", **estimate_call(ANALYSIS_INSTRUCTION, {"evidence": evidence}, analysis_max_tokens)})
    calls.append({
        "kind": "script",
        **estimate_call(SCRIPT_INSTRUCTION, {"duration": duration, "evidence": evidence}, script_max_tokens),
    })
    return {
        "calls": len(calls),
        "per_call": calls,
        "prompt_tokens": sum(c["prompt_tokens"] for c in calls),
        "output_tokens_max": sum(c["output_tokens_max"] for c in calls),
        "total_max": sum(c["total_max"] for c in calls),
        "duration": duration,
    }


def parse_price(value: str | None) -> Decimal | None:
    """User-entered price per one million tokens; None when blank, ValueError when invalid."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    if not re.fullmatch(r"\d{1,6}(\.\d{1,6})?", text):
        raise ValueError("단가는 0 이상 100000 이하의 숫자(소수점 6자리까지)여야 합니다.")
    try:
        price = Decimal(text)
    except InvalidOperation:  # pragma: no cover - the regex already excludes this
        raise ValueError("단가 형식을 확인하세요.") from None
    if not Decimal(0) <= price <= Decimal(100_000):
        raise ValueError("단가는 0 이상 100000 이하의 숫자(소수점 6자리까지)여야 합니다.")
    return price


def estimate_cost(estimate: dict, prices: dict) -> dict | None:
    """Estimated cost from user-entered unit prices; None until both prices are set."""
    input_price = prices.get("input_per_1m")
    output_price = prices.get("output_per_1m")
    if input_price is None or output_price is None:
        return None
    prompt = Decimal(int(estimate.get("prompt_tokens", 0)))
    output = Decimal(int(estimate.get("output_tokens_max", 0)))
    amount = (prompt * input_price + output * output_price) / MILLION
    quantized = amount.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return {
        "amount": format(quantized, "f"),
        "currency": prices.get("currency") or "USD",
        "basis": "사용자 입력 단가 · 참고용 추정치",
    }


def representative_evidence() -> dict:
    """Typical one-article evidence (title 60자, 요약 800자) for settings-level estimates."""
    title = "정부, 내년 예산안 발표와 주요 정책 방향 설명 · 관련 부처 합동 브리핑 진행 결과"[:60]
    summary = ("정부는 오늘 내년도 예산안의 주요 내용을 발표했습니다. 관련 부처는 합동 브리핑에서 세부 사업과 "
               "재원 조달 방안을 설명했으며, 국회 심의 일정과 쟁점에 대해서도 입장을 밝혔습니다. ") * 6
    return {
        "articles": [{
            "id": 1, "title": title, "summary": summary[:800], "category": "정치",
            "published_at": "2026-10-15T00:00:00+00:00",
            "sources": [{"publisher": "공개 RSS 출처", "url": "https://example.com/news/1"}],
            "verification": "unverified", "confidence": "미평가", "score": None,
            "popularity": "RSS 내부 휴리스틱 · 실제 조회수/검색량 미측정",
        }],
        "groups": [[1]],
        "comparison": "제목 유사도 0.65 기준 후보 그룹입니다. 서로 다른 보도 내용과 독립 출처 여부는 사람이 확인해야 합니다.",
        "caution": "검토용 초안 · 사실 확인 미완료",
    }
