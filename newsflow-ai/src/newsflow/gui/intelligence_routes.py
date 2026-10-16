"""AI Studio form routes under the existing CSRF middleware."""

from __future__ import annotations

import json
import os
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from newsflow.db.models import ContentDraft, IntelligenceRun, NewsArticle
from newsflow.easy_setup import preview_preferences
from newsflow.intelligence.estimate import estimate_call, estimate_cost
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


def service(request: Request) -> IntelligenceService:
    return IntelligenceService(
        request.app.state.sessions, getattr(request.app.state, "ai_provider", None),
        getattr(request.app.state, "ai_keys", None),
        api_key_stores=getattr(request.app.state, "api_keys", None),
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
        return page(
            request,
            "ai.html",
            active="ai",
            analysis=analysis,
            draft=draft,
            draft_json=json.dumps(draft.content, ensure_ascii=False, indent=2) if draft else "",
            articles=list(session.scalars(select(NewsArticle).order_by(NewsArticle.id.desc()).limit(100))),
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
        )
    except (IntelligenceError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None
    return go(f"/ai?analysis_id={identifier}")


@router.post("/ai/generate")
def generate(
    request: Request,
    analysis_id: int = Form(ge=1),
    duration: int = Form(),
    provider: str = Form("offline", max_length=20),
    consent: bool = Form(False),
    model: str = Form("gpt-4o-mini", max_length=80),
    temperature: float = Form(0.2),
    timeout: int = Form(20),
    max_tokens: int = Form(1800),
    flow: str | None = Form(None, max_length=2000),
) -> RedirectResponse:
    try:
        incoming = parse_context(flow)
        with request.app.state.sessions() as session:
            production = context_for_run(session.get(IntelligenceRun, analysis_id)) or incoming
        if production:
            production = {**production, "analysis_id": analysis_id}
        options = Options(model, temperature, timeout, max_tokens)
        identifier = service(request).generate(
            analysis_id, duration, provider, consent, options,
            on_run=remember_context(request.app.state.sessions, production),
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
            closing = form.get("closing")
            if isinstance(closing, str):
                payload["closing"] = closing
        service(request).edit(draft_id, revision, payload)
    except (ValueError, TypeError):
        raise HTTPException(422, "대본 필드 길이와 장면 시간을 확인하세요.") from None
    except IntelligenceError as exc:
        raise HTTPException(409 if exc.code == "conflict" else 422, str(exc)) from None
    return go(f"/ai?draft_id={draft_id}")
