"""Local scheduling commands; normal CSRF/Origin checks apply to every POST."""
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from newsflow.autopilot.contracts import STAGE_LABELS
from newsflow.scheduler.service import RETRYABLE
from newsflow.scheduler.timing import ScheduleError

from .routes import go, page

router = APIRouter()


@router.get('/schedules', response_class=HTMLResponse)
def schedules(request: Request, edit: str = '', saved: bool = False) -> HTMLResponse:
    context = request.app.state.scheduler.view()
    selected = next((s for s in context['schedules'] if s.id == edit), None)
    if edit and selected is None:
        raise HTTPException(404, '예약을 찾을 수 없습니다.')
    response = page(request, 'schedules.html', active='autopilot', editing=selected, saved=saved,
                    days=['월', '화', '수', '목', '금', '토', '일'], stage_labels=STAGE_LABELS,
                    retryable=RETRYABLE, **context)
    response.headers['Cache-Control'] = 'no-store'
    return response


@router.post('/schedules')
def save(request: Request, name: str = Form(max_length=80), kind: str = Form(max_length=10),
         local_time: str = Form(max_length=5), weekdays: Annotated[list[int] | None, Form()] = None,
         once_date: str = Form('', max_length=10), source: str = Form('sample', max_length=10),
         duration: int = Form(30), platform: str = Form('youtube', max_length=10),
         voice: str = Form('offline-silence', max_length=30), schedule_id: str = Form('', max_length=32),
         revision: int = Form(0, ge=0)) -> RedirectResponse:
    try:
        request.app.state.scheduler.save(name=name, kind=kind, local_time=local_time, weekdays=weekdays or [],
            once_date=once_date or None, source=source, duration=duration, platform=platform, voice=voice,
            schedule_id=schedule_id or None, revision=revision)
    except ScheduleError as exc:
        raise HTTPException(422, str(exc)) from None
    return go('/schedules?saved=true')


@router.post('/schedules/{schedule_id}/state')
def state(request: Request, schedule_id: str, action: str = Form(max_length=10),
          revision: int = Form(ge=1), consent: bool = Form(False)) -> RedirectResponse:
    if action == 'enable' and not consent:
        raise HTTPException(422, '예약 실행 안내를 확인하고 동의해 주세요.')
    try:
        request.app.state.scheduler.change(schedule_id, revision, action)
    except ScheduleError as exc:
        raise HTTPException(409, str(exc)) from None
    return go('/schedules')


@router.post('/schedules/runs/{run_id}/{action}')
def command(request: Request, run_id: str, action: str, revision: int = Form(ge=1)) -> RedirectResponse:
    if action not in {'retry', 'cancel'}:
        raise HTTPException(404, '지원하지 않는 작업입니다.')
    try:
        getattr(request.app.state.scheduler, action)(run_id, revision)
    except ScheduleError as exc:
        raise HTTPException(409, str(exc)) from None
    return go('/schedules')
