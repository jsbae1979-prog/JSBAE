"""Meta integration contracts. Secret values never participate in repr or JSON views."""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256

from pydantic import SecretStr

SCOPES = (
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "instagram_basic",
    "instagram_content_publish",
)
TASKS = {"CREATE_CONTENT", "MANAGE", "PROFILE_PLUS_CREATE_CONTENT", "PROFILE_PLUS_FULL_CONTROL"}
MESSAGES = {
    "configuration": "계정 연결 또는 외부 미디어 저장소 설정을 확인하세요.",
    "not_found": "이 사용자의 연결 또는 게시 작업이 아닙니다.",
    "consent": "대상 계정·콘텐츠와 전송·게시 승인을 확인하세요.",
    "expired": "인증 또는 데이터 접근이 만료되었습니다. 다시 연결하세요.",
    "authentication": "Meta가 인증을 거절했습니다. 만료로 확인된 것은 아닙니다. 입력한 사용자 토큰과 앱 권한을 확인하세요.",
    "token_expired": "사용자 토큰의 유효기간이 지났습니다. 새 사용자 토큰을 입력하세요.",
    "data_expired": "계정 데이터 접근 기간이 지났습니다. Meta에서 권한을 다시 승인한 사용자 토큰을 입력하세요.",
    "token_type": "사용자 토큰이 아닙니다. 페이지 토큰·앱 시크릿 대신 본인 사용자 토큰을 입력하세요.",
    "token_app": "다른 Meta 앱에서 발급한 토큰입니다. 설정된 NewsFlow AI 앱의 사용자 토큰을 입력하세요.",
    "token_metadata": "Meta에서 토큰 유효기간을 확인하지 못했습니다. 만료일을 직접 입력할 필요는 없습니다.",
    "permission": "선택한 계정의 관리·게시 권한이 부족합니다.",
    "identity": "다른 계정으로 재연결할 수 없습니다. 새 연결로 추가하세요.",
    "invalid": "설정 또는 Meta 응답을 확인하지 못했습니다.",
    "pending": "요청을 처리 중입니다. 자동 재요청하지 않습니다.",
    "unknown": "이전 요청 결과를 확인해야 합니다. 자동 재전송하지 않습니다.",
    "rejected": "Meta가 요청을 거절했습니다. 권한과 콘텐츠를 확인하세요.",
    "media": "검토한 미디어가 변경됐거나 공개 HTTPS 미디어 제공이 준비되지 않았습니다.",
    "disconnected": "연결이 해제됐습니다. 다시 연결하세요.",
}


class MetaError(Exception):
    def __init__(self, code="unknown", *, diagnostics=None):
        self.code = code if code in MESSAGES else "unknown"
        self.diagnostics = {}
        if isinstance(diagnostics, dict):
            for key in ("http_status", "provider_code", "provider_subcode"):
                value = diagnostics.get(key)
                if type(value) is int and 0 <= value <= 2**31 - 1:
                    self.diagnostics[key] = value
            stage = diagnostics.get("stage")
            if stage in {"user_token", "permissions", "pages", "page_token", "instagram"}:
                self.diagnostics["stage"] = stage
        super().__init__(MESSAGES[self.code])


def object_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,39}", value):
        raise MetaError("invalid")
    return value


def fingerprint(value):
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def timestamp(value, *, allow_zero=False):
    if allow_zero and type(value) is int and value == 0:
        return None
    if type(value) is not int or value <= 0:
        raise MetaError("invalid")
    from datetime import UTC

    try:
        return datetime.fromtimestamp(value, UTC)
    except (ValueError, OverflowError, OSError):
        raise MetaError("invalid") from None


@dataclass(frozen=True)
class Grant:
    app_id: str
    page_id: str
    page_name: str
    instagram_id: str | None
    instagram_name: str | None
    scopes: tuple[str, ...]
    tasks: tuple[str, ...]
    user_expires_at: datetime
    page_expires_at: datetime | None
    data_expires_at: datetime
    user_token: SecretStr = field(repr=False)
    page_token: SecretStr = field(repr=False)


def parse_grant(data, app_id, page_id):
    try:
        if data["app_id"] != app_id or data["page_id"] != page_id:
            raise MetaError("identity")
        object_id(app_id)
        object_id(page_id)
        ig = data.get("instagram_id")
        if ig is not None:
            object_id(ig)
        scopes = tuple(data["scopes"])
        tasks = tuple(data["tasks"])
        if not all(isinstance(s, str) for s in (*scopes, *tasks)) or not TASKS.intersection(tasks):
            raise MetaError("permission")
        if not set(SCOPES[:3]) <= set(scopes):
            raise MetaError("permission")
        if ig and not set(SCOPES) <= set(scopes):
            raise MetaError("permission")
        dates = [datetime.fromisoformat(data[k]) for k in ("expires_at", "data_access_expires_at")]
        page_expiry = datetime.fromisoformat(data["page_expires_at"]) if data.get("page_expires_at") else None
        if any(d.tzinfo is None for d in dates + [page_expiry] if d):
            raise MetaError("invalid")
        name = data["page_name"]
        ig_name = data.get("instagram_name")
        if not isinstance(name, str) or not 1 <= len(name) <= 200 or any(ord(c) < 32 for c in name):
            raise MetaError("invalid")
        if ig and (not isinstance(ig_name, str) or not re.fullmatch(r"[A-Za-z0-9_.]{1,30}", ig_name)):
            raise MetaError("invalid")
        tokens = [data["access_token"], data["page_access_token"]]
        if any(
            not isinstance(t, str) or not 1 <= len(t) <= 4096 or any(ord(c) < 33 or ord(c) == 127 for c in t)
            for t in tokens
        ):
            raise MetaError("invalid")
        return Grant(
            app_id,
            page_id,
            name,
            ig,
            ig_name,
            scopes,
            tasks,
            dates[0],
            page_expiry,
            dates[1],
            *(SecretStr(t) for t in tokens),
        )
    except MetaError:
        raise
    except Exception:  # noqa: BLE001 - never expose provider, credential or native exception details
        raise MetaError("invalid") from None
