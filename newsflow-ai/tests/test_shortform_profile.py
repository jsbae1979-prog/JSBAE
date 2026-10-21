"""Synthetic evidence, Fake APIs/TTS, temporary DBs; no operating store access."""
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event

import pytest
from conftest import csrf
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from test_api_news_pipeline import settled, start

pytest_plugins = ("test_api_news_pipeline",)

from newsflow.db.models import AppSetting, ContentDraft, VideoProject
from newsflow.intelligence.provider import ProviderTimeoutError
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.shortform import Shortform, allowed_duration, frozen, read, save, validate_script
from newsflow.video.engine import FFmpegAdapter, RenderError, RenderPlan, ScenePlan, prepare_audio
from newsflow.video.service import VideoCoordinator
from newsflow.video.shortform_visuals import CAPTION_BOX, caption_chunks, write_captions
from newsflow.video.tts import FakeTTS


@pytest.fixture(autouse=True)
def no_external_connections(monkeypatch):
    import socket

    original = socket.socket.connect
    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise AssertionError("External network forbidden in shortform tests")
        return original(sock, address)
    monkeypatch.setattr(socket.socket, "connect", local_only)


def script(duration=30):
    hook = "공개 뉴스 자료의 핵심을 살펴봅니다."
    ending = "확보한 자료의 범위에서 이해하는 것이 중요합니다."
    return {"title": "합성 뉴스 자료 검토", "hook": hook, "summary": "실제 보도가 아닌 테스트 자료",
            "closing": ending, "scenes": [
                {"seconds": 3, "narration": hook, "caption": "자료의 핵심", "material": "직접 만든 카드"},
                {"seconds": duration-6, "narration": "제공된 제목과 요약을 중심으로 내용을 정리하고 자료에 없는 사실은 단정하지 않습니다.",
                 "caption": "입력 자료의 범위", "material": "직접 만든 카드"},
                {"seconds": 3, "narration": ending, "caption": "출처 직접 확인", "material": "직접 만든 카드"}]}


def test_defaults_and_local_settings_preserve_other_preferences(client, app):
    assert not read(app.state.sessions).enabled
    with app.state.sessions.begin() as session:
        session.merge(AppSetting(key="video_default_voice", value="elevenlabs"))
        session.merge(AppSetting(key="video_ai_job_limit", value="5"))
    token = csrf(client)
    response = client.post("/production/shortform", data={"csrf_token": token, "enabled": "true", "hook": "true",
        "captions": "true", "motion": "true", "source": "true", "tight_ending": "true", "speed": "1.1", "target_seconds": "25"}, follow_redirects=False)
    assert response.status_code == 303
    assert read(app.state.sessions) == Shortform(enabled=True, target_seconds=25)
    with app.state.sessions() as session:
        assert session.get(AppSetting, "video_default_voice").value == "elevenlabs"
        assert session.get(AppSetting, "video_ai_job_limit").value == "5"
    html = client.get("/simple-settings").text
    assert "숏폼 옵션 저장" in html and 'value="25"' in html
    assert client.post("/production/shortform", data={"csrf_token": token, "speed": "nan"}).status_code == 422
    assert read(app.state.sessions).target_seconds == 25


@pytest.mark.parametrize("changes", [{"speed": 0.9}, {"speed": float("nan")}, {"speed": 1.3}, {"speed": True},
                                    {"target_seconds": 14}, {"target_seconds": 36}, {"target_seconds": True}, {"hook": 1}])
def test_invalid_profile_fails_closed(changes):
    with pytest.raises(ValueError):
        Shortform(**changes)


@pytest.mark.parametrize("field", ["hook", "captions", "motion", "source", "tight_ending"])
def test_independent_feature_switches(field):
    profile = replace(Shortform(enabled=True), **{field: False})
    assert frozen({"shortform": asdict(profile)}) == profile
    assert not getattr(profile, field)


