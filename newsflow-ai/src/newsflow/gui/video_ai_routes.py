"""AI 고품질 제작 (optional AI video mode) and its settings; the local FFmpeg Video Studio is unchanged.

Every mutation is a CSRF-protected form POST answered with a redirect; refusals return the
service's fixed Korean sentence as ``detail`` so the page can show why (never provider text).
"""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from newsflow.db.models import AIVideoPlan, AIVideoScene, ContentDraft, VideoAIUsage
from newsflow.easy_setup import SetupError, preview_preferences
from newsflow.intelligence.credentials import CredentialError
from newsflow.video.ai.costs import CURRENCIES
from newsflow.video.ai.policy import DEFAULT_PROMPT, SCENE_LABEL, STYLE_GUARD, VIDEO_NOTICE
from newsflow.video.ai.preflight import inspect_setup
from newsflow.video.ai.production import DEFAULT_MODEL, model_ready, read_contract
from newsflow.video.ai.service import DISCARD_LABEL, AIVideoError
from newsflow.video.ai.settings import (
    CANDIDATE_PATHS,
    DISCLAIMER,
    HOSTS,
    PROVIDERS,
    RESOLUTIONS,
    VideoSettingsError,
    delete_model,
    list_models,
    read_settings,
    save_model,
    write_settings,
)

from .production_context import context_for_draft
from .routes import go, page

router = APIRouter()

SOURCE_LABELS = {"card": "기본 카드 (외부 호출 없음)", "local": "로컬 이미지 (assets 폴더)", "generated": "AI 생성 영상 (유료)"}
STATUS_LABELS = {
    "planned": "준비", "waiting": "제출 대기", "submitting": "제출 중", "queued": "공급사 대기열", "in_progress": "생성 중",
    "downloading": "내려받는 중", "ready": "생성 완료", "failed": "실패", "nsfw": "정책 거부", "canceled": "취소",
    "unknown": "결과 불명",
}
PLAN_LABELS = {
    "draft": "계획 편집", "generating": "AI 생성 진행 중", "review": "검토 필요", "composing": "최종 합성 중",
    "composed": "최종 합성 완료", "compose_failed": "최종 합성 실패",
}


def _service(request: Request):
    return request.app.state.video_ai


def _fail(exc: Exception) -> HTTPException:
    status = getattr(exc, "status", 422)
    return HTTPException(status if status in (404, 409, 422, 502) else 422, str(exc))


@router.get("/video/ai", response_class=HTMLResponse)
def plans(request: Request, draft_id: int | None = None) -> HTMLResponse:
    service = _service(request)
    service.sync()
    with request.app.state.sessions() as session:
        rows = list(session.scalars(select(AIVideoPlan).order_by(AIVideoPlan.id.desc()).limit(30)))
        drafts = list(session.scalars(select(ContentDraft).order_by(ContentDraft.id.desc()).limit(100)))
    return page(
        request, "video_ai.html", active="video", plans=rows, drafts=drafts, draft_id=draft_id,
        selected_duration=next((draft.duration for draft in drafts if draft.id == draft_id), 30),
        ready=service.readiness(reported=True), plan_labels=PLAN_LABELS, notice=VIDEO_NOTICE,
        full_models=[model for model in service.models() if model_ready(model)], default_model=DEFAULT_MODEL,
    )


@router.post("/video/ai/plans")
def create_plan(request: Request, draft_id: int = Form(ge=1), duration: int = Form(),
                mode: str = Form("mixed"), model_path: str = Form("", max_length=160),
                external_tts_consent: bool = Form(False)) -> RedirectResponse:
    with request.app.state.sessions() as session:
        choice = context_for_draft(session, session.get(ContentDraft, draft_id)) or {}
    if (choice.get("production_options_version") == 1 and choice.get("initial_video") == "higgsfield"
            and choice.get("initial_voice") == "elevenlabs" and mode != "full"):
        raise HTTPException(422, "ElevenLabs + Higgsfield 동시 합성은 지원하지 않습니다. 생성 요청 전에 제작 방식을 다시 선택하세요. 다른 음성으로 대체하지 않습니다.")
    try:
        plan_id = _service(request).create_plan(draft_id, duration, mode=mode, model_path=model_path,
                                                external_tts_consent=external_tts_consent)
    except AIVideoError as exc:
        raise _fail(exc) from None
    return go(f"/video/ai/plans/{plan_id}")


