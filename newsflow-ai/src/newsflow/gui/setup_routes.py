"""Sequential local setup, shared CSRF boundary and explicit synthetic test production."""
from __future__ import annotations

import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from newsflow.db.models import AppSetting, RenderJob, VideoProject
from newsflow.easy_setup import STEPS, SetupError, diagnostics, read_state, save_step, voice_catalog
from newsflow.video.tts import TTSError

from .autopilot_routes import _error, _media_path
from .routes import go, page

router = APIRouter()


def render(request: Request, step: int, error: str = '', status: int = 200) -> HTMLResponse:
    state = read_state(request.app.state.sessions)
    voices = []
    if step == 5:
        try:
            voices = [v for v in voice_catalog() if v['culture'].lower().startswith('ko-')]
        except TTSError:
            pass
    with request.app.state.sessions() as session:
        row = session.get(AppSetting, 'setup_last_check')
        check = json.loads(row.value) if row else None
    response = page(request, 'setup.html', active='simple-settings', steps=STEPS, step=step,
                    state=state, voices=voices, check=check, error=error,
                    data_path=str(request.app.state.config.data_dir),
                    output_path=str(request.app.state.video.outputs))
    response.status_code = status
    return response


@router.get('/setup', response_class=HTMLResponse)
def wizard(request: Request, step: int | None = None) -> HTMLResponse:
    state = read_state(request.app.state.sessions)
    chosen = state['step'] if step is None else step
    if not 1 <= chosen <= state['step']:
        raise HTTPException(422, '이전 설정 단계부터 진행해 주세요.')
    return render(request, chosen)


def run_check(request: Request) -> dict:
    result = diagnostics(request.app.state.config.data_dir, request.app.state.sessions)
    with request.app.state.sessions.begin() as session:
        row = session.get(AppSetting, 'setup_last_check')
        payload = json.dumps(result, ensure_ascii=False)
        if row:
            row.value = payload
        else:
            session.add(AppSetting(key='setup_last_check', value=payload))
    return result


@router.post('/setup/check')
def check(request: Request) -> RedirectResponse:
    run_check(request)
    return go('/setup')


@router.post('/setup/step')
async def step_save(request: Request, step: int = Form(ge=1, le=7), revision: int = Form(ge=0)):
    form = await request.form()
    values = {str(k): str(v) for k, v in form.items() if k not in {'csrf_token', 'step', 'revision'}}
    if any(len(v) > 200 for v in values.values()):
        raise HTTPException(422, '설정값이 너무 깁니다.')
    try:
        if step == 7 and not run_check(request)['ready']:
            raise SetupError('필수 준비 항목이 남았습니다. 아래 해결 방법을 확인한 후 다시 점검하세요.')
        save_step(request.app.state.sessions, step, revision, values)
    except SetupError as exc:
        return render(request, min(step, read_state(request.app.state.sessions)['step']), str(exc), 422)
    return go('/setup')


@router.post('/setup/test-production')
def test_production(request: Request) -> RedirectResponse:
    from newsflow.autopilot.contracts import AutopilotError

    if not read_state(request.app.state.sessions)['completed']:
        raise HTTPException(409, '초기 설정을 완료한 뒤 체험 제작을 시작하세요.')
    if not run_check(request)['ready']:
        raise HTTPException(409, '필수 준비 항목을 다시 확인하세요.')
    try:
        # Always sample/offline, even if saved source defaults request live RSS.
        identifier = request.app.state.autopilot.start(mode='easy', source='sample', duration=30)
    except AutopilotError as exc:
        raise _error(exc) from None
    return go(f'/autopilot/jobs/{identifier}')


@router.get('/videos', response_class=HTMLResponse)
def library(request: Request) -> HTMLResponse:
    with request.app.state.sessions() as session:
        entries = []
        for job, project in session.execute(select(RenderJob, VideoProject).join(VideoProject)
                                           .order_by(RenderJob.id.desc()).limit(100)):
            entries.append({'job': job, 'project': project, 'playable': _media_path(request, job) is not None})
        return page(request, 'video_library.html', active='videos', entries=entries)
