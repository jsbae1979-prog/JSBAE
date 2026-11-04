"""Official estimate contract and registration, synthetic keys/data and Fake HTTP only."""
import json
from copy import deepcopy
from decimal import Decimal

import pytest
from conftest import csrf
from sqlalchemy import select

from newsflow.db.models import AppSetting, Base
from newsflow.intelligence.credentials import FakeCipher
from newsflow.video.ai import higgsfield
from newsflow.video.ai.contracts import ClipRequest, ProviderResponseError, VideoProviderError
from newsflow.video.ai.keys import VideoAIKeyStore
from newsflow.video.ai.pricing import PRICE_PROMPT, ModelPricingService
from newsflow.video.ai.settings import (
    list_models,
    model_quotes,
    read_settings,
    save_model,
    usage_this_month,
    write_settings,
)

MODEL = 'kling-video/v3.0-turbo/text-to-video'
KEY = 'synthetic-pricing-id:synthetic-pricing-secret'


@pytest.fixture(autouse=True)
def no_remote_or_workers(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Real provider access or video generation is forbidden')
    monkeypatch.setattr(higgsfield, 'pinned_requester', forbidden)
    monkeypatch.setattr(higgsfield.HiggsfieldProvider, 'submit', forbidden)
    monkeypatch.setattr('newsflow.scheduler.service.Scheduler.start', lambda self: None)
    monkeypatch.setattr('newsflow.publishing.calendar.PublishingCalendar.start', lambda self: None)
    monkeypatch.delenv('NEWSFLOW_VIDEO_AI_KEY', raising=False)


class QuoteFake:
    def __init__(self, *, status=200, body=None, error=None, rates=None, hook=None):
        self.status, self.body, self.error, self.rates, self.hook = status, body, error, rates, hook
        self.calls = []

    def __call__(self, host, method, path, body, headers, timeout):
        payload = json.loads(body)
        self.calls.append((host, method, path, payload, headers, timeout))
        if self.hook:
            hook, self.hook = self.hook, None
            hook()
        if self.error:
            raise self.error
        response = self.body if self.body is not None else {
            'usd': str(Decimal(payload['duration']) * (self.rates or {}).get(payload['duration'], Decimal('.056'))),
            'credits': '10.0',
        }
        return self.status, json.dumps(response).encode()


@pytest.fixture
def pricing(app, tmp_path):
    keys = VideoAIKeyStore(tmp_path/'synthetic-keys', cipher=FakeCipher())
    keys.save(KEY)
    sender = QuoteFake()
    service = ModelPricingService(app.state.sessions, keys, requester=sender)
    app.state.video_ai.keys = keys
    app.state.video_ai.model_pricing = service
    write_settings(app.state.sessions, provider='higgsfield', host='api.higgsfield.ai', approved=True,
                   monthly_limit='20', job_limit='5', currency='USD', max_active=2, timeout_minutes=30, poll_seconds=10)
    return service, sender, keys


def data(**updates):
    return {'path':MODEL, 'label':'Kling Turbo', 'durations':'5,10', 'resolution':'720p',
            'pricing_mode':'official', 'estimate_consent':'true', **updates}


def post(client, values):
    return client.post('/video-ai-settings/models', data={'csrf_token':csrf(client), **values}, follow_redirects=False)


def snapshot(app):
    with app.state.sessions() as session:
        return deepcopy({table.name:list(session.execute(select(table))) for table in Base.metadata.sorted_tables})


def test_transport_uses_estimate_only_and_exact_existing_generation_parameters():
    sender = QuoteFake()
    provider = higgsfield.HiggsfieldProvider(lambda:KEY, requester=sender)
    assert provider.estimate_usd(ClipRequest(MODEL, PRICE_PROMPT, 5, '720p')) == Decimal('.280')
    host, method, path, payload, headers, timeout = sender.calls[0]
    assert (host, method, path) == ('api.higgsfield.ai', 'POST', '/estimate/'+MODEL)
    assert payload == {'prompt':PRICE_PROMPT, 'duration':5, 'resolution':'720p', 'aspect_ratio':'9:16'}
    assert headers['Authorization'] == 'Key '+KEY
    assert timeout > 0
    assert 'Idempotency-Key' not in headers
    assert len(sender.calls) == 1


@pytest.mark.parametrize('body', [{}, {'usd':True}, {'usd':'NaN'}, {'usd':'Infinity'},
                                  {'usd':'0'}, {'usd':'-1'}, {'usd':'1e2'}, {'usd':'99999999'},
                                  {'usd':'0.000000001'}, {'usd':None}, ['raw-secret']])
def test_invalid_official_amount_is_never_registered(body):
    sender = QuoteFake(body=body)
    provider = higgsfield.HiggsfieldProvider(lambda:KEY, requester=sender)
    with pytest.raises(ProviderResponseError):
        provider.estimate_usd(ClipRequest(MODEL, PRICE_PROMPT, 5, '720p'))
    assert len(sender.calls) == 1


@pytest.mark.parametrize('status', [401,403,404,422,429,503])
def test_transport_http_failure_never_retries_or_generates(status):
    sender = QuoteFake(status=status, body={'message':KEY})
    with pytest.raises(VideoProviderError):
        higgsfield.HiggsfieldProvider(lambda:KEY, requester=sender).estimate_usd(
            ClipRequest(MODEL, PRICE_PROMPT, 5, '720p'))
    assert len(sender.calls) == 1


def test_auto_registration_fills_price_and_preserves_all_other_records_limits_and_key(app, client, pricing):
    _service, sender, keys = pricing
    before, settings, key_bytes = snapshot(app), read_settings(app.state.sessions), keys.path.read_bytes()
    # A forged manual price cannot replace the authenticated estimate.
    assert post(client, data(price_per_second='0.0001')).status_code == 303
    entry, = list_models(app.state.sessions)
    assert entry.usable and entry.price_per_second == Decimal('.056')
    evidence = model_quotes(app.state.sessions)[entry.id]
    assert evidence['amounts'] == [{'seconds':5,'usd':'0.280'},{'seconds':10,'usd':'0.560'}]
    assert evidence['aspect_ratio'] == '9:16' and evidence['checked_at']
    assert KEY not in json.dumps(evidence,default=str)
    assert [call[3]['duration'] for call in sender.calls] == [5,10]
    assert read_settings(app.state.sessions) == settings
    assert settings.job_limit == 5 and settings.monthly_limit == 0 and settings.approved
    assert keys.path.read_bytes() == key_bytes
    after = snapshot(app)
    assert {k:v for k,v in before.items() if k not in ('app_settings','video_ai_models')} == {
        k:v for k,v in after.items() if k not in ('app_settings','video_ai_models')}
    assert dict(before['app_settings']).items() <= dict(after['app_settings']).items()
    assert usage_this_month(app.state.sessions)['requests'] == 0
    page = client.get('/video-ai-settings')
    assert '공식 견적 조회됨' in page.text and '실시간 가격이나 실제 청구액이 아닙니다' in page.text
    assert KEY not in page.text
    assert len(sender.calls) == 2  # rendering the saved evidence never queries again


def test_different_duration_rates_use_safe_ceiling_not_an_underestimate(app, client, pricing):
    _service, sender, _keys = pricing
    sender.rates = {5:Decimal('.05601'), 10:Decimal('.06009')}
    assert post(client, data()).status_code == 303
    model, = list_models(app.state.sessions)
    assert model.price_per_second == Decimal('.0601')
    assert all(model.price_per_second * seconds >= Decimal('.05601' if seconds==5 else '.06009') * seconds
               for seconds in (5,10))


@pytest.mark.parametrize('updates', [
    {'estimate_consent':'false'}, {'resolution':'480p'}, {'durations':'30'}, {'path':'https://evil.example/model'},
    {'path':'unknown/model/text-to-video'}, {'label':''}, {'pricing_mode':'wrong'},
])
def test_invalid_or_unapproved_registration_makes_zero_requests(app, client, pricing, updates):
    _service, sender, _keys = pricing
    before = snapshot(app)
    assert post(client, data(**updates)).status_code == 422
    assert sender.calls == [] and snapshot(app) == before


def test_failed_lookup_preserves_saved_model_price_evidence_and_all_failure_records(app, client, pricing):
    _service, sender, _keys = pricing
    assert post(client, data()).status_code == 303
    model, = list_models(app.state.sessions)
    before = snapshot(app)
    sender.calls.clear()
    sender.error = TimeoutError(KEY+' private provider response')
    response = post(client, data(model_id=str(model.id), label='새 이름', resolution='1080p'))
    assert response.status_code == 422 and '기존 모델·가격을 유지' in response.text
    assert KEY not in response.text and 'private provider' not in response.text
    assert snapshot(app) == before and len(sender.calls) == 1


def test_partial_batch_failure_is_atomic_and_does_not_save_partial_prices(app, client, pricing):
    service, sender, _keys = pricing
    def partial(*args):
        if len(sender.calls) == 1:
            sender.calls.append(('failed',))
            raise ConnectionError(KEY)
        return sender(*args)
    service.requester = partial
    before = snapshot(app)
    assert post(client, data()).status_code == 422
    assert snapshot(app) == before and len(sender.calls) == 2


def test_read_only_pages_and_legacy_manual_save_never_lookup(app, client, pricing):
    _service, sender, _keys = pricing
    assert client.get('/video-ai-settings').status_code == 200
    assert client.get('/video-ai-settings/preflight').status_code == 200
    assert post(client, data(pricing_mode='manual', estimate_consent='false', confirmed='true',
                             price_per_second='0.112')).status_code == 303
    assert list_models(app.state.sessions)[0].price_per_second == Decimal('.112')
    assert sender.calls == []


def test_auth_quote_is_independent_of_paid_generation_approval(app, client, pricing):
    _service, sender, _keys = pricing
    with app.state.sessions.begin() as session:
        session.get(AppSetting,'video_ai_approved_at').value = ''
    assert post(client, data()).status_code == 303
    assert not read_settings(app.state.sessions).approved and len(sender.calls) == 2


def test_krw_currency_is_preserved_and_not_silently_converted(app, client, pricing):
    _service, sender, _keys = pricing
    with app.state.sessions.begin() as session:
        session.get(AppSetting, 'video_ai_currency').value = 'KRW'
    before = snapshot(app)
    assert post(client, data()).status_code == 422
    assert sender.calls == [] and snapshot(app) == before


def test_csrf_origin_and_busy_guard_block_before_request(app, client, pricing):
    service, sender, _keys = pricing
    assert client.post('/video-ai-settings/models',data=data()).status_code == 403
    token=csrf(client)
    assert client.post('/video-ai-settings/models',data={'csrf_token':token,**data()},
                       headers={'Origin':'https://evil.example'}).status_code == 403
    service.guard.acquire()
    try:
        assert post(client,data()).status_code == 422
    finally:
        service.guard.release()
    assert sender.calls == []


def test_existing_model_changed_during_quote_is_not_overwritten(app, client, pricing):
    _service, sender, _keys = pricing
    model=save_model(app.state.sessions,path=MODEL,label='원래 모델',price_per_second='0.112',durations='5,10',
                     resolution='720p',confirmed=True)
    def concurrent_edit():
        save_model(app.state.sessions,path=MODEL,label='다른 창 수정',price_per_second='0.2',durations='5,10',
                   resolution='720p',confirmed=True,model_id=model.id)
    sender.hook=concurrent_edit
    response=post(client,data(model_id=str(model.id)))
    assert response.status_code == 422 and '덮어쓰지 않았습니다' in response.text
    current,=list_models(app.state.sessions)
    assert current.label == '다른 창 수정' and current.price_per_second == Decimal('.2')
    assert model_quotes(app.state.sessions) == {}


def test_quote_evidence_is_not_used_after_manual_conditions_change(app, client, pricing):
    _service, _sender, _keys = pricing
    assert post(client,data()).status_code == 303
    model,=list_models(app.state.sessions)
    save_model(app.state.sessions,path=MODEL,label=model.label,price_per_second='0.112',durations='5,10',
               resolution='1080p',confirmed=True,model_id=model.id)
    assert model_quotes(app.state.sessions) == {}


def test_missing_key_and_duplicate_model_are_rejected_before_lookup(app, client, pricing):
    service, sender, keys = pricing
    keys.clear()
    assert post(client,data()).status_code == 422
    assert sender.calls == []
    keys.save(KEY)
    save_model(app.state.sessions,path=MODEL,label='기존 모델',price_per_second='0.112',durations='5,10',
               resolution='720p',confirmed=True)
    before=snapshot(app)
    assert post(client,data()).status_code == 422
    assert post(client,data(model_id='999')).status_code == 422
    assert sender.calls == [] and snapshot(app) == before
    assert service.keys is keys


def test_currency_changed_during_lookup_preserves_model(app, client, pricing):
    _service, sender, _keys = pricing
    def change_currency():
        with app.state.sessions.begin() as session:
            session.get(AppSetting,'video_ai_currency').value='KRW'
    sender.hook=change_currency
    response=post(client,data())
    assert response.status_code == 422 and '통화가 바뀌었습니다' in response.text
    assert list_models(app.state.sessions) == [] and model_quotes(app.state.sessions) == {}
    assert read_settings(app.state.sessions).currency == 'KRW'


def test_key_changed_during_lookup_cannot_mix_accounts_or_overwrite_prices(app, client, pricing):
    _service, sender, keys = pricing
    sender.hook=lambda:keys.save('another-synthetic-key:another-synthetic-secret')
    response=post(client,data())
    assert response.status_code == 422 and '키가 바뀌었습니다' in response.text
    assert list_models(app.state.sessions) == []
    assert len(sender.calls) == 2
    assert all(call[4]['Authorization']=='Key '+KEY for call in sender.calls)