def _plan_context(request: Request, plan_id: int) -> dict:
    service = _service(request)
    service.sync()
    with request.app.state.sessions() as session:
        plan = session.get(AIVideoPlan, plan_id)
        if plan is None:
            raise HTTPException(404, "AI 영상 계획을 찾지 못했습니다.")
        scenes = list(session.scalars(
            select(AIVideoScene).where(AIVideoScene.plan_id == plan_id).order_by(AIVideoScene.position)))
        draft = session.get(ContentDraft, plan.draft_id)
        production_context = context_for_draft(session, draft)
        contract = read_contract(session, plan_id)
        usage = list(session.scalars(
            select(VideoAIUsage).where(VideoAIUsage.plan_id == plan_id).order_by(VideoAIUsage.id)))
        session.expunge_all()
    try:
        compose_voice = preview_preferences(request.app.state.sessions)[0]
    except SetupError:
        compose_voice = None
    if contract:
        compose_voice = contract["production"]["voice"]
    return {"plan": plan, "scenes": scenes, "draft": draft, "usage": usage, "service": service,
            "plan_contract": contract,
            "production_context": production_context, "compose_voice": compose_voice}


@router.get("/video/ai/plans/{plan_id}", response_class=HTMLResponse)
def plan_page(request: Request, plan_id: int, saved: str = "") -> HTMLResponse:
    context = _plan_context(request, plan_id)
    service = context.pop("service")
    return page(
        request, "video_ai_plan.html", active="video", **context, estimate=service.estimate(plan_id),
        ready=service.readiness(reported=bool(context["plan_contract"])), provider_off=service.provider() is None,
        models=[m for m in service.models() if model_ready(m)] if context["plan_contract"]
        else [m for m in service.models() if m.usable], assets=request.app.state.video.assets_list(),
        source_labels=SOURCE_LABELS, status_labels=STATUS_LABELS, plan_labels=PLAN_LABELS, style_guard=STYLE_GUARD,
        scene_label=SCENE_LABEL, notice=VIDEO_NOTICE, default_prompt=DEFAULT_PROMPT, saved=saved[:20],
        active_statuses=sorted({"waiting", "submitting", "queued", "in_progress", "downloading"}),
        paid_positions=[s.position for s in context["scenes"] if service.holds_paid_result(s)], discard_label=DISCARD_LABEL,
        refetch_positions=[s.position for s in context["scenes"] if service.can_refetch(s)],
    )


@router.get("/api/video/ai/plans/{plan_id}")
def plan_status(request: Request, plan_id: int) -> dict:
    _service(request).sync()
    with request.app.state.sessions() as session:
        plan = session.get(AIVideoPlan, plan_id)
        if plan is None:
            raise HTTPException(404, "AI 영상 계획이 없습니다.")
        scenes = session.scalars(select(AIVideoScene).where(AIVideoScene.plan_id == plan_id).order_by(AIVideoScene.position))
        return {
            "plan_id": plan.id, "status": plan.status, "revision": plan.revision,
            "scenes": [{"position": s.position, "status": s.status, "message": s.message} for s in scenes],
        }


