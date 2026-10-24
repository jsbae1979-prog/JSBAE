"""All eight choices through existing services; fake vendors, real local FFmpeg."""

import base64
import hashlib
import json
import os
import urllib.request
from copy import deepcopy
from pathlib import Path

import pytest
from pc_cloud_script_fixture import healthy_three_scene
from sqlalchemy import select
from test_api_news_pipeline import api_pipeline as pipeline_fixture
from test_api_news_pipeline import start
from test_cloud_workspace_flow import SyntheticTTS
from test_single_workspace import save_values
from test_voice_engines import Keys, config

from newsflow.db.models import (
    AIVideoPlan,
    AIVideoScene,
    AudioTrack,
    ContentDraft,
    PublishDraft,
    VideoProject,
)
from newsflow.publishing.media import FFprobeMediaInspector
from newsflow.video.ai.fake import FakeVideoProvider
from newsflow.video.ai.service import AIVideoError
from newsflow.video.ai.settings import save_model, write_settings
from newsflow.video.elevenlabs_tts import ElevenLabsTTS, save_settings
from newsflow.video.production_policy import plan_policy

api_pipeline = pipeline_fixture
MODEL = "pixverse/v6/text-to-video"


def options(review=True, voice="supertonic:F1", ai=False):
    return {"version": 2, "script_review": review, "video_provider": "higgsfield" if ai else "off",
            "speech": {"rate": 0, "pause_ms": 250}, "font_size": 48, "subtitle_y": 1420,
            **({"external_tts_consent": True, "elevenlabs": {**config(), "job_limit": 10000, "monthly_limit": 100000, "credential_fingerprint": hashlib.sha256(Keys().key().encode()).hexdigest()}}
               if voice == "elevenlabs" else {})}


@pytest.fixture
def production(app, api_pipeline, monkeypatch):
    coordinator, backend, api, sessions, mode, _rss = api_pipeline
    monkeypatch.setattr(app.state, "autopilot", coordinator)
    monkeypatch.setattr(app.state, "autopilot_backend", backend)
    service = app.state.video_ai
    fake = FakeVideoProvider(steps=1)
    monkeypatch.setattr(service, "injected", fake)
    monkeypatch.setattr(service, "wake", lambda: None)
    monkeypatch.setattr(service, "on_complete", coordinator.attach_completed_ai)
    backend.ai_video = service
    write_settings(sessions, provider="higgsfield", host="api.higgsfield.ai", approved=True,
                   monthly_limit="100", job_limit="10", currency="USD", max_active=2, timeout_minutes=30, poll_seconds=10)
    save_model(sessions, path=MODEL, label="Synthetic model", price_per_second="0.1", durations="5,10,15",
               resolution="720p", confirmed=True)
    save_values(app, video_default_voice="supertonic:F1", video_default_rate="0", video_default_pause_ms="250")
    local = SyntheticTTS()
    # VideoCoordinator imported the original factory; only its existing provider classes are injected.
    monkeypatch.setattr("newsflow.video.supertonic_tts.SupertonicTTS", lambda: local)
    monkeypatch.setattr("newsflow.video.tts.WindowsTTS.voice_details", lambda _: [])
    cfg = options(voice="elevenlabs")["elevenlabs"]
    save_settings(sessions, **{key: value for key, value in cfg.items() if key != "credential_fingerprint"})
    voice_calls = []
    captured_configs = []

    def transport(method, path, payload=None):
        voice_calls.append((method, path))
        if method == "GET":
            return {"tier": "starter", "status": "active", "character_count": 0,
                    "character_limit": 100000, "max_credit_limit_extension": 0}
        text = payload["text"]
        return {"audio_base64": base64.b64encode(b"\0\0" * 220800).decode(), "alignment": {
            "characters": list(text), "character_start_times_seconds": [i * 9.2 / len(text) for i in range(len(text))],
            "character_end_times_seconds": [(i + 1) * 9.2 / len(text) for i in range(len(text))]}}

    def factory(root, config, consent, **kwargs):
        captured_configs.append(deepcopy(config))
        return ElevenLabsTTS(root, config, consent=consent, transport=transport, keys=kwargs.get("keys") or Keys())

    monkeypatch.setattr("newsflow.video.elevenlabs_tts.ElevenLabsKeys.key", lambda _: Keys().key())
    monkeypatch.setattr("newsflow.video.elevenlabs_tts.ElevenLabsTTS", factory)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", lambda *_a, **_k: pytest.fail("No vendor HTTP"))
    complete = api.complete

    def valid_script(evidence, seconds, opts):
        result = complete(evidence, seconds, opts)
        return healthy_three_scene(result, seconds)

    monkeypatch.setattr(api, "complete", valid_script)
    return {"app": app, "pipeline": api_pipeline, "coordinator": coordinator, "backend": backend,
            "service": service, "fake": fake, "voice_calls": voice_calls, "local": local,
            "configs": captured_configs, "sessions": sessions, "mode": mode}


def settle(p, identifier):
    p["coordinator"].future.result(timeout=240)
    return p["coordinator"].snapshot(identifier)


def revision(p, plan_id):
    with p["sessions"]() as session:
        return session.get(AIVideoPlan, plan_id).revision


