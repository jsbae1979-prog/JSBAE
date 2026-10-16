import base64
import hashlib
import io
import json
import math
import wave
from array import array
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from conftest import csrf

from newsflow.intelligence.credentials import FakeCipher
from newsflow.video.cloud_tts import (
    MODELS,
    AccountUsage,
    AzureTTSKeyStore,
    CloudTTS,
    GoogleTTSKeyStore,
    load_settings,
    save_settings,
    usage_rows,
)
from newsflow.video.tts import SpeechSettings, TTSError, wav_has_signal

KEY = 'test-only-key-12345678901234567890'


def config(provider='azure'):
    return {'provider': provider, 'voice': MODELS[provider][0], 'region': 'koreacentral',
            'approved_at': datetime.now(UTC).isoformat(), 'monthly_char_limit': 10000,
            'price_per_million': '30', 'job_usd_limit': '1', 'monthly_usd_limit': '5'}


def verified(provider, voice, key):
    now = datetime.now(UTC)
    return AccountUsage(provider, voice, hashlib.sha256(key.encode()).hexdigest(), now,
                        now.strftime('%Y-%m'), 0, 1_000_000, True, True)


def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(array('h', (int(10000 * math.sin(i * .1)) for i in range(3200))).tobytes())
    return stream.getvalue()


@pytest.mark.parametrize('provider', ['azure', 'google'])
def test_fake_transport_produces_measured_wav_without_real_api(app, tmp_path, provider):
    calls = []

    def requester(host, method, path, body, headers, timeout):
        calls.append((host, method, path, body, headers))
        raw = wav_bytes()
        return 200, raw if provider == 'azure' else json.dumps({'audioContent': base64.b64encode(raw).decode()}).encode()

    adapter = CloudTTS(app.state.sessions, config(provider), lambda: KEY, scope='test-render', confirmed=True,
                       verifier=verified, requester=requester)
    target = tmp_path / 'scene.wav'
    adapter.synthesize('첫 문장입니다. 두 번째 문장입니다.', target, config(provider)['voice'], 30, SpeechSettings(-1, 250))
    assert wav_has_signal(target)
    cues = json.loads(target.with_suffix('.cues.json').read_text(encoding='utf-8'))
    assert len(cues) == 2 and cues[1]['start'] - cues[0]['end'] == pytest.approx(.25)
    assert all(c[1] == 'POST' for c in calls) and len(calls) == 2
    assert all(r['status'] == 'success' for r in usage_rows(app.state.sessions))
    assert KEY not in json.dumps(usage_rows(app.state.sessions))
    if provider == 'azure':
        assert calls[0][0] == 'koreacentral.tts.speech.microsoft.com'
        assert b'<prosody rate="-5%">' in calls[0][3]
    else:
        assert calls[0][0] == 'texttospeech.googleapis.com'
        assert json.loads(calls[0][3])['audioConfig']['audioEncoding'] == 'LINEAR16'
    # Stable logical scene/unit ID prevents resubmission by a newly created worker.
    again = CloudTTS(app.state.sessions, config(provider), lambda: KEY, scope='test-render', confirmed=True,
                     verifier=verified, requester=requester)
    with pytest.raises(TTSError):
        again.synthesize('첫 문장입니다. 두 번째 문장입니다.', tmp_path / 'other' / 'scene.wav', config(provider)['voice'], 30,
                         SpeechSettings(-1, 250))
    assert len(calls) == 2


@pytest.mark.parametrize('change', ['none', 'stale', 'key', 'provider', 'voice', 'month', 'commercial', 'unverified'])
def test_usage_verification_fails_closed_before_network(app, tmp_path, change):
    calls = []

    def verifier(p, v, k):
        state = verified(p, v, k)
        changes = {'stale': {'checked_at': datetime.now(UTC) - timedelta(minutes=6)},
                   'key': {'credential_hash': 'wrong'}, 'provider': {'provider': 'google'},
                   'voice': {'voice': 'wrong'}, 'month': {'month': '2000-01'},
                   'commercial': {'commercial_allowed': False}, 'unverified': {'verified': False}}
        return replace(state, **changes.get(change, {}))

    adapter = CloudTTS(app.state.sessions, config(), lambda: KEY, scope='blocked', confirmed=True,
                       verifier=None if change == 'none' else verifier, requester=lambda *a: calls.append(a))
    with pytest.raises(TTSError):
        adapter.synthesize('한국어 문장.', tmp_path / 'a.wav', config()['voice'], 30)
    assert calls == [] and usage_rows(app.state.sessions) == []


@pytest.mark.parametrize('failure', [TimeoutError, ConnectionError, ValueError])
def test_unknown_result_reservation_survives_restart_and_no_replay(app, tmp_path, failure):
    calls = []

    def requester(*args):
        calls.append(1)
        raise failure('secret should never escape')

    for _ in range(2):
        adapter = CloudTTS(app.state.sessions, config(), lambda: KEY, scope='same-job', confirmed=True,
                           verifier=verified, requester=requester)
        with pytest.raises(TTSError) as error:
            adapter.synthesize('결과 불명 문장.', tmp_path / 'scene.wav', config()['voice'], 30)
        assert 'secret' not in str(error.value)
    assert calls == [1]
    assert usage_rows(app.state.sessions)[0]['status'] == 'unknown'