@router.post("/video/ai/plans/{plan_id}/scenes")
async def save_scenes(request: Request, plan_id: int, revision: int = Form(ge=1), asset_permission: bool = Form(False)) -> RedirectResponse:
    form = await request.form()
    edits = []
    for index in range(8):
        if f"source_{index}" not in form:
            continue
        edits.append({
            "position": index, "source": str(form.get(f"source_{index}", ""))[:12],
            "material": str(form.get(f"material_{index}", ""))[:255], "prompt": str(form.get(f"prompt_{index}", ""))[:2000],
            "model_path": str(form.get(f"model_{index}", ""))[:160],
            "discard": form.get(f"discard_{index}") == "true",
        })
    try:
        # Local images are decoded while validating; keep that off the event loop.
        await run_in_threadpool(_service(request).update_scenes, plan_id, revision, edits, asset_permission)
    except AIVideoError as exc:
        raise _fail(exc) from None
    return go(f"/video/ai/plans/{plan_id}?saved=scenes")


@router.post("/video/ai/plans/{plan_id}/confirm")
def confirm(
    request: Request, plan_id: int, revision: int = Form(ge=1), shown_total: str = Form("", max_length=40),
    confirmed: bool = Form(False),
) -> RedirectResponse:
    try:
        _service(request).confirm_generation(plan_id, revision, shown_total, confirmed)
    except AIVideoError as exc:
        raise _fail(exc) from None
    return go(f"/video/ai/plans/{plan_id}?saved=confirmed")


@router.post("/video/ai/plans/{plan_id}/scenes/{position}/cancel")
def cancel(request: Request, plan_id: int, position: int, revision: int = Form(ge=1)) -> RedirectResponse:
    try:
        _service(request).cancel_scene(plan_id, revision, position)
    except AIVideoError as exc:
        raise _fail(exc) from None
    return go(f"/video/ai/plans/{plan_id}?saved=canceled")


@router.post("/video/ai/plans/{plan_id}/scenes/{position}/resolve")
def resolve(request: Request, plan_id: int, position: int, revision: int = Form(ge=1)) -> RedirectResponse:
    try:
        _service(request).resolve_unknown(plan_id, revision, position)
    except AIVideoError as exc:
        raise _fail(exc) from None
    return go(f"/video/ai/plans/{plan_id}?saved=resolved")


@router.post("/video/ai/plans/{plan_id}/rebase")
def rebase(request: Request, plan_id: int, revision: int = Form(ge=1)) -> RedirectResponse:
    try:
        _service(request).rebase(plan_id, revision)
    except AIVideoError as exc:
        raise _fail(exc) from None
    return go(f"/video/ai/plans/{plan_id}?saved=rebased")


@router.post("/video/ai/plans/{plan_id}/scenes/{position}/refetch")
def refetch(request: Request, plan_id: int, position: int, revision: int = Form(ge=1)) -> RedirectResponse:
    try:
        _service(request).refetch(plan_id, revision, position)
    except AIVideoError as exc:
        raise _fail(exc) from None
    return go(f"/video/ai/plans/{plan_id}?saved=refetch")


@router.post("/video/ai/plans/{plan_id}/review")
async def review(request: Request, plan_id: int, revision: int = Form(ge=1), statement: bool = Form(False)) -> RedirectResponse:
    form = await request.form()
    positions = {index for index in range(8) if form.get(f"reviewed_{index}") == "true"}
    try:
        await run_in_threadpool(_service(request).review, plan_id, revision, positions, statement)
    except AIVideoError as exc:
        raise _fail(exc) from None
    return go(f"/video/ai/plans/{plan_id}?saved=reviewed")


@router.post("/video/ai/plans/{plan_id}/approve")
def approve(request: Request, plan_id: int, revision: int = Form(ge=1), approved: bool = Form(False)) -> RedirectResponse:
    try:
        job_id = _service(request).approve_compose(plan_id, revision, approved)
    except AIVideoError as exc:
        raise _fail(exc) from None
    return go(f"/video?job_id={job_id}")


