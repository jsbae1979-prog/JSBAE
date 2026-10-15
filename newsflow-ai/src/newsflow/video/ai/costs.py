"""Estimated AI video cost from user-entered unit prices (display and limit only).

No provider price is built in: the official price list could not be verified, so the user
enters the price per generated second for each model after checking the official docs.
Limits are compared against these estimates, never against a provider bill.
"""

from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CURRENCIES = ("USD", "KRW")
MAX_PRICE_PER_SECOND = Decimal(1000)
MAX_LIMIT = Decimal(10000000)
MAX_CLIP_SECONDS = 30


class CostError(ValueError):
    pass


def parse_money(value: str | None, *, maximum: Decimal = MAX_LIMIT, blank: bool = True) -> Decimal | None:
    """Non-negative decimal with up to 4 fractional digits; None for blank when allowed."""
    text = "" if value is None else str(value).strip().replace(",", "")
    if not text:
        if blank:
            return None
        raise CostError("금액을 입력하세요.")
    if not re.fullmatch(r"\d{1,8}(\.\d{1,4})?", text):
        raise CostError("금액은 0 이상의 숫자(소수점 4자리까지)로 입력하세요.")
    try:
        amount = Decimal(text)
    except InvalidOperation:  # pragma: no cover - the regex already excludes this
        raise CostError("금액 형식을 확인하세요.") from None
    if amount > maximum:
        raise CostError(f"금액은 {maximum} 이하로 입력하세요.")
    return amount


def money(amount: Decimal) -> str:
    return format(amount.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize(), "f")


_FULL_WIDTH = {0xFF0C: ",", **{0xFF10 + d: str(d) for d in range(10)}}


def parse_durations(value: str) -> tuple[int, ...]:
    """Allowed clip lengths in whole seconds, e.g. "5,10"; sorted, unique, 1..30."""
    # Full-width digits and commas (Korean IME) become ASCII; anything else must already be ASCII,
    # because str.isdigit() also accepts '²' or '①', which int() then rejects.
    parts = [p.strip() for p in str(value or "").translate(_FULL_WIDTH).split(",") if p.strip()]
    if not parts or len(parts) > 8 or not all(re.fullmatch(r"[0-9]{1,3}", p) for p in parts):
        raise CostError("허용 길이는 쉼표로 구분한 초 단위 정수로 입력하세요. 예: 5,10")
    seconds = sorted({int(p) for p in parts})
    if seconds[0] < 1 or seconds[-1] > MAX_CLIP_SECONDS:
        raise CostError(f"허용 길이는 1~{MAX_CLIP_SECONDS}초 사이여야 합니다.")
    return tuple(seconds)


def clip_seconds(scene_seconds: float, allowed: tuple[int, ...]) -> int:
    """Shortest allowed clip that covers the scene; the longest one (looped) if none does."""
    need = max(1, math.ceil(scene_seconds - 1e-9))
    return next((s for s in allowed if s >= need), allowed[-1])


def scene_cost(seconds: int, price_per_second: Decimal) -> Decimal:
    return Decimal(int(seconds)) * price_per_second
