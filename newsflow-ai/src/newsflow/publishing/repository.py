"""Only approved offline simulation. UNIQUE identity reservation before adapter calls."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import (
    PlatformAccount,
    PublishAttempt,
    PublishDraft,
    PublishEvidence,
    PublishJob,
    PublishValidation,
    RenderJob,
    utcnow,
)

from .adapters import ExternalPublishingDisabled, FakePublisher, Publisher
from .service import REAL_BLOCKERS, PublishingError, PublishingService, hash_file, identity


class PublishJobRepository:
    def __init__(self, sessions: sessionmaker[Session], outputs_dir: Path | None = None) -> None:
        self.sessions = sessions
        self.outputs = outputs_dir or Path(sessions.kw["bind"].url.database).parent / "outputs/videos"

    def simulate(self, draft_id: int, publisher: Publisher, approved: bool = False) -> int:
        if not isinstance(publisher, FakePublisher):
            raise ExternalPublishingDisabled()
        if not approved:
            raise PublishingError("Fake 시뮬레이션에도 명시적인 승인 인수가 필요합니다.")
        with self.sessions() as session:
            draft = session.get(PublishDraft, draft_id)
            if not draft:
                raise PublishingError("게시 초안이 없습니다.")
            key = identity(draft)
            existing = session.scalar(select(PublishJob).where(PublishJob.idempotency_key == key))
            if existing:
                return existing.id  # Even failed/unknown/changed-title retries never call again.
            validation = session.scalar(
                select(PublishValidation)
                .where(PublishValidation.draft_id == draft_id)
                .order_by(PublishValidation.id.desc())
            )
            if (
                not validation
                or validation.draft_revision != draft.revision
                or any(r["status"] != "pass" for r in validation.results if r["key"] not in REAL_BLOCKERS)
            ):
                raise PublishingError("수정한 초안을 다시 검증하고 로컬 준비 항목을 확인하세요.")
            account = session.get(PlatformAccount, draft.account_id) if draft.account_id else None
            if account and account.status in {"expired", "revoked", "error"}:
                raise PublishingError("계정 인증 만료·취소·오류 상태에서는 실행할 수 없습니다.")
            job = session.get(RenderJob, draft.render_job_id)
            try:
                path = PublishingService(self.sessions, self.outputs).media_path(job)
                if (
                    hash_file(path) != validation.media_sha256
                    or validation.media_sha256 != draft.media_sha256
                ):
                    raise ValueError
            except Exception:  # noqa: BLE001 - sanitized integrity guard
                raise PublishingError("검증 후 영상이 변경되었거나 접근할 수 없습니다.") from None
            payload = {
                "platform": draft.platform,
                "title": draft.title,
                "description": draft.description,
                "hashtags": draft.hashtags,
                "ai_disclosure": draft.ai_disclosure,
                "media_sha256": draft.media_sha256,
                "simulation_only": True,
                "account_id": draft.account_id,
            }
            platform = draft.platform
            approved_revision = draft.revision
            validation_id = validation.id
        try:
            with self.sessions.begin() as session:
                reserved = session.execute(
                    update(PublishDraft)
                    .where(PublishDraft.id == draft_id, PublishDraft.revision == approved_revision)
                    .values(updated_at=PublishDraft.updated_at)
                    .execution_options(synchronize_session=False)
                )
                if reserved.rowcount != 1:
                    raise PublishingError("검증 후 초안이 변경되었습니다. 새 버전을 다시 검증하세요.")
                job = PublishJob(
                    draft_id=draft_id,
                    platform=platform,
                    status="simulating",
                    message="Fake 시뮬레이션 진행 중; 실제 게시 아님",
                    idempotency_key=key,
                )
                session.add(job)
                session.flush()
                identifier = job.id
                attempt = PublishAttempt(
                    job_id=identifier, status="simulating", message="외부 호출 없는 Fake Adapter"
                )
                session.add(attempt)
                session.flush()
                attempt_id = attempt.id
                session.add(
                    PublishEvidence(
                        draft_id=draft_id,
                        kind="simulation_request",
                        payload={
                            "job_id": identifier,
                            "draft_revision": approved_revision,
                            "validation_id": validation_id,
                            "metadata_snapshot": payload,
                            "approved_fake_only": True,
                        },
                    )
                )
        except IntegrityError:
            with self.sessions() as session:
                return session.scalar(select(PublishJob.id).where(PublishJob.idempotency_key == key))
        try:
            result = publisher.publish(payload, key, approved=True)
            status = (
                result.status if result.status in {"simulated", "unknown", "failed", "expired"} else "unknown"
            )
        except Exception:  # noqa: BLE001 - unknown outcome; no retry and no exception text
            status = "unknown"
        messages = {
            "simulated": "Fake 게시 시뮬레이션 완료; 실제 SNS 성공 아님",
            "unknown": "결과 불명; 자동 재시도 금지",
            "failed": "Fake 실행 실패; 자동 재시도 없음",
            "expired": "Fake 인증 만료; 실제 OAuth 호출 없음",
        }
        with self.sessions.begin() as session:
            job = session.get(PublishJob, identifier)
            job.status, job.message, job.finished_at = status, messages[status], utcnow()
            attempt = session.get(PublishAttempt, attempt_id)
            attempt.status, attempt.message = status, messages[status]
            session.add(
                PublishEvidence(
                    draft_id=draft_id,
                    kind="simulation",
                    payload={
                        "job_id": identifier,
                        "status": status,
                        "idempotency_key": key,
                        "real_api_calls": 0,
                        "auto_retry": False,
                    },
                )
            )
        return identifier

    def recover(self) -> None:
        with self.sessions.begin() as session:
            for job in session.scalars(select(PublishJob).where(PublishJob.status == "simulating")):
                job.status, job.message, job.finished_at = (
                    "unknown",
                    "중단되어 결과 불명; 자동 재시도 금지",
                    utcnow(),
                )
                for attempt in session.scalars(
                    select(PublishAttempt).where(
                        PublishAttempt.job_id == job.id, PublishAttempt.status == "simulating"
                    )
                ):
                    attempt.status, attempt.message = "unknown", job.message
