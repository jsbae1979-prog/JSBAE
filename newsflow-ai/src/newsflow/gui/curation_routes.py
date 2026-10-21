"""Google News + Trends selection inside the existing news screen and AI review flow."""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from filelock import FileLock, Timeout

from newsflow.db.models import AppSetting, ContentDraft, IntelligenceRun
from newsflow.intelligence.curation import (
    CURATION_TIMEOUT_SECONDS,
    WORKSPACE_TOP_K,
    curation_output_tokens,
    ranking_json,
    script_json,
)
from newsflow.intelligence.provider import Options
from newsflow.intelligence.service import IntelligenceError
from newsflow.intelligence.settings import read_studio_settings
from newsflow.news.curator import Curator
from newsflow.news.rss_adapter import FeedError
from newsflow.news.service import CollectionBusy

from .intelligence_routes import service
from .routes import go

router = APIRouter()


def context(request: Request) -> dict:
    """Stored local data only. No network/authentication/AI on a GET."""
    from .serpapi_routes import connection_context

    result = Curator(request.app.state.coordinator).context()
    result["serpapi"] = connection_context(request)
    result["ai"] = read_studio_settings(request.app.state.sessions)
    result["api_selected"] = result["ai"]["provider"] in {"openai", "claude_api"}
    result["selection_limit"] = WORKSPACE_TOP_K
    return result


@router.post("/news/curation/refresh")
def refresh(request: Request, permission: bool = Form(False)):
    try:
        Curator(request.app.state.coordinator).refresh(permission)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except CollectionBusy:
        raise HTTPException(409, "다른 수집 작업이 진행 중입니다.") from None
    return go("/news#curation")


@router.post("/news/curation/import")
def import_rss(request: Request, rss_xml: str = Form(max_length=20000), permission: bool = Form(False)):
    try:
        Curator(request.app.state.coordinator).import_feed(rss_xml.encode("utf-8"), permission)
    except (ValueError, FeedError):
        raise HTTPException(422, "제공 RSS의 이용 권한·형식·공개 URL과 기사 1~5개 조건을 확인해 주세요.") from None
    except CollectionBusy:
        raise HTTPException(409, "다른 수집 작업이 진행 중입니다.") from None
    return go("/news#curation")


def _once(request: Request, identity: list, callback) -> dict:
    """Durable claim before calling. Repeated submits/restarts reuse the record, never the request."""
    sessions = request.app.state.sessions
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:36]
    key = "curation_once:" + digest
    try:
        with FileLock(str(request.app.state.config.data_dir / "curation.lock")).acquire(timeout=0):
            with sessions.begin() as session:
                existing = session.get(AppSetting, key)
                if existing:
                    record = json.loads(existing.value)
                    if record.get("status") == "success":
                        return record
                    raise HTTPException(409, "이미 요청한 작업입니다. 실행/실패 기록을 보존하며 자동 재요청하지 않습니다.")
                session.add(AppSetting(key=key, value=json.dumps({"status": "running"})))

            def remember(run_id):
                with sessions.begin() as session:
                    session.get(AppSetting, key).value = json.dumps({"status": "running", "run_id": run_id})

            try:
                record = {"status": "success", **callback(remember)}
            except (IntelligenceError, ValueError):
                with sessions.begin() as session:
                    row = session.get(AppSetting, key)
                    record = json.loads(row.value)
                    row.value = json.dumps({**record, "status": "failed"})
                raise
            with sessions.begin() as session:
                session.get(AppSetting, key).value = json.dumps(record)
            return record
    except Timeout:
        raise HTTPException(409, "다른 뉴스 평가·대본 요청이 진행 중입니다.") from None


