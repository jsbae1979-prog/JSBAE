"""TikTok Desktop Login Kit contracts; real network/browser activation stays closed."""
from __future__ import annotations

import hashlib
import http.client
import json
import re
import ssl
import webbrowser
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import urlencode

from pydantic import SecretStr

from newsflow.db.models import utcnow
from newsflow.publishing.auth import TokenBundle

SCOPES = ("user.info.basic", "video.publish")
AUTHORIZE = "https://www.tiktok.com/v2/auth/authorize/"
MESSAGES = {
    "blocked": "TikTok 실계정 인증·전송은 운영 활성화 전까지 차단되어 있습니다.",
    "config": "TikTok Desktop 앱 설정을 확인하세요.",
    "consent": "이번 계정 연결 또는 인증 작업에 동의해 주세요.",
    "pending": "진행 중인 TikTok 인증 작업이 있습니다.",
    "expired": "인증이 만료되었습니다. 다시 연결해 주세요.",
    "cancelled": "TikTok 연결을 취소했습니다.",
    "callback": "인증 응답을 검증하지 못했습니다. 새로 연결해 주세요.",
    "permission": "계정 조회와 게시 권한이 모두 필요합니다.",
    "identity": "TikTok 계정 또는 앱이 일치하지 않습니다.",
    "unknown": "인증 처리 결과를 확인하지 못했습니다. 자동 재시도하지 않습니다.",
    "storage": "Windows 보호 저장소를 확인하세요. 비밀값은 표시하지 않습니다.",
    "port": "인증 응답 포트를 사용할 수 없습니다. 진행 중인 연결을 확인하세요.",
}


class TikTokError(Exception):
    def __init__(self, code="unknown"):
        self.code = code if code in MESSAGES else "unknown"
        super().__init__(MESSAGES[self.code])


def production_enabled() -> bool:
    # Separate reviewed code activation, never an environment variable or consent checkbox.
    return False


def safe(value, maximum=4096):
    return isinstance(value, str) and 1 <= len(value) <= maximum and all(32 < ord(c) < 127 for c in value)


