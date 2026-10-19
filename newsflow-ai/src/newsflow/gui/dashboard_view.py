"""Read-only dashboard projections. No network, credential access or production commands."""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newsflow.db.models import (
    AutopilotJob,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    PublishDraft,
    RenderJob,
)

from .production_context import context_for_run
from .task_views import PROVIDERS

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
        "workflow": workflow_context(session, focus, draft),
        "activity": activity, "sparks": [points(s, max(1, *s), 36) for s in (news, jobs, videos, queue)],
        "spark_totals": [sum(s) for s in (news, jobs, videos, queue)],
        "unknown_finished": session.scalar(select(func.count()).select_from(RenderJob).where(
            RenderJob.status == "success", RenderJob.finished_at.is_(None))),
    }


def workflow_context(session: Session, focus: dict | None, draft: ContentDraft | None) -> dict:
    """Only confirmed records mark a step complete; task choices never read global defaults."""
    run = session.get(IntelligenceRun, draft.run_id) if draft else None
    context = context_for_run(run) or {}
    job = session.get(AutopilotJob, focus["task_id"]) if focus and focus.get("task_id") else None
    results = job.stage_results if job and isinstance(job.stage_results, dict) else {}
    request = results.get("request", {})
    choices = request.get("production_options", {})
    if not isinstance(choices, dict):
        choices = {}
    analysis_id = context.get("analysis_id")
    for stage in ("select", "script"):
        analysis_id = results.get(stage, {}).get("analysis_run_id", analysis_id)
    analysis = session.get(IntelligenceRun, analysis_id) if type(analysis_id) is int else None
    render = session.get(RenderJob, focus["render_job_id"]) if focus and focus.get("render_job_id") else None
    evidence = run.evidence if run and isinstance(run.evidence, dict) else {}
    articles = evidence.get("articles")
    news_done = bool(job and job.article_id) or isinstance(articles, list) and bool(articles)
    analysis_done = bool(analysis and analysis.status == "success")
    script_done = bool(draft and run and run.status == "success")
    render_done = bool(render and render.status == "success")
    approved = bool(job and job.status == "completed")
    # A saved draft still awaiting human review remains the current script step.
    current = 4 if render_done else 3 if render else 2 if draft else None
    if job:
        current = {"collect": 0, "dedup": 0, "select": 1, "script": 2,
                   "render": 3, "validate": 4, "queue": 4}.get(job.current_stage)
    done = [news_done, analysis_done, script_done, render_done, approved]
    failed = bool(focus and focus["status"] in {"failed", "interrupted", "cancelled", "unknown"})
    steps = []
    for index, label in enumerate(("뉴스 수집", "AI 분석", "대본 작성", "영상 합성", "검토")):
        state = "error" if index == current and failed else "current" if index == current and not approved else "done" if done[index] else "pending"
        steps.append({"label": label, "state": state})
    provider = run.provider if run else job.ai_mode if job else None
    voice = choices.get("voice") or (job.voice if job else None) or context.get("initial_voice")
    voice_label = ("ElevenLabs" if voice == "elevenlabs" else "무음 검토용" if voice == "offline-silence"
                   else "Supertonic" if voice and voice.startswith("supertonic")
                   else "Windows 음성" if voice else "음성 미정")
    video = choices.get("video_provider", context.get("initial_video"))
    review = choices.get("script_review", context.get("script_review", True)) is not False
    return {"steps": steps, "provider": PROVIDERS.get(provider, provider or "AI 미정"),
            "provider_id": provider or "unknown", "voice": voice_label,
            "video": "AI 영상" if video == "higgsfield" else "기본 영상" if video == "off" else "방식 미정",
            "video_detail": "Higgsfield + FFmpeg · 장면별 승인 유지" if video == "higgsfield"
            else "FFmpeg · 로컬 합성" if video == "off" else "저장된 영상 선택 기록이 없습니다.",
            "review": review, "review_legacy": not choices and "script_review" not in context}
