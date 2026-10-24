"""Durable additional-platform delivery using existing drafts and validation.

Production credentials are intentionally unavailable. Synthetic injection exercises
all journal/adapter steps and records simulated completion, never real success.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select, update

from newsflow.db.models import (
    PlatformAccount,
    PublishAttempt,
    PublishDraft,
    PublishEvidence,
    PublishJob,
    PublishValidation,
    RenderJob,
    VideoProject,
    utcnow,
)

from .platforms import REQUIREMENTS, FacebookPublisher, PlatformBlocked, TikTokPublisher
from .service import REAL_BLOCKERS, PublishingError, PublishingService, hash_file
from .youtube import _locked_media


class ExtendedPublishingService:
    def __init__(
        self, sessions, outputs: Path, platform: str, *, inspector=None, synthetic_binding=None, adapter=None
    ):
        if platform not in REQUIREMENTS:
            raise ValueError("Unsupported platform")
        self.sessions, self.platform, self.outputs = sessions, platform, outputs
        self.local = PublishingService(sessions, outputs, inspector)
        self.binding = synthetic_binding
        self.adapter = adapter or (TikTokPublisher() if platform == "tiktok" else FacebookPublisher())

    def status(self) -> dict:
        with self.sessions() as session:
            accounts = [
                {
                    "id": a.id,
                    "label": a.label,
                    "ready": self.binding is not None,
                    "synthetic": self.binding is not None,
                }
                for a in session.scalars(
                    select(PlatformAccount).where(PlatformAccount.platform == self.platform)
                )
            ]
        return {"accounts": accounts, "blocked": True, **REQUIREMENTS[self.platform]}

    def account_identity(self, account_id: int) -> str | None:
        if self.binding is None:
            return None
        grant = self.binding(account_id)
        if (
            grant.get("synthetic") is not True
            or grant.get("account_id") != account_id
            or grant.get("platform") != self.platform
        ):
            raise PlatformBlocked("플랫폼 계정 바인딩을 확인하지 못했습니다.")
        from .platforms import identifier

        return identifier(grant.get("identity"))

    def validate_options(self, options: dict) -> None:
        allowed = (
            {
                "privacy",
                "music_consent",
                "branded",
                "brand_consent",
                "own_brand",
                "allow_comment",
                "allow_duet",
                "allow_stitch",
            }
            if self.platform == "tiktok"
            else {"public_consent"}
        )
        if not isinstance(options, dict) or set(options) - allowed:
            raise PublishingError("플랫폼별 승인 항목이 올바르지 않습니다.")
        if any(type(v) is not bool for k, v in options.items() if k != "privacy"):
            raise PublishingError("승인 항목은 명시적으로 선택해야 합니다.")
        if self.platform == "facebook" and options.get("public_consent") is not True:
            raise PublishingError("Facebook Page 공개 게시에 동의하세요.")
        if self.platform == "tiktok" and (
            options.get("privacy")
            not in {"SELF_ONLY", "PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR"}
            or options.get("music_consent") is not True
        ):
            raise PublishingError("TikTok 공개 범위를 직접 선택하고 음악 이용 조건에 동의하세요.")

    def execute(
        self,
        draft_id: int,
        revision: int,
        *,
        consent: bool = False,
        options: dict | None = None,
        expected_identity: str | None = None,
    ) -> int:
        options = options or {}
        if consent is not True:
            raise PublishingError("이번 영상의 플랫폼 전송 승인이 필요합니다.")
        self.validate_options(options)
        if self.binding is None:
            raise PlatformBlocked("실계정 게시가 차단되어 있습니다. 앱 심사와 별도 연결 승인이 필요합니다.")
        validation_id = self.local.validate(draft_id)
        with self.sessions() as session:
            draft = session.get(PublishDraft, draft_id)
            validation = session.get(PublishValidation, validation_id)
            if (
                not draft
                or draft.platform != self.platform
                or draft.revision != revision
                or validation.draft_revision != revision
            ):
                raise PublishingError("게시 대상 또는 검토 버전이 변경되었습니다.")
            if any(
                r["status"] != "pass"
                for r in validation.results
                if r["key"] not in REAL_BLOCKERS | {"duplicate_identity"}
            ):
                raise PublishingError("영상·내용·출처·권리를 먼저 검토하세요.")
            account = session.get(PlatformAccount, draft.account_id)
            remote = self.binding(account.id) if account and account.platform == self.platform else None
            if (
                not isinstance(remote, dict)
                or remote.get("synthetic") is not True
                or remote.get("account_id") != draft.account_id
                or remote.get("platform") != self.platform
                or expected_identity is None
                or remote.get("identity") != expected_identity
                or not set(REQUIREMENTS[self.platform]["scopes"]) <= set(remote.get("scopes", []))
            ):
                raise PlatformBlocked("계정 격리·권한·합성 인증 경계를 확인하지 못했습니다.")
            if self.platform == "facebook" and "CREATE_CONTENT" not in remote.get("tasks", []):
                raise PlatformBlocked("Facebook Page 콘텐츠 제작 권한이 필요합니다.")
            path = self.local.media_path(session.get(RenderJob, draft.render_job_id))
            if hash_file(path) != draft.media_sha256 or validation.media_sha256 != draft.media_sha256:
                raise PublishingError("검토한 영상이 변경되었습니다.")
            render = session.get(RenderJob, draft.render_job_id)
            duration = session.get(VideoProject, render.project_id).duration
            snapshot = {
                "revision": revision,
                "account_id": draft.account_id,
                "hash": draft.media_sha256,
                "caption": "\n".join(
                    [draft.title, draft.description, " ".join("#" + t for t in draft.hashtags)]
                ),
                "ai": draft.ai_disclosure == "disclose",
            }
        key = hashlib.sha256(
            f"extension:{self.platform}:{remote['identity']}:{snapshot['hash']}".encode()
        ).hexdigest()
        with self.sessions.begin() as session:
            changed = session.execute(
                update(PublishDraft)
                .where(
                    PublishDraft.id == draft_id,
                    PublishDraft.revision == revision,
                    PublishDraft.account_id == snapshot["account_id"],
                    PublishDraft.media_sha256 == snapshot["hash"],
                )
                .values(updated_at=PublishDraft.updated_at)
            )
            if changed.rowcount != 1:
                raise PublishingError("게시 직전 검토 내용이 변경되었습니다.")
            existing = session.scalar(select(PublishJob).where(PublishJob.idempotency_key == key))
            if existing:
                return existing.id  # Includes unknown/failed/waiting; never repeat a submit.
            if self.platform == "facebook":
                recent = session.scalar(
                    select(func.count())
                    .select_from(PublishJob)
                    .join(PublishDraft)
                    .where(
                        PublishJob.platform == "facebook",
                        PublishDraft.account_id == snapshot["account_id"],
                        PublishJob.created_at >= utcnow() - timedelta(hours=24),
                    )
                )
                if recent >= 30:
                    raise PublishingError(
                        "Facebook Page의 24시간 게시 준비 한도에 도달했습니다. 자동 재시도하지 않습니다."
                    )
            job = PublishJob(
                draft_id=draft_id,
                platform=self.platform,
                status="ext_running",
                message="합성 플랫폼 전송 검증 중",
                idempotency_key=key,
            )
            session.add(job)
            session.flush()
            job_id = job.id
            session.add(
                PublishEvidence(
                    draft_id=draft_id,
                    kind="extension_request",
                    payload={
                        "job_id": job_id,
                        "synthetic": True,
                        "identity": remote["identity"],
                        "account_id": snapshot["account_id"],
                        "media_sha256": snapshot["hash"],
                        "options": options,
                        "revision": revision,
                    },
                )
            )
        try:
            with _locked_media(path) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != snapshot["hash"]:
                    raise PublishingError("검토한 파일이 변경되었습니다.")
                stream.seek(0)
                size = path.stat().st_size
                upload = self.adapter.initialize(
                    account=remote["identity"],
                    caption=snapshot["caption"],
                    size=size,
                    duration=duration,
                    options=options,
                    ai_generated=snapshot["ai"],
                )
                # Never persist upload URLs containing bearer capabilities.
                self._record(job_id, "ext_running", reference=upload.reference)
                self.adapter.upload(upload, stream, size)
                if self.platform == "facebook":
                    self.adapter.finish(
                        remote["identity"], upload.reference, snapshot["caption"], snapshot["ai"]
                    )
                result = self.adapter.check(upload.reference)
                status = {"complete": "ext_simulated", "waiting": "ext_waiting", "failed": "ext_failed"}.get(
                    result["status"], "unknown"
                )
                self._record(job_id, status, reference=upload.reference, remote_id=result.get("remote_id"))
        except Exception:  # noqa: BLE001 - no provider text, upload URL or secrets in diagnostics
            self._record(job_id, "unknown")
        return job_id

    def _record(self, job_id: int, status: str, **evidence) -> None:
        with self.sessions.begin() as session:
            job = session.get(PublishJob, job_id)
            job.status = status
            job.message = {
                "ext_simulated": "합성 응답 완료 · 실제 게시 아님",
                "ext_waiting": "합성 처리 대기 · 재전송 안 함",
                "ext_failed": "플랫폼 처리 실패 · 재전송 안 함",
                "unknown": "결과 불명 · 재전송 안 함",
            }.get(status, "요청 식별자 보존")
            job.finished_at = utcnow() if status not in {"ext_running", "ext_waiting"} else None
            session.add(PublishAttempt(job_id=job_id, status=status, message=job.message))
            session.add(
                PublishEvidence(
                    draft_id=job.draft_id,
                    kind="extension_result",
                    payload={"job_id": job_id, "synthetic": True, **evidence},
                )
            )

    def recover(self) -> int:
        with self.sessions.begin() as session:
            result = session.execute(
                update(PublishJob)
                .where(
                    PublishJob.platform == self.platform,
                    PublishJob.status.in_({"ext_running", "ext_checking"}),
                )
                .values(status="unknown", message="중단된 전송 · 재전송 안 함", finished_at=utcnow())
            )
            return result.rowcount

    def results(self) -> list[dict]:
        with self.sessions() as session:
            rows = []
            for job in session.scalars(
                select(PublishJob).where(PublishJob.platform == self.platform).order_by(PublishJob.id.desc())
            ):
                evidence = session.scalar(
                    select(PublishEvidence)
                    .where(
                        PublishEvidence.draft_id == job.draft_id,
                        PublishEvidence.kind == "extension_result",
                        PublishEvidence.payload["job_id"].as_integer() == job.id,
                    )
                    .order_by(PublishEvidence.id.desc())
                    .limit(1)
                )
                rows.append(
                    {
                        "id": job.id,
                        "status": job.status,
                        "synthetic": True,
                        "media_id": evidence.payload.get("remote_id") if evidence else None,
                    }
                )
            return rows

    def check(self, job_id: int, *, consent: bool = False) -> int:
        if consent is not True or self.binding is None:
            raise PlatformBlocked("선택한 계정의 상태 조회 승인이 필요합니다.")
        with self.sessions.begin() as session:
            job = session.get(PublishJob, job_id)
            if not job or job.platform != self.platform:
                raise PublishingError("게시 작업을 확인하세요.")
            if job.status != "ext_waiting":
                return job_id
            draft = session.get(PublishDraft, job.draft_id)
            binding = self.binding(draft.account_id)
            request = session.scalar(
                select(PublishEvidence).where(
                    PublishEvidence.draft_id == draft.id,
                    PublishEvidence.kind == "extension_request",
                    PublishEvidence.payload["job_id"].as_integer() == job_id,
                )
            )
            if (
                not request
                or binding.get("synthetic") is not True
                or binding.get("account_id") != draft.account_id
                or binding.get("platform") != self.platform
                or binding.get("identity") != request.payload.get("identity")
                or not set(REQUIREMENTS[self.platform]["scopes"]) <= set(binding.get("scopes", []))
            ):
                raise PublishingError("게시 계정 또는 권한이 변경되었습니다.")
            evidence = list(
                session.scalars(
                    select(PublishEvidence)
                    .where(
                        PublishEvidence.draft_id == draft.id,
                        PublishEvidence.kind == "extension_result",
                        PublishEvidence.payload["job_id"].as_integer() == job_id,
                    )
                    .order_by(PublishEvidence.id.desc())
                )
            )
            reference = next(
                (e.payload.get("reference") for e in evidence if e.payload.get("reference")), None
            )
            if not reference:
                raise PublishingError("기존 요청 식별자가 없습니다. 새 전송은 하지 않습니다.")
            changed = session.execute(
                update(PublishJob)
                .where(PublishJob.id == job_id, PublishJob.status == "ext_waiting")
                .values(status="ext_checking")
            )
            if changed.rowcount != 1:
                return job_id
        try:
            result = self.adapter.check(reference)
            status = {"complete": "ext_simulated", "waiting": "ext_waiting", "failed": "ext_failed"}.get(
                result["status"], "unknown"
            )
            self._record(job_id, status, reference=reference, remote_id=result.get("remote_id"))
        except Exception:  # noqa: BLE001 - unknown reads are not resubmissions
            self._record(job_id, "unknown", reference=reference)
        return job_id

    def prepare_options(self, draft_id: int, *, consent=False) -> dict:
        if consent is not True or self.binding is None or self.platform != "tiktok":
            raise PlatformBlocked("계정 게시 조건 조회 승인이 필요합니다. 실계정 조회는 차단되어 있습니다.")
        with self.sessions() as session:
            draft = session.get(PublishDraft, draft_id)
            if not draft or draft.platform != self.platform:
                raise PublishingError("TikTok 게시 초안을 확인하세요.")
            binding = self.binding(draft.account_id)
            if (
                binding.get("synthetic") is not True
                or binding.get("account_id") != draft.account_id
                or binding.get("platform") != self.platform
            ):
                raise PlatformBlocked("계정이 일치하지 않습니다.")
            revision, account_id = draft.revision, draft.account_id
        creator = self.adapter.creator()
        choices = creator["privacy_level_options"]
        if not all(
            p in {"SELF_ONLY", "PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR"}
            for p in choices
        ):
            raise PublishingError("지원하지 않는 공개 범위 응답입니다.")
        safe = {
            "nickname": creator["creator_nickname"][:100],
            "privacy": choices,
            "maximum": creator["max_video_post_duration_sec"],
            "disabled": {n: creator.get(n + "_disabled") is not False for n in ("comment", "duet", "stitch")},
            "revision": revision,
            "account_id": account_id,
            "synthetic": True,
        }
        with self.sessions.begin() as session:
            session.add(PublishEvidence(draft_id=draft_id, kind="tiktok_creator", payload=safe))
        return safe

    def prepared_options(self, draft_id: int) -> dict | None:
        with self.sessions() as session:
            draft = session.get(PublishDraft, draft_id)
            row = session.scalar(
                select(PublishEvidence)
                .where(PublishEvidence.draft_id == draft_id, PublishEvidence.kind == "tiktok_creator")
                .order_by(PublishEvidence.id.desc())
                .limit(1)
            )
            if (
                row
                and draft
                and row.created_at > utcnow() - timedelta(minutes=5)
                and row.payload["revision"] == draft.revision
                and row.payload["account_id"] == draft.account_id
            ):
                return row.payload
        return None