@pytest.mark.parametrize("duration", [15, 20, 25, 30, 35])
def test_opt_in_lengths_and_hook_contract(duration):
    value = script(duration)
    evidence = {"shortform": asdict(Shortform(enabled=True))}
    assert allowed_duration(duration, True)
    assert allowed_duration(duration) == (duration == 30)
    validate_script(value, evidence)
    value["scenes"][0]["narration"] = "잘못된 훅"
    with pytest.raises(ValueError):
        validate_script(value, evidence)
    assert allowed_duration(45) and allowed_duration(60)


def test_safe_caption_layout_and_ass_escape(tmp_path, monkeypatch):
    # Unit contracts do not depend on Korean font installation on CI runners.
    selected_font = ImageFont.load_default(size=72)
    monkeypatch.setattr(ImageFont, "truetype", lambda *a, **kw: selected_font)
    font = Path("fixture-font.ttf")
    cues = [{"start_ms": 0, "end_ms": 6000, "text": "안전 점검 3가지 {\\pos(0,0)} " * 8}]
    chunks = caption_chunks(cues, font, 72)
    assert len(chunks) > 1 and all(1 <= len(c["lines"]) <= 2 for c in chunks)
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    selected = ImageFont.truetype(str(font), 72)
    left, top, right, bottom = CAPTION_BOX
    assert top >= 1920*.35 and bottom <= 1920*.65 and right <= 1080*.85
    assert all(draw.textlength(line, font=selected) <= right-left for c in chunks for line in c["lines"])
    target = tmp_path / "caption.ass"
    write_captions(target, cues, font, 72)
    ass = target.read_text("utf-8-sig")
    assert r"\pos(495,960)" in ass and r"\pos(0,0)" not in ass
    assert r"\c&H00D7FF&" in ass and chunks[-1]["end_ms"] == 6000


def test_filter_composition_keeps_motion_subtitles_ai_labels_and_no_shell():
    cmd = ["ffmpeg", "-filter_complex", "[0:v][1:v]overlay=0:0[v]", "out.mp4"]
    cmd = FFmpegAdapter.add_filter(cmd, "zoompan=z=1.01:d=1:s=1080x1920")
    cmd = FFmpegAdapter.add_filter(cmd, "ass=scene-000.ass")
    graph = cmd[cmd.index("-filter_complex")+1]
    assert graph.count("[style0]") == 2 and graph.count("[style1]") == 2
    assert "overlay" in graph and "zoompan" in graph and "ass=" in graph


@pytest.mark.parametrize("audio", [[4, 12, 4], [2, 3, 2], [2, 32, 4]])
def test_audio_mismatch_does_not_resynthesize_or_pad(tmp_path, audio):
    class TTS(FakeTTS):
        def synthesize(self, *args):
            self.seconds_per_call = audio[len(self.calls)]
            super().synthesize(*args)
    tts = TTS()
    plan = RenderPlan("합성", [ScenePlan(s["seconds"], s["narration"], s["caption"]) for s in script()["scenes"]], [],
                      voice="offline-silence", shortform=Shortform(enabled=True, speed=1))
    with pytest.raises(RenderError, match="훅|분량"):
        prepare_audio(plan, tmp_path, tts, Event())
    assert len(tts.calls) == 3


@pytest.mark.parametrize("duration", [15, 30, 35])
def test_api_pipeline_freezes_profile_and_keeps_one_call_each(api_pipeline, duration, monkeypatch):
    _coordinator, _backend, provider, sessions, _mode, rss = api_pipeline
    save(sessions, Shortform(enabled=True))
    seen = []
    def complete(evidence, seconds, options):
        provider.calls.append("script")
        seen.append(deepcopy(evidence))
        return script(seconds)
    monkeypatch.setattr(provider, "complete", complete)
    identifier = start(api_pipeline, duration=duration)
    result = settled(api_pipeline, identifier)
    assert result["status"] == "waiting_review", result
    assert provider.calls == ["search", "analysis", "script"] and rss.calls == []
    assert seen[0]["shortform_contract"]["hook"] is True
    assert seen[0]["shortform"]["speed"] == 1.1
    with sessions() as session:
        draft = session.get(ContentDraft, result["content_draft_id"])
        assert draft.duration == duration and draft.review_status == "review_required"
        assert draft.sources["shortform"]["enabled"]
    save(sessions, Shortform(enabled=False))
    assert seen[0]["shortform"]["enabled"]  # existing draft snapshot does not follow changed defaults


