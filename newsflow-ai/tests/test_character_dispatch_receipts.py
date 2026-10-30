"""Only pre-transport proof releases cost reservations; all I/O is Fake."""
import json
import urllib.error
import urllib.request

import pytest

from newsflow.character.schema import CharacterError
from newsflow.intelligence.api_providers import (
    AnthropicProvider, APIRequestNotDispatched, APICancelled,
)
from newsflow.intelligence.provider import Options, ProviderKeyMissing, ProviderResponseError
from test_character_authoring_v3 import Budget
from test_character_story_preflight import episode

PRIVATE = 'synthetic-private-value-must-not-leak'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('External network is forbidden in this test')
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', denied)


def prepared(tmp_path):
    budget = Budget()
    reserve = budget.reserve
    def capped(**kwargs):
        value = reserve(**kwargs)
        value.reserved_usd = '0.252'
        return value
    budget.reserve = capped
    service, authoring, _, identifier = episode(tmp_path, None, budget)
    return service, authoring, identifier, budget


@pytest.mark.parametrize('failure,reason', [
    ('key_exception', 'credential_unavailable'),
    ('empty_key', 'credential_unavailable'),
    ('invalid_key', 'credential_unavailable'),
    ('body_size', 'request_invalid'),
    ('body_json', 'request_invalid'),
    ('cancel', 'request_cancelled'),
])
def test_proven_pretransport_failure_does_not_poison_future_jobs(tmp_path, monkeypatch, failure, reason):
    service, authoring, identifier, budget = prepared(tmp_path)
    def key():
        if failure == 'key_exception':
            raise ValueError(PRIVATE)
        return '' if failure == 'empty_key' else 'bad\nkey' if failure == 'invalid_key' else 'synthetic-key'
    adapter = AnthropicProvider(key)
    calls = []
    def forbidden(*args):
        calls.append(1)
        raise AssertionError('Preflight must not reach transport')
    monkeypatch.setattr(adapter, '_open', forbidden)
    authoring.providers['claude_api'] = adapter
    if failure.startswith('body_'):
        body = {'system': 'x' * 64001} if failure == 'body_size' else {'system': {object()}}
        monkeypatch.setattr('newsflow.character.authoring.request_body', lambda *args: body)
    if failure == 'cancel':
        adapter.cancel()
    with pytest.raises(CharacterError):
        service.write(identifier, consent=True)
    job = service.read(identifier)
    assert calls == []
    assert job['state'] == 'needs_script' and job['script_attempts'] == 0
    assert job['script_failure']['dispatched'] is False
    assert job['script_failure']['preflight_reason'] == reason
    assert not job.get('text_reservations') and authoring.last_reserved_usd == '0'
    assert budget.finished == [('1', {'status': 'failed', 'usage': {
        'prompt_tokens': 0, 'completion_tokens': 0, 'search_calls': 0}})]
    assert PRIVATE not in json.dumps(job, ensure_ascii=False)


@pytest.mark.parametrize('failure', ['timeout', 'connection', 'typed_after_open', 'http400'])
def test_transport_boundary_failure_remains_unknown_and_is_not_retried(tmp_path, monkeypatch, failure):
    service, authoring, identifier, budget = prepared(tmp_path)
    adapter = AnthropicProvider(lambda: 'synthetic-key')
    authoring.providers['claude_api'] = adapter
    calls = []
    def send(*args):
        calls.append(1)
        if failure == 'timeout':
            raise TimeoutError(PRIVATE)
        if failure == 'connection':
            raise urllib.error.URLError(PRIVATE)
        if failure == 'typed_after_open':
            raise APIRequestNotDispatched('request_invalid')
        raise urllib.error.HTTPError('https://api.anthropic.com/v1/messages', 400, 'bad', {}, None)
    monkeypatch.setattr(adapter, '_open', send)
    with pytest.raises(CharacterError):
        service.write(identifier, consent=True)
    job = service.read(identifier)
    assert len(calls) == 1 and job['state'] == 'script_failed'
    assert job['response_received'] is False and job['script_attempts'] == 1
    assert job['script_failure'].get('dispatched') is not False
    assert budget.finished[0][1]['status'] == 'unknown'
    assert job['text_reservations'][0]['usd'] == '0.252'
    with pytest.raises(CharacterError):
        service.write(identifier, consent=True)
    assert len(calls) == 1 and PRIVATE not in json.dumps(job, ensure_ascii=False)


@pytest.mark.parametrize('failure,expected', [
    ('key', ProviderKeyMissing), ('model', ProviderResponseError), ('cancel', APICancelled),
])
def test_preflight_subtypes_preserve_existing_error_contract(failure, expected, monkeypatch):
    provider = AnthropicProvider(lambda: '' if failure == 'key' else 'synthetic-key')
    monkeypatch.setattr(provider, '_open', lambda *args: pytest.fail('Must not dispatch'))
    if failure == 'cancel':
        provider.cancel()
    with pytest.raises(expected) as caught:
        provider._post({}, Options(model='gpt-4.1-mini' if failure == 'model' else 'claude-sonnet-4-6'))
    assert isinstance(caught.value, APIRequestNotDispatched)
