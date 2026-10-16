"""Dated official schema checks for the existing four-field adapter, reviewed 2026-10-16 KST.

No remote discovery, price defaults or new model adapters. Unknown user-entered models retain
Phase 5D's explicit user-confirmation policy and are NOT VERIFIED in the local preflight.
"""
from __future__ import annotations

# path: (allowed whole seconds, resolutions). Evidence: phase5d1_higgsfield_verification.md.
CONTRACTS = {
    "kling-video/v3.0-turbo/text-to-video": (tuple(range(3, 16)), ("720p", "1080p")),
    "wan/v2.7/text-to-video": (tuple(range(2, 16)), ("720p", "1080p")),
    "alibaba/wan-3.0/text-to-video": (tuple(range(2, 31)), ("480p", "720p", "1080p")),
    "alibaba/wan-3.0-prime/text-to-video": (tuple(range(2, 31)), ("480p", "720p", "1080p")),
    "pixverse/v6/text-to-video": (tuple(range(1, 16)), ("360p", "540p", "720p", "1080p")),
    "lightricks/ltx-2.5/text-to-video/fast": ((6, 8, 10), ("720p", "1080p", "2k", "4k")),
}
INCOMPATIBLE = {"kling-video/v2.6/pro/text-to-video", "wan/v2.6/text-to-video"}


def check_model_contract(path: str, durations: tuple[int, ...], resolution: str) -> tuple[str, str]:
    if path in INCOMPATIBLE:
        return "FAIL", "공식 스키마와 현재 공통 요청 형식이 달라 제출할 수 없습니다. 지원 모델을 선택하세요."
    if path not in CONTRACTS:
        return "NOT VERIFIED", "이 모델의 최신 요청 형식·9:16 지원을 별도로 확인해야 합니다."
    seconds, resolutions = CONTRACTS[path]
    if not durations or any(type(d) is not int or d not in seconds for d in durations) or resolution not in resolutions:
        return "FAIL", "등록한 길이 또는 해상도가 확인한 공식 스키마와 다릅니다. 모델 설정을 확인하세요."
    return "PASS", "2026-10-16 공식 스키마와 공통 요청 필드·길이·해상도·9:16이 일치합니다. 실제 계정 동작은 미검증입니다."
