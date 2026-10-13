from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
    ]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(query), ""))


def normalize_title(title: str) -> str:
    return re.sub(r"[^\w가-힣]", "", unicodedata.normalize("NFKC", title).lower())


def similar_title(left: str, right: str, left_date: datetime | None, right_date: datetime | None) -> bool:
    a, b = normalize_title(left), normalize_title(right)
    if not a or not b:
        return False
    if left_date and right_date and abs((left_date - right_date).total_seconds()) > 72 * 3600:
        return False
    if a == b:
        return True
    if not left_date or not right_date or min(len(a), len(b)) < 12:
        return False
    # Different numerical facts must not be folded together.
    if re.findall(r"\d+", a) != re.findall(r"\d+", b):
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.92
