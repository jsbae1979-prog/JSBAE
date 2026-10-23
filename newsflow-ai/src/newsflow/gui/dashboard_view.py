"""Read-only dashboard projections. No network, credential access or production commands."""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from newsflow.db.models import (
    ArticleThumbnail,
    AutopilotJob,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    PublishDraft,
    RenderJob,
)
from newsflow.news.ranking import CATEGORY_WORDS

from .production_context import context_for_run
from .task_views import PROVIDERS

KST = timezone(timedelta(hours=9))
CATEGORY_FILTERS = {"": (), **{category: (category,) for category in CATEGORY_WORDS}, "미분류": ("미분류",)}
CATEGORY_FILTERS.update({"정치": ("정치", "politics"), "IT·과학": ("IT·과학", "it", "science"),
                         "경제": ("경제", "economy"), "국제": ("국제", "world"), "사회": ("사회", "society"),
                         "문화": ("문화", "culture"), "스포츠": ("스포츠", "sports")})


def news_context(session: Session, category: str = "") -> dict:
    if category not in CATEGORY_FILTERS:
        raise ValueError("뉴스 분야를 확인해 주세요.")
    from newsflow.news.lifecycle import visible_news

    query = select(NewsArticle).where(visible_news())
    if category:
        query = query.where(NewsArticle.category.in_(CATEGORY_FILTERS[category]))
    articles = list(session.scalars(query.order_by(NewsArticle.id.desc()).limit(5)))
    return {"recent_news": articles, "dashboard_news_category": category,
            "dashboard_news_categories": tuple(CATEGORY_FILTERS),
            "news_thumbnails": {row.article_id: row for row in session.scalars(
                select(ArticleThumbnail).where(ArticleThumbnail.article_id.in_([a.id for a in articles])))}}


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

    # The task list can contain older failures and omit a rendered manual draft from
    # its compact active list. A running job wins; otherwise use the latest work.
    def task_time(item):
        try:
            value = datetime.fromisoformat(item.get("updated_at", ""))
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        except (TypeError, ValueError):
            return datetime.min.replace(tzinfo=UTC)

    running = [item for item in tasks if item.get("status") in {"running", "queued"}]
    candidates = running or [item for item in tasks if item.get("status") != "cancelled"] or tasks
    focus = max(candidates, key=task_time) if candidates else None
    draft = session.get(ContentDraft, focus["draft_id"]) if focus and focus.get("draft_id") else None
    content = draft.content if draft and isinstance(draft.content, dict) else {}
    excerpt = content.get("summary", "")
    if not isinstance(excerpt, str):
        excerpt = ""
    collection_flow = latest_collection_workflow(session, focus) if not running else None
    if collection_flow:
        focus, draft, excerpt = collection_flow["focus"], None, ""
    from newsflow.db.models import WorkspaceRemoval
    from newsflow.news.lifecycle import visible_news

    removed = set(session.scalars(select(WorkspaceRemoval.key)))
    recent_drafts = [d for d in session.scalars(select(ContentDraft).order_by(ContentDraft.updated_at.desc()))
                     if f"activity:draft:{d.id}" not in removed][:3]
    activity = [{"title": str(d.content.get("title", "저장된 대본")) if isinstance(d.content, dict) else "저장된 대본", "label": "대본 저장",
                 "href": f"/ai?draft_id={d.id}", "at": d.updated_at, "id": f"draft:{d.id}"} for d in recent_drafts]
    return {
        "task_review_counts": {
            "script": sum(bool(t.get("status") == "waiting_review" and t.get("draft_id") and not t.get("render_job_id")) for t in tasks),
            "video": sum(t.get("status") == "waiting_review" and bool(t.get("render_job_id")) for t in tasks),
            "failed": sum(t.get("status") in {"failed", "interrupted", "unknown"} for t in tasks),
        },
        "today": today.isoformat(), "news_count": session.scalar(select(func.count()).select_from(NewsArticle).where(visible_news())),
        "days": [{"date": d.isoformat(), "label": d.strftime("%m.%d"), "news": n, "videos": v,
                  "x": 20 + i * 80, "news_y": 112 - round(n / maximum * 100, 2),
                  "video_y": 112 - round(v / maximum * 100, 2)}
                 for i, (d, n, v) in enumerate(zip(days, news, videos, strict=True))],
        "news_points": points(news, maximum), "video_points": points(videos, maximum), "maximum": maximum,
        "has_activity": any(news) or any(videos), "focus": focus, "excerpt": excerpt[:240],
        "workflow": collection_flow["workflow"] if collection_flow else workflow_context(session, focus, draft),
        "activity": activity, "sparks": [points(s, max(1, *s), 36) for s in (news, jobs, videos, queue)],
        "spark_totals": [sum(s) for s in (news, jobs, videos, queue)],
        "unknown_finished": session.scalar(select(func.count()).select_from(RenderJob).where(
            RenderJob.status == "success", RenderJob.finished_at.is_(None))),
    }


