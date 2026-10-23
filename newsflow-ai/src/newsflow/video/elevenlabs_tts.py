"""Opt-in fixed-origin ElevenLabs adapter, conservative credit reservations, no POST retries."""

import base64
import hashlib
import json
import math
import os
import re
import shutil
import urllib.error
import urllib.request
import wave
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

from newsflow.intelligence.credentials import AIKeyStore
from newsflow.intelligence.korean import split_sentences
from newsflow.intelligence.provider import NoRedirect

from .tts import SpeechSettings, TTSError, wav_duration

MODELS = ("eleven_multilingual_v2", "eleven_flash_v2_5", "eleven_v3")
BASE = "https://api.elevenlabs.io/v1"


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


def save_settings(sessions, *, enabled, voice_id, model, job_limit, monthly_limit, commercial):
    from newsflow.db.models import AppSetting

    if (model not in MODELS or (voice_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", voice_id))
            or not 1 <= job_limit <= 10000 or not job_limit <= monthly_limit <= 1000000):
        raise TTSError("ElevenLabs 음성 ID·모델·크레딧 한도를 확인하세요.")
    values = {"enabled": bool(enabled), "voice_id": voice_id, "model": model, "job_limit": job_limit,
              "monthly_limit": monthly_limit, "commercial": bool(commercial)}
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
            message = {401: "API 키 인증 실패", 403: "권한·플랜 확인 필요", 429: "사용량·요청 한도 초과"}.get(
                error.code, "요청 실패 · 자동 재시도 없음")
            raise TTSError("ElevenLabs " + message) from None
        except (OSError, ValueError, TypeError):
            raise TTSError("ElevenLabs 연결·시간 초과·응답 검증 실패 · 자동 재시도 없음") from None

    def subscription(self, credits=0):
        info = self.transport("GET", "/user/subscription")
        if (not isinstance(info, dict) or type(info.get("character_count")) is not int
                or type(info.get("character_limit")) is not int
                or not 0 <= info["character_count"] <= info["character_limit"]
                or type(info.get("max_credit_limit_extension")) is not int
                or info.get("max_credit_limit_extension") != 0
                or info.get("status") != "active"):
            raise TTSError("계정 한도 확인 실패 또는 추가 과금 가능: 공급사에서 초과 과금을 끈 뒤 확인하세요.")
        tier = info.get("tier")
        if tier not in ("free", "starter", "creator", "pro", "scale", "business", "enterprise"):
            raise TTSError("ElevenLabs 플랜 이용 조건 미확인")
        if self.config["commercial"] and tier == "free":
            raise TTSError("ElevenLabs 무료 플랜은 상업적 이용이 불가합니다. 로컬 음성 또는 허용된 유료 플랜을 선택하세요.")
        if info["character_limit"] == info["character_count"]:
            raise TTSError("ElevenLabs에서 확인한 잔여 크레딧이 없습니다.")
        self.attribution_required = tier == "free"
        return {"tier": tier, "remaining": info["character_limit"] - info["character_count"],
                "overage_disabled": True, "attribution_required": self.attribution_required}

    def synthesize_timed(self, text, target, voice, seconds, speech=None, *, cancel=None):
        config = self.config
        speech = speech or SpeechSettings()
        if (not self.consent or not config["enabled"] or voice != "elevenlabs"
                or config["model"] not in MODELS or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", config["voice_id"])
                or not 0 < len(text) <= 400):
            raise TTSError("ElevenLabs는 키·음성 설정과 이번 제작의 외부 전송·사용량 동의가 필요합니다.")
        if cancel is not None and cancel.is_set():
            raise TTSError("외부 음성 요청 취소")
        # Resource limits stay; speculative credit multipliers and reservations do not.
        digest = hashlib.sha256(json.dumps([text, config["voice_id"], config["model"], speech.rate,
                                           hashlib.sha256(self.keys.key().encode()).hexdigest(),
                                           config["commercial"]], ensure_ascii=False).encode()).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        ledger_path, cache = self.root / "ledger.json", self.root / f"{digest}.wav"
        with FileLock(str(self.root / "requests.lock"), timeout=1):
            ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}

            def persist():
                temporary = ledger_path.with_name("ledger-" + uuid4().hex + ".tmp")
                temporary.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
                os.replace(temporary, ledger_path)

            previous = ledger.get(digest)
            if previous:
                if (previous["state"] == "completed" and cache.is_file()
                        and hashlib.sha256(cache.read_bytes()).hexdigest() == previous["sha256"]):
                    self.attribution_required = previous.get("attribution_required", True)
                    shutil.copyfile(cache, target)
                    return previous["cues"]
                raise TTSError("동일 외부 음성 요청의 결과 불명·캐시 손상: 중복 청구 방지를 위해 재요청을 차단했습니다.")
            if any(item["state"] != "completed" for item in ledger.values()):
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
                persist()
                if cancel is not None and cancel.is_set():
                    raise TTSError("응답 후 취소 · 사용량과 캐시는 보존했습니다.")
                shutil.copyfile(cache, target)
                return cues
            except TTSError:
                raise
            except Exception:  # noqa: BLE001 - uncertain POST outcome stays reserved; never replay
                raise TTSError("ElevenLabs 생성 결과 확인 실패 · 요청 기록 유지 · 사용량 미확인 · 자동 재시도 없음") from None

    def synthesize(self, text, target, voice, seconds, speech=None):
        self.synthesize_timed(text, target, voice, seconds, speech)
        if wav_duration(target) > seconds + .05:
            raise TTSError("외부 음성이 영상 길이를 초과했습니다.")