@router.get("/video/ai/scenes/{scene_id}/clip")
def clip(request: Request, scene_id: int) -> FileResponse:
    service = _service(request)
    try:
        path = service.clip_path(scene_id)
    except AIVideoError as exc:
        raise _fail(exc) from None
    with request.app.state.sessions() as session:
        scene = session.get(AIVideoScene, scene_id)
        media = "video/webm" if (scene.clip_meta or {}).get("format") == "matroska" else "video/mp4"
    return FileResponse(path, media_type=media, content_disposition_type="inline", filename=path.name)


# --------------------------------------------------------------------------- settings

@router.get("/video-ai-settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: str = "") -> HTMLResponse:
    service = _service(request)
    sessions = request.app.state.sessions
    with sessions() as session:
        usage = list(session.scalars(select(VideoAIUsage).order_by(VideoAIUsage.id.desc()).limit(20)))
    return page(
        request, "video_ai_settings.html", active="simple-settings", settings=read_settings(sessions),
        ready=service.readiness(reported=True), providers=PROVIDERS, hosts=HOSTS, currencies=CURRENCIES, resolutions=RESOLUTIONS,
        models=list_models(sessions), model_schema_ready=[m.id for m in list_models(sessions) if model_ready(m)],
        candidates=CANDIDATE_PATHS, disclaimer=DISCLAIMER, usage=usage,
        key=service.keys.status(), saved=saved[:20], style_guard=STYLE_GUARD,
    )


@router.post("/video-ai-settings/preflight")
def start_preflight() -> RedirectResponse:
    # Match the existing fetch/redirect forms; the destination is strictly read-only.
    return go("/video-ai-settings/preflight")


@router.get("/video-ai-settings/preflight", response_class=HTMLResponse)
def preflight(request: Request) -> HTMLResponse:
    report = inspect_setup(request.app.state.sessions, _service(request).keys, reported=True)
    return page(request, "video_ai_preflight.html", active="simple-settings", report=report)


@router.post("/video-ai-settings")
def save_settings(
    request: Request, provider: str = Form(max_length=20), host: str = Form(HOSTS[0], max_length=40),
    approved: bool = Form(False), monthly_limit: str = Form("", max_length=20), job_limit: str = Form("", max_length=20),
    currency: str = Form("USD", max_length=3), max_active: int = Form(2), timeout_minutes: int = Form(30),
    poll_seconds: int = Form(10),
) -> RedirectResponse:
    try:
        write_settings(
            request.app.state.sessions, provider=provider, host=host, approved=approved, monthly_limit=monthly_limit,
            job_limit=job_limit, currency=currency, max_active=max_active, timeout_minutes=timeout_minutes,
            poll_seconds=poll_seconds,
        )
    except VideoSettingsError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/video-ai-settings?saved=settings")


@router.post("/video-ai-settings/models")
def save_model_route(
    request: Request, path: str = Form(max_length=160), label: str = Form(max_length=80),
    price_per_second: str = Form("", max_length=20), durations: str = Form("5", max_length=60),
    resolution: str = Form("720p", max_length=10), confirmed: bool = Form(False), model_id: int | None = Form(None),
) -> RedirectResponse:
    try:
        save_model(
            request.app.state.sessions, path=path, label=label, price_per_second=price_per_second, durations=durations,
            resolution=resolution, confirmed=confirmed, model_id=model_id,
        )
    except VideoSettingsError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/video-ai-settings?saved=model")


@router.post("/video-ai-settings/models/{model_id}/delete")
def delete_model_route(request: Request, model_id: int) -> RedirectResponse:
    try:
        delete_model(request.app.state.sessions, model_id)
    except VideoSettingsError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/video-ai-settings?saved=deleted")


@router.post("/video-ai-settings/key")
def save_key(request: Request, api_key: str = Form(max_length=520)) -> RedirectResponse:
    try:
        _service(request).keys.save(api_key)
    except CredentialError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/video-ai-settings?saved=key")


@router.post("/video-ai-settings/key/clear")
def clear_key(request: Request) -> RedirectResponse:
    try:
        _service(request).keys.clear()
    except CredentialError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/video-ai-settings?saved=cleared")
