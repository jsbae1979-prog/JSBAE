"""Explicit account voice lookup and existing samples; never submits synthesis requests."""

import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from filelock import FileLock, Timeout

from newsflow.intelligence.credentials import CredentialError
from newsflow.intelligence.provider import NoRedirect
from newsflow.news.rss_adapter import FeedError, PublicTransport

from .tts import TTSError

VOICE_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
MAX_SAMPLE = 2 * 1024 * 1024
MAX_ERROR_BYTES = 8192
VOICE_TYPE = "saved"  # Official My Voices filter, including default voices explicitly saved to collections.
# Explicit values only: an arbitrary "code", message, header or request ID may contain a secret.
ERROR_CODES = {
    "invalid_api_key": "API Key가 유효하지 않음",
    "missing_api_key": "API Key 누락",
    "invalid_authorization_header": "인증 헤더 형식 오류",
    "unauthorized": "인증 필요",
    "sign_in_required": "계정 인증 필요",
    "insufficient_permissions": "음성 조회 권한 부족",
    "missing_permissions": "음성 조회 권한 부족",  # Compatibility with legacy status responses.
    "forbidden": "접근 권한 없음",
    "workspace_access_denied": "워크스페이스 접근 권한 없음",
    "feature_not_available": "현재 플랜에서 기능 이용 불가",
    "subscription_required": "해당 기능의 구독 조건 확인 필요",
    "quota_exceeded": "공급사 사용량 한도 부족",
    "insufficient_credits": "공급사 크레딧 부족",
}


def http_error_code(error):
    """Bounded inspection of the already-received error; never performs another request."""
    try:
        raw = error.read(MAX_ERROR_BYTES + 1)
        if not isinstance(raw, bytes) or len(raw) > MAX_ERROR_BYTES:
            return "unavailable"
        value = json.loads(raw)
        detail = value.get("detail") if isinstance(value, dict) else None
        if not isinstance(detail, dict):
            return "unavailable"
        # A present but unknown modern code must not be overridden by a legacy status.
        code = detail["code"] if "code" in detail else detail.get("status")
        if code is None:
            return "unavailable"
        return code if isinstance(code, str) and code in ERROR_CODES else "unrecognized"
    except (OSError, ValueError, TypeError, RecursionError):
        return "unavailable"
    finally:
        try:
            error.close()
        except OSError:
            pass


class VoiceListError(TTSError):
    """Allowlisted diagnostics only. Never displays raw bodies or native exception text."""

    def __init__(self, code, http_status=None, provider_error_code="unavailable"):
        labels = {"http": {401: "API Key 인증 실패", 403: "음성 조회 권한·플랜 확인 필요",
                           429: "사용량·요청 제한"}.get(http_status, "음성 조회 실패"),
                  "key_store": "보호 저장된 API Key 읽기 실패",
                  "timeout": "음성 목록 조회 시간 초과", "network": "음성 목록 연결·TLS 오류",
                  "response": "음성 목록 응답 형식·안전 검사 실패"}
        self.code, self.http_status = code, http_status
        safe_code = (provider_error_code if isinstance(provider_error_code, str)
                     and provider_error_code in ERROR_CODES else
                     "unavailable" if provider_error_code == "unavailable" else "unrecognized")
        self.provider_error_code = safe_code if code == "http" else None
        if code == "http" and safe_code in ERROR_CODES:
            labels["http"] = ERROR_CODES[safe_code]
        detail = (f" · 오류 코드 {safe_code}" if safe_code in ERROR_CODES
                  else f" · 세부 코드 미확인 ({safe_code})") if code == "http" else ""
        status = f" (공급사 HTTP {http_status})" if http_status is not None else ""
        super().__init__("ElevenLabs " + labels[code] + status + detail + " · 자동 재시도 없음")


def sample_url(value):
    """Only the documented public sample bucket; no arbitrary URLs or redirects."""
    if not isinstance(value, str) or len(value) > 1000:
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme != "https" or parts.netloc != "storage.googleapis.com"
                or parts.query or parts.fragment or not parts.path.startswith("/eleven-public-prod/")
                or not parts.path.endswith(".mp3") or ".." in parts.path
                or not re.fullmatch(r"/[A-Za-z0-9_./-]+", parts.path)):
            return None
    except ValueError:
        return None
    return value