@router.post("/news/curation/analyze")
def analyze(request: Request, collection_context_id: int = Form(ge=1), consent: bool = Form(False)):
    ctx = context(request)
    if not consent or not ctx["api_selected"]:
        raise HTTPException(422, "선택한 API의 뉴스 자료 전송·사용량 발생 동의가 필요합니다.")
    if collection_context_id != ctx["run_id"]:
        raise HTTPException(409, "수집 회차가 변경됐습니다. 전체 평가 대상과 전송 동의를 다시 확인해 주세요.")
    article_ids = sorted(a.id for a in ctx["articles"])
    if not ctx["ready"] or not article_ids:
        raise HTTPException(422, "24시간 이내 뉴스·Trends 자료를 준비해 주세요.")
    ai = ctx["ai"]
    try:
        result = _once(request, ["analysis", ctx["run_id"], sorted(article_ids), ai["provider"], ai["model"], WORKSPACE_TOP_K],
                       lambda remember: {"run_id": service(request).analyze(
                           article_ids, ai["provider"], True,
                           Options(ai["model"], timeout=CURATION_TIMEOUT_SECONDS,
                                   max_tokens=curation_output_tokens(ai["provider"], ai["model"])),
                           on_run=remember, curate=True,
                           trend_snapshot={**ctx["snapshot"], "collection_context_id": ctx["run_id"]},
                           curation_top_k=WORKSPACE_TOP_K)})
    except (IntelligenceError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None
    return go(f"/news?curation_id={result['run_id']}#curation-results")


@router.post("/news/curation/generate")
def generate(request: Request, analysis_id: int = Form(ge=1), rank: int = Form(ge=1, le=10),
             duration: int = Form(30), consent: bool = Form(False)):
    if not consent or duration not in {30, 45, 60}:
        raise HTTPException(422, "대본 1회 전송·과금 동의와 30·45·60초 중 길이를 선택하세요.")
    with request.app.state.sessions() as session:
        analysis = session.get(IntelligenceRun, analysis_id)
        if (not analysis or analysis.status != "success" or not analysis.evidence.get("curation_contract")
                or analysis.provider not in {"openai", "claude_api"}):
            raise HTTPException(422, "성공한 화제성 평가를 선택하세요.")
        item = next((r for r in analysis.result["ranking"] if r["rank"] == rank), None)
        if item is None:
            raise HTTPException(422, "뉴스 순위를 확인하세요.")
        ids, provider, model = item["article_ids"], analysis.provider, analysis.options["model"]
    current = read_studio_settings(request.app.state.sessions)
    if current["provider"] != provider or current["model"] != model:
        raise HTTPException(422, "평가 이후 AI 선택이 변경됐습니다. 같은 API·모델을 선택해 주세요.")
    try:
        result = _once(request, ["script", analysis_id, rank, duration, provider, model],
                       lambda remember: {"draft_id": service(request).generate(
                           analysis_id, duration, provider, True, Options(model, timeout=60, max_tokens=2200),
                           article_ids=ids, on_run=remember)})
    except (IntelligenceError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None
    return go(f"/ai?draft_id={result['draft_id']}")


@router.get("/news/curation/{analysis_id}/ranking.json")
def export_ranking(request: Request, analysis_id: int):
    with request.app.state.sessions() as session:
        run = session.get(IntelligenceRun, analysis_id)
        if not run or run.status != "success" or not run.evidence.get("curation_contract"):
            raise HTTPException(404, "화제성 평가를 찾지 못했습니다.")
        return JSONResponse(ranking_json(run.result))


@router.get("/news/curation/drafts/{draft_id}/script.json")
def export_script(request: Request, draft_id: int):
    with request.app.state.sessions() as session:
        draft = session.get(ContentDraft, draft_id)
        if not draft or not draft.sources.get("curation_contract"):
            raise HTTPException(404, "화제성 대본을 찾지 못했습니다.")
        run = session.get(IntelligenceRun, draft.run_id)
        analysis = session.get(IntelligenceRun, run.options["analysis_run_id"])
        selected = set(run.options["selected_article_ids"])
        item = next(r for r in analysis.result["ranking"] if set(r["article_ids"]) == selected)
        return JSONResponse(script_json(draft.content, item["score"]))
