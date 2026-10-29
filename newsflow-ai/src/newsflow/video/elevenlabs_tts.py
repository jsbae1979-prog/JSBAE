"""Opt-in fixed-origin ElevenLabs adapter, conservative credit reservations, no POST retries."""

import base64
import hashlib
import json
import math
import os
import re
import shutil
import time
import urllib.error
import urllib.request
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from filelock import FileLock

from newsflow.intelligence.credentials import AIKeyStore
from newsflow.intelligence.korean import split_sentences
from newsflow.intelligence.provider import NoRedirect

from .tts import SpeechSettings, TTSError, wav_duration

MODELS = ("eleven_multilingual_v2", "eleven_flash_v2_5", "eleven_v3")
BASE = "https://api.elevenlabs.io/v1"


def replace_metadata(temporary, destination):
    """Bounded local rename only, under requests.lock. Never repeats a supplier request."""
    for attempt in range(4):
        try:
            os.replace(temporary, destination)
            return
        except PermissionError:
            if os.name != 'nt' or attempt == 3:
                raise
            time.sleep((.01, .03, .10)[attempt])


class SubscriptionError(TTSError):
    """Fixed local policy messages; never expose supplier response text."""

    MESSAGES: ClassVar[dict[str, str]] = {
        "invalid_usage": "ElevenLabs 사용량 응답을 확인할 수 없습니다. 음성 생성은 실행하지 않았습니다.",
        "overage_unknown": "ElevenLabs 초과 과금 설정을 확인할 수 없습니다. 계정의 사용량 기반 과금 설정을 확인하세요.",
        "overage_enabled": "ElevenLabs 초과 과금이 허용되어 있습니다. 계정에서 초과 과금을 끈 뒤 확인하세요.",
        "unknown_plan": "ElevenLabs 플랜 이용 조건을 확인할 수 없습니다.",
        "inactive": "ElevenLabs 계정 상태가 음성 생성 허용 상태가 아닙니다. 계정 상태를 확인하세요.",
        "free_commercial": "ElevenLabs 무료 플랜은 상업적 이용이 불가합니다. 비상업용 검토 또는 허용된 유료 플랜이 필요합니다.",
        "insufficient_credits": "ElevenLabs 잔여 크레딧이 이번 요청에 필요한 한도보다 부족합니다.",
    }

    def __init__(self, code):
        self.code = code if isinstance(code, str) and code in self.MESSAGES else "invalid_usage"
        super().__init__(self.user_message)

    @property
    def user_message(self):
        return self.MESSAGES.get(self.code, self.MESSAGES["invalid_usage"])


class PaymentRequiredError(TTSError):
    """An HTTP 402 is a definite provider rejection, not a lost response."""

    def __init__(self):
        super().__init__("ElevenLabs가 이 음성의 API 생성에 유료 플랜을 요구했습니다 (HTTP 402). 자동 재시도하지 않습니다.")


def rejected_payment(item):
    # Preserve the original reservation and its credit count; only an explicit
    # provider rejection annotation lets a DIFFERENT request proceed.
    return (item.get("state") == "reserved"
            and item.get("provider_rejection") == {"http_status": 402, "code": "payment_required"})


class ElevenLabsKeys(AIKeyStore):
    FILE = "tts-elevenlabs-key.dpapi"
    ENV = "NEWSFLOW_ELEVENLABS_KEY"
    ENTROPY = b"NewsFlowAI:ElevenLabs:TTS"


def settings(sessions):
    from newsflow.db.models import AppSetting

    defaults = {"enabled": False, "voice_id": "", "model": MODELS[0], "job_limit": 1000,
                "monthly_limit": 10000, "commercial": True}
    with sessions() as session:
        for name, default in defaults.items():
            row = session.get(AppSetting, "tts_el_" + name)
            if row is not None:
                try:
                    value = json.loads(row.value)
                    if type(value) is type(default):
                        defaults[name] = value
                except ValueError:
                    pass
    return defaults


