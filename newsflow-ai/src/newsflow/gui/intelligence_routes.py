"""AI Studio form routes under the existing CSRF middleware."""

from __future__ import annotations

import json
import os
import re
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from newsflow.db.models import (
    AutopilotArtifact,
    AutopilotJob,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    RenderJob,
    VideoProject,
)
from newsflow.easy_setup import preview_preferences, speech_preferences
from newsflow.intelligence.estimate import estimate_call, estimate_cost
from newsflow.intelligence.news_usage import API_SCRIPT_METHODS, safe_topic_script
from newsflow.intelligence.presentation import AUDIENCES, STYLES, TONES
from newsflow.intelligence.provider import SCRIPT_INSTRUCTION, Options
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.intelligence.settings import (
    PRICE_DISCLAIMER,
    SettingsError,
    read_prices,
    read_settings,
    read_studio_settings,
    write_studio_settings,
)
from newsflow.news.lifecycle import visible_news

from .production_context import (
    context_for_draft,
    context_for_run,
    context_json,
    parse_context,
    remember_context,
    validate_context,
)
from .routes import go, page

router = APIRouter()


def _topic_editor_options(draft: ContentDraft | None) -> list[dict]:
    """Only known text variants for this saved source and scene role enter controls."""
    if (not draft or not draft.sources.get("news_usage")
            or draft.sources.get("script_method") in API_SCRIPT_METHODS):
        return []
    try:
        variants = [safe_topic_script(draft.sources, duration) for duration in (30, 45, 60)]
        topic = variants[0]["title"].split(" · ")[0]
    except (ValueError, TypeError, KeyError):
        return [{} for _ in draft.content.get("scenes", [])]
    result = []
    for scene in draft.content.get("scenes", []):
        roles = {index for variant in variants for index, allowed in enumerate(variant["scenes"])
                 if scene["narration"] == allowed["narration"] and scene["material"] == allowed["material"]}
        if len(roles) != 1:
            result.append({})  # Older preserved drafts remain readable without guessed alternatives.
            continue
        role = roles.pop()
        narrations = sorted({variant["scenes"][role]["narration"] for variant in variants}, key=lambda value: (len(value), value))
        caption = variants[0]["scenes"][role]["caption"]
        protected = "개별 기사 미확인" in caption
        result.append({"short": narrations[0], "full": narrations[-1], "topic": topic,
                       "protected": protected, "captions": [caption] if protected else [caption, topic]})
    return result


def _draft_workspace_link(session, draft: ContentDraft | None) -> str:
    """Derive a local return link from the durable relationship, never a supplied URL."""
    if draft is None:
        return "/"
    identifier = session.scalar(select(AutopilotJob.id).join(
        AutopilotArtifact, AutopilotArtifact.job_id == AutopilotJob.id,
    ).where(AutopilotArtifact.kind == "content_draft_id", AutopilotArtifact.reference == str(draft.id))
        .order_by(AutopilotJob.created_at.desc()).limit(1))
    return f"/?task={identifier}#workspace-detail" if identifier and re.fullmatch(r"[a-f0-9]{32}", identifier) else "/"


@router.post("/ai/codex/status")
def codex_status(request: Request) -> dict:
    from newsflow.intelligence.codex import CODEX_PROVIDER
    from newsflow.intelligence.settings import usage_this_month

    status = CODEX_PROVIDER.status()
    request.app.state.codex_status = status
    return {**status, "local_usage": usage_this_month(request.app.state.sessions, "codex"),
            "usage_notice": "로컬 기록이며 ChatGPT 계정 잔여량·실제 청구량이 아닙니다."}


@router.post("/ai/codex/cancel")
def codex_cancel(request: Request) -> dict:
    from newsflow.intelligence.codex import CODEX_PROVIDER

    return {"cancel_requested": CODEX_PROVIDER.cancel()}


