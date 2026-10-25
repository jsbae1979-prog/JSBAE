"""Step13I readiness: synthetic credentials and injected transports only."""
import io
import json
import urllib.error

import pytest

from newsflow.intelligence.api_connection import _check_model
from newsflow.intelligence.credentials import AIKeyStore, AnthropicKeyStore, FakeCipher
from newsflow.news.serpapi import SerpApiAdapter, SerpApiError, SerpApiKeys
from newsflow.paths import default_data_dir
from newsflow.video.elevenlabs_tts import ElevenLabsKeys

KEY_A = 'nf-synthetic-step13i-user-a-credential'
KEY_B = 'nf-synthetic-step13i-user-b-credential'


@pytest.fixture(autouse=True)
def no_supplier_network(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('Step13I: real supplier transport is prohibited')
    monkeypatch.setattr('urllib.request.OpenerDirector.open', denied)


@pytest.mark.parametrize('store_type', [AIKeyStore, AnthropicKeyStore, SerpApiKeys, ElevenLabsKeys])
def test_separate_profile_keys_never_load_or_replace_other_profile(tmp_path, monkeypatch, store_type):
    monkeypatch.delenv(store_type.ENV, raising=False)
    first = store_type(tmp_path / 'user-a', FakeCipher())
    second = store_type(tmp_path / 'user-b', FakeCipher())
    first.save(KEY_A)
    assert first.key() == KEY_A and second.key() == ''
    before = first.path.read_bytes()
    second.save(KEY_B)
    assert first.key() == KEY_A and second.key() == KEY_B
    assert first.path.read_bytes() == before
    assert KEY_A.encode() not in before
    assert KEY_B.encode() not in second.path.read_bytes()
    second.clear()
    assert first.key() == KEY_A and first.path.read_bytes() == before
    assert second.key() == ''


def test_windows_data_roots_are_per_user_and_outside_installation(tmp_path):
    first = default_data_dir('win32', {'LOCALAPPDATA': str(tmp_path / 'user-a/Local')})
    second = default_data_dir('win32', {'LOCALAPPDATA': str(tmp_path / 'user-b/Local')})
    assert first != second
    assert first == tmp_path / 'user-a/Local/NewsFlowAI'
    assert second == tmp_path / 'user-b/Local/NewsFlowAI'
    override = tmp_path / 'explicit-test-profile'
    assert default_data_dir('win32', {'NEWSFLOW_DATA_DIR': str(override)}) == override.resolve()
    with pytest.raises(ValueError):
        default_data_dir('win32', {})


@pytest.mark.parametrize('provider,model', [('openai', 'gpt-4.1-mini'), ('claude_api', 'claude-sonnet-4-6')])
@pytest.mark.parametrize('status,expected', [(401, 'auth_error'), (403, 'permission'), (402, 'unavailable'),
                                             (429, 'rate_limit'), (408, 'timeout'), (504, 'timeout')])
def test_metadata_errors_are_single_attempt_redacted_and_not_billing_proof(provider, model, status, expected):
    calls, streams = [], []
    def transport(request, timeout, limit):
        calls.append(request)
        stream = io.BytesIO(KEY_A.encode())
        streams.append(stream)
        raise urllib.error.HTTPError('https://synthetic.invalid/' + KEY_A, status, KEY_A, {}, stream)
    result = _check_model(model, KEY_A, transport, provider)
    assert result == expected and len(calls) == 1
    assert all(stream.closed for stream in streams)
    assert KEY_A not in result
    assert calls[0].get_method() == 'GET' and calls[0].data is None


@pytest.mark.parametrize('status,expected', [(401, 'auth_failed'), (403, 'auth_failed'),
                                             (402, 'usage_limited'), (429, 'usage_limited'), (500, 'http_failed')])
def test_serpapi_payment_auth_rate_errors_never_retry_or_disclose_key(tmp_path, monkeypatch, status, expected):
    monkeypatch.delenv(SerpApiKeys.ENV, raising=False)
    keys = SerpApiKeys(tmp_path, FakeCipher())
    keys.save(KEY_A)
    adapter = SerpApiAdapter(keys)
    calls, streams = [], []
    def transport(request, timeout):
        calls.append(request)
        stream = io.BytesIO(KEY_A.encode()); streams.append(stream)
        raise urllib.error.HTTPError('https://synthetic.invalid/' + KEY_A, status, KEY_A, {}, stream)
    monkeypatch.setattr(adapter, '_open', transport)
    before = keys.path.read_bytes()
    with pytest.raises(SerpApiError) as failure:
        adapter.search()
    assert failure.value.code == expected and len(calls) == 1
    assert all(stream.closed for stream in streams)
    assert KEY_A not in str(failure.value)
    assert keys.path.read_bytes() == before


@pytest.mark.parametrize('error,expected', [(TimeoutError(), 'timeout_unknown'),
    (urllib.error.URLError('nf-synthetic-not-a-secret'), 'network_unknown')])
def test_serpapi_timeout_is_unknown_without_automatic_resubmit(tmp_path, monkeypatch, error, expected):
    keys = SerpApiKeys(tmp_path, FakeCipher()); keys.save(KEY_A)
    adapter = SerpApiAdapter(keys); calls = []
    def transport(*args):
        calls.append(True)
        raise error
    monkeypatch.setattr(adapter, '_open', transport)
    with pytest.raises(SerpApiError) as failure:
        adapter.search()
    assert failure.value.code == expected and calls == [True]
    assert KEY_A not in str(failure.value)