def save_settings(sessions, *, enabled, voice_id, model, job_limit, monthly_limit=None, commercial):
    from newsflow.db.models import AppSetting

    if (model not in MODELS or (voice_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", voice_id))
            or type(job_limit) is not int or not 1 <= job_limit <= 10000):
        raise TTSError("ElevenLabs 음성 ID·모델·크레딧 한도를 확인하세요.")
    values = {"enabled": bool(enabled), "voice_id": voice_id, "model": model, "job_limit": job_limit,
              "commercial": bool(commercial)}
    with sessions.begin() as session:
        for name, value in values.items():
            row = session.get(AppSetting, "tts_el_" + name)
            if row is None:
                session.add(AppSetting(key="tts_el_" + name, value=json.dumps(value)))
            else:
                row.value = json.dumps(value)


def alignment_cues(text, value, seconds):
    if not isinstance(value, dict):
        raise TTSError("ElevenLabs 발화 시점 정보가 없습니다.")
    chars = value.get("characters", [])
    starts, ends = (value.get(key, []) for key in ("character_start_times_seconds", "character_end_times_seconds"))
    if (not isinstance(chars, list) or not all(isinstance(c, str) and len(c) == 1 for c in chars)
            or "".join(chars) != text or len(chars) != len(starts) or len(chars) != len(ends)):
        raise TTSError("ElevenLabs 원문·타임스탬프가 일치하지 않습니다.")
    previous = 0
    for start, end in zip(starts, ends):
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end)
                or not previous <= start <= end <= seconds + .001):
            raise TTSError("ElevenLabs 발화 타임스탬프 범위 오류")
        previous = start
    cues, cursor = [], 0
    for sentence in split_sentences(text):
        index = text.find(sentence, cursor)
        if index < 0:
            raise TTSError("ElevenLabs 문장 타임스탬프 일치 실패")
        cursor = index + len(sentence)
        cues.append({"start_ms": round(starts[index] * 1000),
                     "end_ms": round(ends[cursor - 1] * 1000), "text": sentence})
    return cues


