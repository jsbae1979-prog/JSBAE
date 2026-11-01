"""Keep only recently published articles from a collection; TOP 3 scoring judges newsworthiness."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from newsflow.db.models import NewsArticle

HOT_HOURS = (6, 12, 24, 48)
DEFAULT_HOT_HOURS = 24
MINIMUM = 3


def check_hours(hours) -> int:
    if type(hours) is not int or hours not in HOT_HOURS:
        raise ValueError("수집 기간은 6·12·24·48시간 중에서 선택해 주세요.")
    return hours


def select_recent(session, article_ids: list[int], now: datetime,
                  hours: int = DEFAULT_HOT_HOURS) -> tuple[list[int], dict]:
    """Articles published within the window, in collection order.

    Unknown publication times are kept and counted, never guessed. Topic/interest
    signals are left to the TOP 3 formula. When fewer than three remain, the newest
    older articles fill the list and the shortfall is recorded instead of blocking analysis.
    """
    check_hours(hours)
    window = now - timedelta(hours=hours)
    order = {identifier: index for index, identifier in enumerate(article_ids)}
    recent, older, unknown_time = [], [], 0
    for article in session.scalars(select(NewsArticle).where(NewsArticle.id.in_(article_ids))):
        published = article.published_at
        if published is not None and published.tzinfo is None:
            published = published.replace(tzinfo=now.tzinfo or UTC)
        if published is None:
            unknown_time += 1
            recent.append(article.id)
        elif published >= window:
            recent.append(article.id)
        else:
            older.append((published, article.id))
    chosen = sorted(recent, key=order.__getitem__)
    shortfall = len(chosen) < MINIMUM
    filled = []
    if shortfall:
        filled = [i for _, i in sorted(older, key=lambda row: (-row[0].timestamp(), row[1]))][:MINIMUM - len(chosen)]
        chosen += filled
    return chosen, {"hours": hours, "collected": len(article_ids), "recent": len(recent),
                    "excluded_old": len(older) - len(filled), "kept": len(chosen),
                    "unknown_published_at": unknown_time, "recent_shortfall": shortfall, "filled_old": len(filled)}