@router.post("/ai/claude/status")
def claude_status(request: Request) -> dict:
    from newsflow.intelligence.claude_code import CLAUDE_LOGIN
    from newsflow.intelligence.settings import usage_this_month

    status = CLAUDE_LOGIN.check()
    request.app.state.claude_status = status
    return {**status, "local_usage": usage_this_month(request.app.state.sessions, "claude_code"),
            "usage_notice": "로컬 기록이며 Claude 계정 잔여량·실제 청구량이 아닙니다."}


@router.post("/ai/claude/login")
def claude_login(request: Request, consent: bool = Form(False)) -> dict:
    from newsflow.intelligence.claude_code import CLAUDE_LOGIN

    if not consent:
        raise HTTPException(422, "공식 로그인 창 열기에 동의해 주세요.")
    result = CLAUDE_LOGIN.start(consent=True)
    request.app.state.claude_status = result
    return result


@router.post("/ai/preferences")
def studio_preferences(request: Request, provider: str = Form(max_length=20),
                       model: str = Form(max_length=80),
                       return_to: str = Form("studio", max_length=20)) -> RedirectResponse:
    if return_to not in ("studio", "settings"):
        raise HTTPException(422, "설정 저장 화면을 다시 열어 주세요.")
    try:
        write_studio_settings(request.app.state.sessions, provider, model)
    except SettingsError as exc:
        raise HTTPException(422, str(exc)) from None
    if return_to == "settings":
        return go("/simple-settings?saved=true#connections")
    anchor = "codex-connection" if provider == "codex" else "claude-connection"
    return go(f"/ai?saved=true#{anchor}")


@router.post("/ai/claude/cancel")
def claude_cancel(request: Request) -> dict:
    from newsflow.intelligence.claude_code import CLAUDE_PROVIDER

    return {"cancel_requested": CLAUDE_PROVIDER.cancel()}


def service(request: Request, production=None) -> IntelligenceService:
    from newsflow.video.narration_planning import selected_voice

    speech = speech_preferences(request.app.state.sessions)
    voice = selected_voice(request.app.state.sessions, (production or {}).get('initial_voice'))
    return IntelligenceService(
        request.app.state.sessions, getattr(request.app.state, "ai_provider", None),
        getattr(request.app.state, "ai_keys", None),
        speech={"rate": speech.rate, "pause_ms": speech.pause_ms},
        api_key_stores=getattr(request.app.state, "api_keys", None),
        narration_root=getattr(getattr(request.app.state, 'video', None), 'root', None), narration_voice=voice,
    )


def connection_context(request: Request) -> dict:
    """Saved defaults and cached diagnostics only; viewing settings never starts a CLI."""
    from newsflow.intelligence.claude_code import connection_state

    return {
        "studio_defaults": read_studio_settings(request.app.state.sessions),
        "claude_status": getattr(request.app.state, "claude_status", connection_state("unchecked")),
        "codex_status": getattr(request.app.state, "codex_status", {
            "state": "unchecked", "installed": False, "authenticated": False, "ready": False,
            "version": None, "checked_at": None, "web_search_verified": False,
            "message": "아직 연결을 확인하지 않았습니다. 설치·로그인 확인을 눌러 주세요.",
        }),
    }