@pytest.mark.parametrize('field,value', [('monthly_char_limit', 1), ('job_usd_limit', '0'), ('monthly_usd_limit', '0')])
def test_local_caps_stop_before_post(app, tmp_path, field, value):
    settings = {**config(), field: value}
    calls = []
    adapter = CloudTTS(app.state.sessions, settings, lambda: KEY, scope='cap', confirmed=True,
                       verifier=verified, requester=lambda *args: calls.append(args))
    with pytest.raises(TTSError):
        adapter.synthesize('한도 테스트.', tmp_path / 'scene.wav', settings['voice'], 30)
    assert not calls


def test_dpapi_namespaces_and_no_plaintext_in_settings(app, tmp_path):
    stores = [AzureTTSKeyStore(tmp_path, FakeCipher()), GoogleTTSKeyStore(tmp_path, FakeCipher())]
    for item in stores:
        item.save(KEY)
        assert item.key() == KEY and KEY.encode() not in item.path.read_bytes()
    assert stores[0].path != stores[1].path and stores[0].ENTROPY != stores[1].ENTROPY
    values = {**config(), 'approved': True}
    save_settings(app.state.sessions, values)
    assert KEY not in json.dumps(load_settings(app.state.sessions))


def test_settings_ui_csrf_and_unverified_preview(client, monkeypatch):
    monkeypatch.setattr(AzureTTSKeyStore, '_get_cipher', lambda self: FakeCipher())
    assert client.get('/tts-settings').status_code == 200
    assert client.post('/tts-settings/key', data={'provider': 'azure', 'api_key': KEY}).status_code == 403
    token = csrf(client)
    assert client.post('/tts-settings/key', data={'provider': 'azure', 'api_key': KEY, 'csrf_token': token}).status_code == 200
    data = {**config(), 'approved': 'true', 'csrf_token': token}
    assert client.post('/tts-settings', data=data).status_code == 200
    response = client.post('/tts-settings/preview', data={'confirmed': 'true', 'csrf_token': token})
    assert response.status_code == 422 and '사용량' in response.text
    page = client.get('/tts-settings').text
    assert KEY not in page and '청구량' in page and '실제 합성·미리 듣기는 차단' in page


def test_ssml_escapes_user_markup_and_closed_model(app):
    adapter = CloudTTS(app.state.sessions, config(), lambda: KEY, scope='escape')
    _, _, payload, _ = adapter.request_payload('<audio src="https://evil.test"/> & 3.5%', config()['voice'], SpeechSettings())
    assert b'<audio' not in payload and b'&lt;audio' in payload and b'&amp;' in payload


@pytest.mark.parametrize('status', [302, 401, 403, 408, 429, 500])
def test_http_errors_are_not_retried_or_redirected(app, tmp_path, status):
    calls = []
    def requester(*args):
        calls.append(args)
        return status, b'credential-provider-detail-must-stay-private'
    adapter = CloudTTS(app.state.sessions, config(), lambda: KEY, scope='http', confirmed=True,
                       verifier=verified, requester=requester)
    with pytest.raises(TTSError) as error:
        adapter.synthesize('음성.', tmp_path / 'a.wav', config()['voice'], 30)
    assert len(calls) == 1 and 'credential-provider' not in str(error.value)
    assert usage_rows(app.state.sessions)[0]['status'] == 'unknown'


def test_no_per_request_consent_and_free_overflow_are_blocked(app, tmp_path):
    calls = []
    def verifier(p, v, k):
        return replace(verified(p, v, k), used=999999)
    for confirmed in (False, True):
        adapter = CloudTTS(app.state.sessions, {**config(), 'price_per_million': '0'}, lambda: KEY,
                           scope='free-cap', confirmed=confirmed, verifier=verifier,
                           requester=lambda *args: calls.append(args))
        with pytest.raises(TTSError):
            adapter.synthesize('음성.', tmp_path / 'a.wav', config()['voice'], 30)
    assert not calls


def test_chirp_nondefault_speed_is_rejected_before_reservation(app, tmp_path):
    options = {**config('google'), 'voice': 'ko-KR-Chirp3-HD-Kore'}
    adapter = CloudTTS(app.state.sessions, options, lambda: KEY, scope='chirp', confirmed=True,
                       verifier=verified, requester=lambda *args: pytest.fail('network called'))
    with pytest.raises(TTSError, match='속도'):
        adapter.synthesize('음성.', tmp_path / 'a.wav', options['voice'], 30, SpeechSettings(-1))
    assert not usage_rows(app.state.sessions)


def test_approval_revocation_is_checked_before_every_unit(app, tmp_path):
    settings = config()
    adapter = CloudTTS(app.state.sessions, settings, lambda: KEY, scope='revoked', confirmed=True,
                       verifier=verified, requester=lambda *args: pytest.fail('network called'),
                       current_settings=lambda: {**settings, 'approved_at': ''})
    with pytest.raises(TTSError, match='변경'):
        adapter.synthesize('문장.', tmp_path / 'a.wav', settings['voice'], 30)
