"""Collect submitted sibling results without retrying failed/unknown generations."""
from copy import deepcopy
from pathlib import Path
import pytest

from bat_distribution import character_manual_execution as m
from newsflow.video.ai.contracts import ClipStatus
from test_character_manual_execution import execution
from test_api_settings import sessions, store
from test_character_kling_studio import studio


def status_adapter(x, monkeypatch, statuses):
    positions = {s['handle']['request_id']: s['position'] for s in x.service.read(x.identifier)['scenes']}
    def check(self, handle):
        assert self.credential() == 'synthetic-only'
        position = positions[handle['request_id']]
        x.state.calls.append(('check', position))
        return ClipStatus(statuses.get(position, 'completed'), 'https://example.com/synthetic.mp4')
    monkeypatch.setattr(m.KlingClient, 'check', check)


@pytest.mark.parametrize('terminal', ['failed', 'nsfw', 'canceled'])
def test_first_terminal_result_does_not_hide_four_successful_siblings(execution, monkeypatch, terminal):
    x = execution
    assert x.post() == 200
    status_adapter(x, monkeypatch, {1: terminal})
    assert x.post('check') == 200
    job = x.service.read(x.identifier)
    assert job['state'] == 'scene_review'
    assert [s['state'] for s in job['scenes']] == [terminal] + ['downloaded']*4
    assert [p.name for p in sorted(x.service.folder(x.identifier).glob('scene-*.mp4'))] == [f'scene-{n}.mp4' for n in range(2, 6)]
    assert sum(c[0] == 'submit' for c in x.state.calls) == 5
    assert [c[1] for c in x.state.calls if c[0] == 'check'] == [1, 2, 3, 4, 5]
    assert x.studio.writer.calls == 0


@pytest.mark.parametrize('terminal', ['failed', 'nsfw', 'canceled'])
def test_existing_terminal_record_is_preserved_and_never_requested_again(execution, monkeypatch, terminal):
    x = execution
    assert x.post() == 200
    job = x.service.read(x.identifier)
    job['state'] = 'scene_review'
    job['scenes'][0].update(state=terminal, finished_at='2026-10-30T01:00:00+00:00')
    x.service.save(job)
    failed_before = deepcopy(job['scenes'][0])
    status_adapter(x, monkeypatch, {})
    assert x.post('check') == 200
    result = x.service.read(x.identifier)
    assert result['scenes'][0] == failed_before
    assert [c[1] for c in x.state.calls if c[0] == 'check'] == [2, 3, 4, 5]
    assert result['state'] == 'scene_review'
    before_calls = deepcopy(x.state.calls)
    before_bytes = (x.service.folder(x.identifier)/'jobs.json').read_bytes()
    assert x.post('check') == 200
    assert x.state.calls == before_calls
    assert (x.service.folder(x.identifier)/'jobs.json').read_bytes() == before_bytes
    assert x.post() == 409
    assert x.state.calls == before_calls


def test_pending_siblings_keep_review_and_finish_on_explicit_later_check(execution, monkeypatch):
    x = execution
    assert x.post() == 200
    states = {1: 'failed', 3: 'in_progress'}
    status_adapter(x, monkeypatch, states)
    assert x.post('check') == 200
    first = x.service.read(x.identifier)
    assert [s['state'] for s in first['scenes']] == ['failed', 'downloaded', 'submitted', 'downloaded', 'downloaded']
    assert first['state'] == 'scene_review'
    before = len(x.state.calls)
    states[3] = 'completed'
    assert x.post('check') == 200
    assert [c for c in x.state.calls[before:] if c[0] == 'check'] == [('check', 3)]
    assert x.service.read(x.identifier)['scenes'][0] == first['scenes'][0]
    assert sum(c[0] == 'submit' for c in x.state.calls) == 5


@pytest.mark.parametrize('uncertain', ['unknown', 'submitting', 'not_submitted', 'downloading'])
def test_unknown_or_unsubmitted_work_stops_before_any_provider_io(execution, monkeypatch, uncertain):
    x = execution
    assert x.post() == 200
    job = x.service.read(x.identifier)
    job['state'] = 'scene_review'
    job['scenes'][0].update(state='failed', finished_at='2026-10-30T01:00:00+00:00')
    job['scenes'][4]['state'] = uncertain
    x.service.save(job)
    before_calls = deepcopy(x.state.calls)
    before_bytes = (x.service.folder(x.identifier)/'jobs.json').read_bytes()
    status_adapter(x, monkeypatch, {})
    assert x.post('check') == 409
    assert x.state.calls == before_calls
    assert (x.service.folder(x.identifier)/'jobs.json').read_bytes() == before_bytes
    assert list(x.service.folder(x.identifier).glob('scene-*.mp4')) == []