@router.get("/ai", response_class=HTMLResponse)
def studio(request: Request, analysis_id: int | None = None, draft_id: int | None = None,
           saved: bool = False, flow: str | None = None, failed_run_id: int | None = None) -> HTMLResponse:
    connections = connection_context(request)
    studio_defaults = connections["studio_defaults"]
    with request.app.state.sessions() as session:
        analysis = session.get(IntelligenceRun, analysis_id) if analysis_id else None
        draft = session.get(ContentDraft, draft_id) if draft_id else None
        if (analysis_id and (not analysis or analysis.kind != "analysis")) or (draft_id and not draft):
            raise HTTPException(404, "분석 또는 초안이 없습니다.")
        try:
            incoming = parse_context(flow)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        production = context_for_draft(session, draft) or context_for_run(analysis) or incoming
        if production is None and analysis is None and draft is None:
            from .autopilot_routes import _defaults

            production = validate_context({
                "source": "feeds", "initial_duration": _defaults(request)["duration"],
                "initial_provider": studio_defaults["provider"], "initial_model": studio_defaults["model"],
                "initial_voice": preview_preferences(request.app.state.sessions)[0],
            })
        actual_run = session.get(IntelligenceRun, draft.run_id) if draft else analysis
        failed_run = session.get(IntelligenceRun, failed_run_id) if failed_run_id else None
        if failed_run_id and (not failed_run or failed_run.kind != "script" or failed_run.status == "success"
                              or (context_for_run(failed_run) or {}).get("analysis_id") != analysis_id):
            raise HTTPException(404, "해당 분석의 대본 실행 기록을 찾지 못했습니다.")
        selected_provider = actual_run.provider if actual_run else (
            production["initial_provider"] if production else studio_defaults["provider"]
        )
        selected_model = actual_run.options.get("model") if actual_run else (
            production["initial_model"] if production else studio_defaults["model"]
        )
        execution_defaults = {**studio_defaults, "provider": selected_provider, "model": selected_model,
                              "models": {**studio_defaults["models"], selected_provider: selected_model}}
        selected_duration = draft.duration if draft else production["initial_duration"] if production else 30
        settings = read_settings(request.app.state.sessions)
        estimate = None
        if analysis is not None and analysis.status == "success":
            estimate = estimate_call(SCRIPT_INSTRUCTION, {"duration": selected_duration, "evidence": analysis.evidence}, 1800)
            estimate["cost"] = estimate_cost(estimate, read_prices(request.app.state.sessions))
        preview = None
        if draft:
            from .autopilot_routes import _workspace_video

            latest = session.execute(select(RenderJob, VideoProject).join(VideoProject).where(
                VideoProject.draft_id == draft.id, RenderJob.status == "success",
            ).order_by(RenderJob.id.desc()).limit(1)).first()
            if latest:
                preview = _workspace_video(request, *latest)
        return page(
            request,
            "ai.html",
            preview=preview,
            script_styles=STYLES, script_tones=TONES, script_audiences=AUDIENCES,
            active="ai",
            analysis=analysis,
            draft=draft,
            topic_editor=bool(draft and draft.sources.get("news_usage")
                              and draft.sources.get("script_method") not in API_SCRIPT_METHODS),
            api_editor=bool(draft and draft.sources.get("script_method") in API_SCRIPT_METHODS),
            topic_options=_topic_editor_options(draft),
            workspace_return=_draft_workspace_link(session, draft),
            draft_json=json.dumps(draft.content, ensure_ascii=False, indent=2) if draft else "",
            articles=list(session.scalars(select(NewsArticle).where(
                visible_news())
                .order_by(NewsArticle.id.desc()).limit(100))),
            runs=list(session.scalars(select(IntelligenceRun).order_by(IntelligenceRun.id.desc()).limit(30))),
            drafts=list(session.scalars(select(ContentDraft).order_by(ContentDraft.id.desc()).limit(30))),
            key_available=bool(os.environ.get("NEWSFLOW_AI_API_KEY")) or bool(
                getattr(request.app.state, "ai_keys", None) and request.app.state.ai_keys.status()["configured"]
            ),
            default_model=selected_model, default_timeout=settings.timeout, estimate=estimate,
            execution_defaults=execution_defaults, production=production, production_json=context_json(production),
            selected_duration=selected_duration, actual_run=actual_run,
            failed_run=failed_run,
            saved=saved, **connections,
            disclaimer=PRICE_DISCLAIMER,
        )


