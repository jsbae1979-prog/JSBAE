"""Optional Azure/Google speech. Fail closed on unverified account usage; no retries.

No public UI or environment variable can manufacture provider usage verification.
The supplied account verifier is a separately authenticated integration boundary;
without one, real synthesis is blocked even when a key and approval are saved.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import wave
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from newsflow.db.models import AppSetting
from newsflow.intelligence.credentials import AIKeyStore
from newsflow.video.ai.higgsfield import pinned_requester

from .speech_audio import prepare_pcm, reading_units
from .speech_text import normalize_for_speech
from .tts import SpeechSettings, TTSError, wav_duration

PROVIDERS = {'windows': 'Windows SAPI · 무료·로컬', 'azure': 'Azure AI Speech · 계정 확인 필요',
             'google': 'Google Cloud TTS · 계정 확인 필요', 'offline': 'Offline 무음 · 체험·테스트'}
MODELS = {'azure': ('ko-KR-SunHiNeural', 'ko-KR-InJoonNeural'),
          'google': ('ko-KR-Neural2-A', 'ko-KR-Neural2-B', 'ko-KR-Neural2-C',
                     'ko-KR-Wavenet-A', 'ko-KR-Standard-A', 'ko-KR-Chirp3-HD-Kore')}
REGIONS = ('koreacentral', 'eastus', 'westus', 'westeurope', 'southeastasia')
MAX_AUDIO = 16000 * 2 * 60 + 4096


class AzureTTSKeyStore(AIKeyStore):
    FILE, ENV = 'tts-azure-key.dpapi', 'NEWSFLOW_AZURE_TTS_KEY'
    ENTROPY = b'NewsFlowAI:TTS:Azure'
    PATTERN = re.compile(r'[A-Za-z0-9_-]{20,256}\Z')


class GoogleTTSKeyStore(AIKeyStore):
    FILE, ENV = 'tts-google-key.dpapi', 'NEWSFLOW_GOOGLE_TTS_KEY'
    ENTROPY = b'NewsFlowAI:TTS:Google'
    PATTERN = re.compile(r'[A-Za-z0-9_-]{20,256}\Z')


@dataclass(frozen=True)
class AccountUsage:
    provider: str
    voice: str
    credential_hash: str
    checked_at: datetime
    month: str
    used: int
    free_limit: int
    verified: bool = False
    # Azure paid-tier commercial rights must be established separately from F0 price.
    commercial_allowed: bool = False


def load_settings(sessions) -> dict:
    with sessions() as session:
        row = session.get(AppSetting, 'tts_settings')
        return json.loads(row.value) if row else {'provider': 'windows', 'voice': MODELS['azure'][0],
                    'region': REGIONS[0], 'approved_at': '', 'monthly_char_limit': 0, 'price_per_million': '0',
                    'job_usd_limit': '0', 'monthly_usd_limit': '0'}


def save_settings(sessions, values: dict) -> None:
    provider = values.get('provider')
    if provider not in PROVIDERS or values.get('region') not in REGIONS:
        raise TTSError('제공자와 지역을 목록에서 선택하세요.')
    if provider in MODELS and values.get('voice') not in MODELS[provider]:
        raise TTSError('선택한 제공자의 한국어 음성을 다시 선택하세요.')
    if type(values.get('monthly_char_limit')) is not int or not 0 <= values['monthly_char_limit'] <= 10_000_000:
        raise TTSError('월 문자 한도는 0~1000만 사이여야 합니다.')
    for name in ('price_per_million', 'job_usd_limit', 'monthly_usd_limit'):
        raw = values.get(name, '')
        if not re.fullmatch(r'\d{1,7}(\.\d{1,4})?', raw):
            raise TTSError('비용은 0 이상의 USD 숫자로 입력하세요.')
    allowed = {k: values[k] for k in ('provider', 'voice', 'region', 'monthly_char_limit',
                                    'price_per_million', 'job_usd_limit', 'monthly_usd_limit')}
    allowed['approved_at'] = datetime.now(UTC).isoformat() if values.get('approved') else ''
    with sessions.begin() as session:
        row = session.get(AppSetting, 'tts_settings')
        if row is None:
            session.add(AppSetting(key='tts_settings', value=json.dumps(allowed)))
        else:
            row.value = json.dumps(allowed)


def usage_rows(sessions) -> list[dict]:
    with sessions() as session:
        row = session.get(AppSetting, 'tts_ledger')
        return json.loads(row.value) if row else []


class CloudTTS:
    """SAPI-compatible adapter; one bounded synchronous REST request per reading unit."""

    def __init__(self, sessions, settings: dict, credential: Callable[[], str], *,
                 scope: str, confirmed: bool = False, verifier=None, requester=None, current_settings=None):
        self.sessions, self.settings, self.credential = sessions, dict(settings), credential
        self.scope, self.confirmed = scope, confirmed
        self.verifier = verifier
        self.requester = requester or pinned_requester
        self.current_settings = current_settings

    def voices(self) -> list[str]:
        return list(MODELS.get(self.settings['provider'], ()))

    def _reserve(self, text: str, voice: str, rate: int, request_label: str) -> tuple[str, str]:
        config = self.settings
        if self.current_settings:
            current = self.current_settings()
            fields = ('provider', 'voice', 'region', 'approved_at', 'monthly_char_limit',
                      'price_per_million', 'job_usd_limit', 'monthly_usd_limit')
            if not current.get('approved_at') or any(current.get(k) != config.get(k) for k in fields):
                raise TTSError('음성 설정·비용 승인이 변경되었습니다. 새로 확인하기 전 요청하지 않습니다.')
        key = self.credential()
        store = AzureTTSKeyStore if config['provider'] == 'azure' else GoogleTTSKeyStore
        if not store.PATTERN.fullmatch(key or '') or not self.confirmed or not config.get('approved_at'):
            raise TTSError('외부 음성 키와 이번 요청의 비용·전송 승인이 필요합니다.')
        if self.verifier is None:
            raise TTSError('공급사 계정의 실제 사용량·무료 한도를 확인하지 못해 외부 합성을 차단했습니다.')
        try:
            state = self.verifier(config['provider'], voice, key)
            now = datetime.now(UTC)
            fingerprint = hashlib.sha256(key.encode()).hexdigest()
            if (not isinstance(state, AccountUsage) or not state.verified or not state.commercial_allowed
                    or state.provider != config['provider'] or state.voice != voice
                    or state.credential_hash != fingerprint or state.month != now.strftime('%Y-%m')
                    or not 0 <= (now - state.checked_at).total_seconds() <= 300
                    or type(state.used) is not int or type(state.free_limit) is not int
                    or state.used < 0 or state.free_limit < 0):
                raise ValueError
        except Exception:  # noqa: BLE001 -- never disclose account/key/provider errors
            raise TTSError('공급사 사용량 또는 이용 조건 확인에 실패하여 차단했습니다.') from None
        # UTF-8 byte count is a conservative upper bound, not the supplier's billable
        # character count (astral symbols/SSML/account rules differ by provider).
        count = len(text.encode('utf-8'))
        cost = Decimal(count) * Decimal(config['price_per_million']) / 1_000_000
        # Free-only requests may never cross the verified allowance. Paid overage needs
        # per-call consent AND positive task/month cost caps; no local counter implies a free bill.
        paid = state.used + count > state.free_limit
        if paid and (cost <= 0 or Decimal(config['job_usd_limit']) <= 0 or Decimal(config['monthly_usd_limit']) <= 0):
            raise TTSError('무료 한도 초과 가능성이 있어 유료 한도 승인 전에는 차단합니다.')
        identity = hashlib.sha256(json.dumps([self.scope, request_label, config['provider'], voice,
                                              fingerprint, text, rate], ensure_ascii=False).encode()).hexdigest()
        with self.sessions.begin() as session:
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
            row = session.get(AppSetting, 'tts_ledger')
            ledger = json.loads(row.value) if row else []
            month = [r for r in ledger if r['month'] == state.month]
            job = [r for r in ledger if r['scope'] == self.scope]
            if state.used + sum(r['chars'] for r in month) + count > state.free_limit and (
                    cost <= 0 or Decimal(config['job_usd_limit']) <= 0 or Decimal(config['monthly_usd_limit']) <= 0):
                raise TTSError('공급사 사용량과 로컬 예약을 합하면 무료 한도를 넘을 수 있어 차단합니다.')
            if any(r['status'] == 'unknown' for r in job):
                raise TTSError('이 작업의 이전 음성 요청 결과가 불명입니다. 재전송하지 않습니다.')
            if any(r['id'] == identity for r in ledger):
                raise TTSError('같은 음성 요청이 이미 제출되었거나 결과 불명입니다. 자동 재요청하지 않습니다.')
            if len(ledger) >= 5000:
                raise TTSError('음성 사용 기록이 가득 찼습니다. 기록을 보존한 채 관리가 필요합니다.')
            # Successful, reserved and unknown requests all consume local safety reservations.
            if sum(r['chars'] for r in month) + count > config['monthly_char_limit']:
                raise TTSError('로컬 월 문자 한도를 초과합니다.')
            if (cost > Decimal(config['job_usd_limit'])
                    or sum(Decimal(r['cost_upper_usd']) for r in job) + cost > Decimal(config['job_usd_limit'])
                    or sum(Decimal(r['cost_upper_usd']) for r in month) + cost > Decimal(config['monthly_usd_limit'])):
                raise TTSError('승인된 작업별·월별 비용 상한을 초과합니다.')
            ledger.append({'id': identity, 'scope': self.scope, 'provider': config['provider'], 'voice': voice,
                           'month': state.month, 'chars': count, 'cost_upper_usd': str(cost),
                           'submitted_characters': len(text), 'count_basis': 'utf8-byte-upper-bound',
                           'status': 'unknown', 'at': now.isoformat()})
            if row:
                row.value = json.dumps(ledger)
            else:
                session.add(AppSetting(key='tts_ledger', value=json.dumps(ledger)))
        return identity, key

    def _success(self, identity: str) -> None:
        with self.sessions.begin() as session:
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
            row = session.get(AppSetting, 'tts_ledger')
            ledger = json.loads(row.value)
            next(r for r in ledger if r['id'] == identity)['status'] = 'success'
            row.value = json.dumps(ledger)

    def request_payload(self, text: str, voice: str, speech: SpeechSettings):
        provider = self.settings['provider']
        if provider == 'azure':
            host = self.settings['region'] + '.tts.speech.microsoft.com'
            ssml = ('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="ko-KR"><voice name="' + voice
                    + '"><prosody rate="' + str(speech.rate * 5) + '%">' + escape(text)
                    + '</prosody></voice></speak>')
            return host, '/cognitiveservices/v1', ssml.encode(), {'Content-Type': 'application/ssml+xml',
                    'X-Microsoft-OutputFormat': 'riff-16khz-16bit-mono-pcm'}
        # Chirp3 HD does not promise the same SSML/speakingRate controls as Neural2.
        if 'Chirp3' in voice and speech.rate != 0:
            raise TTSError('Chirp3 HD는 이 연동에서 속도 조절을 지원하지 않습니다. 보통 또는 Neural2를 선택하세요.')
        config = {'audioEncoding': 'LINEAR16', 'sampleRateHertz': 16000}
        if 'Chirp3' not in voice:
            config['speakingRate'] = 1.05 ** speech.rate
        payload = {'input': {'text': text}, 'voice': {'languageCode': 'ko-KR', 'name': voice}, 'audioConfig': config}
        return 'texttospeech.googleapis.com', '/v1/text:synthesize', json.dumps(payload).encode(), {'Content-Type': 'application/json'}

    def synthesize(self, text: str, target: Path, voice: str, seconds: float, speech: SpeechSettings | None = None):
        speech = speech or SpeechSettings()
        target = target.resolve()
        if voice not in self.voices() or not 0 < len(text) <= 400 or target.exists() or not 0 < seconds <= 60:
            raise TTSError('음성·문장·파일 경로·길이를 확인하세요.')
        pcm, cues = bytearray(), []
        for index, unit in enumerate(reading_units(text)):
            spoken = normalize_for_speech(unit)
            host, path, body, headers = self.request_payload(spoken, voice, speech)
            # Include Azure SSML tags in a conservative count; Google receives plain text.
            billable = body.decode() if self.settings['provider'] == 'azure' else spoken
            identity, key = self._reserve(billable, voice, speech.rate, f'{target.name}:{index}')
            headers['Ocp-Apim-Subscription-Key' if self.settings['provider'] == 'azure' else 'X-Goog-Api-Key'] = key
            try:
                status, raw = self.requester(host, 'POST', path, body, headers, 30)
                if status != 200 or len(raw) > MAX_AUDIO * 2:
                    raise ValueError
                if self.settings['provider'] == 'google':
                    raw = base64.b64decode(json.loads(raw)['audioContent'], validate=True)
                if len(raw) > MAX_AUDIO:
                    raise ValueError
                with wave.open(io.BytesIO(raw)) as audio:
                    if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
                        raise ValueError
                    frames = prepare_pcm(audio.readframes(16000 * 61))
                start = len(pcm) / 32000
                pcm.extend(frames)
                if len(pcm) / 32000 > seconds:
                    raise ValueError
                cues.append({'start': start, 'end': len(pcm) / 32000, 'text': unit})
                pcm.extend(b'\0\0' * (16000 * speech.pause_ms // 1000))
                self._success(identity)
            except Exception:  # noqa: BLE001 -- outcome uncertain: keep reservation, never retry or fallback
                raise TTSError('외부 음성 결과가 불명확하거나 검증에 실패했습니다. 자동 재요청·대체하지 않습니다.') from None
        if speech.pause_ms:
            del pcm[-2 * (16000 * speech.pause_ms // 1000):]
        with target.open('xb') as output, wave.open(output, 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(pcm)
        target.with_suffix('.cues.json').write_text(json.dumps(cues, ensure_ascii=False), encoding='utf-8')
        if wav_duration(target) > seconds + 0.05:
            raise TTSError('음성이 영상 길이를 초과했습니다. 대본을 줄이세요.')
