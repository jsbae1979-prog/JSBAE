"""Protected cloud speech configuration. No UI assertion can unlock unverified usage."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from newsflow.intelligence.credentials import CredentialError
from newsflow.video.cloud_tts import (
    MODELS,
    PROVIDERS,
    REGIONS,
    AzureTTSKeyStore,
    CloudTTS,
    GoogleTTSKeyStore,
    load_settings,
    save_settings,
    usage_rows,
)
from newsflow.video.speech_text import normalize_for_speech
from newsflow.video.tts import PREVIEW_TEXT, SpeechSettings, TTSError

from .routes import go, page

router = APIRouter()


def store(request, provider):
    if provider not in {'azure', 'google'}:
        raise HTTPException(422, 'Azure 또는 Google을 선택하세요.')
    cls = AzureTTSKeyStore if provider == 'azure' else GoogleTTSKeyStore
    return cls(request.app.state.config.data_dir)


@router.get('/tts-settings')
def settings(request: Request, message: str = ''):
    sessions = request.app.state.sessions
    config = load_settings(sessions)
    rows = usage_rows(sessions)
    month = [row for row in rows if row['month'] == datetime.now(UTC).strftime('%Y-%m')]
    count = len(normalize_for_speech(PREVIEW_TEXT))
    return page(request, 'tts_settings.html', active='simple-settings', config=config,
                providers=PROVIDERS, models=MODELS, regions=REGIONS, usage=rows[-30:],
                local_characters=sum(row['chars'] for row in month),
                local_reserved_usd=sum(Decimal(row['cost_upper_usd']) for row in month),
                sample_estimate=Decimal(count) * Decimal(config['price_per_million']) / 1_000_000,
                keys={p: store(request, p).status() for p in MODELS},
                characters=count, message=message[:200])


@router.post('/tts-settings')
def save(request: Request, provider: str = Form(max_length=20), voice: str = Form(max_length=100),
         region: str = Form(max_length=30), approved: bool = Form(False), monthly_char_limit: int = Form(0),
         price_per_million: str = Form('0', max_length=20), job_usd_limit: str = Form('0', max_length=20),
         monthly_usd_limit: str = Form('0', max_length=20)):
    try:
        save_settings(request.app.state.sessions, {'provider': provider, 'voice': voice, 'region': region,
                      'approved': approved, 'monthly_char_limit': monthly_char_limit,
                      'price_per_million': price_per_million, 'job_usd_limit': job_usd_limit,
                      'monthly_usd_limit': monthly_usd_limit})
    except TTSError as error:
        raise HTTPException(422, str(error)) from None
    return go('/tts-settings?message=설정을 저장했습니다. 실제 합성은 계정 사용량 확인 후에만 가능합니다.')


@router.post('/tts-settings/key')
def key(request: Request, provider: str = Form(max_length=20), api_key: str = Form(max_length=256)):
    try:
        store(request, provider).save(api_key)
    except CredentialError as error:
        raise HTTPException(422, str(error)) from None
    return go('/tts-settings?message=키를 Windows DPAPI로 보호 저장했습니다.')


@router.post('/tts-settings/check')
def check(request: Request):
    config = load_settings(request.app.state.sessions)
    if config['provider'] not in MODELS:
        return go('/tts-settings?message=로컬 음성 모드입니다. 외부 연결을 호출하지 않았습니다.')
    try:
        cls = AzureTTSKeyStore if config['provider'] == 'azure' else GoogleTTSKeyStore
        cls.validate(store(request, config['provider']).key())
    except CredentialError:
        return go('/tts-settings?message=API 키가 없거나 형식·보호 저장소를 확인하지 못했습니다.')
    # Speech API keys don't establish billing-account usage/free entitlement. We do not
    # infer a verified balance from a successful voices GET or a local checkbox/counter.
    return go('/tts-settings?message=키 구성 확인. 실제 연결·공급사 사용량은 미검증이므로 합성은 차단 상태입니다.')


@router.post('/tts-settings/preview')
def preview(request: Request, confirmed: bool = Form(False), rate: int = Form(0), pause_ms: int = Form(250)) -> RedirectResponse:
    config = load_settings(request.app.state.sessions)
    if config['provider'] not in MODELS or not confirmed:
        raise HTTPException(422, '외부 제공자와 이번 미리 듣기의 비용·전송 승인을 확인하세요.')
    name = f'preview-{uuid4().hex}.wav'
    directory = request.app.state.config.data_dir / 'voice-preview'
    directory.mkdir(parents=True, exist_ok=True)
    adapter = CloudTTS(request.app.state.sessions, config, store(request, config['provider']).key,
                       scope=f'preview:{name}', confirmed=confirmed,
                       current_settings=lambda: load_settings(request.app.state.sessions))
    try:
        adapter.synthesize(PREVIEW_TEXT, directory / name, config['voice'], 30, SpeechSettings(rate, pause_ms))
    except (TTSError, CredentialError) as error:
        raise HTTPException(422, str(error)) from None
    return go('/voices?preview=' + name)
