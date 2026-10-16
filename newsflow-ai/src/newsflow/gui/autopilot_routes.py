"""Easy Studio presentation; explicit commands reuse the durable coordinator."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select

from newsflow.autopilot.contracts import (
    STAGE_LABELS,
    STAGES,
    AutopilotBusy,
    AutopilotConflict,
    AutopilotError,
    AutopilotNotFound,
)
from newsflow.autopilot.samples import SAMPLE_URL
from newsflow.db.models import (
    AIUsage,
    AppSetting,
    AutopilotArtifact,
    ContentDraft,
    NewsArticle,
    NewsSource,
    NewsSourceCheck,
    PublishDraft,
    RenderJob,
    VideoProject,
)
from newsflow.easy_setup import preview_preferences, speech_preferences
from newsflow.intelligence.korean import speech_plan
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.intelligence.settings import (
    STUDIO_PROVIDERS,
    external_ready,
    job_estimate,
    read_settings,
    read_studio_settings,
)
from newsflow.publishing.service import PublishingError, PublishingService, hash_file
from newsflow.video.tts import TTSError

from .production_context import context_query, parse_context, validate_context
from .routes import go, page
from .task_views import task_rows

router = APIRouter()
PLATFORMS = {"youtube": "YouTube Shorts", "instagram": "Instagram Reels"}
STATUSES = {
    "queued": "준비 중", "running": "제작 중", "waiting_review": "내 확인 필요",
    "completed": "제작 완료", "failed": "확인 필요", "interrupted": "중단됨", "cancelled": "취소됨",
}
CHOICES = {
    "mode": {"easy", "guided"}, "source": {"sample", "feeds"},
    "duration": {"30", "45", "60"}, "platform": set(PLATFORMS), "ai": {"offline", "openai"},
}
DEFAULTS = {"mode": "easy", "source": "sample", "duration": "30", "platform": "youtube", "ai": "offline"}
AI_LABELS = {"offline": "기본 대본 (외부 호출 없음)", "openai": "외부 AI 대본 (OpenAI · 유료)"}
DESCRIPTIONS = {
    "collect": "뉴스를 모으고 같은 기사는 정리해요.",
    "select": "새 영상으로 만들 이야기를 골라요.",
    "script": "내용과 출처를 담은 기본 대본을 만들어요.",
    "render": "자막이 있는 세로 검토영상을 만들어요.",
    "validate": "영상 파일과 재생 규격을 확인해요.",
    "queue": "사람이 검토할 로컬 게시 초안으로 보관해요.",
}


def _defaults(request: Request) -> dict[str, Any]:
    values = dict(DEFAULTS)
    with request.app.state.sessions() as session:
        for name, choices in CHOICES.items():
            value = session.get(AppSetting, "autopilot_" + name)
            if value and value.value in choices:
                values[name] = value.value
    return {**values, "duration": int(values["duration"])}


def _page(request: Request, template: str, **context: Any) -> HTMLResponse:
    response = page(
        request, template, platform_labels=PLATFORMS, status_labels=STATUSES,
        stage_labels=STAGE_LABELS, ai_labels=AI_LABELS, **context,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def readiness(request: Request) -> dict[str, Any]:
    """Status chips for the Easy UI: RSS, AI and Korean voice readiness without external calls."""
    sessions = request.app.state.sessions
    with sessions() as session:
        enabled = list(session.scalars(select(NewsSource).where(NewsSource.enabled, NewsSource.url != SAMPLE_URL)))
        checks = {c.source_id: c for c in session.scalars(select(NewsSourceCheck))}
    passed = sum(1 for source in enabled if checks.get(source.id) and checks[source.id].status == "pass")
    ai = external_ready(sessions, request.app.state.ai_keys)
    voice, _size, _position = preview_preferences(sessions)
    try:
        speech = speech_preferences(sessions)
        speech_values = {"rate": speech.rate, "pause_ms": speech.pause_ms}
    except TTSError:
        speech_values = {"rate": 0, "pause_ms": 250}
    installed = voice == "offline-silence" or request.app.state.video.voice_available(voice)
    return {
        "rss": {"enabled": len(enabled), "tested": passed, "ready": bool(enabled)},
        "ai": ai,
        "voice": {"name": voice, "silent": voice == "offline-silence", "installed": installed, **speech_values},
    }


def production_summary(request: Request, ready: dict[str, Any]) -> dict[str, Any]:
    """Presentation only; saved Studio choices are never rewritten or silently replaced."""
    saved = read_studio_settings(request.app.state.sessions)
    provider = saved["provider"]
    voice = ready["voice"]
    supported = provider in {"offline", "openai"}
    with request.app.state.sessions() as session:
        video_setting = session.get(AppSetting, "video_ai_provider")
        manual_video = bool(video_setting and video_setting.value == "higgsfield")
    model_mismatch = provider == "openai" and saved["model"] != read_settings(request.app.state.sessions).model
    if manual_video:
        supported = False
        notice = "Higgsfield는 장면별 비용·내용 승인이 필요합니다. 대본을 준비한 뒤 별도 장면 계획으로 이어갑니다."
    elif model_mismatch:
        supported = False
        notice = "선택 모델과 기존 자동 제작 모델이 달라 선택한 모델의 대본 검토 흐름으로 이어갑니다."
    elif not supported:
        notice = (
            "선택한 AI는 뉴스 분석·대본 화면에서 사용할 수 있어요. "
            "등록된 뉴스는 대본을 검토한 뒤 영상 제작으로 이어집니다."
        )
    elif provider == "openai" and not ready["ai"]["ready"]:
        notice = "등록 뉴스 자동 제작에 필요한 AI 연결·비용 승인을 설정에서 확인해 주세요."
    else:
        notice = "등록 뉴스는 대본과 완성 영상을 확인한 뒤 보관합니다. 체험 뉴스는 기본 대본으로 연습해요."
    if voice["name"] == "elevenlabs":
        voice_label = "외부 한국어 음성 · 제작별 동의 필요"
    elif voice["silent"]:
        voice_label = "무음 검토영상 · 음성 없음"
    else:
        voice_label = "한국어 음성" if voice["installed"] else "선택한 음성 준비 필요"
    return {
        "provider": provider, "provider_label": STUDIO_PROVIDERS[provider],
        "automatic_supported": supported, "notice": notice,
        "voice_label": voice_label, "voice_ready": voice["installed"],
        "action_url": "/autopilot/quick-start", "guide_url": "/ai", "rss_ready": ready["rss"]["ready"],
    }


def _ai_usage(request: Request, snapshot: dict[str, Any], article: NewsArticle | None) -> tuple[dict | None, dict | None]:
    """Estimate before the paid script call and the recorded usage after it; route-level only."""
    if snapshot.get("content_mode") != "real" or snapshot.get("ai_mode") != "openai":
        return None, None
    sessions = request.app.state.sessions
    estimate = actual = None
    with sessions() as session:
        # Every analysis/script run the job ever used, including failed attempts that were retried.
        run_ids = {
            int(reference) for reference in session.scalars(select(AutopilotArtifact.reference).where(
                AutopilotArtifact.job_id == snapshot["id"],
                AutopilotArtifact.kind.in_(("analysis_run_id", "script_run_id")),
            ))
        }
        run_ids |= {snapshot[key] for key in ("analysis_run_id", "script_run_id") if snapshot.get(key)}
        rows = (
            session.scalars(select(AIUsage).where(AIUsage.run_id.in_(run_ids)).order_by(AIUsage.id)).all()
            if run_ids else []
        )
        if rows:
            actual = {
                "calls": len(rows), "failed": sum(1 for row in rows if row.status != "success"),
                "prompt": sum(row.prompt_tokens for row in rows), "completion": sum(row.completion_tokens for row in rows),
                "total": sum(row.total_tokens for row in rows), "model": rows[-1].model,
            }
    if article is not None and "script" not in snapshot.get("stage_results", {}):
        try:
            evidence = IntelligenceService(sessions).evidence_for([article.id])
            estimate = job_estimate(sessions, int(snapshot["duration"]), evidence)
        except (IntelligenceError, ValueError, TypeError):
            estimate = None
    return estimate, actual


def _error(exc: AutopilotError) -> HTTPException:
    # Never echo provider, database or file error details in the public UI.
    if isinstance(exc, AutopilotNotFound):
        return HTTPException(404, "작업을 찾을 수 없습니다.")
    if isinstance(exc, AutopilotBusy):
        return HTTPException(409, "진행 중이거나 확인을 기다리는 작업이 있습니다. 나의 제작 작업을 확인하세요.")
    if isinstance(exc, AutopilotConflict):
        return HTTPException(409, "작업 상태가 바뀌었습니다. 새로고침한 뒤 다시 확인해 주세요.")
    return HTTPException(422, "선택한 제작 방식과 현재 작업 상태를 확인해 주세요.")


def _snapshot(request: Request, job_id: str) -> dict[str, Any]:
    try:
        return request.app.state.autopilot.snapshot(job_id)
    except AutopilotError as exc:
        raise _error(exc) from None


def _media_path(request: Request, video: RenderJob | None):
    if video is None:
        return None
    try:
        return PublishingService(
            request.app.state.sessions, request.app.state.video.outputs,
        ).media_path(video)
    except (OSError, ValueError, PublishingError):
        return None


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    jobs = request.app.state.autopilot.list_jobs(100)
    ready = readiness(request)
    from .production_status import production_context

    overview = production_context(request)
    tasks = task_rows(request, jobs)
    with request.app.state.sessions() as session:
        completed = []
        videos = session.execute(
            select(RenderJob, VideoProject).join(VideoProject)
            .where(RenderJob.status == "success").order_by(RenderJob.id.desc()).limit(100)
        ).all()
        job_links = {item.get("render_job_id"): item["id"] for item in jobs}
        video_count = 0
        for video, project in videos:
            if _media_path(request, video) is not None:
                video_count += 1
                if len(completed) < 5:
                    task = job_links.get(video.id)
                    completed.append({
                        "title": project.title, "duration": project.duration,
                        "link": f"/autopilot/jobs/{task}" if task else f"/video?job_id={video.id}",
                    })
        return _page(
            request, "easy_home.html", active="home", defaults=_defaults(request), ready=ready,
            production=production_summary(request, ready),
            active_jobs=[item for item in tasks if not item["completed"]],
            completed=completed, video_count=video_count,
            queue_count=session.scalar(select(func.count()).select_from(PublishDraft)),
            recent_news=list(session.scalars(select(NewsArticle).order_by(NewsArticle.id.desc()).limit(5))),
            **overview,
        )


@router.get("/autopilot/start", response_class=HTMLResponse)
def start_page(request: Request, guide: str = "", flow: str | None = None, advanced: bool = False) -> HTMLResponse:
    try:
        production_flow = parse_context(flow)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    with request.app.state.sessions() as session:
        enabled = session.scalar(select(func.count()).select_from(NewsSource).where(
            NewsSource.enabled, NewsSource.url != SAMPLE_URL,
        ))
    ready = readiness(request)
    return _page(
        request, "autopilot_start.html", active="autopilot", defaults=_defaults(request),
        enabled_sources=enabled, ready=ready, production=production_summary(request, ready),
        guide=guide if guide in {"provider", "voice", "approval", "sources", "model", "video"} else "",
        production_flow=production_flow, manual_url="/ai?" + context_query(production_flow), advanced=advanced,
    )


@router.post("/autopilot/quick-start")
def quick_start(
    request: Request, source: str = Form(max_length=10), duration: int = Form(),
) -> RedirectResponse:
    """Two-choice entry point, with the same coordinator and all existing review gates."""
    if source not in CHOICES["source"] or duration not in {30, 45, 60}:
        raise HTTPException(422, "뉴스 종류와 30·45·60초 중 영상 길이를 선택해 주세요.")
    ready = readiness(request)
    saved = read_studio_settings(request.app.state.sessions)
    with request.app.state.sessions() as session:
        video_setting = session.get(AppSetting, "video_ai_provider")
        video_mode = video_setting.value if video_setting and video_setting.value == "higgsfield" else "off"
    flow = validate_context({
        "source": source, "initial_duration": duration,
        "initial_provider": saved["provider"] if source == "feeds" else "offline",
        "initial_model": saved["model"] if source == "feeds" else "offline",
        "initial_voice": ready["voice"]["name"], "initial_video": video_mode,
    })

    def guide_to(reason: str):
        return go(f"/autopilot/start?guide={reason}&{context_query(flow)}")

    if video_mode == "higgsfield":
        return guide_to("video")
    if source == "feeds":
        if saved["provider"] not in {"offline", "openai"}:
            return guide_to("provider")
        if not ready["rss"]["ready"]:
            return guide_to("sources")
        if saved["provider"] == "openai" and not ready["ai"]["ready"]:
            return guide_to("approval")
        if saved["provider"] == "openai" and saved["model"] != read_settings(request.app.state.sessions).model:
            return guide_to("model")
    # An external voice needs the existing Video Studio per-render consent flow.
    # A missing selected voice never becomes silent or switches providers.
    if ready["voice"]["name"] == "elevenlabs" or not ready["voice"]["installed"]:
        return guide_to("voice")
    defaults = _defaults(request)
    try:
        identifier = request.app.state.autopilot.start(
            mode="guided", source=source, duration=duration, platform=defaults["platform"],
            content_mode="real" if source == "feeds" else "trial",
            ai_mode=saved["provider"] if source == "feeds" else "offline",
            voice=ready["voice"]["name"],
        )
    except AutopilotError as exc:
        raise _error(exc) from None
    return go(f"/autopilot/jobs/{identifier}")


@router.post("/autopilot/start")
def start(
    request: Request, mode: str | None = Form(None, max_length=10),
    source: str | None = Form(None, max_length=10), duration: int | None = Form(None),
    platform: str | None = Form(None, max_length=20), ai: str | None = Form(None, max_length=10),
    voice: str | None = Form(None, max_length=200),
) -> RedirectResponse:
    defaults = _defaults(request)
    chosen_source = source if source is not None else defaults["source"]
    ai_mode = ai if ai is not None else defaults["ai"]
    if chosen_source == "sample":
        ai_mode = "offline"  # the trial path never calls an external provider
    if voice is not None and voice not in {"", "default", "offline-silence"}:
        chosen_voice: str | None = voice
    elif voice == "offline-silence":
        chosen_voice = "offline-silence"
    else:
        chosen_voice = None  # saved default from the voice settings page
    try:
        job_id = request.app.state.autopilot.start(
            mode=mode if mode is not None else defaults["mode"],
            source=chosen_source,
            duration=duration if duration is not None else defaults["duration"],
            platform=platform if platform is not None else defaults["platform"],
            content_mode="real" if chosen_source == "feeds" else "trial",
            ai_mode=ai_mode, voice=chosen_voice,
        )
    except AutopilotError as exc:
        raise _error(exc) from None
    return go(f"/autopilot/jobs/{job_id}")


@router.get("/autopilot/jobs", response_class=HTMLResponse)
def jobs(request: Request) -> HTMLResponse:
    return _page(request, "autopilot_jobs.html", active="autopilot", jobs=task_rows(request))


@router.get("/autopilot/jobs/{job_id}", response_class=HTMLResponse)
def job(request: Request, job_id: str) -> HTMLResponse:
    snapshot = _snapshot(request, job_id)
    task_summary = next(row for row in task_rows(request, [snapshot]) if row["id"] == "auto:" + job_id)
    stages = [
        {"key": key, "label": STAGE_LABELS[key], "description": DESCRIPTIONS[key], "done": key in snapshot["stage_results"]}
        for key in STAGES
    ]
    with request.app.state.sessions() as session:
        draft = session.get(ContentDraft, snapshot["content_draft_id"]) if snapshot.get("content_draft_id") else None
        video = session.get(RenderJob, snapshot["render_job_id"]) if snapshot.get("render_job_id") else None
        article = session.get(NewsArticle, snapshot["article_id"]) if snapshot.get("article_id") else None
        output = _media_path(request, video)
        ai_estimate, ai_actual = _ai_usage(request, snapshot, article)
        plan = None
        if draft:
            try:
                speech = speech_preferences(request.app.state.sessions)
                plan = speech_plan(draft.content, draft.duration, speech.rate, speech.pause_ms)
            except TTSError:
                plan = speech_plan(draft.content, draft.duration)
        return _page(
            request, "autopilot_job.html", active="autopilot", job=snapshot, stages=stages,
            task_summary=task_summary,
            draft=draft, video=video, article=article, plan=plan,
            notes=list(draft.review_notes or []) if draft else [],
            playable=output is not None, output_path=str(output) if output else None,
            audio=(video.metadata_json or {}).get("audio") if video else None,
            ai_estimate=ai_estimate, ai_actual=ai_actual,
        )


@router.get("/api/autopilot/jobs/{job_id}")
def job_status(request: Request, job_id: str) -> JSONResponse:
    return JSONResponse(_snapshot(request, job_id), headers={"Cache-Control": "no-store"})


@router.post("/autopilot/jobs/{job_id}/cancel")
def cancel(request: Request, job_id: str, revision: int = Form(ge=1)) -> RedirectResponse:
    try:
        request.app.state.autopilot.cancel(job_id, revision)
    except AutopilotError as exc:
        raise _error(exc) from None
    return go(f"/autopilot/jobs/{job_id}")


@router.post("/autopilot/jobs/{job_id}/resume")
def resume(
    request: Request, job_id: str, revision: int = Form(ge=1), article_id: int | None = Form(None, ge=1),
) -> RedirectResponse:
    try:
        request.app.state.autopilot.resume(job_id, revision, article_id=article_id)
    except AutopilotError as exc:
        raise _error(exc) from None
    return go(f"/autopilot/jobs/{job_id}")


@router.post("/autopilot/jobs/{job_id}/retry")
def retry(request: Request, job_id: str, revision: int = Form(ge=1)) -> RedirectResponse:
    try:
        request.app.state.autopilot.retry(job_id, revision)
    except AutopilotError as exc:
        raise _error(exc) from None
    return go(f"/autopilot/jobs/{job_id}")


@router.get("/queue", response_class=HTMLResponse)
def queue(request: Request) -> HTMLResponse:
    with request.app.state.sessions() as session:
        entries = []
        for draft, video in session.execute(
            select(PublishDraft, RenderJob).join(RenderJob).order_by(PublishDraft.id.desc()).limit(100)
        ):
            target = _media_path(request, video)
            try:
                valid = target is not None and hash_file(target) == draft.media_sha256
            except OSError:
                valid = False
            entries.append({"draft": draft, "video": video, "playable": valid})
        return _page(request, "queue.html", active="queue", entries=entries)


@router.get("/simple-settings", response_class=HTMLResponse)
def simple_settings(request: Request, saved: bool = False) -> HTMLResponse:
    from .production_routes import settings_page

    return settings_page(request, saved=saved)


@router.post("/simple-settings")
def save_settings(
    request: Request, duration: int = Form(), platform: str = Form(max_length=20),
    source: str = Form(max_length=10), mode: str = Form("easy", max_length=10), ai: str = Form("offline", max_length=10),
) -> RedirectResponse:
    values = {"duration": str(duration), "platform": platform, "source": source, "mode": mode, "ai": ai}
    if any(value not in CHOICES[name] for name, value in values.items()):
        raise HTTPException(422, "제작 방식, 영상 길이, 목적지와 뉴스 종류를 다시 선택해 주세요.")
    if ai == "openai" and source != "feeds":
        raise HTTPException(422, "외부 AI 대본은 등록한 뉴스 출처(실제 콘텐츠)에서만 사용할 수 있습니다.")
    with request.app.state.sessions.begin() as session:
        for name, value in values.items():
            row = session.get(AppSetting, "autopilot_" + name)
            if row:
                row.value = value
            else:
                session.add(AppSetting(key="autopilot_" + name, value=value))
    return go("/simple-settings?saved=true")
