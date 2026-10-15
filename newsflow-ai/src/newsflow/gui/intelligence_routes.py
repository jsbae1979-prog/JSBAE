"""AI Studio form routes under the existing CSRF middleware."""

from __future__ import annotations

import json
import os
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from newsflow.db.models import ContentDraft, IntelligenceRun, NewsArticle
from newsflow.intelligence.provider import Options
from newsflow.intelligence.service import IntelligenceError, IntelligenceService

from .routes import go, page

router = APIRouter()


def service(request: Request) -> IntelligenceService:
    return IntelligenceService(
        request.app.state.sessions, getattr(request.app.state, "ai_provider", None),
        getattr(request.app.state, "ai_keys", None),
    )


@router.get("/ai", response_class=HTMLResponse)
def studio(request: Request, analysis_id: int | None = None, draft_id: int | None = None) -> HTMLResponse:
    with request.app.state.sessions() as session:
        analysis = session.get(IntelligenceRun, analysis_id) if analysis_id else None
        draft = session.get(ContentDraft, draft_id) if draft_id else None
        if (analysis_id and (not analysis or analysis.kind != "analysis")) or (draft_id and not draft):
            raise HTTPException(404, "분석 또는 초안이 없습니다.")
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
) -> RedirectResponse:
    try:
        identifier = service(request).analyze(
            article_ids, provider, consent, Options(model, temperature, timeout, max_tokens)
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
) -> RedirectResponse:
    try:
        options = Options(model, temperature, timeout, max_tokens)
        identifier = service(request).generate(analysis_id, duration, provider, consent, options)
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