class ElevenLabsTTS:
    def __init__(self, root: Path, config: dict, *, consent=False, transport=None, keys=None):
        self.root, self.config, self.consent = root / "tts-elevenlabs", config, consent
        self.keys = keys or ElevenLabsKeys(root)
        self.transport = transport or self._http
        self.reported_credits = None
        self.attribution_required = False

    def voices(self):
        return ["elevenlabs"]

    def _http(self, method, path, payload=None):
        key = self.keys.key()
        if not key:
            raise TTSError("ElevenLabs API 키가 없습니다.")
        request = urllib.request.Request(BASE + path, method=method,
                                         data=json.dumps(payload).encode() if payload is not None else None,
                                         headers={"xi-api-key": key, "Content-Type": "application/json"})
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
                raw = response.read(10000001)
                if method == "POST":
                    value = response.headers.get("character-cost", "")
                    self.reported_credits = int(value) if re.fullmatch(r"[0-9]{1,9}", value) else None
            if len(raw) > 10000000:
                raise ValueError
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise TypeError
            return result
        except urllib.error.HTTPError as error:
            if error.code == 402:
                error.close()
                raise PaymentRequiredError() from None
            message = {401: "API 키 인증 실패", 403: "권한·플랜 확인 필요", 429: "사용량·요청 한도 초과"}.get(
                error.code, "요청 실패 · 자동 재시도 없음")
            raise TTSError("ElevenLabs " + message) from None
        except (OSError, ValueError, TypeError):
            raise TTSError("ElevenLabs 연결·시간 초과·응답 검증 실패 · 자동 재시도 없음") from None

    def subscription(self, credits=0):
        info = self.transport("GET", "/user/subscription")
        if (not isinstance(info, dict) or type(info.get("character_count")) is not int
                or type(info.get("character_limit")) is not int
                or not 0 <= info["character_count"] <= info["character_limit"]):
            raise SubscriptionError("invalid_usage")
        extension = info.get("max_credit_limit_extension")
        if extension == "unlimited" or (type(extension) is int and extension > 0):
            raise SubscriptionError("overage_enabled")
        if type(extension) is not int or extension != 0:
            raise SubscriptionError("overage_unknown")
        tier = info.get("tier")
        if tier not in ("free", "starter", "creator", "pro", "scale", "business", "enterprise"):
            raise SubscriptionError("unknown_plan")
        # Official subscription responses use "free" for a usable free account.
        # Do not accept it for a paid tier, or accept free_disabled/trialing/unknown.
        status = info.get("status")
        if status != "active" and not (tier == "free" and status == "free"):
            raise SubscriptionError("inactive")
        if self.config["commercial"] and tier == "free":
            raise SubscriptionError("free_commercial")
        if info["character_limit"] - info["character_count"] <= 0:
            raise SubscriptionError("insufficient_credits")
        self.attribution_required = tier == "free"
        return {"tier": tier, "remaining": info["character_limit"] - info["character_count"],
                "overage_disabled": True, "attribution_required": self.attribution_required}

    def _cache_digest(self, text, speech):
        secret = self.keys.key()
        if secret and secret in text:
            raise TTSError('비밀정보가 포함된 음성 요청은 실행할 수 없습니다.')
        return hashlib.sha256(json.dumps([text, self.config['voice_id'], self.config['model'], speech.rate,
                              hashlib.sha256(secret.encode()).hexdigest(),
                              self.config['commercial']], ensure_ascii=False).encode()).hexdigest()

    def remember_completed_cache(self, text, speech=None):
        """Explicit local reuse only. Missing/unknown cache never turns into an HTTP request."""
        from .narration_planning import measurement

        speech = speech or SpeechSettings()
        if not isinstance(text, str) or not 0 < len(text) <= 400 or not self.root.is_dir():
            raise TTSError('완료된 기존 음성 캐시가 필요합니다. 새 요청하지 않습니다.')
        name = self._cache_digest(text, speech)
        with FileLock(str(self.root / 'requests.lock'), timeout=1):
            ledger = json.loads((self.root/'ledger.json').read_text(encoding='utf-8'))
            row, audio = ledger.get(name), self.root/(name+'.wav')
            cues = row.get('cues') if isinstance(row, dict) else None
            if (not isinstance(row, dict) or row.get('state') != 'completed' or not audio.is_file()
                    or audio.is_symlink() or hashlib.sha256(audio.read_bytes()).hexdigest() != row.get('sha256')
                    or not isinstance(cues, list) or any(not isinstance(cue, dict) or not isinstance(cue.get('text'), str) for cue in cues)
                    or ''.join(cue['text'] for cue in cues).replace(' ', '') != text.replace(' ', '')):
                raise TTSError('완료·텍스트·WAV 연결이 확인되지 않아 기존 기록만 보존합니다. 새 요청하지 않습니다.')
            receipt = measurement(text, self.config, speech, self.keys, audio, row.get('reported_credits'))
            if receipt is None:
                raise TTSError('확인된 사용량·키 식별 근거가 없어 보정 기록을 만들지 않습니다.')
            path = self.root/'narration-measurements.json'
            if path.is_symlink() or path.is_file() and path.stat().st_size > 4_000_000:
                raise TTSError('기존 보정 기록을 확인할 수 없습니다.')
            values = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
            if not isinstance(values, dict):
                raise TTSError('기존 보정 기록을 확인할 수 없습니다.')
            if name in values:
                if values[name] != receipt:
                    raise TTSError('기존 보정 기록이 달라 자동 덮어쓰지 않습니다.')
                return
            values[name] = receipt
            temporary = path.with_name('narration-measurements-'+uuid4().hex+'.tmp')
            temporary.write_text(json.dumps(values, ensure_ascii=False), encoding='utf-8')
            replace_metadata(temporary, path)  # Separate additive receipts; original ledger/cache untouched.

    def synthesize_timed(self, text, target, voice, seconds, speech=None, *, cancel=None):
        config = self.config
        speech = speech or SpeechSettings()
        if (not self.consent or not config["enabled"] or voice != "elevenlabs"
                or config["model"] not in MODELS or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", config["voice_id"])
                or not 0 < len(text) <= 400):
            raise TTSError("ElevenLabs는 키·음성 설정과 이번 제작의 외부 전송·사용량 동의가 필요합니다.")
        if cancel is not None and cancel.is_set():
            raise TTSError("외부 음성 요청 취소")
        # This explicit synthesis request is limited by characters, not historical monthly usage.
        if type(config.get("job_limit")) is not int or not 1 <= config["job_limit"] <= 10000 or len(text) > config["job_limit"]:
            raise TTSError("이번 음성 요청의 글자 수가 1회 실행 한도를 넘습니다.")
        digest = self._cache_digest(text, speech)
        self.root.mkdir(parents=True, exist_ok=True)
        ledger_path, cache = self.root / "ledger.json", self.root / f"{digest}.wav"
        with FileLock(str(self.root / "requests.lock"), timeout=1):
            ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}

            def persist():
                temporary = ledger_path.with_name("ledger-" + uuid4().hex + ".tmp")
                temporary.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
                replace_metadata(temporary, ledger_path)

            previous = ledger.get(digest)
            if previous:
                if (previous["state"] == "completed" and cache.is_file()
                        and hashlib.sha256(cache.read_bytes()).hexdigest() == previous["sha256"]):
                    self.attribution_required = previous.get("attribution_required", True)
                    shutil.copyfile(cache, target)
                    return previous["cues"]
                raise TTSError("동일 외부 음성 요청의 결과 불명·캐시 손상: 중복 청구 방지를 위해 재요청을 차단했습니다.")
            if any(item["state"] != "completed" and not rejected_payment(item) for item in ledger.values()):
                raise TTSError("이전 외부 음성 요청 결과 불명: 공급사 사용량 확인 전 추가 요청 차단")
            month = datetime.now(UTC).strftime("%Y-%m")
            self.subscription()
            ledger[digest] = {"state": "reserved", "credits": 0, "month": month,
                              "accounting": "reported_usage", "reported_credits": None,
                              "vendor_billing": "NOT VERIFIED"}
            persist()
            try:
                if cancel is not None and cancel.is_set():
                    raise TTSError("전송 직전 취소 · 요청 기록 유지")
                self.reported_credits = None
                response = self.transport("POST", f"/text-to-speech/{config['voice_id']}/with-timestamps?output_format=pcm_24000",
                                          {"text": text, "model_id": config["model"],
                                           "voice_settings": {"speed": 1 + speech.rate * .03}})
                pcm = base64.b64decode(response["audio_base64"], validate=True)
                if not 0 < len(pcm) <= 24000 * 2 * 120 or len(pcm) % 2:
                    raise TTSError("ElevenLabs PCM 형식 오류")
                with wave.open(str(cache), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(24000)
                    output.writeframes(pcm)
                cues = alignment_cues(text, response.get("alignment"), wav_duration(cache))
                ledger[digest].update(state="completed", cues=cues,
                                      reported_credits=self.reported_credits,
                                      attribution_required=self.attribution_required,
                                      sha256=hashlib.sha256(cache.read_bytes()).hexdigest())
                # Optional local writing guidance, after response/alignment/usage validation.
                # Never backfill or rewrite an old receipt and never submit to obtain samples.
                from .narration_planning import measurement

                try:
                    receipt = measurement(text, config, speech, self.keys, cache, self.reported_credits)
                except (OSError, ValueError, TTSError):
                    receipt = None
                if receipt:
                    ledger[digest]['narration_measurement'] = receipt
                persist()
                if cancel is not None and cancel.is_set():
                    raise TTSError("응답 후 취소 · 사용량과 캐시는 보존했습니다.")
                shutil.copyfile(cache, target)
                return cues
            except PaymentRequiredError:
                ledger[digest]["provider_rejection"] = {"http_status": 402, "code": "payment_required"}
                persist()
                raise
            except TTSError:
                raise
            except Exception:  # noqa: BLE001 - uncertain POST outcome stays reserved; never replay
                raise TTSError("ElevenLabs 생성 결과 확인 실패 · 요청 기록 유지 · 사용량 미확인 · 자동 재시도 없음") from None

    def synthesize(self, text, target, voice, seconds, speech=None):
        self.synthesize_timed(text, target, voice, seconds, speech)
        if wav_duration(target) > seconds + .05:
            raise TTSError("외부 음성이 영상 길이를 초과했습니다.")
