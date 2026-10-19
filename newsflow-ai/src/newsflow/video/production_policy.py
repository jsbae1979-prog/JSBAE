"""Server-owned per-plan production snapshots in existing Autopilot JSON; no secrets."""

import hashlib
import json
from copy import deepcopy

from sqlalchemy import select

from newsflow.db.models import AIVideoPlan, AutopilotArtifact, AutopilotJob, ContentDraft, utcnow


def check_draft(sessions, draft: ContentDraft, options: dict, root) -> None:
    """Reuse the intelligence checks after edits/rebase, without any inference call."""
    from newsflow.intelligence.credentials import AIKeyStore, AnthropicKeyStore
    from newsflow.intelligence.service import IntelligenceError, IntelligenceService
    from newsflow.video.ai.keys import VideoAIKeyStore
    from newsflow.video.elevenlabs_tts import ElevenLabsKeys

    service = IntelligenceService(sessions, speech=options["speech"], api_key_stores={
        "openai": AIKeyStore(root), "claude_api": AnthropicKeyStore(root),
        "elevenlabs": ElevenLabsKeys(root), "video_ai": VideoAIKeyStore(root)})
    service.validate(draft.content, draft.duration)
    service.check_news_usage(draft.content, draft.sources)
    service.check_copy(draft.content, draft.sources)
    service._check_stored_secret(draft.content)
    notes = service._review_notes(draft.content, draft.sources, draft.duration)
    if (not draft.sources.get("articles") or any(not a.get("sources") for a in draft.sources["articles"])
            or any(note.get("level") != "info" for note in notes)):
        raise IntelligenceError("수정한 대본의 자동 검사 경고를 확인·수정하세요.", "ai_bad_response", False)


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def full_job(session, draft_id: int):
    jobs = session.scalars(select(AutopilotJob).join(AutopilotArtifact, AutopilotArtifact.job_id == AutopilotJob.id).where(
        AutopilotArtifact.kind == "content_draft_id", AutopilotArtifact.reference == str(draft_id)))
    matches = [job for job in jobs if job.stage_results.get("request", {}).get("production_options", {}).get("version") == 2
               and job.stage_results["request"]["production_options"].get("video_provider") == "higgsfield"]
    if len(matches) > 1:
        raise ValueError("영상 계획의 원래 작업을 명확히 확인할 수 없습니다.")
    return matches[0] if matches else None


def plan_policy(session, plan_id: int):
    link = session.scalar(select(AutopilotArtifact).where(AutopilotArtifact.kind == "ai_plan_id",
                                                       AutopilotArtifact.reference == str(plan_id)))
    if link is None:
        plan = session.get(AIVideoPlan, plan_id)
        if plan and full_job(session, plan.draft_id):
            raise ValueError("원래 AI 제작 작업과 계획 참조가 끊겨 합성을 차단했습니다.")
        return None
    job = session.get(AutopilotJob, link.job_id)
    policy = job.stage_results.get("ai_plan_policies", {}).get(str(plan_id)) if job else None
    if not isinstance(policy, dict) or policy.get("mode") != "all_higgsfield":
        raise ValueError("영상 계획의 저장 정책이 없어 합성을 차단했습니다.")
    return deepcopy(policy)


def write_policy(session, job, plan_id: int, policy: dict) -> None:
    job.stage_results = {**job.stage_results, "ai_plan_policies": {
        **job.stage_results.get("ai_plan_policies", {}), str(plan_id): deepcopy(policy)}}


def voice_scope(draft: ContentDraft, options: dict) -> str:
    return digest({"draft_id": draft.id, "revision": draft.revision, "content": draft.content,
                   "voice": options["voice"], "speech": options["speech"], "elevenlabs": options.get("elevenlabs")})


def voice_allowed(job, draft: ContentDraft, options: dict) -> bool:
    if options["voice"] != "elevenlabs":
        return True
    if options.get("external_tts_consent") is not True:
        return False
    original = job.stage_results.get("script", {})
    if original.get("script_revision") == draft.revision and original.get("script_sha256") == digest(draft.content):
        return True
    return any(item.get("scope") == voice_scope(draft, options) for item in job.stage_results.get("voice_approvals", []))


def approve_voice(session, job, draft: ContentDraft, options: dict) -> None:
    entry = {"scope": voice_scope(draft, options), "draft_id": draft.id, "draft_revision": draft.revision,
             "approved_at": utcnow().isoformat()}
    job.stage_results = {**job.stage_results, "voice_approvals": [*job.stage_results.get("voice_approvals", []), entry]}
