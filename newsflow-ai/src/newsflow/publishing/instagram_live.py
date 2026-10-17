"""Durable, explicitly approved Instagram preparation, processing checks and publication.

Only public identifiers and reviewed metadata enter SQLite. A network mutation's
intent is committed before sending it; unknown outcomes are never replayed.
"""

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

from .instagram import InstagramPublishResult, InstagramUploadAdapter, InstagramUploadError
from .service import REAL_BLOCKERS, ConflictError, PublishingError, PublishingService, hash_file

_ID = re.compile(r"[1-9][0-9]{0,39}\Z")
_TRANSIENT = {"ig_creating", "ig_uploading", "ig_checking", "ig_publishing", "ig_linking"}
_TERMINAL = {"ig_failed", "ig_unknown", "ig_published", "ig_published_no_link"}
_MESSAGES = {
    "ig_creating": "Instagram 업로드 준비 중",
    "ig_uploading": "Instagram으로 영상 전송 중 · 아직 게시하지 않았습니다.",
    "ig_processing": "영상 처리 중 · 처리 상태를 확인한 뒤 게시할 수 있습니다.",
    "ig_checking": "Instagram 영상 처리 상태 확인 중",
    "ig_ready": "영상 처리 완료 · 대상 계정과 영상을 승인하면 공개 게시합니다.",
    "ig_publishing": "사용자가 승인한 Instagram 공개 게시 중",
    "ig_linking": "Instagram 게시 완료 · 결과 링크 확인 중",
    "ig_published": "Instagram Reels 게시 완료",
    "ig_published_no_link": "Instagram 게시 ID 저장 완료 · 결과 링크는 확인하지 못했습니다. 재게시하지 않습니다.",
    "ig_failed": "Instagram 요청을 완료하지 못했습니다. 자동 재시도하지 않습니다.",
    "ig_status_failed": "영상 처리 상태를 확인하지 못했습니다. 다시 확인하려면 상태 확인을 선택하세요.",
    "ig_unknown": "Instagram 결과 불명 · 계정에서 확인하기 전 재전송하거나 재게시하지 마세요.",
}


