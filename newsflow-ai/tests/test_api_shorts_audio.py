"""Measured WAV pacing for new API drafts; no real TTS, FFmpeg or provider requests."""

import wave
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from newsflow.db.models import AudioTrack, ContentDraft, IntelligenceRun, RenderJob, VideoProject
from newsflow.intelligence.news_usage import API_SCRIPT_METHOD
from newsflow.intelligence.provider import OfflineProvider, Options
from newsflow.video.engine import (
    FakeRenderAdapter,
    FFmpegAdapter,
    RenderError,
    RenderPlan,
    ScenePlan,
    fit_api_timings,
    prepare_audio,
)
from newsflow.video.tts import SpeechSettings, wav_duration


class MeasuredFakeTTS:
    def __init__(self, durations):
        self.durations = list(durations)
        self.calls = []

    def voices(self):
        return ["saved-korean-voice"]

    def synthesize(self, text, target, voice, seconds, speech=None):
        self.calls.append((text, voice, speech))
        duration = self.durations[len(self.calls) - 1]
        with wave.open(str(target), "wb") as output:
            output.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            output.writeframes(b"\0\0" * round(8000 * duration))


def strict_plan(duration):
    return RenderPlan(
        "API 초안 검토", [ScenePlan(duration / 3, f"주제 문장 {i}. 덧붙인 문장.", f"주제 {i}") for i in range(3)],
        [], voice="saved-korean-voice", speech=SpeechSettings(rate=1, pause_ms=200),
        fit_audio=True, strict_audio_fit=True,
    )


@pytest.mark.parametrize("duration", [30, 45, 60])
def test_api_audio_matches_target_once_without_rewriting(tmp_path, duration):
    plan = strict_plan(duration)
    tts = MeasuredFakeTTS([duration * .9 / 3] * 3)
    scenes, timings = prepare_audio(plan, tmp_path, tts, Event())
    assert sum(s.seconds for s in scenes) == duration
    assert [s.narration for s in scenes] == [s.narration for s in plan.scenes]
    assert len(tts.calls) == 3
    assert all(call[1:] == (plan.voice, plan.speech) for call in tts.calls)
    assert all(not t["shortened"] and 0 < t["seconds"] - t["audio_seconds"] <= 2.001 for t in timings)
    assert all(t["sentence_cues"][0]["end_ms"] == round(t["audio_seconds"] * 1000) for t in timings)
    assert timings[-1]["audio_end_ms"] <= duration * 1000


@pytest.mark.parametrize("duration", [30, 45, 60])
@pytest.mark.parametrize("coverage", [.3, .89, 1.1])
def test_api_underfill_and_overflow_stop_before_render_without_resynthesis(tmp_path, monkeypatch, duration, coverage):
    plan = strict_plan(duration)
    tts = MeasuredFakeTTS([duration * coverage / 3] * 3)
    adapter = FFmpegAdapter()
    monkeypatch.setattr(adapter, "check", lambda: (Path("fake-ffmpeg"), Path("fake-ffprobe"), "fake"))
    monkeypatch.setattr("newsflow.video.engine.font_path", lambda: Path("fake-font.ttf"))
    execute = Mock(side_effect=AssertionError("No rendering after pacing rejection"))
    monkeypatch.setattr(adapter, "execute", execute)
    with pytest.raises(RenderError) as caught:
        adapter.render(plan, tmp_path, tts, lambda _value: None, Event())
    assert caught.value.kind == "audio_review"
    assert len(tts.calls) == 3  # Even a multi-sentence script is never shortened/resubmitted.
    assert [call[0] for call in tts.calls] == [s.narration for s in plan.scenes]
    assert all(wav_duration(tmp_path / f"scene-{i:03d}.wav") > 0 for i in range(3))
    assert not list(tmp_path.glob("*.png")) and not list(tmp_path.glob("*.mp4"))
    execute.assert_not_called()


def test_api_scene_tail_cap_and_even_distribution():
    assert fit_api_timings([5, 10, 12], 30) == [6, 11, 13]
    with pytest.raises(RenderError) as caught:
        fit_api_timings([27], 30)  # 90% overall still leaves a long single static tail.
    assert caught.value.kind == "audio_review"


def test_api_strict_pacing_cannot_be_bypassed_with_fit_audio_off(tmp_path, monkeypatch):
    plan = replace(strict_plan(30), fit_audio=False)
    tts = MeasuredFakeTTS([1, 1, 1])
    adapter = FFmpegAdapter()
    monkeypatch.setattr(adapter, "check", lambda: (Path("fake-ffmpeg"), Path("fake-ffprobe"), "fake"))
    monkeypatch.setattr("newsflow.video.engine.font_path", lambda: Path("fake-font.ttf"))
    execute = Mock(side_effect=AssertionError("Strict pacing must run before rendering"))
    monkeypatch.setattr(adapter, "execute", execute)
    with pytest.raises(RenderError) as caught:
        adapter.render(plan, tmp_path, tts, lambda _value: None, Event())
    assert caught.value.kind == "audio_review"
    assert len(tts.calls) == 3
    execute.assert_not_called()
    assert not list(tmp_path.glob("*.png")) and not list(tmp_path.glob("*.mp4"))


def seed_draft(sessions, api):
    sources = {"articles": [{"id": 1, "title": "합성 자료", "sources": [
        {"publisher": "Fake source", "url": "https://example.com/test"},
    ]}]}
    if api:
        sources["script_method"] = API_SCRIPT_METHOD
    content = OfflineProvider().complete(sources, 30, Options())
    with sessions.begin() as session:
        run = IntelligenceRun(kind="script", status="success", provider="claude_api" if api else "offline",
                              options={}, evidence=sources, result=content, message="Fake fixture")
        session.add(run)
        session.flush()
        draft = ContentDraft(run_id=run.id, duration=30, content=content, sources=sources)
        session.add(draft)
        session.flush()
        return draft.id


@pytest.mark.parametrize("api", [False, True])
def test_api_pacing_policy_is_snapshotted_and_voice_preserved(app, api):
    video = app.state.video
    video.engine = FakeRenderAdapter()
    video.tts = MeasuredFakeTTS([9, 9, 9])
    try:
        identifier = video.start(seed_draft(app.state.sessions, api), 30, "saved-korean-voice", reviewed=True)
        video.future.result(timeout=10)
        with app.state.sessions() as session:
            job = session.get(RenderJob, identifier)
            project = session.get(VideoProject, job.project_id)
            audio = session.scalar(select(AudioTrack).where(AudioTrack.project_id == project.id))
            assert project.snapshot["speech"]["strict_audio_fit"] is api
            assert video.engine.calls[0].strict_audio_fit is api
            assert audio.voice == "saved-korean-voice"
            assert job.status == "simulated"  # Not a claim of a real playable video.
    finally:
        video.close()


def test_pacing_failure_is_sanitized_and_routes_back_to_editing(app):
    video = app.state.video
    video.engine = FakeRenderAdapter(RenderError("PRIVATE RESPONSE", kind="audio_review"))
    video.tts = MeasuredFakeTTS([9, 9, 9])
    try:
        identifier = video.start(seed_draft(app.state.sessions, True), 30, "saved-korean-voice", reviewed=True)
        video.future.result(timeout=10)
        with app.state.sessions() as session:
            job = session.get(RenderJob, identifier)
            assert job.status == "failed" and job.message.startswith("음성 분량 검토 필요")
            assert "대본을 수정" in job.message and "PRIVATE" not in job.message
            assert not video.output_path(job.output_name).exists()
    finally:
        video.close()
