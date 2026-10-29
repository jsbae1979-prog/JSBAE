"""Synthetic terminal-request GET diagnostics; no provider/network/app execution."""
from copy import deepcopy
import json
from urllib.parse import quote

import pytest

from bat_distribution import character_manual_execution as m
from newsflow.character.higgsfield_client import HiggsfieldVideoClient
from newsflow.character.schema import CharacterError
from newsflow.character.status_diagnostics import facts, private_inputs, safe_error, public_diagnostic
from newsflow.video.ai.contracts import ClipStatus, ProviderResponseError
from test_character_manual_execution import execution
from test_api_settings import sessions, store
from test_character_kling_studio import studio

RID = '01234567-89ab-cdef-0123-456789abcdef'
HANDLE = {'request_id': RID, 'status_url': f'https://api.higgsfield.ai/requests/{RID}/status'}


@pytest.fixture
def failed(execution, monkeypatch):
    x = execution
    assert x.post() == 200
    job = x.service.read(x.identifier)
    job['state'] = 'scene_review'
    for scene in job['scenes']:
        scene.update(state='failed', finished_at='2026-10-30T01:00:00+00:00')
    x.service.save(job)
    x.before = deepcopy(job)
    x.state.diagnostic_state = 'failed'
    x.state.diagnostic_error = 'Generation failed'
    x.state.observed = []
    x.state.inside_diagnose = None
    x.state.fail_diagnose = False
    def diagnose(self, handle, *, protected=()):
        assert self.credential() == 'synthetic-only'
        x.state.observed.append(deepcopy(handle))
        if x.state.inside_diagnose:
            x.state.inside_diagnose()
        if x.state.fail_diagnose:
            raise ProviderResponseError()
        return ClipStatus(x.state.diagnostic_state, facts=facts(x.state.diagnostic_error, protected))
    monkeypatch.setattr(m.KlingClient, 'diagnose', diagnose)
    return x


def without_diagnostics(job):
    result = deepcopy(job)
    for scene in result['scenes']:
        scene.pop('status_diagnostics', None)
    return result


def test_explicit_get_diagnostics_preserve_five_failure_records_and_quotes(failed):
    x = failed
    calls = deepcopy(x.state.calls)
    assert x.post('diagnose') == 200
    job = x.service.read(x.identifier)
    assert without_diagnostics(job) == x.before
    assert len(x.state.observed) == 5
    assert x.state.calls == calls  # No submit/check/fetch/estimate/upload.
    for scene in job['scenes']:
        assert scene['status_diagnostics']['error_message'] == 'Generation failed'
        assert scene['status_diagnostics']['detail_available'] is True
        assert scene['status_diagnostics']['observed_state'] == 'failed'
        assert scene['status_diagnostics']['state_mismatch'] is False
    assert x.studio.writer.calls == 0
    assert m._REQUEST.get() is None and m._ACTIVE.get() is None


@pytest.mark.parametrize('message', [None, '', '   ', {'message': 'not a string'}])
def test_missing_provider_detail_is_explicit_and_not_invented(failed, message):
    failed.state.diagnostic_error = message
    assert failed.post('diagnose') == 200
    for scene in failed.service.read(failed.identifier)['scenes']:
        assert scene['status_diagnostics']['detail_available'] is False
        assert scene['status_diagnostics']['error_message'] == ''


@pytest.mark.parametrize('state', ['completed', 'queued', 'in_progress', 'nsfw', 'canceled'])
def test_different_observed_state_does_not_overwrite_terminal_state(failed, state):
    failed.state.diagnostic_state = state
    assert failed.post('diagnose') == 200
    job = failed.service.read(failed.identifier)
    assert without_diagnostics(job) == failed.before
    assert all(s['status_diagnostics']['state_mismatch'] is True for s in job['scenes'])
    assert all(s['status_diagnostics']['observed_state'] == state for s in job['scenes'])
    assert list(failed.service.folder(failed.identifier).glob('scene-*.mp4')) == []


@pytest.mark.parametrize('kwargs', [{'auth': False}, {'csrf': False}, {'origin': 'https://example.com'}, {'consent': False}])
def test_existing_auth_origin_csrf_and_consent_are_required(failed, kwargs):
    native = failed.state.native
    assert failed.post('diagnose', **kwargs) in {403, 409}
    assert failed.state.observed == [] and failed.state.native == native
    assert failed.service.read(failed.identifier) == failed.before


@pytest.mark.parametrize('mutation', ['unknown', 'submitting', 'not_submitted', 'downloading', 'foreign_handle', 'duplicate_handle'])
def test_all_target_preflight_stops_before_first_get(failed, mutation):
    job = failed.service.read(failed.identifier)
    if mutation == 'foreign_handle':
        job['scenes'][-1]['handle']['status_url'] = 'https://example.com/not-registered'
    elif mutation == 'duplicate_handle':
        job['scenes'][-1]['handle'] = deepcopy(job['scenes'][0]['handle'])
    else:
        job['scenes'][-1]['state'] = mutation
    failed.service.save(job)
    assert failed.post('diagnose') == 409
    assert failed.state.observed == []
    assert failed.service.read(failed.identifier) == job