class InstagramPublishingService:
    def __init__(self, sessions, outputs_dir: Path, connections, inspector=None, adapter_factory=None):
        self.sessions, self.outputs, self.connections = sessions, outputs_dir, connections
        self.local = PublishingService(sessions, outputs_dir, inspector)
        self.adapter_factory = adapter_factory or InstagramUploadAdapter

    @staticmethod
    def _identifier(value: object) -> str:
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise PublishingError("Instagram 계정 또는 게시 식별자를 확인하지 못했습니다.")
        return value

    def _record(self, session, job: PublishJob) -> dict:
        item = session.scalar(select(PublishEvidence).where(
            PublishEvidence.draft_id == job.draft_id, PublishEvidence.kind == "instagram_state",
        ).order_by(PublishEvidence.id.desc()))
        # A draft can be used for a different connected account later. Do not
        # accidentally read another job's container or approval snapshot.
        if not item or item.payload.get("job_id") != job.id:
            item = next((row for row in session.scalars(select(PublishEvidence).where(
                PublishEvidence.draft_id == job.draft_id, PublishEvidence.kind == "instagram_state",
            ).order_by(PublishEvidence.id.desc())) if row.payload.get("job_id") == job.id), None)
        if not item:
            raise PublishingError("게시 상태 기록이 없어 외부 요청을 차단했습니다.")
        return dict(item.payload)

    def _save(self, session, job: PublishJob, state: str, data: dict, **changes) -> dict:
        data = {**data, **changes, "job_id": job.id, "status": state, "auto_retry": False}
        job.status, job.message = state, _MESSAGES[state]
        job.finished_at = utcnow() if state in _TERMINAL else None
        session.add(PublishEvidence(draft_id=job.draft_id, kind="instagram_state", payload=data))
        session.add(PublishAttempt(job_id=job.id, status=state, message=job.message))
        return data

    def _finish(self, job_id: int, state: str, **changes) -> dict:
        with self.sessions.begin() as session:
            job = session.get(PublishJob, job_id)
            return self._save(session, job, state, self._record(session, job), **changes)

    def _failure(self, job_id: int, error: Exception, *, status_only: bool = False) -> None:
        known = isinstance(error, InstagramUploadError)
        code = error.code if known else "unknown"
        unknown = error.unknown if known else True
        state = ("ig_status_failed" if status_only else
                 "ig_processing" if code == "not_ready" and not unknown else
                 "ig_unknown" if unknown else "ig_failed")
        self._finish(job_id, state, error_code=code)

    def _validate(self, draft_id: int, revision: int) -> tuple[Path, dict]:
        validation_id = self.local.validate(draft_id)
        with self.sessions() as session:
            draft = session.get(PublishDraft, draft_id)
            validation = session.get(PublishValidation, validation_id)
            if not draft or draft.platform != "instagram" or not draft.account_id:
                raise PublishingError("Instagram 게시 초안과 연결 계정을 선택하세요.")
            if draft.revision != revision or validation.draft_revision != revision:
                raise ConflictError("게시 초안이 변경되었습니다. 현재 내용을 다시 검토하세요.")
            ignored = REAL_BLOCKERS | {"duplicate_identity"}
            if any(item["status"] != "pass" for item in validation.results if item["key"] not in ignored):
                raise PublishingError("영상·내용·출처·권리·AI 표시 검토를 먼저 완료하세요.")
            path = self.local.media_path(session.get(RenderJob, draft.render_job_id))
            if hash_file(path) != draft.media_sha256 or validation.media_sha256 != draft.media_sha256:
                raise PublishingError("검토한 MP4 파일이 변경되었습니다.")
            return path, {
                "draft_revision": revision, "validation_id": validation_id, "account_id": draft.account_id,
                "render_job_id": draft.render_job_id, "media_sha256": draft.media_sha256,
                "metadata": {"title": draft.title, "description": draft.description, "hashtags": draft.hashtags,
                             "ai_disclosure": draft.ai_disclosure, "upload_approved": True},
            }

    def _existing(self, draft: PublishDraft) -> int | None:
        with self.sessions() as session:
            for item in session.scalars(select(PublishEvidence).where(
                PublishEvidence.kind == "instagram_state",
            ).order_by(PublishEvidence.id.desc())):
                data = item.payload
                if data.get("account_id") == draft.account_id and data.get("media_sha256") == draft.media_sha256:
                    job = session.get(PublishJob, data.get("job_id"))
                    if job and job.platform == "instagram":
                        return job.id
        return None

    def prepare(self, draft_id: int, revision: int, *, consent: bool = False) -> int:
        if consent is not True:
            raise PublishingError("선택한 계정으로 영상과 게시 정보를 전송하는 데 동의하세요.")
        with self.sessions() as session:
            draft = session.get(PublishDraft, draft_id)
            if not draft or draft.platform != "instagram" or not draft.account_id:
                raise PublishingError("Instagram 게시 초안과 연결 계정을 선택하세요.")
            if draft.revision != revision:
                raise ConflictError("초안이 변경되었습니다. 다시 확인하세요.")
            account = session.get(PlatformAccount, draft.account_id)
            if not account or account.platform != "instagram":
                raise PublishingError("선택한 Instagram 계정이 일치하지 않습니다.")
            existing = self._existing(draft)
            if existing is not None:
                return existing
        path, data = self._validate(draft_id, revision)
        credential = self.connections.access_for_upload(data["account_id"], consent=True)
        ig_id = self._identifier(credential.instagram_id)
        self._identifier(credential.page_id)
        self._identifier(credential.app_id)
        data.update(instagram_id=ig_id, page_id=credential.page_id, app_id=credential.app_id,
                    container_id=None, media_id=None, url=None, upload_approved=True, public_approved=False)
        key = hashlib.sha256(f"real:instagram:{ig_id}:{data['media_sha256']}".encode()).hexdigest()
        try:
            with self.sessions.begin() as session:
                changed = session.execute(update(PublishDraft).where(
                    PublishDraft.id == draft_id, PublishDraft.revision == revision,
                    PublishDraft.account_id == data["account_id"], PublishDraft.media_sha256 == data["media_sha256"],
                ).values(updated_at=PublishDraft.updated_at))
                if changed.rowcount != 1:
                    raise ConflictError("계정 확인 중 초안이 변경되었습니다.")
                existing = session.scalar(select(PublishJob).where(PublishJob.idempotency_key == key))
                if existing:
                    return existing.id
                if hash_file(path) != data["media_sha256"]:
                    raise PublishingError("영상 파일이 변경되어 전송하지 않았습니다.")
                job = PublishJob(draft_id=draft_id, platform="instagram", status="ig_creating",
                                 message=_MESSAGES["ig_creating"], idempotency_key=key)
                session.add(job)
                session.flush()
                job_id = job.id
                self._save(session, job, "ig_creating", data)
        except IntegrityError:
            with self.sessions() as session:
                existing = session.scalar(select(PublishJob.id).where(PublishJob.idempotency_key == key))
                if existing is not None:
                    return existing
            raise PublishingError("게시 기록을 보존하지 못해 전송하지 않았습니다.") from None
        try:
            adapter = self.adapter_factory()
            container = adapter.create_container(data["metadata"], credential.bundle, ig_id)
            container_id = self._identifier(container.container_id)
            # Commit the returned container before the MP4 request. A crash can
            # never cause an automatic second container or second upload.
            self._finish(job_id, "ig_uploading", container_id=container_id)
            adapter.upload(path, credential.bundle, container_id, data["media_sha256"])
            self._finish(job_id, "ig_processing", error_code=None)
        except Exception as error:  # noqa: BLE001 - provider text/credentials never enter logs/DB
            self._failure(job_id, error)
        return job_id

    def _claim(self, job_id: int, allowed: set[str], state: str, *, expected: dict | None = None) -> dict | None:
        with self.sessions.begin() as session:
            claimed = session.execute(update(PublishJob).where(
                PublishJob.id == job_id, PublishJob.platform == "instagram", PublishJob.status.in_(allowed),
            ).values(status=state, message=_MESSAGES[state]))
            job = session.get(PublishJob, job_id)
            if not job or job.platform != "instagram":
                raise PublishingError("Instagram 게시 작업이 없습니다.")
            if claimed.rowcount != 1:
                return None
            data = self._record(session, job)
            if expected is not None:
                draft = session.get(PublishDraft, job.draft_id)
                if not draft or any((
                    draft.revision != expected["draft_revision"], draft.account_id != expected["account_id"],
                    draft.media_sha256 != expected["media_sha256"],
                )):
                    raise ConflictError("게시 직전 초안이 변경되었습니다. 다시 검토하세요.")
            return self._save(session, job, state, data,
                              **({"public_approved": True} if state == "ig_publishing" else {}))

    def _credential(self, data: dict):
        credential = self.connections.access_for_upload(data["account_id"], consent=True)
        if any(getattr(credential, name) != data[name] for name in ("instagram_id", "page_id", "app_id")):
            raise PublishingError("준비 당시의 Instagram 계정·페이지·앱과 달라 실행하지 않았습니다.")
        return credential

    def check(self, job_id: int, *, consent: bool = False) -> int:
        if consent is not True:
            raise PublishingError("Instagram 영상 처리 상태를 확인하려면 동의하세요.")
        data = self._claim(job_id, {"ig_processing", "ig_ready", "ig_status_failed"}, "ig_checking")
        if data is None:
            return job_id
        try:
            credential = self._credential(data)
            status = self.adapter_factory().status(credential.bundle, self._identifier(data["container_id"]))
            state = {"IN_PROGRESS": "ig_processing", "FINISHED": "ig_ready",
                     "ERROR": "ig_failed", "EXPIRED": "ig_failed", "PUBLISHED": "ig_unknown"}.get(status)
            if state is None:
                raise InstagramUploadError("unknown")
            self._finish(job_id, state, processing_status=status, error_code=None)
        except Exception as error:  # noqa: BLE001
            self._failure(job_id, error, status_only=True)
        return job_id

    def publish(
        self, job_id: int, *, consent: bool = False, public_consent: bool = False,
        account_id: int | None = None, media_sha256: str | None = None,
    ) -> int:
        if consent is not True or public_consent is not True:
            raise PublishingError("선택한 Instagram 계정과 영상의 공개 게시를 명시적으로 승인하세요.")
        with self.sessions() as session:
            job = session.get(PublishJob, job_id)
            if not job or job.platform != "instagram":
                raise PublishingError("Instagram 게시 작업이 없습니다.")
            data = self._record(session, job)
            if account_id != data["account_id"] or media_sha256 != data["media_sha256"]:
                raise PublishingError("승인한 대상 계정과 영상 파일이 게시 준비 기록과 일치하지 않습니다.")
            if job.status != "ig_ready":
                return job_id
            draft_id = job.draft_id
        _path, current = self._validate(draft_id, data["draft_revision"])
        if any(current[name] != data[name] for name in ("account_id", "media_sha256", "metadata")):
            raise ConflictError("준비한 게시 내용이 변경되었습니다. 다시 검토하세요.")
        data = self._claim(job_id, {"ig_ready"}, "ig_publishing", expected=data)
        if data is None:
            return job_id
        try:
            credential = self._credential(data)
            adapter = self.adapter_factory()
            # Adapter rechecks FINISHED immediately before its single publish POST.
            media_id = adapter.publish(credential.bundle, data["instagram_id"], data["container_id"],
                                       public_approved=True)
            media_id = self._identifier(media_id)
            self._finish(job_id, "ig_linking", media_id=media_id, public_approved=True, error_code=None)
        except Exception as error:  # noqa: BLE001
            self._failure(job_id, error)
            return job_id
        try:
            result = adapter.result(credential.bundle, media_id, data["instagram_id"])
            if (type(result) is not InstagramPublishResult or result.media_id != media_id
                    or result.account_id != data["instagram_id"]):
                raise InstagramUploadError("unknown")
            # Never persist a raw URL returned by an arbitrary/malformed provider.
            if not re.fullmatch(r"https://www\.instagram\.com/(?:reel|p)/[A-Za-z0-9_-]+/", result.url):
                raise InstagramUploadError("unknown")
            self._finish(job_id, "ig_published", url=result.url)
        except Exception:  # noqa: BLE001 - a link lookup failure must not erase known publication success
            self._finish(job_id, "ig_published_no_link", error_code="result_lookup_failed")
        return job_id

    def results(self) -> list[dict]:
        """Local status only. Page loads never poll Meta or refresh credentials."""
        with self.sessions() as session:
            output = []
            for job in session.scalars(select(PublishJob).where(PublishJob.platform == "instagram")
                                       .order_by(PublishJob.id.desc()).limit(100)):
                try:
                    data = self._record(session, job)
                except PublishingError:
                    continue  # Legacy simulated/preparation records are not actual external upload jobs.
                output.append({**data, "id": job.id, "job_id": job.id, "draft_id": job.draft_id,
                               "status": job.status, "message": job.message, "video_url": data.get("url"),
                               "can_check": job.status in {"ig_processing", "ig_ready", "ig_status_failed"},
                               "can_publish": job.status == "ig_ready"})
            return output

    def recover(self) -> int:
        """Interrupted mutations remain blocked. No network or automatic state advancement."""
        with self.sessions.begin() as session:
            jobs = list(session.scalars(select(PublishJob).where(
                PublishJob.platform == "instagram", PublishJob.status.in_(_TRANSIENT),
            )))
            for job in jobs:
                data = self._record(session, job)
                state = "ig_published_no_link" if job.status == "ig_linking" and data.get("media_id") else "ig_unknown"
                self._save(session, job, state, data, error_code="interrupted")
            return len(jobs)
