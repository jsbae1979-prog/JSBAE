"""One reviewed video, independent YouTube/Instagram delivery journals.

This coordinates the existing platform services. It never implements transport,
authentication or automatic retry, and never publishes from a page-load request.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy
from pathlib import Path
from threading import RLock

from sqlalchemy import select, update

from newsflow.db.models import (
    PlatformAccount,
    PublishDraft,
    PublishEvidence,
    PublishJob,
    PublishValidation,
    RenderJob,
)
from newsflow.oauth.instagram import InstagramConnectionError
from newsflow.oauth.youtube import YouTubeConnectionError

from .categories import valid_category
from .platforms import PlatformBlocked
from .service import REAL_BLOCKERS, ConflictError, PublishingError, PublishingService, hash_file

_PLATFORMS = ("youtube", "instagram", "tiktok", "facebook")
_REVIEW = "unified_review"
_STATE = "unified_state"
_WAITING = {"ext_waiting","ig_processing", "ig_ready", "ig_status_failed"}
_SUCCESS = {"uploaded", "ig_published", "ig_published_no_link"}
_FAILED = {"ext_failed","failed", "ig_failed"}
_BLOCKED_CONNECTION = {"not_connected", "auth_relay_required", "client_missing", "client_changed",
                       "permission_denied", "professional_required", "expired", "consent_required",
                       "pending", "identity_mismatch"}
_FIELDS = ("title", "description", "hashtags", "content_reviewed", "copyright_confirmed", "sources_confirmed", "ai_disclosure")


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class UnifiedPublishingService:
    def __init__(self, sessions, outputs_dir: Path, youtube, instagram, inspector=None, extensions=None):
        self.sessions, self.outputs = sessions, outputs_dir
        self.youtube, self.instagram = youtube, instagram
        self.extensions = extensions or {}
        self.local = PublishingService(sessions, outputs_dir, inspector)
        self._save_lock = RLock()

    def save_local_draft(self, render_job_id: int, *, target: str, title: str = "",
                         description: str = "", hashtags: str = "", youtube_category_id: str = "") -> int:
        """Save unfinished copy only. No account checks, validation, approval or transport."""
        if target not in {"youtube", "instagram", "both", "tiktok", "facebook", "all"}:
            raise PublishingError("게시할 플랫폼을 선택하세요.")
        if len(title) > 100 or len(description) > 5000 or len(hashtags) > 2000 or len(youtube_category_id) > 3:
            raise PublishingError("게시 초안의 입력 길이를 확인하세요.")
        with self._save_lock, self.sessions.begin() as session:
            if not session.get(RenderJob, render_job_id):
                raise PublishingError("영상 작업을 찾지 못했습니다.")
            draft = PublishDraft(render_job_id=render_job_id, platform="youtube" if target in {"both", "all"} else target,
                title=title, description=description, hashtags=hashtags.split(), account_id=None,
                sources={}, media_sha256="", state="local_draft", youtube_category_id=youtube_category_id or "25")
            session.add(draft)
            session.flush()
            evidence = PublishEvidence(draft_id=draft.id, kind="local_workspace", payload={
                "render_job_id": render_job_id, "target": target,
                "metadata": {"title": title, "description": description, "hashtags": hashtags.split(),
                             "youtube_category_id": youtube_category_id}, "approval": False})
            session.add(evidence)
            session.flush()
            return evidence.id

    def local_draft(self, render_job_id: int) -> dict | None:
        with self.sessions() as session:
            row = session.scalar(select(PublishEvidence).where(PublishEvidence.kind == "local_workspace",
                PublishEvidence.payload["render_job_id"].as_integer() == render_job_id
            ).order_by(PublishEvidence.id.desc()).limit(1))
            return {**deepcopy(row.payload), "id": row.id, "saved_at": row.created_at} if row else None

    @staticmethod
    def _snapshot(draft: PublishDraft) -> dict:
        # Legacy snapshots omitted the previously fixed category25. Preserve their approval hashes.
        category = {"youtube_category_id": draft.youtube_category_id} if (
            draft.platform == "youtube" and draft.youtube_category_id != "25") else {}
        return {**category, "id": draft.id, "revision": draft.revision, "platform": draft.platform,
                "account_id": draft.account_id, "media_sha256": draft.media_sha256,
                "render_job_id": draft.render_job_id, "sources": draft.sources,
                **{name: getattr(draft, name) for name in _FIELDS}}

    def _load(self, session, cohort_id: int) -> tuple[PublishEvidence, dict]:
        review = session.get(PublishEvidence, cohort_id)
        if not review or review.kind != _REVIEW:
            raise PublishingError("통합 게시 검토 기록을 찾지 못했습니다.")
        item = session.scalar(select(PublishEvidence).where(
            PublishEvidence.kind == _STATE, PublishEvidence.payload["cohort_id"].as_integer() == cohort_id,
        ).order_by(PublishEvidence.id.desc()).limit(1))
        return review, deepcopy(item.payload if item else {"cohort_id": cohort_id, "targets": review.payload["targets"]})

    def _record(self, session, review: PublishEvidence, state: dict) -> None:
        session.add(PublishEvidence(draft_id=review.draft_id, kind=_STATE,
                                    payload={**deepcopy(state), "cohort_id": review.id, "auto_retry": False}))

    def _previous_targets(self, render_job_id: int) -> list[tuple[dict, dict]]:
        with self.sessions() as session:
            found = []
            for item in session.scalars(select(PublishEvidence).where(
                PublishEvidence.kind == _REVIEW,
                PublishEvidence.payload["render_job_id"].as_integer() == render_job_id,
            ).order_by(PublishEvidence.id.desc())):
                review, state = self._load(session, item.id)
                found.append((deepcopy(review.payload), state))
            return found

    def _snapshot_matches(self, target: dict) -> bool:
        with self.sessions() as session:
            draft = session.get(PublishDraft, target["draft_id"])
            extension = self.extensions.get(target["platform"])
            identity_matches = not extension or extension.account_identity(target["account_id"]) == target.get("connection_identity")
            return bool(draft and self._snapshot(draft) == target["snapshot"] and identity_matches)

    def save_review(
        self, render_job_id: int, accounts: dict[str, int], *, title: str, description: str = "", hashtags: str = "",
        content_reviewed: bool = False, copyright_confirmed: bool = False, sources_confirmed: bool = False,
        ai_disclosure: str = "unreviewed", youtube_category_id: str | None = None,
    ) -> int:
        """Save local reviews only. Repeated saves retain previous outcomes, including failures."""
        if (not isinstance(accounts, dict) or not accounts or not set(accounts) <= set(_PLATFORMS)
                or any(type(identifier) is not int or identifier <= 0 for identifier in accounts.values())):
            raise PublishingError("게시할 플랫폼과 계정을 선택하세요.")
        fields = {"title": title, "description": description, "hashtags": hashtags,
                  "content_reviewed": content_reviewed is True, "copyright_confirmed": copyright_confirmed is True,
                  "sources_confirmed": sources_confirmed is True, "ai_disclosure": ai_disclosure}
        if "youtube" in accounts and youtube_category_id is not None:
            if not valid_category(youtube_category_id):
                raise PublishingError("YouTube 영상 카테고리를 선택하세요.")
            fields["youtube_category_id"] = youtube_category_id
        normalized = self.local.input(next(iter(accounts)), title, description, hashtags, ai_disclosure)
        metadata = {**fields, **{key: normalized[key] for key in ("title", "description", "hashtags")}}
        with self._save_lock:
            with self.sessions() as session:
                render = session.get(RenderJob, render_job_id)
                if not render:
                    raise PublishingError("완성 영상을 찾지 못했습니다.")
                media_hash = hash_file(self.local.media_path(render))
                for platform, account_id in accounts.items():
                    self.local.account_check(session, account_id, platform)
            identities = {p: self.extensions[p].account_identity(a) for p, a in accounts.items() if p in self.extensions}
            fingerprint = _digest({"connection_identities": identities, "render_job_id": render_job_id, "media_sha256": media_hash,
                                   "accounts": accounts, "metadata": metadata})
            previous = self._previous_targets(render_job_id)
            for review, state in previous:
                if (review["fingerprint"] == fingerprint
                        and all(target["status"] != "superseded" for target in state["targets"].values())
                        and all(self._snapshot_matches(target) for target in state["targets"].values())):
                    return review["cohort_id"]
            targets = {}
            for platform in _PLATFORMS:
                if platform not in accounts:
                    continue
                reused = None
                for review, state in previous:
                    old = state["targets"].get(platform)
                    if (not old or old["account_id"] != accounts[platform]
                            or review["media_sha256"] != media_hash):
                        continue
                    if old["status"] not in {"ready", "superseded"} and review["metadata"] != metadata:
                        raise ConflictError("이미 전송을 시작한 영상의 게시 정보는 바꾸지 않습니다. 기존 결과를 확인하세요.")
                    if not self._snapshot_matches(old):
                        if old["status"] not in {"ready", "superseded"}:
                            raise ConflictError("기존 게시 검토 내용이 변경되었습니다. 먼저 이전 게시 결과를 확인하세요.")
                        continue
                    if review["metadata"] == metadata and old["status"] != "superseded":
                        reused = deepcopy(old)
                        break
                if reused is not None:
                    targets[platform] = reused
                    continue
                draft_fields = {k: v for k, v in fields.items() if k != "youtube_category_id" or platform == "youtube"}
                draft_id = self.local.create(render_job_id, platform, account_id=accounts[platform], **draft_fields)
                self.local.validate(draft_id)
                with self.sessions() as session:
                    snapshot = self._snapshot(session.get(PublishDraft, draft_id))
                    label = session.get(PlatformAccount, accounts[platform]).label
                targets[platform] = {"platform": platform, "draft_id": draft_id, "revision": snapshot["revision"],
                                     "account_id": accounts[platform], "account_label": label, "connection_identity": identities.get(platform),
                                     "snapshot": snapshot, "job_id": None, "status": "ready",
                                     "message": "검토한 내용을 게시할 준비가 되었습니다.", "url": None}
            anchor = next(iter(targets.values()))["draft_id"]
            with self.sessions.begin() as session:
                session.execute(update(RenderJob).where(RenderJob.id == render_job_id)
                                .values(status=RenderJob.status))
                # A revised review invalidates old, unstarted approval forms. Do
                # not let an older browser tab publish a different caption first.
                for old_review, _old_state in previous:
                    if old_review["media_sha256"] != media_hash or old_review["metadata"] == metadata:
                        continue
                    old_row, old_state = self._load(session, old_review["cohort_id"])
                    changed = False
                    for platform, target in old_state["targets"].items():
                        if accounts.get(platform) != target["account_id"]:
                            continue
                        if target["status"] not in {"ready", "superseded"}:
                            raise ConflictError("기존 검토에서 게시가 시작되었습니다. 해당 결과를 먼저 확인하세요.")
                        target.update(status="superseded", message="새 검토 내용으로 교체되었습니다. 최신 검토를 이용하세요.")
                        changed = True
                    if changed:
                        self._record(session, old_row, old_state)
                row = PublishEvidence(draft_id=anchor, kind=_REVIEW, payload={})
                session.add(row)
                session.flush()
                payload = {"cohort_id": row.id, "render_job_id": render_job_id, "media_sha256": media_hash,
                           "fingerprint": fingerprint, "accounts": accounts, "metadata": metadata, "targets": targets}
                row.payload = {**payload, "approval_token": _digest(payload)}
                self._record(session, row, {"targets": targets})
                return row.id

    def get(self, cohort_id: int) -> dict:
        """Return stored status, without authentication, polling, uploads or publication."""
        with self.sessions() as session:
            review, state = self._load(session, cohort_id)
            targets = list(state["targets"].values())
            reviewed, checks = True, []
            for target in targets:
                draft = session.get(PublishDraft, target["draft_id"])
                validation = session.scalar(select(PublishValidation).where(
                    PublishValidation.draft_id == target["draft_id"],
                ).order_by(PublishValidation.id.desc()).limit(1))
                valid = bool(draft and validation and self._snapshot(draft) == target["snapshot"]
                             and validation.draft_revision == draft.revision)
                local_checks = [row for row in validation.results
                                if row["key"] not in REAL_BLOCKERS | {"duplicate_identity"}] if validation else []
                valid = valid and bool(local_checks) and all(row["status"] == "pass" for row in local_checks)
                reviewed = reviewed and valid
                checks.extend({**row, "platform": target["platform"]} for row in local_checks if row["status"] != "pass")
                target["can_continue"] = valid and target["status"] in {"ready", "waiting"}
            return {**deepcopy(review.payload), "id": cohort_id, "targets": deepcopy(targets),
                    "results": deepcopy(targets), "checks": checks, "reviewed": reviewed,
                    "platforms": list(state["targets"]),
                    "can_execute": reviewed and any(target["can_continue"] for target in targets),
                    "locked": any(target["status"] != "ready" for target in targets)}

    def for_video(self, render_job_id: int) -> dict | None:
        with self.sessions() as session:
            identifier = session.scalar(select(PublishEvidence.id).where(
                PublishEvidence.kind == _REVIEW,
                PublishEvidence.payload["render_job_id"].as_integer() == render_job_id,
            ).order_by(PublishEvidence.id.desc()).limit(1))
        return self.get(identifier) if identifier is not None else None

    def _preflight(self, cohort_id: int, approval_token: str) -> tuple[dict, dict]:
        with self.sessions() as session:
            review, state = self._load(session, cohort_id)
            payload = deepcopy(review.payload)
            if not isinstance(approval_token, str) or not hmac.compare_digest(approval_token, payload["approval_token"]):
                raise ConflictError("승인 화면의 영상·계정·검토 내용이 달라졌습니다. 새로 확인하세요.")
            render = session.get(RenderJob, payload["render_job_id"])
            if not render or hash_file(self.local.media_path(render)) != payload["media_sha256"]:
                raise PublishingError("검토한 MP4가 변경되어 게시하지 않았습니다.")
            for target in state["targets"].values():
                draft = session.get(PublishDraft, target["draft_id"])
                if not draft or self._snapshot(draft) != target["snapshot"]:
                    raise ConflictError("게시 초안이 변경되었습니다. 현재 내용을 다시 검토하세요.")
        for target in state["targets"].values():
            validation_id = self.local.validate(target["draft_id"])
            with self.sessions() as session:
                validation = session.get(PublishValidation, validation_id)
                ignored = REAL_BLOCKERS | {"duplicate_identity"}
                if (validation.draft_revision != target["revision"]
                        or validation.media_sha256 != payload["media_sha256"]
                        or any(row["status"] != "pass" for row in validation.results if row["key"] not in ignored)):
                    raise PublishingError("영상·내용·출처·권리·AI 표시 검토를 마친 뒤 게시하세요.")
        return payload, state

    def _claim(self, cohort_id: int, platform: str, approval: dict) -> dict | None:
        with self.sessions.begin() as session:
            review, _state = self._load(session, cohort_id)
            # Obtain SQLite's write lock before reading the last journal entry.
            session.execute(update(PublishDraft).where(PublishDraft.id == review.draft_id)
                            .values(updated_at=PublishDraft.updated_at))
            review, state = self._load(session, cohort_id)
            target = state["targets"][platform]
            if target["status"] not in {"ready", "waiting"}:
                return None
            draft = session.get(PublishDraft, target["draft_id"])
            if not draft or self._snapshot(draft) != target["snapshot"]:
                raise ConflictError("게시 직전 초안이 변경되었습니다.")
            target.update(status="running", message="승인한 플랫폼의 게시 작업을 진행 중입니다.", approval=approval)
            self._record(session, review, state)
            return deepcopy(target)

    def _finish(self, cohort_id: int, platform: str, **changes) -> None:
        with self.sessions.begin() as session:
            review, _state = self._load(session, cohort_id)
            session.execute(update(PublishDraft).where(PublishDraft.id == review.draft_id)
                            .values(updated_at=PublishDraft.updated_at))
            review, state = self._load(session, cohort_id)
            state["targets"][platform].update(changes)
            self._record(session, review, state)

    def _platform_result(self, platform: str, job_id: int) -> dict:
        service = self.extensions.get(platform) or (self.youtube if platform == "youtube" else self.instagram)
        result = next((item for item in service.results() if item.get("id", item.get("job_id")) == job_id), None)
        with self.sessions() as session:
            job = session.get(PublishJob, job_id)
            if not job or job.platform != platform:
                raise PublishingError("플랫폼 게시 작업 기록을 확인하지 못했습니다.")
            status, message = job.status, job.message
        return {**(result or {}), "job_id": job_id, "platform_status": status, "message": message,
                "status": "simulated" if status == "ext_simulated" else "complete" if status in _SUCCESS else "waiting" if status in _WAITING else
                          "failed" if status in _FAILED else "unknown",
                "url": (result or {}).get("url") or (result or {}).get("video_url")}

    def execute(
        self, cohort_id: int, *, consent: bool = False, approval_token: str = "", privacy: str = "private",
        made_for_kids: bool | None = None, youtube_public_consent: bool = False,
        instagram_public_consent: bool = False, extension_options: dict | None = None,
    ) -> dict:
        if consent is not True:
            raise PublishingError("선택한 계정과 영상의 이번 게시 실행에 동의하세요.")
        payload, state = self._preflight(cohort_id, approval_token)
        selected = state["targets"]
        active = {platform for platform, target in selected.items() if target["status"] in {"ready", "waiting"}}
        if "youtube" in active and (privacy not in {"private", "unlisted", "public"}
                or type(made_for_kids) is not bool or (privacy != "private" and youtube_public_consent is not True)):
            raise PublishingError("YouTube 공개 범위·아동용 여부와 필요한 공개 동의를 확인하세요.")
        if "instagram" in active and instagram_public_consent is not True:
            raise PublishingError("선택한 Instagram 계정과 영상의 공개 게시에 동의하세요.")
        extension_options = extension_options or {}
        for platform in active & {"tiktok", "facebook"}:
            service = self.extensions.get(platform)
            if not service:
                raise PublishingError("추가 플랫폼의 연결 준비가 필요합니다.")
            service.validate_options(extension_options.get(platform, {}))
            if service.account_identity(selected[platform]["account_id"]) != selected[platform].get("connection_identity"):
                raise PublishingError("게시 대상 계정이 검토 이후 변경되었습니다. 다시 검토하세요.")
        approval = {"extension_options": extension_options, "approval_token": approval_token, "consent": True,
                    "privacy": privacy if "youtube" in active else None,
                    "made_for_kids": made_for_kids if "youtube" in active else None,
                    "youtube_public_consent": "youtube" in active and youtube_public_consent is True,
                    "instagram_public_consent": instagram_public_consent is True}
        for platform in _PLATFORMS:
            if platform not in selected:
                continue
            target = self._claim(cohort_id, platform, approval)
            if target is None:
                continue
            try:
                if platform == "youtube":
                    job_id = self.youtube.execute(target["draft_id"], target["revision"], privacy=privacy,
                        made_for_kids=made_for_kids, consent=True, public_consent=youtube_public_consent)
                elif platform in self.extensions:
                    if target.get("job_id"):
                        job_id = self.extensions[platform].check(target["job_id"], consent=True)
                    else:
                        job_id = self.extensions[platform].execute(target["draft_id"], target["revision"],
                            consent=True, options=extension_options.get(platform, {}), expected_identity=target.get("connection_identity"))
                else:
                    job_id = target.get("job_id")
                    if job_id is None:
                        job_id = self.instagram.prepare(target["draft_id"], target["revision"], consent=True)
                        self._finish(cohort_id, platform, job_id=job_id)
                    result = self._platform_result(platform, job_id)
                    if result["platform_status"] in {"ig_processing", "ig_status_failed"}:
                        self.instagram.check(job_id, consent=True)
                        result = self._platform_result(platform, job_id)
                    if result["platform_status"] == "ig_ready":
                        self.instagram.publish(job_id, consent=True, public_consent=True,
                            account_id=target["account_id"], media_sha256=payload["media_sha256"])
                result = self._platform_result(platform, job_id)
                self._finish(cohort_id, platform, **{name: result.get(name) for name in (
                    "job_id", "platform_status", "status", "message", "url", "media_id", "video_id",
                )})
            except Exception as error:  # noqa: BLE001 - no raw OAuth/provider detail and no retry
                blocked = isinstance(error, PlatformBlocked) or (isinstance(error, (YouTubeConnectionError, InstagramConnectionError))
                           and error.code in _BLOCKED_CONNECTION)
                self._finish(cohort_id, platform, status="blocked" if blocked else "unknown",
                    error_code=getattr(error, "code", "activation_required") if blocked else "unknown",
                    message="계정 연결 또는 게시 권한 준비가 필요합니다. 자동 재실행하지 않습니다." if blocked else
                            "게시 요청을 완료하거나 결과를 확인하지 못했습니다. 자동 재시도하지 않습니다.")
        return self.get(cohort_id)

    def recover(self) -> int:
        """Quarantine interrupted coordination. Platform journals remain authoritative and untouched."""
        count = 0
        with self.sessions.begin() as session:
            for review in session.scalars(select(PublishEvidence).where(PublishEvidence.kind == _REVIEW)):
                _review, state = self._load(session, review.id)
                changed = False
                for target in state["targets"].values():
                    if target["status"] == "running":
                        job_id = target.get("job_id")
                        if job_id is None:
                            # The platform may have committed success before the
                            # coordinator recorded its ID. Recover local evidence,
                            # never repeat the operation to discover its result.
                            job_id = session.scalar(select(PublishJob.id).where(
                                PublishJob.draft_id == target["draft_id"],
                                PublishJob.platform == target["platform"],
                                PublishJob.status.in_(_SUCCESS | _WAITING | _FAILED | {"unknown", "ig_unknown", "ext_simulated"}),
                            ).order_by(PublishJob.id.desc()).limit(1))
                        try:
                            result = self._platform_result(target["platform"], job_id) if job_id is not None else None
                        except PublishingError:
                            result = None
                        if result:
                            target.update({name: result.get(name) for name in (
                                "job_id", "platform_status", "status", "message", "url", "media_id", "video_id",
                            )})
                        else:
                            target.update(status="unknown", message="중단된 게시 결과를 확인해야 합니다. 자동 재실행하지 않습니다.")
                        count += 1
                        changed = True
                if changed:
                    self._record(session, review, state)
        return count
