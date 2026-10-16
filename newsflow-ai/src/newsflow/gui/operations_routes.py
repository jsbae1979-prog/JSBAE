"""Readiness, explicit OS-task consent, and local human review forms."""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from newsflow.easy_setup import SetupError, listening_summary
from newsflow.operations import evidence
from newsflow.operations.startup import StartupError, local_service

from .routes import go, kst, page

router = APIRouter()


def service(request: Request):
    injected = getattr(request.app.state,'startup_service',None)
    return injected or local_service(request.app.state.config.data_dir)


def status(request: Request) -> dict:
    try:
        return service(request).view()
    except StartupError as exc:
        return {'status':'unavailable','revision':'','prepared':False,'message':str(exc)}


@router.get('/operations', response_class=HTMLResponse)
def operations(request: Request, saved: bool = False) -> HTMLResponse:
    runtime = '기록 없음'
    try:
        value = json.loads((request.app.state.config.data_dir/'startup-status.json').read_text(encoding='utf-8'))
        runtime = {'starting':'시작 시도 기록 · 현재 상태는 확인 필요',
            'running':'실행 기록 · 강제 종료 여부는 확인 필요', 'stopped':'정상 종료 기록',
            'failed':'실행 실패 · 기존 실행과 포트, 설치 상태를 확인하세요.'}.get(value.get('status'),'확인 필요')
    except (OSError, ValueError, TypeError):
        pass
    review = evidence.read(request.app.state.sessions)
    reviewed_at = kst(datetime.fromisoformat(review['at'])) if review['at'] else ''
    return page(request,'operations.html',active='simple-settings',startup=status(request),runtime=runtime,
        review=review,reviewed_at=reviewed_at,items=evidence.ITEMS,verdicts=evidence.VERDICTS,
        listening=listening_summary(request.app.state.sessions),saved=saved)


@router.post('/operations/startup')
def startup(request: Request, command: str = Form(max_length=10), revision: str = Form(max_length=64),
            consent: bool = Form(False)) -> RedirectResponse:
    if not consent:
        raise HTTPException(422,'등록 또는 해제 내용을 확인하고 직접 동의해 주세요.')
    try:
        service(request).change(command,revision,consent)
    except StartupError as exc:
        raise HTTPException(409,str(exc)) from None
    return go('/operations?saved=true')


@router.post('/operations/review')
async def review(request: Request, revision: int = Form(ge=0), consent: bool = Form(False)) -> RedirectResponse:
    form = await request.form()
    try:
        evidence.save(request.app.state.sessions,revision,{key:str(form.get(key,'')) for key in evidence.ITEMS},consent)
    except SetupError as exc:
        raise HTTPException(422,str(exc)) from None
    return go('/operations?saved=true')


@router.get('/operations/evidence.json')
def download(request: Request) -> JSONResponse:
    return JSONResponse(evidence.export(request.app.state.sessions),headers={
        'Content-Disposition':'attachment; filename="newsflow-pc-review.json"'})