def test_diagnose_cannot_open_submit_upload_estimate_fetch_or_other_handle(failed):
    x = failed
    def inside():
        client = m._Client(x.manual, x.state.clients[-1])
        for name, args in [('submit_scene', ({}, 'synthetic')), ('upload_reference', ('synthetic',)),
                           ('estimate', ({},)), ('fetch', (ClipStatus('completed'), x.profile/'external.mp4', None)),
                           ('check', (HANDLE,)), ('diagnose', (HANDLE,))]:
            with pytest.raises(CharacterError):
                getattr(client, name)(*args)
    x.state.inside_diagnose = inside
    assert x.post('diagnose') == 200
    assert len(x.state.observed) == 5


def test_network_error_stops_without_retry_or_success_reclassification(failed):
    failed.state.fail_diagnose = True
    with pytest.raises(ProviderResponseError):
        failed.post('diagnose')
    assert len(failed.state.observed) == 1
    assert failed.service.read(failed.identifier) == failed.before
    assert m._REQUEST.get() is None and m._ACTIVE.get() is None


def test_read_model_exposes_only_safe_fields_and_keeps_failure(failed):
    from types import SimpleNamespace
    from newsflow.studio.read_models import character_rows
    failed.state.diagnostic_error = 'Generation failed'
    assert failed.post('diagnose') == 200
    row = next(r for r in character_rows(SimpleNamespace(character=failed.service)) if r['id'] == failed.identifier)
    for scene in row['scenes']:
        assert scene['state'] == 'failed'
        assert set(scene['status_diagnostics']) == {'observed_state', 'error_message', 'detail_available', 'state_mismatch', 'checked_at'}
        assert scene['status_diagnostics']['error_message'] == 'Generation failed'
        assert 'handle' not in scene and 'idempotency_key' not in scene


def test_sanitizer_removes_private_values_fragments_urls_auth_identifiers_paths():
    private = 'Original SECRETFRAGMENT 독창인물 walks beside a private office'
    key = 'syntheticIdentifier:syntheticSecretValue'
    text = ('Generation failed: '+private+'; Original SECRETFRAGMENT 독창인물; '+quote(private)+'; '+key+
            '; syntheticSecretValue; https://example.com/signed?secret=yes; Bearer LongAuthTokenValue; '+RID+
            '; C:\\Users\\private-user\\secret.png\n/home/private/file.txt\n')
    result = safe_error(text, (private, key, *key.split(':'), RID))
    assert result.startswith('Generation failed:')
    for value in ('SECRETFRAGMENT', '독창인물', 'syntheticIdentifier', 'syntheticSecretValue',
                  'https://', 'secret=yes', 'LongAuthTokenValue', RID, 'private-user', '/home/private'):
        assert value not in result
    assert len(safe_error('failure '*2000)) <= 1000


def test_provider_get_preserves_real_error_field_with_no_raw_url_or_key_parts():
    calls = []
    key = 'syntheticIdentifier:syntheticSecretValue'
    def requester(host, method, path, body, headers, timeout):
        calls.append((host, method, path, body))
        return 200, json.dumps({'status': 'failed', 'error': 'Generation failed syntheticSecretValue https://example.com/private'}).encode()
    provider = HiggsfieldVideoClient(lambda: key, requester=requester)
    status = provider.diagnose(HANDLE)
    assert calls == [('api.higgsfield.ai', 'GET', f'/requests/{RID}/status', None)]
    assert status.state == 'failed' and status.facts['detail_available'] is True
    assert 'Generation failed' in status.facts['error_message']
    assert 'syntheticSecretValue' not in status.facts['error_message'] and 'https://' not in status.facts['error_message']
    assert set(status.facts) == {'error_message', 'detail_available'}


def test_diagnostic_completed_observation_needs_no_media_url_or_fetch():
    calls = []
    def requester(host, method, path, body, headers, timeout):
        calls.append((method, path))
        return 200, b'{"status":"completed","error":null}'
    provider = HiggsfieldVideoClient(lambda: 'syntheticIdentifier:syntheticSecretValue', requester=requester)
    result = provider.diagnose(HANDLE)
    assert result.state == 'completed' and result.video_url is None
    assert result.facts == {'error_message': '', 'detail_available': False}
    assert calls == [('GET', f'/requests/{RID}/status')]


@pytest.mark.parametrize('message', ['prompt exceeds maximum length', 'unsupported duration', 'Reference image resolution is invalid'])
def test_generic_provider_error_meaning_survives_prompt_redaction(message):
    private = 'Use the reference character image to create a generation. The duration follows the prompt.'
    assert safe_error(message, (private,)) == message
