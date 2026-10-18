"""Easy Studio presentation; explicit commands reuse the durable coordinator."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

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
    IntelligenceRun,
    NewsArticle,
    NewsSource,
    NewsSourceCheck,
    PublishDraft,
    RenderJob,
    Scene,
    VideoProject,
)
from newsflow.easy_setup import preview_preferences, speech_preferences
from newsflow.intelligence.capabilities import DEFAULT_ACQUISITION_POLICY
from newsflow.intelligence.korean import speech_plan
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.intelligence.settings import (
    STUDIO_PROVIDERS,
    external_ready,
    job_estimate,
    max_tokens_for,
    read_studio_settings,
)
from newsflow.publishing.service import PublishingError, PublishingService, hash_file
from newsflow.video.tts import TTSError

from .api_settings_routes import connection_status
from .production_context import (
    ACQUISITION_LABELS,
    CATEGORY_LABELS,
    NEWS_USAGE_LABELS,
    PERIOD_LABELS,
    acquisition_preferences,
    context_json,
    context_query,
    parse_context,
    validate_context,
)
from .routes import go, page
from .task_views import task_rows
from .unified_publishing_routes import workspace_context as unified_publishing_context
from .youtube_routes import publishing_context

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
DEFAULTS = {"mode": "easy", "source": "feeds", "duration": "30", "platform": "youtube", "ai": "offline"}
AI_LABELS = {"offline": "기본 대본 (외부 호출 없음)", "openai": "외부 AI 대본 (OpenAI · 유료)",
             "claude_api": "Claude API · 별도 API 과금",
             "claude_code": "Claude Code · 본인 구독", "codex": "Codex · 본인 구독"}
GUIDES = {"provider", "voice", "approval", "sources", "model", "video", "consent", "search"}
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
        stage_labels=STAGE_LABELS, ai_labels=AI_LABELS, news_usage_labels=NEWS_USAGE_LABELS, **context,
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
        "apis": {provider: {"analysis": connection_status(request, provider, "analysis"),
                            "search": connection_status(request, provider, "search")}
                 for provider in ("openai", "claude_api")},
        "voice": {"name": voice, "silent": voice == "offline-silence", "installed": installed, **speech_values},
    }


def production_summary(request: Request, ready: dict[str, Any]) -> dict[str, Any]:
    """Presentation only; saved Studio choices are never rewritten or silently replaced."""
    saved = read_studio_settings(request.app.state.sessions)
    provider = saved["provider"]
    voice = ready["voice"]
    rss_supported = provider in STUDIO_PROVIDERS
    with request.app.state.sessions() as session:
        video_setting = session.get(AppSetting, "video_ai_provider")
        manual_video = bool(video_setting and video_setting.value == "higgsfield")
    acquisition = acquisition_preferences(request.app.state.sessions)
    if manual_video:
        rss_supported = False
        rss_notice = "Higgsfield는 장면별 비용·내용 승인이 필요합니다. 대본을 준비한 뒤 별도 장면 계획으로 이어갑니다."
    elif voice["name"] == "elevenlabs" or not voice["installed"]:
        rss_supported = False
        rss_notice = "선택한 음성의 설치·제작별 승인이 필요합니다. 다른 음성으로 자동 전환하지 않습니다."
    elif not ready["rss"]["ready"]:
        rss_supported = False
        rss_notice = "사용 중인 RSS 출처가 없습니다. 설정에서 출처를 등록한 뒤 RSS 제작을 시작하세요."
    elif provider in ready["apis"] and not ready["apis"][provider]["analysis"]["ready"]:
        rss_supported = False
        rss_notice = "등록 뉴스 자동 제작에 필요한 AI 연결·비용 승인을 설정에서 확인해 주세요."
    else:
        rss_notice = ("RSS 자료 → 선택한 API 분석·대본 → 대본 검토 → 영상 제작. "
                      "분석과 대본은 별도 사용량·비용이 발생하며 자동 대체하지 않습니다."
                      if provider in {"openai", "claude_api"} else
                      "RSS 자료 확인 → 대본 검토 → 영상 제작. 실제 처리 엔진은 작업 이력에서 확인하세요.")
    cached = getattr(request.app.state, "claude_status" if provider == "claude_code" else "codex_status", {})
    auth_checked = provider == "offline" or (provider in {"claude_code", "codex"}
                                             and cached.get("state") == "ready" and cached.get("ready") is True)
    if provider in ready["apis"]:
        auth_checked = ready["apis"][provider]["analysis"]["authentication_verified"]
    policy_states = {
        "rss": {"supported": rss_supported,
                "auth_checked": auth_checked,
                "title": "RSS 분석·대본 경로 지원" if rss_supported else "RSS 제작 조건 확인 필요",
                "detail": "실행 전 인증·승인을 확인합니다. 경로 지원은 현재 로그인·사용 가능 상태를 보장하지 않습니다."
                if rss_supported else rss_notice,
                "notice": rss_notice},
    }
    for policy in ("ai_web", "hybrid"):
        policy_states[policy] = {
            "supported": False, "title": "AI 웹 뉴스 조사 BLOCKED",
            "detail": "선택한 AI의 웹 검색이 승인·검증되지 않아 실행하지 않습니다.",
            "notice": "선택한 AI 웹 뉴스 조사는 아직 실행할 수 없습니다. RSS로 자동 전환하지 않습니다.",
        }
        if provider in ready["apis"]:
            gate = ready["apis"][provider]["search"]
            usable = (gate["ready"] and ready["apis"][provider]["analysis"]["ready"]
                      and voice["installed"] and voice["name"] != "elevenlabs"
                      and not manual_video and (policy != "hybrid" or ready["rss"]["ready"]))
            detail = " ".join(gate["reasons"]) if not gate["ready"] else (
                "검색 최대 1회 → 선택한 API 분석 1회 → 대본 1회 → 사용자 검토. 단계별 비용 승인이 필요합니다."
                if usable else "선택한 API의 분석·대본 승인, 음성·영상 또는 RSS 보완 출처를 확인하세요.")
            policy_states[policy].update(supported=usable, auth_checked=gate["authentication_verified"],
                title="API 뉴스 검색 실행 조건 확인됨" if usable else "AI 웹 뉴스 조사 BLOCKED",
                detail=detail, notice=detail + " RSS·다른 Provider로 자동 전환하지 않습니다.")
    current_policy = policy_states[acquisition["acquisition_policy"]]
    if voice["name"] == "elevenlabs":
        voice_label = "외부 한국어 음성 · 제작별 동의 필요"
    elif voice["silent"]:
        voice_label = "무음 검토영상 · 음성 없음"
    else:
        voice_label = "한국어 음성" if voice["installed"] else "선택한 음성 준비 필요"
    return {
        "provider": provider, "provider_label": STUDIO_PROVIDERS[provider],
        "automatic_supported": current_policy["supported"], "notice": current_policy["notice"],
        "policy_states": policy_states, "current_policy": current_policy,
        "voice_label": voice_label, "voice_ready": voice["installed"],
        "action_url": "/autopilot/quick-start", "guide_url": "/ai", "rss_ready": ready["rss"]["ready"],
    }


def _ai_usage(request: Request, snapshot: dict[str, Any], article: NewsArticle | None) -> tuple[dict | None, dict | None]:
    """Estimate before the paid script call and the recorded usage after it; route-level only."""
    if snapshot.get("content_mode") != "real" or snapshot.get("ai_mode") == "offline":
        return None, None
    sessions = request.app.state.sessions
    estimate = actual = None
    with sessions() as session:
        # Every analysis/script run the job ever used, including failed attempts that were retried.
        run_ids = {
            int(reference) for reference in session.scalars(select(AutopilotArtifact.reference).where(
                AutopilotArtifact.job_id == snapshot["id"],
                AutopilotArtifact.kind.in_(("search_run_id", "analysis_run_id", "script_run_id")),
            ))
        }
        run_ids |= {snapshot[key] for key in ("search_run_id", "analysis_run_id", "script_run_id") if snapshot.get(key)}
        rows = (
            session.scalars(select(AIUsage).where(AIUsage.run_id.in_(run_ids)).order_by(AIUsage.id)).all()
            if run_ids else []
        )
        if rows:
            actual = {
                "calls": len(rows), "failed": sum(1 for row in rows if row.status != "success"),
                "prompt": sum(row.prompt_tokens for row in rows), "completion": sum(row.completion_tokens for row in rows),
                "total": sum(row.total_tokens for row in rows), "model": rows[-1].model,
                "provider": snapshot["ai_mode"],
                "notice": "응답에서 받은 로컬 사용량 기록 · 공급사 계정 잔여량·실제 청구량과 다를 수 있습니다.",
                "stages": [{"kind": kind, "calls": sum(row.kind == kind for row in rows),
                            "total": sum(row.total_tokens for row in rows if row.kind == kind)}
                           for kind in ("search", "analysis", "script")],
            }
    if article is not None and snapshot.get("ai_mode") == "openai" and "script" not in snapshot.get("stage_results", {}):
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


def _workspace_video(
    request: Request, video: RenderJob, project: VideoProject, task: dict | None = None, *, ai_scenes: bool = False,
) -> dict | None:
    """The existing media boundary decides playability; a completed file never grants review."""
    output = _media_path(request, video)
    if output is None:
        return None
    stored = bool(task and task["status"] == "completed")
    return {
        "id": video.id, "title": project.title, "duration": project.duration,
        "project_id": project.id, "draft_id": project.draft_id, "task_id": task["id"] if task else None,
        "review_status": "stored" if stored else "review_required",
        "review_label": "보관 완료 · 게시 전 내용·출처·권리 검토 필요" if stored else "직접 시청·내용 확인 필요",
        "playable": True, "link": f"/?video={video.id}&publish_platform=unified#workspace-detail",
        "media_url": f"/video/jobs/{video.id}/file", "download_url": f"/video/jobs/{video.id}/file?download=true",
        "edit_url": f"/video?job_id={video.id}&draft_id={project.draft_id}",
        "review_url": f'/?task={task["id"]}#workspace-detail' if task else f"/video?job_id={video.id}&draft_id={project.draft_id}",
        "audio": (video.metadata_json or {}).get("audio"), "output_path": str(output),
        "ai_scenes": ai_scenes, "preview_only": project.preview_only,
    }


@router.get("/create", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def home(
    request: Request, task: str | None = None, video: int | None = None, show: str = "",
    guide: str = "", flow: str | None = None, publish_platform: str = "youtube",
) -> HTMLResponse:
    if (show not in {"", "tasks", "videos"} or sum((task is not None, video is not None, bool(guide))) > 1
            or video is not None and video < 1 or guide and guide not in GUIDES
            or publish_platform not in {*PLATFORMS, "unified"}):
        raise HTTPException(422, "작업 또는 영상 하나를 선택해 주세요.")
    jobs = request.app.state.autopilot.list_jobs(100)
    ready = readiness(request)
    from .production_status import production_context

    overview = production_context(request)
    tasks = task_rows(request, jobs)
    selected_task_context = job_detail_context(request, task) if task is not None else None
    workspace_guide_context = None
    if guide:
        workspace_guide_context = _guide_context(request, guide, flow)
        if workspace_guide_context["production_flow"] is None:
            raise HTTPException(422, "작업실에서 제작할 뉴스와 길이를 다시 선택해 주세요.")
    selected_video = None
    with request.app.state.sessions() as session:
        completed = []
        selected_video_id = video
        videos = session.execute(
            select(RenderJob, VideoProject).join(VideoProject)
            .where(RenderJob.status == "success").order_by(RenderJob.id.desc()).limit(100)
        ).all()
        with_ai = set(session.scalars(select(Scene.project_id).where(
            Scene.project_id.in_([project.id for _render, project in videos]), Scene.ai_generated.is_(True))))
        job_links = {item.get("render_job_id"): item for item in jobs if item.get("render_job_id")}
        for render, project in videos:
            result = _workspace_video(request, render, project, job_links.get(render.id), ai_scenes=project.id in with_ai)
            if result:
                completed.append(result)
                if render.id == selected_video_id:
                    selected_video = result
        if selected_video_id is not None and selected_video is None:
            render = session.get(RenderJob, selected_video_id)
            project = session.get(VideoProject, render.project_id) if render else None
            if project:
                ai_scenes = session.scalar(select(Scene.id).where(
                    Scene.project_id == project.id, Scene.ai_generated.is_(True)).limit(1)) is not None
                selected_video = _workspace_video(request, render, project, job_links.get(render.id), ai_scenes=ai_scenes)
            if selected_video is None:
                raise HTTPException(404, "검증된 완성 영상을 찾지 못했습니다.")
        playable_ids = {item["id"] for item in completed}
        # Missing or invalid media needs the existing render recovery view, not a player that must 404.
        tasks = [{**item, "workspace_href": item["href"]}
                 if item["kind"] == "manual" and item.get("render_job_id") not in playable_ids
                 else item for item in tasks]
        active_jobs = [item for item in tasks if not item["completed"] and not (
            item["kind"] == "manual" and item.get("render_job_id") in playable_ids)]
        # A pending Autopilot review remains actionable; don't repeat the same video below it.
        active_render_ids = {item.get("render_job_id") for item in active_jobs}
        recent_videos = completed if show == "videos" else [item for item in completed if item["id"] not in active_render_ids]
        visible_tasks = tasks[:100] if show == "tasks" else active_jobs[:5]
        visible_videos = recent_videos[:100 if show == "videos" else 5]
        return _page(
            request, "easy_home.html", active="home", defaults=_defaults(request), ready=ready,
            production=production_summary(request, ready),
            active_jobs=visible_tasks, workspace_tasks=visible_tasks, task_count=len(tasks), active_task_count=len(active_jobs),
            completed=visible_videos, workspace_videos=visible_videos, video_count=len(completed),
            selected_task_context=selected_task_context, selected_video=selected_video, workspace=True, show=show,
            workspace_guide_context=workspace_guide_context,
            publish_platform=publish_platform,
            youtube_publish=publishing_context(request, video) if publish_platform == "youtube" else None,
            instagram_publish=publishing_context(request, video, platform="instagram")
            if publish_platform == "instagram" else None,
            unified_publish=unified_publishing_context(request, video) if publish_platform == "unified" else None,
            queue_count=session.scalar(select(func.count()).select_from(PublishDraft)),
            recent_news=list(session.scalars(select(NewsArticle).order_by(NewsArticle.id.desc()).limit(5))),
            **overview,
        )


def _guide_context(request: Request, guide: str, flow: str | None) -> dict[str, Any]:
    try:
        production_flow = parse_context(flow)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    with request.app.state.sessions() as session:
        enabled = session.scalar(select(func.count()).select_from(NewsSource).where(
            NewsSource.enabled, NewsSource.url != SAMPLE_URL,
        ))
    ready = readiness(request)
    api_gate = None
    if production_flow and production_flow["initial_provider"] in ready["apis"]:
        capability = "analysis" if production_flow.get("acquisition_policy") == "rss" else "search"
        api_gate = ready["apis"][production_flow["initial_provider"]][capability]
        ready = {**ready, "ai": {**ready["ai"], "reasons": api_gate["reasons"]}}
    return {
        "defaults": _defaults(request), "enabled_sources": enabled, "ready": ready,
        "production": production_summary(request, ready), "guide": guide if guide in GUIDES else "",
        "production_flow": production_flow, "manual_url": "/ai?" + context_query(production_flow),
        "production_json": context_json(production_flow),
        "api_gate": api_gate,
        "script_output_limit": max_tokens_for(production_flow["initial_duration"] if production_flow else 30),
        "acquisition_labels": ACQUISITION_LABELS, "category_labels": CATEGORY_LABELS, "period_labels": PERIOD_LABELS,
    }


@router.get("/autopilot/start", response_class=HTMLResponse)
def start_page(request: Request, guide: str = "", flow: str | None = None, advanced: bool = False) -> HTMLResponse:
    return _page(request, "autopilot_start.html", active="autopilot", advanced=advanced,
                 **_guide_context(request, guide, flow))


@router.post("/autopilot/quick-start")
def quick_start(
    request: Request, source: str = Form(max_length=10), duration: int = Form(),
    acquisition_policy: str | None = Form(None, max_length=10),
    category: str | None = Form(None, max_length=20), period: str | None = Form(None, max_length=10),
    news_usage: str = Form("STANDARD", max_length=12),
    workspace: bool = Form(False),
) -> RedirectResponse:
    """Workspace entry point, with the same coordinator and all existing review gates."""
    if source not in CHOICES["source"] or duration not in {30, 45, 60}:
        raise HTTPException(422, "뉴스 종류와 30·45·60초 중 영상 길이를 선택해 주세요.")
    ready = readiness(request)
    saved = read_studio_settings(request.app.state.sessions)
    acquisition = acquisition_preferences(request.app.state.sessions)
    for key, value in (("acquisition_policy", acquisition_policy), ("category", category), ("period", period)):
        if value is not None:
            acquisition[key] = value
    with request.app.state.sessions() as session:
        video_setting = session.get(AppSetting, "video_ai_provider")
        video_mode = video_setting.value if video_setting and video_setting.value == "higgsfield" else "off"
    try:
        flow = validate_context({
        "source": source, "initial_duration": duration,
        "initial_provider": saved["provider"] if source == "feeds" else "offline",
        "initial_model": saved["model"] if source == "feeds" else "offline",
        "initial_voice": ready["voice"]["name"], "initial_video": video_mode,
        "news_usage": news_usage,
        "initial_platform": _defaults(request)["platform"], **acquisition,
        **({"request_id": uuid4().hex} if source == "feeds" else {}),
        })
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return _start_production(request, flow, external_consent=False, workspace=workspace)


def _start_production(request: Request, flow: dict, *, external_consent: bool, workspace: bool = False) -> RedirectResponse:
    """An explicit confirmation freezes choices; it does not grant any stored API approval."""
    source, provider = flow["source"], flow["initial_provider"]
    ready = readiness(request)

    def guide_to(reason: str):
        if workspace:
            return go(f"/?guide={reason}&{context_query(flow)}#workspace-detail")
        return go(f"/autopilot/start?guide={reason}&{context_query(flow)}")

    if flow.get("initial_video") == "higgsfield":
        return guide_to("video")
    if source == "feeds":
        policy = flow.get("acquisition_policy", DEFAULT_ACQUISITION_POLICY)
        if policy != "rss" and (provider not in ready["apis"] or not ready["apis"][provider]["search"]["ready"]):
            return guide_to("search")
        if policy in {"rss", "hybrid"} and not ready["rss"]["ready"]:
            return guide_to("sources")
        if provider in ready["apis"] and not ready["apis"][provider]["analysis"]["ready"]:
            return guide_to("approval")
    # An external voice needs the existing Video Studio per-render consent flow.
    # A missing selected voice never becomes silent or switches providers.
    voice = flow["initial_voice"]
    if voice == "elevenlabs" or (voice != "offline-silence" and not request.app.state.video.voice_available(voice)):
        return guide_to("voice")
    if source == "feeds" and provider != "offline" and not external_consent:
        return guide_to("consent")
    options = {}
    if source == "feeds":
        options = {"ai_model": flow["initial_model"], "acquisition_policy": flow["acquisition_policy"],
                   "category": flow.get("category", "all"), "period": flow.get("period", "7d"),
                   "external_consent": external_consent}
        if flow.get("request_id"):
            options["request_id"] = flow["request_id"]
    try:
        identifier = request.app.state.autopilot.start(
            mode="guided", source=source, duration=flow["initial_duration"],
            platform=flow.get("initial_platform", _defaults(request)["platform"]),
            content_mode="real" if source == "feeds" else "trial",
            ai_mode=provider if source == "feeds" else "offline", voice=voice,
            news_usage=flow.get("news_usage", "STANDARD"), **options,
        )
    except AutopilotError as exc:
        raise _error(exc) from None
    return go(f"/?task={identifier}#workspace-detail" if workspace else f"/autopilot/jobs/{identifier}")


@router.post("/autopilot/confirm-start")
def confirm_start(
    request: Request, flow: str = Form(max_length=2000), consent: bool = Form(False), workspace: bool = Form(False),
) -> RedirectResponse:
    if not consent:
        raise HTTPException(422, "이번 분석·대본 요청의 외부 자료 전송과 계정 사용량에 동의해 주세요.")
    try:
        production = parse_context(flow)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if not production or production["source"] != "feeds" or not production.get("request_id"):
        raise HTTPException(422, "홈에서 제작할 등록 뉴스를 다시 선택해 주세요.")
    return _start_production(request, production, external_consent=True, workspace=workspace)


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


def job_detail_context(request: Request, job_id: str) -> dict[str, Any]:
    """Read-only detail shared by the workspace and the existing per-job URL."""
    snapshot = _snapshot(request, job_id)
    task_summary = next(row for row in task_rows(request, [snapshot]) if row["id"] == "auto:" + job_id)
    stages = [
        {"key": key, "label": STAGE_LABELS[key], "description": DESCRIPTIONS[key], "done": key in snapshot["stage_results"]}
        for key in STAGES
    ]
    if snapshot.get("unified"):
        stages[1].update(label="기사 분석·뉴스 선정", description="확보한 기사 자료를 비교하고 대본을 만들 뉴스를 고릅니다.")
    with request.app.state.sessions() as session:
        draft = session.get(ContentDraft, snapshot["content_draft_id"]) if snapshot.get("content_draft_id") else None
        video = session.get(RenderJob, snapshot["render_job_id"]) if snapshot.get("render_job_id") else None
        article = session.get(NewsArticle, snapshot["article_id"]) if snapshot.get("article_id") else None
        analysis = session.get(IntelligenceRun, snapshot["analysis_run_id"]) if snapshot.get("analysis_run_id") else None
        search = session.get(IntelligenceRun, snapshot["search_run_id"]) if snapshot.get("search_run_id") else None
        output = _media_path(request, video)
        ai_estimate, ai_actual = _ai_usage(request, snapshot, article)
        plan = None
        if draft:
            try:
                speech = speech_preferences(request.app.state.sessions)
                plan = speech_plan(draft.content, draft.duration, speech.rate, speech.pause_ms)
            except TTSError:
                plan = speech_plan(draft.content, draft.duration)
        return {
            "job": snapshot, "stages": stages, "task_summary": task_summary,
            "draft": draft, "video": video, "article": article, "plan": plan,
            "notes": list(draft.review_notes or []) if draft else [],
            "playable": output is not None, "output_path": str(output) if output else None,
            "audio": (video.metadata_json or {}).get("audio") if video else None,
            "ai_estimate": ai_estimate, "ai_actual": ai_actual,
            "analysis": analysis, "analysis_sources": (analysis.evidence or {}).get("articles", []) if analysis else [],
            "search": search,
        }


@router.get("/autopilot/jobs/{job_id}", response_class=HTMLResponse)
def job(request: Request, job_id: str) -> HTMLResponse:
    return _page(request, "autopilot_job.html", active="autopilot", **job_detail_context(request, job_id))


@router.get("/api/autopilot/jobs/{job_id}")
def job_status(request: Request, job_id: str) -> JSONResponse:
    return JSONResponse(_snapshot(request, job_id), headers={"Cache-Control": "no-store"})


@router.post("/autopilot/jobs/{job_id}/cancel")
def cancel(request: Request, job_id: str, revision: int = Form(ge=1), workspace: bool = Form(False)) -> RedirectResponse:
    try:
        request.app.state.autopilot.cancel(job_id, revision)
    except AutopilotError as exc:
        raise _error(exc) from None
    return go(f"/?task={job_id}#workspace-detail" if workspace else f"/autopilot/jobs/{job_id}")


@router.post("/autopilot/jobs/{job_id}/resume")
def resume(
    request: Request, job_id: str, revision: int = Form(ge=1), article_id: int | None = Form(None, ge=1),
    workspace: bool = Form(False),
) -> RedirectResponse:
    try:
        request.app.state.autopilot.resume(job_id, revision, article_id=article_id)
    except AutopilotError as exc:
        raise _error(exc) from None
    return go(f"/?task={job_id}#workspace-detail" if workspace else f"/autopilot/jobs/{job_id}")


@router.post("/autopilot/jobs/{job_id}/retry")
def retry(request: Request, job_id: str, revision: int = Form(ge=1), workspace: bool = Form(False)) -> RedirectResponse:
    try:
        request.app.state.autopilot.retry(job_id, revision)
    except AutopilotError as exc:
        raise _error(exc) from None
    return go(f"/?task={job_id}#workspace-detail" if workspace else f"/autopilot/jobs/{job_id}")


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
def simple_settings(request: Request, saved: str = "") -> HTMLResponse:
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
