"""Explicit local-only inspection. Never creates a provider, reserves money or sends requests."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import VideoAIUsage
from newsflow.video.engine import FFmpegAdapter, RenderError

from .keys import VideoAIKeyStore
from .model_contracts import check_model_contract
from .settings import ledger_valid, list_models, read_settings, readiness


def inspect_setup(sessions: sessionmaker[Session], keys: VideoAIKeyStore) -> dict:
    checks = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    settings = read_settings(sessions)
    gate = readiness(sessions, keys)
    add("승인과 비용 한도", "PASS" if gate["ready"] else "FAIL",
        "저장된 조건을 통과했습니다. 장면별 비용 확인은 별도로 필요합니다." if gate["ready"] else " ".join(gate["reasons"]))
    try:
        key = VideoAIKeyStore.validate(keys.key())
        # Current official docs specify an ID and secret; legacy single tokens remain unverified.
        paired = len(key.split(":")) == 2 and all(key.split(":"))
        add("키 형식", "PASS" if paired else "NOT VERIFIED",
            "공식 문서의 ID:비밀값 형식입니다. 실제 인증은 실행하지 않았습니다." if paired else
            "단일 키의 실제 인증 호환성은 확인되지 않았습니다. 발급 화면과 공식 인증 문서를 확인하세요.")
    except Exception:  # noqa: BLE001 - a vault/OS error may contain secret material
        add("키 형식", "FAIL", "키를 안전하게 읽거나 형식을 확인하지 못했습니다. 키 값을 공유하지 마세요.")
    models = list_models(sessions)
    if not models:
        add("모델", "FAIL", "공식 문서를 확인한 모델·단가·길이·해상도를 등록하세요.")
    for index, model in enumerate(models, 1):
        status, detail = check_model_contract(model.path, model.durations, model.resolution)
        if not model.usable:
            status, detail = "FAIL", "모델의 문서 확인 또는 유효한 초당 단가가 없습니다."
        add(f"등록 모델 {index}", status, detail)
    with sessions() as session:
        valid = ledger_valid(session)
        counts = Counter(session.scalars(select(VideoAIUsage.status)))
    add("비용 예약 기록", "PASS" if valid else "FAIL",
        "예약·전송·결과 불명 기록을 보존합니다. 실제 청구·환불 금액은 조회하지 않았습니다." if valid else
        "비용 기록 형식이 올바르지 않아 새 제출이 차단됩니다. 원본 DB를 보존하세요.")
    try:
        FFmpegAdapter().check()
        add("영상 도구", "PASS", "FFmpeg와 ffprobe를 확인했습니다. 받은 클립은 별도 안전 다운로드·영상 검사를 거칩니다.")
    except (RenderError, OSError):
        add("영상 도구", "FAIL", "FFmpeg와 ffprobe 설치·PATH를 확인하세요.")
    return {
        "checked_at_kst": datetime.now(timezone(timedelta(hours=9))).isoformat(),
        "checks": checks, "local_ready": all(c["status"] == "PASS" for c in checks),
        "mode": "LOCAL_ONLY", "external_api_calls": 0, "new_reservations": 0,
        "submit_auto_retry": False, "actual_billing": "NOT VERIFIED", "actual_service": "NOT VERIFIED",
        "usage_counts": {status: counts[status] for status in
                         ("reserved", "submitted", "completed", "failed", "unknown", "canceled", "not_sent")},
        "currency": settings.currency,
    }
