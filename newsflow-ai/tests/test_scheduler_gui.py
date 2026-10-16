from datetime import UTC, datetime

import pytest
from conftest import csrf
from sqlalchemy import select

from newsflow.db.models import ProductionSchedule, ScheduledRun

FIELDS = {'name':'아침 예약', 'kind':'daily', 'local_time':'09:00', 'source':'sample',
          'duration':'30', 'platform':'youtube', 'voice':'offline-silence'}


def post(client, path, data):
    return client.post(path, data={**data, 'csrf_token':csrf(client)},
                       headers={'Origin':'http://127.0.0.1'}, follow_redirects=False)


def test_gui_crud_pause_resume_remove_and_readonly_get(client, app):
    page = client.get('/schedules')
    assert page.status_code == 200 and '자동 제작 예약' in page.text
    assert '90초' in page.text and '유료 AI 사용 안 함' in page.text
    assert 'Content-Security-Policy' in page.headers
    result = post(client, '/schedules', FIELDS)
    assert result.status_code == 303
    with app.state.sessions() as session:
        schedule = session.scalar(select(ProductionSchedule))
        assert schedule.status == 'paused'
    identifier = schedule.id
    path = f'/schedules/{identifier}/state'
    assert post(client, path, {'action':'enable','revision':1}).status_code == 422
    assert post(client, path, {'action':'enable','revision':1,'consent':'true'}).status_code == 303
    assert post(client, path, {'action':'pause','revision':1}).status_code == 409
    assert post(client, path, {'action':'pause','revision':2}).status_code == 303
    assert client.get(f'/schedules?edit={identifier}').status_code == 200
    assert post(client, '/schedules', {**FIELDS,'name':'수정한 예약','schedule_id':identifier,'revision':3}).status_code == 303
    assert '수정한 예약' in client.get('/schedules').text
    assert post(client, path, {'action':'remove','revision':4}).status_code == 303
    with app.state.sessions() as session:
        assert session.get(ProductionSchedule, identifier).status == 'removed'
        assert not session.scalar(select(ScheduledRun))
    assert client.get(f'/schedules?edit={identifier}').status_code == 404


@pytest.mark.parametrize('path', ['/schedules', '/schedules/abc/state', '/schedules/runs/abc/retry', '/schedules/runs/abc/cancel'])
def test_mutations_require_csrf_and_exact_origin(client, path):
    token = csrf(client)
    assert client.post(path, data=FIELDS).status_code == 403
    assert client.post(path, data={**FIELDS,'csrf_token':token},headers={'Origin':'https://evil.test'}).status_code == 403
    assert client.post(path, data={**FIELDS,'csrf_token':token},headers={'Origin':'null'}).status_code == 403


def test_name_escaped_and_invalid_options_no_provider_calls(client, app):
    assert post(client, '/schedules', {**FIELDS,'name':'<script>alert(1)</script>'}).status_code == 303
    html = client.get('/schedules').text
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert '<script>alert(1)</script>' not in html
    for field, value in [('duration','900'),('voice','paid'),('source','openai'),('platform','shell')]:
        assert post(client, '/schedules', {**FIELDS,field:value}).status_code == 422
    assert app.state.autopilot.future is None


def test_kst_in_history_and_removed_history_remains(client, app):
    assert post(client, '/schedules', FIELDS).status_code == 303
    with app.state.sessions.begin() as session:
        schedule = session.scalar(select(ProductionSchedule))
        session.add(ScheduledRun(id='a'*32,job_id='b'*32,schedule_id=schedule.id,
            scheduled_for=datetime(2026,10,17,tzinfo=UTC),options=schedule.options,
            status='skipped',message='미실행 합성 이력'))
        identifier = schedule.id
    assert post(client,f'/schedules/{identifier}/state',{'action':'remove','revision':1}).status_code == 303
    html = client.get('/schedules').text
    assert '2026-10-17 09:00' in html and '미실행 합성 이력' in html
    assert '/schedules/runs/' not in html
