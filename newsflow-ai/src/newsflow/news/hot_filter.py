"""Keep only recent articles with a hot-news signal from a Google News/Trends collection."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from newsflow.db.models import ArticleMention, ArticleScore, NewsArticle

from .trends import trend_matches

HOT_HOURS = (6, 12, 24, 48)
DEFAULT_HOT_HOURS = 24
MINIMUM = 3


def select_hot(session, article_ids: list[int], snapshot: dict | None, now: datetime,
               hours: int = DEFAULT_HOT_HOURS) -> tuple[list[int], dict]:
    """Recent window first, then a Trends match or two or more publishers.

    Unknown publication times are kept and counted, never guessed. When fewer than three
    articles carry a signal, the highest-scored recent articles fill the list and the
    shortfall is recorded instead of blocking the TOP 3 analysis.
    """
    if hours not in HOT_HOURS:
        raise ValueError("수집 기간을 확인해 주세요.")
    window = now - timedelta(hours=hours)
    recent, signalled, unknown_time, reasons = [], [], 0, {}
    for article in session.scalars(select(NewsArticle).where(NewsArticle.id.in_(article_ids))):
        published = article.published_at
        if published is not None and published.tzinfo is None:
            published = published.replace(tzinfo=now.tzinfo)
        if published is None:
            unknown_time += 1
        elif published < window:
            continue
        recent.append(article.id)
        mentions = list(session.execute(select(ArticleMention.publisher, ArticleMention.url)
                                        .where(ArticleMention.article_id == article.id)))
        publishers = {p.strip().casefold() for p, _ in mentions if p.strip()}
        if article.publisher and article.publisher.strip():
            publishers.add(article.publisher.strip().casefold())
        interest = trend_matches({"title": article.title,
                                  "sources": [{"url": article.url}] + [{"url": u} for _, u in mentions]},
                                 snapshot, now)
        why = []
        if interest["status"] == "matched":
            why.append("trends")
        if len(publishers) >= 2:
            why.append("publishers")
        if why:
            signalled.append(article.id)
            reasons[article.id] = why
    chosen = [i for i in article_ids if i in set(signalled)]
    shortfall = len(chosen) < MINIMUM
    if shortfall:
        scores = {row.article_id: row.total for row in session.scalars(
            select(ArticleScore).where(ArticleScore.article_id.in_(recent)))}
        fill = sorted((i for i in recent if i not in set(chosen)), key=lambda i: (-(scores.get(i) or 0), i))
        chosen += fill[:MINIMUM - len(chosen)]
    return chosen, {"hours": hours, "collected": len(article_ids), "recent": len(recent),
                    "signalled": len(signalled), "kept": len(chosen), "unknown_published_at": unknown_time,
                    "signal_shortfall": shortfall,
                    "reasons": {str(k): v for k, v in reasons.items()}}