def test_api_failure_no_retry_or_provider_switch(api_pipeline, monkeypatch):
    _coordinator, _backend, provider, sessions, _mode, _rss = api_pipeline
    save(sessions, Shortform(enabled=True))
    def fail(*args):
        provider.calls.append("script")
        raise ProviderTimeoutError()
    monkeypatch.setattr(provider, "complete", fail)
    result = settled(api_pipeline, start(api_pipeline))
    assert result["status"] == "failed"
    assert provider.calls == ["search", "analysis", "script"]


def test_review_cannot_remove_hook_gate():
    value = script()
    evidence = {"shortform": asdict(Shortform(enabled=True))}
    value["hook"] = "왜곡"
    with pytest.raises(IntelligenceError):
        IntelligenceService.check_news_usage(value, evidence)


def test_legacy_draft_untouched_when_profile_changes(app):
    from newsflow.db.models import IntelligenceRun
    from newsflow.video.engine import FakeRenderAdapter

    sessions = app.state.sessions
    with sessions.begin() as session:
        run = IntelligenceRun(kind="script", provider="offline", status="success", evidence={}, options={}, result={}, message="합성")
        session.add(run)
        session.flush()
        draft = ContentDraft(run_id=run.id, duration=30, content=script(), sources={})
        session.add(draft)
        session.flush()
        identifier = draft.id
    save(sessions, Shortform(enabled=True))
    engine = FakeRenderAdapter()
    video = VideoCoordinator(sessions, app.state.config.data_dir, engine, FakeTTS())
    try:
        video.start(identifier, 30, "offline-silence", reviewed=True)
        video.future.result(timeout=10)
        assert not engine.calls[0].shortform.enabled
        with sessions() as session:
            project = session.scalar(select(VideoProject).where(VideoProject.draft_id == identifier))
            assert project.snapshot["shortform"]["enabled"] is False
    finally:
        video.close()


def test_first_ai_scene_priority_is_only_a_plan_and_does_not_generate(app):
    from newsflow.db.models import AIVideoScene, IntelligenceRun

    with app.state.sessions.begin() as session:
        run = IntelligenceRun(kind="script", provider="offline", status="success", evidence={}, options={}, result={}, message="合成")
        session.add(run)
        session.flush()
        draft = ContentDraft(run_id=run.id, duration=20, content=script(20), sources={"shortform": asdict(Shortform(enabled=True))})
        session.add(draft)
        session.flush()
        identifier = draft.id
    plan_id = app.state.video_ai.create_plan(identifier, 20)
    with app.state.sessions() as session:
        scenes = list(session.scalars(select(AIVideoScene).where(AIVideoScene.plan_id == plan_id).order_by(AIVideoScene.position)))
        assert [s.source for s in scenes] == ["generated", "card", "card"]
        assert all(s.status == "planned" and not s.request_id for s in scenes)


def test_caption_hook_uses_narration_when_adapter_has_no_alignment(tmp_path):
    tts = FakeTTS(seconds_per_call=6)
    # First scene must be <=3s: use a fixed-duration adapter without timestamps.
    original = tts.synthesize
    def synthesize(*args):
        tts.seconds_per_call = 2 if not tts.calls else 8
        original(*args)
    tts.synthesize = synthesize
    plan = RenderPlan("합성", [ScenePlan(s["seconds"],s["narration"],s["caption"]) for s in script()["scenes"]], [],
                      voice="offline-silence", shortform=Shortform(enabled=True, speed=1))
    scenes, timings = prepare_audio(plan, tmp_path, tts, Event())
    assert timings[0]["sentence_cues"][0]["text"] == script()["hook"]
    assert .34 <= scenes[-1].seconds-timings[-1]["audio_seconds"] <= .39
    assert 15 <= sum(s.seconds for s in scenes) < 30
