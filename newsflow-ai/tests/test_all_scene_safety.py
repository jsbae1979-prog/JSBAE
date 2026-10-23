"""No fallback, unsigned consent, partial scenes, replay or mutable-default promotion."""

from copy import deepcopy

import pytest
import test_all_scene_production as flows
from sqlalchemy import select
from test_all_scene_production import (
    generate,
    options,
    prepare_plan,
    revision,
    settle,
)
from test_api_news_pipeline import start
from test_api_shorts_pipeline import context_for
from test_voice_engines import Keys

from newsflow.autopilot.contracts import AutopilotError
from newsflow.autopilot.service import AutopilotCoordinator
from newsflow.db.models import AIVideoPlan, AIVideoScene, AutopilotJob, ContentDraft
from newsflow.video.ai.service import AIVideoError
from newsflow.video.elevenlabs_tts import ElevenLabsTTS
from newsflow.video.production_policy import plan_policy
from newsflow.video.tts import TTSError
from newsflow.video.voice_engines import provider_for

api_pipeline = flows.api_pipeline
production = flows.production


def test_external_voice_missing_separate_consent_blocks_before_any_vendor(production):
    p = production
    choice = options(False, "elevenlabs", True)
    choice["external_tts_consent"] = False
    with pytest.raises(AutopilotError):
        start(p["pipeline"], voice="elevenlabs", production_options=choice)
    assert p["voice_calls"] == [] and p["fake"].calls == [] and p["pipeline"][2].calls == []


@pytest.mark.parametrize("fault", ["card", "local", "missing", "timing", "caption"])
def test_all_scene_policy_rejects_partial_or_tampered_plans_before_paid_submit(production, fault):
    p = production
    identifier = start(p["pipeline"], production_options=options(False, ai=True))
    plan_id = prepare_plan(p, identifier)
    if fault in {"card", "local"}:
        with pytest.raises(AIVideoError):
            p["service"].update_scenes(plan_id, revision(p, plan_id), [{"position": 0, "source": fault}], asset_permission=True)
    with p["sessions"].begin() as session:
        scene = session.scalar(select(AIVideoScene).where(AIVideoScene.plan_id == plan_id, AIVideoScene.position == 0))
        if fault == "missing":
            session.delete(scene)
        elif fault == "timing":
            scene.end_ms -= 100
        elif fault == "caption":
            scene.caption = "다른 자막"
        else:
            scene.source = fault
    with pytest.raises(AIVideoError):
        p["service"].confirm_generation(plan_id, revision(p, plan_id), "1.5", True)
    assert p["fake"].calls == [] and p["voice_calls"] == []


def test_parent_cancel_prevents_previously_approved_waiting_submissions(production):
    p = production
    identifier = start(p["pipeline"], production_options=options(False, ai=True))
    plan_id = prepare_plan(p, identifier)
    quote = p["service"].estimate(plan_id)
    p["service"].confirm_generation(plan_id, revision(p, plan_id), quote["total"], True)
    job = p["coordinator"].snapshot(identifier)
    p["coordinator"].cancel(identifier, job["revision"])
    p["service"].tick()
    assert p["fake"].calls == []


def test_unknown_generation_is_not_resubmitted_after_restart_or_other_approval(production):
    p = production
    identifier = start(p["pipeline"], production_options=options(False, ai=True))
    plan_id = prepare_plan(p, identifier)
    p["service"].update_scenes(plan_id, revision(p, plan_id), [{"position": 0, "source": "generated",
        "model_path": "vendor/model/text-to-video", "prompt": "푸른 추상 배경 [fake:ambiguous]"}])
    quote = p["service"].estimate(plan_id)
    p["service"].confirm_generation(plan_id, revision(p, plan_id), quote["total"], True)
    p["service"].tick()
    submitted = len([call for call in p["fake"].calls if call[0] == "submit"])
    p["service"].recover()
    for _ in range(4):
        p["service"].tick()
    assert len([call for call in p["fake"].calls if call[0] == "submit"]) == submitted
    assert p["voice_calls"] == []
    with pytest.raises(AIVideoError):
        p["service"].approve_compose(plan_id, revision(p, plan_id), True)


def test_changed_draft_needs_new_voice_scope_consent_not_url_flags(production, client):
    p = production
    identifier = start(p["pipeline"], voice="elevenlabs", production_options=options(True, "elevenlabs"))
    job = settle(p, identifier)
    with p["sessions"].begin() as session:
        draft = session.get(ContentDraft, job["content_draft_id"])
        content = deepcopy(draft.content)
        content["title"] = "수정된 합성 제목"
        draft.content, draft.revision = content, draft.revision + 1
    # Existing review acknowledgement alone is not renewed external voice consent.
    p["coordinator"].resume(identifier, job["revision"])
    stopped = settle(p, identifier)
    assert stopped["error_code"] == "voice_consent_required" and not p["voice_calls"]
    assert client.post(f"/autopilot/jobs/{identifier}/voice-consent", data={"revision": stopped["revision"],
        "consent": "true"}).status_code == 403
    with pytest.raises(AutopilotError):
        p["coordinator"].approve_voice(identifier, stopped["revision"], False)
    renewed = p["coordinator"].approve_voice(identifier, stopped["revision"], True)
    assert renewed["status"] == "waiting_review" and p["voice_calls"] == []
    ctx = context_for(p["pipeline"], identifier)
    assert p["backend"]._voice(ctx) == "elevenlabs"
    with p["sessions"]() as session:
        assert len(session.get(AutopilotJob, identifier).stage_results["voice_approvals"]) == 1