@router.post("/ai/analyze")
def analyze(
    request: Request,
    article_ids: Annotated[list[int], Form()],
    provider: str = Form("offline", max_length=20),
    consent: bool = Form(False),
    model: str = Form("gpt-4o-mini", max_length=80),
    temperature: float = Form(0.2),
    timeout: int = Form(20),
    max_tokens: int = Form(1800),
    flow: str | None = Form(None, max_length=2000),
) -> RedirectResponse:
    try:
        production = parse_context(flow)
        identifier = service(request).analyze(
            article_ids, provider, consent, Options(model, temperature, timeout, max_tokens),
            on_run=remember_context(request.app.state.sessions, production),
            news_usage=production.get("news_usage") if production and provider in {"openai", "claude_api"} else None,
        )
    except (IntelligenceError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None
    return go(f"/ai?analysis_id={identifier}")


@router.post("/ai/generate")
def generate(
    request: Request,
    analysis_id: int = Form(ge=1),
    source_draft_id: int | None = Form(None, ge=1),
    duration: int = Form(),
    provider: str = Form("offline", max_length=20),
    consent: bool = Form(False),
    model: str = Form("gpt-4o-mini", max_length=80),
    temperature: float = Form(0.2),
    timeout: int = Form(20),
    max_tokens: int = Form(1800),
    flow: str | None = Form(None, max_length=2000),
    script_style: str = Form("news", max_length=20),
    script_tone: str = Form("neutral", max_length=20),
    script_audience: str = Form("general", max_length=20),
) -> RedirectResponse:
    try:
        incoming = parse_context(flow)
        selected_ids = None
        with request.app.state.sessions() as session:
            if source_draft_id is not None:
                original = session.get(ContentDraft, source_draft_id)
                original_run = session.get(IntelligenceRun, original.run_id) if original else None
                if (not original_run or original_run.options.get("analysis_run_id") != analysis_id
                        or original_run.provider != provider or original_run.options.get("model") != model):
                    raise ValueError("원본 대본과 같은 분석·AI·모델을 사용하세요.")
                selected_ids = original_run.options.get("selected_article_ids")
            production = context_for_run(session.get(IntelligenceRun, analysis_id)) or incoming
        if production:
            production = {**production, "analysis_id": analysis_id}
        options = Options(model, temperature, timeout, max_tokens)
        identifier = service(request, production).generate(
            analysis_id, duration, provider, consent, options,
            on_run=remember_context(request.app.state.sessions, production),
            script_style=script_style, script_tone=script_tone, script_audience=script_audience,
            article_ids=selected_ids,
            news_usage=production.get("news_usage") if production and provider in {"openai", "claude_api"} else None,
        )
    except (IntelligenceError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None
    return go(f"/ai?analysis_id={analysis_id}&draft_id={identifier}")


@router.post("/ai/drafts/{draft_id}")
async def edit(
    request: Request,
    draft_id: int,
    revision: int = Form(ge=1),
    content: str | None = Form(None, max_length=20000),
) -> RedirectResponse:
    try:
        if content is not None:
            payload = json.loads(content)
        else:
            form = await request.form()
            seconds = form.getlist("seconds")
            narrations, captions, materials = (form.getlist(k) for k in ("narration", "caption", "material"))
            if not len(seconds) == len(narrations) == len(captions) == len(materials):
                raise ValueError
            payload = {
                "title": form.get("title"),
                "hook": form.get("hook"),
                "summary": form.get("summary"),
                "scenes": [
                    {"seconds": int(sec), "narration": n, "caption": c, "material": m}
                    for sec, n, c, m in zip(seconds, narrations, captions, materials)
                ],
            }
            note_fields = form.getlist("scene_review_notes")
            if note_fields and len(note_fields) != len(payload["scenes"]):
                raise ValueError
            for scene, notes in zip(payload["scenes"], note_fields):
                scene["review_notes"] = [line.strip() for line in str(notes).splitlines() if line.strip()]
            closing = form.get("closing")
            if isinstance(closing, str):
                payload["closing"] = closing
        service(request).edit(draft_id, revision, payload)
    except (ValueError, TypeError):
        raise HTTPException(422, "대본 필드 길이와 장면 시간을 확인하세요.") from None
    except IntelligenceError as exc:
        raise HTTPException(409 if exc.code == "conflict" else 422, str(exc)) from None
    return go(f"/ai?draft_id={draft_id}")
