"""Safe errors and immutable Phase 4B-1 execution boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass

FIXED_REDIRECT = "http://127.0.0.1:8765/oauth/callback"
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
_ACCOUNT = re.compile(r"(?:youtube|instagram):[1-9][0-9]{0,18}\Z")
_MESSAGES = {
    "blocked": "Phase 4B-1에서는 실제 계정 로그인·토큰 교환·회수 요청이 차단됩니다.",
    "invalid_input": "인증 준비 입력을 확인하세요.",
    "callback_invalid": "인증 응답을 안전하게 검증하지 못했습니다.",
    "reused": "인증 요청이 없거나 이미 처리되었습니다. 새 요청을 준비하세요.",
    "expired": "인증 요청 또는 인증정보가 만료되었습니다.",
    "state_mismatch": "인증 요청 상관관계가 일치하지 않습니다.",
    "redirect_mismatch": "등록된 로컬 응답 주소가 일치하지 않습니다.",
    "account_mismatch": "인증 요청의 대상 계정이 일치하지 않습니다.",
    "cancelled": "합성 인증이 취소되었습니다. 실제 계정 연결은 없습니다.",
    "provider_error": "합성 인증 처리에 실패했습니다. 새 요청을 준비하세요.",
    "credential_error": "합성 인증정보를 안전하게 사용할 수 없습니다.",
    "revision_conflict": "다른 계정 작업이 반영되었습니다. 현재 상태를 다시 확인하세요.",
    "scope_mismatch": "합성 인증 권한이 요청한 범위와 일치하지 않습니다.",
}


class OAuthError(Exception):
    def __init__(self, code: str = "callback_invalid") -> None:
        self.code = code if code in _MESSAGES else "callback_invalid"
        super().__init__(_MESSAGES[self.code])


class OAuthBlocked(OAuthError):
    def __init__(self) -> None:
        super().__init__("blocked")


def account_key_valid(value: str) -> bool:
    return isinstance(value, str) and bool(_ACCOUNT.fullmatch(value))


@dataclass(frozen=True)
class OAuthPolicy:
    feature_enabled: bool = False
    user_approved: bool = False

    @property
    def allows_real(self) -> bool:
        # Neither environment flags nor HTTP input can authorize this phase boundary.
        return False
