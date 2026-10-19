"""Read-only dashboard projections. No network, credential access or production commands."""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newsflow.db.models import AutopilotJob, ContentDraft, NewsArticle, PublishDraft, RenderJob

KST = timezone(timedelta(hours=9))


def dashboard_context(session: Session, tasks: list[dict], *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    today = now.astimezone(KST).date()
    days = [today - timedelta(days=6 - i) for i in range(7)]
    start = datetime.combine(days[0], time(), KST).astimezone(UTC)
    end = datetime.combine(today + timedelta(days=1), time(), KST).astimezone(UTC)

    def series(column, *conditions) -> list[int]:
        day = func.date(column, "+9 hours")
        rows = dict(session.execute(select(day, func.count()).where(
            column >= start, column < end, column <= now, *conditions,
        ).group_by(day)).all())
        return [int(rows.get(d.isoformat(), 0)) for d in days]

    news = series(NewsArticle.collected_at)
    videos = series(RenderJob.finished_at, RenderJob.status == "success")
    jobs = series(AutopilotJob.created_at)
    queue = series(PublishDraft.created_at)
    maximum = max(1, *news, *videos)

    def points(values: list[int], ceiling: int, height: int = 100) -> str:
        return " ".join(f"{20 + i * 80},{height + 12 - round(value / ceiling * height, 2)}"
                        for i, value in enumerate(values))

    focus = tasks[0] if tasks else None
    draft = session.get(ContentDraft, focus["draft_id"]) if focus and focus.get("draft_id") else None
    content = draft.content if draft and isinstance(draft.content, dict) else {}
    excerpt = content.get("summary", "")
    if not isinstance(excerpt, str):
        excerpt = ""
    recent_drafts = list(session.scalars(select(ContentDraft).order_by(ContentDraft.updated_at.desc()).limit(3)))
    activity = [{"title": str(d.content.get("title", "저장된 대본")) if isinstance(d.content, dict) else "저장된 대본", "label": "대본 저장",
                 "href": f"/ai?draft_id={d.id}", "at": d.updated_at} for d in recent_drafts]
    return {
        "today": today.isoformat(), "news_count": session.scalar(select(func.count()).select_from(NewsArticle)),
        "days": [{"date": d.isoformat(), "label": d.strftime("%m.%d"), "news": n, "videos": v,
                  "x": 20 + i * 80, "news_y": 112 - round(n / maximum * 100, 2),
                  "video_y": 112 - round(v / maximum * 100, 2)}
                 for i, (d, n, v) in enumerate(zip(days, news, videos, strict=True))],
        "news_points": points(news, maximum), "video_points": points(videos, maximum), "maximum": maximum,
        "has_activity": any(news) or any(videos), "focus": focus, "excerpt": excerpt[:240],
        "activity": activity, "sparks": [points(s, max(1, *s), 36) for s in (news, jobs, videos, queue)],
        "spark_totals": [sum(s) for s in (news, jobs, videos, queue)],
        "unknown_finished": session.scalar(select(func.count()).select_from(RenderJob).where(
            RenderJob.status == "success", RenderJob.finished_at.is_(None))),
    }