def test_voice_key_rotation_cannot_rebill_an_existing_scope(production, monkeypatch):
    p = production
    cfg = options(False, "elevenlabs")["elevenlabs"]
    monkeypatch.setattr("newsflow.video.elevenlabs_tts.ElevenLabsKeys.key", lambda _: "another-synthetic-key-0000")
    with pytest.raises(TTSError, match="계정 키가 바뀌었습니다"):
        provider_for("elevenlabs", p["sessions"], p["backend"].video.root, external_consent=True, elevenlabs_config=cfg)
    assert p["voice_calls"] == []


def test_coordinator_restart_keeps_plan_identity_and_never_generates(production):
    p = production
    identifier = start(p["pipeline"], production_options=options(False, ai=True))
    plan_id = prepare_plan(p, identifier)
    before = p["coordinator"].snapshot(identifier)["production_options"]
    p["coordinator"].close()
    restored = AutopilotCoordinator(p["sessions"], p["backend"].video.root, p["backend"])
    p["service"].on_complete = restored.attach_completed_ai
    try:
        job = restored.snapshot(identifier)
        assert job["production_options"] == before and job["ai_plan_id"] == plan_id
        assert p["service"].create_plan(job["content_draft_id"], 30, production_job_id=identifier) == plan_id
        assert not p["fake"].calls and not p["voice_calls"]
        with p["sessions"]() as session:
            assert session.query(AIVideoPlan).count() == 1
            assert plan_policy(session, plan_id)["options"] == before
    finally:
        restored.close()


def test_deleted_or_unreviewed_generated_clip_prevents_synthesis(production):
    p = production
    identifier = start(p["pipeline"], voice="elevenlabs", production_options=options(False, "elevenlabs", True))
    plan_id = prepare_plan(p, identifier)
    generate(p, plan_id)
    p["service"].review(plan_id, revision(p, plan_id), {0, 1}, True)
    with pytest.raises(AIVideoError):
        p["service"].approve_compose(plan_id, revision(p, plan_id), True)
    p["service"].review(plan_id, revision(p, plan_id), {0, 1, 2}, True)
    with p["sessions"]() as session:
        scene = session.scalar(select(AIVideoScene).where(AIVideoScene.plan_id == plan_id))
        clip = p["service"].clips.path(scene.clip_name)
    clip.write_bytes(b"TAMPERED SYNTHETIC CLIP")
    with pytest.raises(AIVideoError):
        p["service"].approve_compose(plan_id, revision(p, plan_id), True)
    assert p["voice_calls"] == []


@pytest.mark.parametrize("review", [True, False])
def test_automatic_checks_precede_both_review_modes(production, monkeypatch, review):
    p = production
    original = p["pipeline"][2].complete
    def unsafe(*args):
        result = original(*args)
        result["summary"] += " 987654명이 참여했습니다."
        return result
    monkeypatch.setattr(p["pipeline"][2], "complete", unsafe)
    identifier = start(p["pipeline"], production_options=options(review, ai=True))
    job = settle(p, identifier)
    assert job["status"] == "failed" and not p["fake"].calls and not p["voice_calls"]


def test_key_change_after_provider_creation_blocks_each_new_request(production, monkeypatch, tmp_path):
    p = production
    selected = [Keys().key()]
    monkeypatch.setattr("newsflow.video.elevenlabs_tts.ElevenLabsKeys.key", lambda _: selected[0])
    tts = provider_for("elevenlabs", p["sessions"], p["backend"].video.root, external_consent=True,
                       elevenlabs_config=options(False, "elevenlabs")["elevenlabs"])
    selected[0] = "changed-synthetic-key-not-real-0000"
    with pytest.raises(TTSError):
        tts.synthesize_timed("합성 문장입니다.", tmp_path / "never.wav", "elevenlabs", 10)
    assert p["voice_calls"] == []


def test_failed_voice_with_completed_ai_clips_is_not_recharged_on_compose_retry(production, monkeypatch):
    p = production
    identifier = start(p["pipeline"], voice="elevenlabs", production_options=options(False, "elevenlabs", True))
    plan_id = prepare_plan(p, identifier)
    generate(p, plan_id)
    p["service"].review(plan_id, revision(p, plan_id), {0, 1, 2}, True)
    posts = []
    def transport(method, path, payload=None):
        if method == "GET":
            return {"tier": "starter", "status": "active", "character_count": 0,
                    "character_limit": 100000, "max_credit_limit_extension": 0}
        posts.append(path)
        raise TimeoutError("SYNTHETIC UNKNOWN OUTCOME")
    monkeypatch.setattr("newsflow.video.elevenlabs_tts.ElevenLabsTTS", lambda root, config, consent, **kw:
                        ElevenLabsTTS(root, config, consent=consent, transport=transport, keys=kw["keys"]))
    for _ in range(2):
        p["service"].approve_compose(plan_id, revision(p, plan_id), True)
        p["backend"].video.future.result(timeout=60)
        p["service"].sync()
        p["service"].recover()
    assert len(posts) == 1
    assert len([call for call in p["fake"].calls if call[0] == "submit"]) == 3
    with p["sessions"]() as session:
        assert session.get(AIVideoPlan, plan_id).status == "compose_failed"
        assert len(list(session.scalars(select(AIVideoScene).where(AIVideoScene.plan_id == plan_id, AIVideoScene.status == "ready")))) == 3