def prepare_plan(p, identifier):
    job = settle(p, identifier)
    assert job["current_stage"] == "render" and job["status"] == "waiting_review", job
    plan_id = job["ai_plan_id"]
    with p["sessions"]() as session:
        rows = list(session.scalars(select(AIVideoScene).where(AIVideoScene.plan_id == plan_id)))
        assert len(rows) == 3 and all(scene.source == "generated" for scene in rows)
    p["service"].update_scenes(plan_id, revision(p, plan_id), [
        {"position": index, "source": "generated", "prompt": f"푸른 추상 배경과 상징 도형 장면 {index}", "model_path": MODEL}
        for index in range(3)])
    return plan_id


def generate(p, plan_id):
    quote = p["service"].estimate(plan_id)
    assert quote["accounting"] == "reported_usage" and quote["total"] == ""
    assert quote["remaining"] is None
    with pytest.raises(AIVideoError):
        p["service"].confirm_generation(plan_id, revision(p, plan_id), quote["total"], False)
    assert not p["fake"].calls
    p["service"].confirm_generation(plan_id, revision(p, plan_id), quote["total"], True)
    for _ in range(8):
        p["service"].tick()
        with p["sessions"]() as session:
            if all(s.status == "ready" for s in session.scalars(select(AIVideoScene).where(AIVideoScene.plan_id == plan_id))):
                break
    else:
        pytest.fail("Synthetic clips did not become ready")


@pytest.mark.parametrize("review", [True, False])
@pytest.mark.parametrize("voice", ["supertonic:F1", "elevenlabs"])
@pytest.mark.parametrize("ai", [False, True])
def test_eight_choice_matrix_real_ffmpeg(production, review, voice, ai, tmp_path):
    p = production
    identifier = start(p["pipeline"], voice=voice, production_options=options(review, voice, ai))
    job = settle(p, identifier)
    assert p["pipeline"][2].calls == ["search", "analysis", "script"]
    if review:
        assert (job["status"], job["current_stage"]) == ("waiting_review", "script")
        assert not p["voice_calls"] and not p["fake"].calls
        p["coordinator"].resume(identifier, job["revision"])
        job = settle(p, identifier)
    if ai:
        plan_id = prepare_plan(p, identifier)
        assert not p["voice_calls"] and not p["fake"].calls
        generate(p, plan_id)
        with pytest.raises(AIVideoError):
            p["service"].approve_compose(plan_id, revision(p, plan_id), True)
        p["service"].review(plan_id, revision(p, plan_id), {0, 1, 2}, True)
        with pytest.raises(AIVideoError):
            p["service"].approve_compose(plan_id, revision(p, plan_id), False)
        save_values(p["app"], video_default_voice="Missing changed voice", video_default_rate="5", video_default_pause_ms="1000")
        render_id = p["service"].approve_compose(plan_id, revision(p, plan_id), True)
        p["backend"].video.future.result(timeout=240)
        p["service"].sync()
        job = settle(p, identifier)
        assert job["render_job_id"] == render_id
        assert len([call for call in p["fake"].calls if call[0] == "submit"]) == 3
        with p["sessions"]() as session:
            policy = plan_policy(session, plan_id)
            assert policy["options"]["speech"] == {"rate": 0, "pause_ms": 250}
            assert len(policy["generation_approvals"]) == 1
            project = session.get(VideoProject, job["video_project_id"])
            assert len(project.snapshot["ai_clips"]) == 3
    else:
        assert not p["fake"].calls
    assert (job["status"], job["current_stage"]) == ("waiting_review", "validate"), job
    assert p["coordinator"].snapshot(identifier)["status"] != "completed"
    with p["sessions"]() as session:
        assert session.get(ContentDraft, job["content_draft_id"]).review_status == "review_required"
        assert session.scalar(select(PublishDraft)) is None
        audio = session.scalar(select(AudioTrack).where(AudioTrack.project_id == job["video_project_id"]))
        assert audio.provider == ("elevenlabs" if voice == "elevenlabs" else "supertonic")
    if voice == "elevenlabs":
        assert len([call for call in p["voice_calls"] if call[0] == "POST"]) == 3
        assert p["configs"][-1] == options(voice=voice)["elevenlabs"]
    else:
        assert p["voice_calls"] == []
    path = p["backend"].video.outputs / job["output_name"]
    media = FFprobeMediaInspector().inspect(path)
    assert (media["width"], media["height"], media["video_codec"], media["audio_codec"]) == (1080, 1920, "h264", "aac")
    count = (len(p["fake"].calls), len(p["voice_calls"]))
    p["service"].recover()
    p["service"].sync()
    assert count == (len(p["fake"].calls), len(p["voice_calls"]))
    p["coordinator"].resume(identifier, job["revision"])
    job = settle(p, identifier)
    assert job["status"] == "completed" and job["publish_draft_id"]
    with p["sessions"]() as session:
        draft = session.get(PublishDraft, job["publish_draft_id"])
        assert not draft.content_reviewed and draft.account_id is None
    output = Path(os.environ.get("NEWSFLOW_VALIDATION_OUTPUT", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    (output / f"matrix-{p['mode']}-{review}-{voice.replace(':','-')}-{ai}.json").write_text(json.dumps({
        "status": "PASS", "script_review": review, "voice": voice, "all_ai": ai, "media": media,
        "source_api_calls": p["pipeline"][2].calls, "actual_paid_calls": 0,
        "human_audio_quality": "NOT VERIFIED", "output": "temporary synthetic MP4; not committed"}, ensure_ascii=False, indent=2))