def latest_collection_workflow(session: Session, focus: dict | None) -> dict | None:
    """A newer collection cannot inherit the completed steps or script of an older video."""
    from newsflow.news.lifecycle import visible_news

    collection = session.scalar(select(IntelligenceRun).where(IntelligenceRun.kind == "trends",
                                 IntelligenceRun.provider == "google_trends").order_by(IntelligenceRun.id.desc()).limit(1))
    if collection is None:
        return None
    try:
        focus_time = datetime.fromisoformat(focus["updated_at"]) if focus else datetime.min.replace(tzinfo=UTC)
        focus_time = focus_time.replace(tzinfo=UTC) if focus_time.tzinfo is None else focus_time
    except (KeyError, TypeError, ValueError):
        return None
    if collection.created_at <= focus_time:
        return None
    ids = set(collection.result.get("collection", {}).get("article_ids", []))
    visible = set(session.scalars(select(NewsArticle.id).where(visible_news())))
    if not ids or not ids <= visible:
        return None
    analyses = session.scalars(select(IntelligenceRun).where(IntelligenceRun.kind == "analysis",
                               IntelligenceRun.created_at >= collection.created_at)
                               .order_by(IntelligenceRun.id.desc()).limit(50))
    analysis = next((row for row in analyses if row.evidence.get("curation_contract")
                     and {a["id"] for a in row.evidence.get("articles", [])} == ids), None)
    success = bool(analysis and analysis.status == "success")
    failed = bool(analysis and analysis.status in {"failed", "interrupted", "unknown"})
    ranking = analysis.result.get("ranking", []) if success else []
    href = f"/news?curation_id={analysis.id}#curation-results" if analysis else "/news#curation"
    title = ranking[0]["title"] if ranking else f"수집 뉴스 {len(ids)}건 · 화제성 평가 {'확인 필요' if failed else '진행 중' if analysis else '대기'}"
    current = 2 if success else 1
    states = ["done", "done" if success else "error" if failed else "current", "current" if success else "pending", "pending", "pending"]
    return {"focus": {"id": f"collection:{collection.id}", "kind": "collection", "title": title,
                      "status": "failed" if failed else "running" if analysis and not success else "waiting_review",
                      "status_label": "조치 필요" if failed else "추천 뉴스 검토" if success else "화제성 평가 전" if not analysis else "평가 중",
                      "stage": f"현재 수집 {len(ids)}건", "href": href, "workspace_href": href,
                      "updated_at": (analysis or collection).created_at.isoformat(),
                      "next_action": "추천 1건·다른 후보 확인" if success else "전체 뉴스 화제성 평가",
                      "draft_id": None},
            "workflow": {"steps": [{"label":label,"state":state} for label,state in zip(
                ("뉴스 자료", "화제성 평가", "대본 작성", "영상 합성", "검토"), states, strict=True)],
                "news_method": f"Google News + Trends · {len(ids)}건 · 현재 수집 회차",
                "current_stage": current, "provider": PROVIDERS.get(analysis.provider) if analysis else None}}


