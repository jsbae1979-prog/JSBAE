"""Approved YouTube uploads through existing drafts, reviews and durable job records."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

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

from .service import REAL_BLOCKERS, ConflictError, PublishingError, PublishingService, hash_file
from .youtube import YouTubeUploadAdapter, YouTubeUploadError, YouTubeUploadResult

_PENDING = "uploading"
_CHANNEL = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")


class LivePublishingService:
    def __init__(self, sessions, outputs_dir: Path, connections, inspector=None, adapter_factory=None) -> None:
        self.sessions, self.outputs, self.connections = sessions, outputs_dir, connections
        self.local = PublishingService(sessions, outputs_dir, inspector)
        self.adapter_factory = adapter_factory or YouTubeUploadAdapter

    def _existing_draft_job(self, draft: PublishDraft) -> int | None:
        with self.sessions() as session:
            evidence = session.scalars(select(PublishEvidence).where(
                PublishEvidence.draft_id == draft.id, PublishEvidence.kind == "youtube_upload_request",
            ).order_by(PublishEvidence.id.desc()))
            for item in evidence:
                data = item.payload
                if data.get("account_id") == draft.account_id and data.get("media_sha256") == draft.media_sha256:
                    job = session.get(PublishJob, data.get("job_id"))
                    if job and job.platform == "youtube":
                        return job.id
        return None

    def execute(
        self, draft_id: int, revision: int, privacy: str = "private", made_for_kids: bool = False,
        consent: bool = False, public_consent: bool = False,
    ) -> int:
        if consent is not True or (privacy != "private" and public_consent is not True):
            raise PublishingError("선택한 채널·영상·공개 범위에 대한 업로드 동의가 필요합니다.")
        if privacy not in {"private", "unlisted", "public"} or type(made_for_kids) is not bool:
            raise PublishingError("공개 상태와 아동용 영상 여부를 확인하세요.")
        with self.sessions() as session:
            draft = session.get(PublishDraft, draft_id)
            if not draft or draft.platform != "youtube" or not draft.account_id:
                raise PublishingError("YouTube 게시 초안과 연결할 채널을 선택하세요.")
            if draft.revision != revision:
                raise ConflictError("초안이 변경되었습니다. 현재 영상·제목·공개 범위를 다시 확인하세요.")
            existing = self._existing_draft_job(draft)
            if existing is not None:
                return existing
            account = session.get(PlatformAccount, draft.account_id)
            if not account or account.platform != "youtube":
                raise PublishingError("선택한 채널이 초안의 게시 대상과 일치하지 않습니다.")
        # Retain all existing local media, rights, source and human review gates.
        validation_id = self.local.validate(draft_id)
        with self.sessions() as session:
            validation = session.get(PublishValidation, validation_id)
            current = session.get(PublishDraft, draft_id)
            if current.revision != revision or validation.draft_revision != revision:
                raise ConflictError("검사 중 초안이 변경되었습니다. 다시 확인하세요.")
            ignored = REAL_BLOCKERS | {"duplicate_identity"}
            if any(row["status"] != "pass" for row in validation.results if row["key"] not in ignored):
                raise PublishingError("영상·내용·출처·권리·AI 표시 검토를 마친 뒤 업로드하세요.")
            path = self.local.media_path(session.get(RenderJob, current.render_job_id))
            if validation.media_sha256 != current.media_sha256 or hash_file(path) != current.media_sha256:
                raise PublishingError("검토한 MP4가 변경되었습니다. 다시 확인하세요.")
            payload = {
                "title": current.title, "description": current.description, "hashtags": current.hashtags,
                "ai_disclosure": current.ai_disclosure, "privacy": privacy, "made_for_kids": made_for_kids,
                "upload_approved": True, "public_approved": public_consent is True,
            }
            media_hash, account_id, render_job_id = current.media_sha256, current.account_id, current.render_job_id
        # Explicit upload consent is also consent for necessary expiry refresh/channel revalidation.
        # The connection service preserves failed/unknown credential operations without retrying them.
        bundle, channel_id = self.connections.access_for_upload(account_id, consent=True)
        if not isinstance(channel_id, str) or not _CHANNEL.fullmatch(channel_id):
            raise PublishingError("연결한 YouTube 채널을 확인하지 못했습니다.")
        key = hashlib.sha256(f"real:youtube:{channel_id}:{media_hash}".encode()).hexdigest()
        try:
            with self.sessions.begin() as session:
                # Obtain SQLite's write lock before checking the unique upload identity/revision.
                changed = session.execute(update(PublishDraft).where(
                    PublishDraft.id == draft_id, PublishDraft.revision == revision,
                    PublishDraft.account_id == account_id, PublishDraft.media_sha256 == media_hash,
                ).values(updated_at=PublishDraft.updated_at))
                if changed.rowcount != 1:
                    raise ConflictError("채널 확인 중 초안이 변경되었습니다. 다시 확인하세요.")
                existing = session.scalar(select(PublishJob).where(PublishJob.idempotency_key == key))
                if existing:
                    return existing.id
                if hash_file(path) != media_hash:
                    raise PublishingError("업로드 전 영상 파일이 변경되었습니다.")
                job = PublishJob(draft_id=draft_id, platform="youtube", status=_PENDING,
                                 message="YouTube 업로드 중", idempotency_key=key)
                session.add(job)
                session.flush()
                identifier = job.id
                attempt = PublishAttempt(job_id=identifier, status=_PENDING, message="사용자가 승인한 업로드")
                session.add(attempt)
                session.flush()
                attempt_id = attempt.id
                session.add(PublishEvidence(draft_id=draft_id, kind="youtube_upload_request", payload={
                    "job_id": identifier, "draft_revision": revision, "validation_id": validation_id,
                    "account_id": account_id, "channel_id": channel_id, "render_job_id": render_job_id,
                    "media_sha256": media_hash, "privacy": privacy, "made_for_kids": made_for_kids,
                    "metadata": payload, "user_approved": True, "auto_retry": False,
                }))
        except IntegrityError:
            with self.sessions() as session:
                existing = session.scalar(select(PublishJob.id).where(PublishJob.idempotency_key == key))
                if existing is not None:
                    return existing
            raise PublishingError("업로드 기록을 보존하지 못해 전송하지 않았습니다.") from None
        result, error_code = None, None
        try:
            result = self.adapter_factory().upload(path, payload, bundle, channel_id, media_hash)
            if (
                type(result) is not YouTubeUploadResult
                or not re.fullmatch(r"[A-Za-z0-9_-]{11}", result.video_id)
                or result.url != "https://www.youtube.com/watch?v=" + result.video_id
                or result.privacy not in {"private", "unlisted", "public"}
            ):
                raise YouTubeUploadError("unknown")
            status = "uploaded"
            message = "YouTube 업로드 완료 · 플랫폼 영상 처리 상태는 YouTube Studio에서 확인하세요."
            if result.processing_status in {"failed", "rejected", "deleted"}:
                status = "failed"
                message = "YouTube가 업로드된 영상의 처리를 완료하지 못했습니다. 결과 링크를 확인하세요."
        except YouTubeUploadError as error:
            status = "unknown" if error.unknown else "failed"
            message, error_code = str(error), error.code
        except Exception:  # noqa: BLE001 - preserve unknown outcome without raw provider details
            status, message, error_code = "unknown", str(YouTubeUploadError("unknown")), "unknown"
        with self.sessions.begin() as session:
            job = session.get(PublishJob, identifier)
            job.status, job.message, job.finished_at = status, message, utcnow()
            attempt = session.get(PublishAttempt, attempt_id)
            attempt.status, attempt.message = status, message
            session.add(PublishEvidence(draft_id=draft_id, kind="youtube_upload_result", payload={
                "job_id": identifier, "status": status, "error_code": error_code,
                "video_id": result.video_id if result else None, "url": result.url if result else None,
                "privacy": result.privacy if result else privacy,
                "processing_status": result.processing_status if result else None,
                "account_id": account_id, "channel_id": channel_id, "media_sha256": media_hash,
                "auto_retry": False,
            }))
        return identifier

    def results(self) -> list[dict]:
        """Read stored public identifiers only; opening a page makes no provider request."""
        with self.sessions() as session:
            results = []
            seen = set()
            for item in session.scalars(select(PublishEvidence).where(
                PublishEvidence.kind == "youtube_upload_result",
            ).order_by(PublishEvidence.id.desc()).limit(100)):
                data = item.payload
                job_id = data.get("job_id")
                if job_id in seen:
                    continue
                job, draft = session.get(PublishJob, job_id), session.get(PublishDraft, item.draft_id)
                if not job or not draft:
                    continue
                seen.add(job_id)
                results.append({"draft_id": item.draft_id, **data, "id": job_id,
                                "render_job_id": draft.render_job_id, "status": job.status,
                                "message": job.message, "video_url": data.get("url")})
            return results

    def recover(self) -> int:
        """A crashed upload stays unknown across restart; no POST/PUT is replayed."""
        with self.sessions.begin() as session:
            jobs = list(session.scalars(select(PublishJob).where(
                PublishJob.platform == "youtube", PublishJob.status == _PENDING,
            )))
            for job in jobs:
                job.status, job.message, job.finished_at = "unknown", str(YouTubeUploadError("unknown")), utcnow()
                session.execute(update(PublishAttempt).where(
                    PublishAttempt.job_id == job.id, PublishAttempt.status == _PENDING,
                ).values(status="unknown", message=job.message))
                session.add(PublishEvidence(draft_id=job.draft_id, kind="youtube_upload_result", payload={
                    "job_id": job.id, "status": "unknown", "error_code": "interrupted",
                    "video_id": None, "url": None, "auto_retry": False,
                }))
            return len(jobs)