@dataclass(frozen=True)
class DesktopConfig:
    client_key: str
    client_secret: SecretStr = field(repr=False)
    port: int = 0

    def __post_init__(self):
        if (not isinstance(self.client_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{5,128}", self.client_key)
                or not isinstance(self.client_secret, SecretStr)
                or not safe(self.client_secret.get_secret_value(), 256)
                or len(self.client_secret.get_secret_value()) < 16
                or type(self.port) is not int or self.port != 0 and not 1024 <= self.port <= 65535
                or self.port == 8765):
            raise TikTokError("config")

    @property
    def registered_redirect(self):
        return f"http://127.0.0.1:{self.port or '*'}/oauth/tiktok/callback/"


def challenge(verifier: str) -> str:
    if not isinstance(verifier, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
        raise TikTokError("callback")
    # TikTok Desktop documentation specifies SHA256 HEX, unlike Google's base64url S256.
    return hashlib.sha256(verifier.encode("ascii")).hexdigest()


def token_result(data: dict, expected_id: str | None = None):
    if not isinstance(data, dict):
        raise TikTokError()
    if data.get("error"):
        raise TikTokError("expired" if data.get("error") == "invalid_grant" else "permission")
    keys = {"access_token", "refresh_token", "expires_in", "refresh_expires_in", "scope", "token_type", "open_id"}
    if set(data) != keys or data.get("token_type") != "Bearer":
        raise TikTokError()
    if (not all(safe(data[k]) for k in ("access_token", "refresh_token", "open_id"))
            or len(data["open_id"]) > 128
            or type(data["expires_in"]) is not int or not 1 <= data["expires_in"] <= 86400
            or type(data["refresh_expires_in"]) is not int or not 1 <= data["refresh_expires_in"] <= 366 * 86400):
        raise TikTokError()
    if not isinstance(data["scope"], str) or set(data["scope"].split(",")) != set(SCOPES) or len(data["scope"].split(",")) != 2:
        raise TikTokError("permission")
    if expected_id and data["open_id"] != expected_id:
        raise TikTokError("identity")
    return TokenBundle(access_token=SecretStr(data["access_token"]), refresh_token=SecretStr(data["refresh_token"]),
                       expires_at=utcnow() + timedelta(seconds=data["expires_in"]), scopes=SCOPES), data["open_id"], (
                           utcnow() + timedelta(seconds=data["refresh_expires_in"]))


def identity_result(data: dict, expected: str) -> str:
    try:
        user = data["data"]["user"]
        label = user["display_name"]
        if (data["error"]["code"] != "ok" or user["open_id"] != expected
                or not isinstance(label, str) or not 1 <= len(label) <= 100
                or any(ord(c) < 32 for c in label)):
            raise ValueError
        return label
    except Exception:  # noqa: BLE001 - redact credentials and provider diagnostics
        raise TikTokError("identity") from None


class TikTokHTTP:
    """Fixed HTTPS destinations, TLS verification, bounded response, no retry/redirect."""
    def __init__(self, *, synthetic_connection=None):
        self.factory = synthetic_connection
        self.synthetic = synthetic_connection is not None

    def request(self, operation: str, values: dict):
        if not self.synthetic and not production_enabled():
            raise TikTokError("blocked")
        paths = {"token": "/v2/oauth/token/", "revoke": "/v2/oauth/revoke/",
                 "identity": "/v2/user/info/?fields=open_id,display_name"}
        if operation not in paths:
            raise TikTokError("config")
        allowed = {"token": {"client_key", "client_secret", "grant_type", "code", "redirect_uri", "code_verifier", "refresh_token"},
                   "revoke": {"client_key", "client_secret", "token"}, "identity": {"access_token"}}
        if set(values) - allowed[operation] or any(not isinstance(v, str) or len(v) > 4096 for v in values.values()):
            raise TikTokError("config")
        if self.synthetic and any(not v.startswith("nf-synthetic-") for k, v in values.items()
                                  if k in {"client_secret", "code", "refresh_token", "token", "access_token"}):
            raise TikTokError("blocked")
        connection = None
        try:
            factory = self.factory or http.client.HTTPSConnection
            connection = factory("open.tiktokapis.com", timeout=20, context=ssl.create_default_context())
            if operation == "identity":
                connection.request("GET", paths[operation], headers={"Authorization": "Bearer " + values["access_token"]})
            else:
                connection.request("POST", paths[operation], body=urlencode(values).encode(),
                                   headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-store"})
            response = connection.getresponse()
            raw = response.read(65537)
            if len(raw) > 65536 or response.status not in (200, 400, 401, 403):
                raise TikTokError()
            value = {} if operation == "revoke" and not raw else json.loads(raw)
            if not isinstance(value, dict):
                raise TikTokError()
            if response.status != 200:
                raise TikTokError("expired" if value.get("error") == "invalid_grant" else "permission")
            if operation == "revoke" and value != {}:
                raise TikTokError()
            return value
        except TikTokError:
            raise
        except Exception:  # noqa: BLE001 - redact credentials and provider diagnostics
            raise TikTokError() from None
        finally:
            if connection:
                try:
                    connection.close()
                except Exception:  # noqa: BLE001, S110 - never log transport secrets on cleanup
                    pass


class TikTokBrowser:
    def open(self, url: SecretStr):
        if not production_enabled():
            raise TikTokError("blocked")
        if not url.get_secret_value().startswith(AUTHORIZE + "?"):
            raise TikTokError("config")
        try:
            if not webbrowser.open(url.get_secret_value(), new=1, autoraise=True):
                raise TikTokError("callback")
        except Exception:  # noqa: BLE001 - redact credentials and provider diagnostics
            raise TikTokError("callback") from None