def workflow_context(session: Session, focus: dict | None, draft: ContentDraft | None) -> dict:
    """Only confirmed records mark a step complete; task choices never read global defaults."""
    run_id = draft.run_id if draft else focus.get("script_run_id") if focus else None
    run = session.get(IntelligenceRun, run_id) if run_id else None
    context = context_for_run(run) or {}
    job = session.get(AutopilotJob, focus["task_id"]) if focus and focus.get("task_id") else None
    results = job.stage_results if job and isinstance(job.stage_results, dict) else {}
    request = results.get("request", {})
    choices = request.get("production_options", {})
    if not isinstance(choices, dict):
        choices = {}
    analysis_id = (context.get("analysis_id")
                   or (run.options.get("analysis_run_id") if run and isinstance(run.options, dict) else None)
                   or (focus.get("analysis_run_id") if focus else None))
    for stage in ("select", "script"):
        analysis_id = results.get(stage, {}).get("analysis_run_id", analysis_id)
    analysis = session.get(IntelligenceRun, analysis_id) if type(analysis_id) is int else None
    render = session.get(RenderJob, focus["render_job_id"]) if focus and focus.get("render_job_id") else None
    evidence_run = run or analysis
    evidence = evidence_run.evidence if evidence_run and isinstance(evidence_run.evidence, dict) else {}
    articles = evidence.get("articles")
    news_done = bool(job and job.article_id) or isinstance(articles, list) and bool(articles)
    analysis_done = bool(analysis and analysis.status == "success")
    script_done = bool(draft and run and run.status == "success")
    render_done = bool(render and render.status == "success")
    approved = bool(job and job.status == "completed")
    # A saved draft still awaiting human review remains the current script step.
    current = 4 if render_done else 3 if render else 2 if draft or run else 1 if analysis else None
    if job:
        current = {"collect": 0, "dedup": 0, "select": 1, "script": 2,
                   "render": 3, "validate": 4, "queue": 4}.get(job.current_stage)
    done = [news_done, analysis_done, script_done, render_done, approved]
    failed = bool(focus and focus["status"] in {"failed", "interrupted", "cancelled", "unknown"})
    steps = []
    for index, label in enumerate(("뉴스 자료", "AI 분석", "대본 작성", "영상 합성", "검토")):
        state = "error" if index == current and failed else "current" if index == current and not approved else "done" if done[index] else "pending"
        steps.append({"label": label, "state": state})
    provider = (run or analysis).provider if run or analysis else job.ai_mode if job else None
    voice = choices.get("voice") or (job.voice if job else None) or context.get("initial_voice")
    voice_label = ("ElevenLabs" if voice == "elevenlabs" else "무음 검토용" if voice == "offline-silence"
                   else "Supertonic" if voice and voice.startswith("supertonic")
                   else "Windows 음성" if voice else "음성 미정")
    video = choices.get("video_provider", context.get("initial_video"))
    review = choices.get("script_review", context.get("script_review", True)) is not False
    news_method = (focus.get("news_method") if focus else None) or (
        "보관 기사 자료 · 수집 방식 기록 없음" if news_done else "뉴스 자료 확보 전")
    return {"steps": steps, "news_method": news_method,
            "provider": PROVIDERS.get(provider, provider or "AI 미정"),
            "provider_id": provider or "unknown", "voice": voice_label,
            "video": "AI 영상" if video == "higgsfield" else "기본 영상" if video == "off" else "방식 미정",
            "video_detail": "Higgsfield + FFmpeg · 장면별 승인 유지" if video == "higgsfield"
            else "FFmpeg · 로컬 합성" if video == "off" else "저장된 영상 선택 기록이 없습니다.",
            "review": review, "review_legacy": not choices and "script_review" not in context}