def clean_voice(value):
    if (not isinstance(value, dict) or not isinstance(value.get("voice_id"), str)
            or not VOICE_ID.fullmatch(value["voice_id"])):
        raise TTSError("ElevenLabs 음성 목록 응답 형식 오류 · 자동 재시도 없음")
    name = value.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise TTSError("ElevenLabs 음성 이름 형식 오류 · 자동 재시도 없음")
    preview, language = sample_url(value.get("preview_url")), "기본 샘플 · 한국어 여부 미확인"
    verified = value.get("verified_languages", [])
    if isinstance(verified, list):
        for item in verified[:100]:
            if (isinstance(item, dict) and item.get("language") in {"ko", "ko-KR", "kor"}
                    and sample_url(item.get("preview_url"))):
                preview, language = sample_url(item["preview_url"]), "한국어 샘플"
                break
    # Cache only public picker metadata, never the account/sharing/private-samples response.
    return {"voice_id": value["voice_id"], "name": name.strip(),
            "preview_url": preview, "sample_label": language}


def atomic_write(path, data):
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            name = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


class ElevenLabsVoices:
    def __init__(self, root: Path, keys, *, transport=None, samples=None):
        self.root = root / "tts-elevenlabs"
        self.keys = keys
        self.transport = transport or self._http
        self.samples = samples or PublicTransport()

    def _tag(self):
        # No DPAPI decryption on a page load. A changed key hides stale account metadata.
        status = self.keys.status()
        if status["stored"]:
            return hashlib.sha256(self.keys.path.read_bytes()).hexdigest()
        if status["environment"]:
            return hashlib.sha256(os.environ.get(self.keys.ENV, "").strip().encode()).hexdigest()
        return None

    def cached(self):
        empty = {"voices": [], "has_more": False, "next_page_token": None, "fetched_at": ""}
        path = self.root / "voices.json"
        try:
            if not path.is_file() or path.stat().st_size > 2_000_000:
                return empty
            result = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(result, dict) or not self._tag() or result.get("key_tag") != self._tag()
                    or not isinstance(result.get("voices"), list) or len(result["voices"]) > 1000
                    or type(result.get("has_more")) is not bool
                    or (result["has_more"] and (not isinstance(result.get("next_page_token"), str)
                                               or not 1 <= len(result["next_page_token"]) <= 2048))):
                return empty
            for voice in result["voices"]:
                if (not isinstance(voice, dict) or not VOICE_ID.fullmatch(voice.get("voice_id", ""))
                        or not isinstance(voice.get("name"), str) or len(voice["name"]) > 200
                        or (voice.get("preview_url") is not None and not sample_url(voice["preview_url"]))):
                    return empty
            return result
        except (OSError, ValueError, TypeError):
            return empty

    def _http(self, token):
        try:
            key = self.keys.key()
            if not key:
                raise TTSError("ElevenLabs API Key 미등록")
            query = {"page_size": 100, "voice_type": VOICE_TYPE}
            if token:
                query["next_page_token"] = token
            request = urllib.request.Request("https://api.elevenlabs.io/v2/voices?" + urlencode(query),
                                             headers={"xi-api-key": key, "Accept": "application/json"})
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
                raw = response.read(4_000_001)
            if len(raw) > 4_000_000 or key.encode() in raw:
                raise ValueError
            result = json.loads(raw)
            if key in json.dumps(result, ensure_ascii=False):
                raise ValueError
            return result
        except urllib.error.HTTPError as exc:
            raise VoiceListError("http", exc.code, http_error_code(exc)) from None
        except CredentialError:
            raise VoiceListError("key_store") from None
        except TimeoutError:
            raise VoiceListError("timeout") from None
        except urllib.error.URLError as exc:
            raise VoiceListError("timeout" if isinstance(exc.reason, TimeoutError) else "network") from None
        except OSError:
            raise VoiceListError("network") from None
        except (ValueError, TypeError):
            raise VoiceListError("response") from None

    def record_failure(self, error):
        """Retain only classification/status/time, never text, key, URL, headers or response body."""
        code, status, provider_code = "validation_or_local", None, None
        if isinstance(error, VoiceListError):
            code, status, provider_code = error.code, error.http_status, error.provider_error_code
        try:
            directory = self.root / "diagnostics"
            directory.mkdir(parents=True, exist_ok=True)
            record = {"operation": "voice_list", "failure_code": code, "provider_http_status": status,
                      "provider_error_code": provider_code,
                      "recorded_at": datetime.now(UTC).isoformat(timespec="seconds")}
            atomic_write(directory / (uuid4().hex + ".json"), json.dumps(record).encode())
        except OSError:
            pass  # Recording failure must not hide the original safe error or trigger another request.

    def load(self, *, more=False):
        """Exactly one page per explicit action; a failure keeps the last successful cache."""
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(str(self.root / "voices.lock"), timeout=0):
                tag, previous = self._tag(), self.cached()
                if not tag:
                    raise TTSError("ElevenLabs API Key 미등록")
                token = previous.get("next_page_token") if more and previous.get("has_more") else None
                if more and previous.get("voice_type") != VOICE_TYPE:
                    raise TTSError("기존 전체 목록의 다음 페이지는 불러오지 않습니다. 내 음성 목록을 새로 조회하세요.")
                if more and (not token or len(previous["voices"]) >= 1000):
                    raise TTSError("더 불러올 음성이 없습니다. 목록 새로 불러오기를 사용하세요.")
                result = self.transport(token)
                if (not isinstance(result, dict) or not isinstance(result.get("voices"), list)
                        or len(result["voices"]) > 200 or type(result.get("has_more")) is not bool):
                    raise TTSError("ElevenLabs 음성 목록 응답 형식 오류 · 자동 재시도 없음")
                next_token = result.get("next_page_token")
                if result["has_more"] and (not isinstance(next_token, str) or not 1 <= len(next_token) <= 2048
                                           or next_token == token):
                    raise TTSError("ElevenLabs 다음 목록 정보 오류 · 자동 재시도 없음")
                voices = {v["voice_id"]: v for v in previous["voices"]} if more else {}
                for item in result["voices"]:
                    voice = clean_voice(item)
                    voices[voice["voice_id"]] = voice
                if len(voices) > 1000 or self._tag() != tag:
                    raise TTSError("목록 한도 또는 키 변경 감지 · 목록을 저장하지 않았습니다.")
                cached = {"key_tag": tag, "voices": list(voices.values()), "has_more": result["has_more"],
                          "voice_type": VOICE_TYPE,
                          "next_page_token": next_token if result["has_more"] else None,
                          "fetched_at": datetime.now(UTC).isoformat(timespec="seconds")}
                atomic_write(self.root / "voices.json", json.dumps(cached, ensure_ascii=False).encode())
                return cached
        except (OSError, Timeout):
            raise TTSError("ElevenLabs 음성 목록 저장·동시 작업 오류 · 자동 재시도 없음") from None

    def voice(self, voice_id):
        return next((v for v in self.cached()["voices"] if v["voice_id"] == voice_id), None)

    def sample_path(self, voice_id):
        voice = self.voice(voice_id)
        if not voice or not sample_url(voice.get("preview_url")):
            raise TTSError("이 음성은 지원되는 공개 샘플이 없습니다. 음성 생성은 실행하지 않았습니다.")
        return self.root / "previews" / (hashlib.sha256(voice["preview_url"].encode()).hexdigest() + ".mp3")

    def prepare_sample(self, voice_id):
        path = self.sample_path(voice_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(str(path) + ".lock", timeout=0):
                if path.is_file():
                    return
                # No account key/cookies go to the CDN. Pinned public DNS and default TLS, no redirect.
                response = self.samples.get(self.voice(voice_id)["preview_url"], timeout=15)
                body = response.body
                if (response.status != 200 or not 4 <= len(body) <= MAX_SAMPLE
                        or not (body.startswith(b"ID3") or (body[0] == 255 and body[1] & 224 == 224))):
                    raise TTSError("샘플 다운로드·MP3 형식 확인 실패 · 자동 재시도 없음")
                atomic_write(path, body)
        except (OSError, Timeout, FeedError):
            raise TTSError("샘플 연결·시간 초과·안전 검사 실패 · 자동 재시도 없음") from None


def select_voice(sessions, voice_id, catalog):
    """Explicit save changes only the existing voice ID, never another provider or approval."""
    from newsflow.db.models import AppSetting

    if not catalog.voice(voice_id):
        raise TTSError("불러온 음성 목록에서 이름을 선택하세요. 기존 선택값은 유지됩니다.")
    with sessions.begin() as session:
        row = session.get(AppSetting, "tts_el_voice_id")
        if row is None:
            session.add(AppSetting(key="tts_el_voice_id", value=json.dumps(voice_id)))
        else:
            row.value = json.dumps(voice_id)
