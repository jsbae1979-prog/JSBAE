import json
import re
import sys
from itertools import pairwise
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from conftest import csrf
from PIL import Image
from sqlalchemy import select

from newsflow.db.models import AudioTrack, NewsArticle, RenderJob, Scene, SubtitleTrack, VideoProject
from newsflow.intelligence.service import IntelligenceService
from newsflow.video.engine import (
    FakeRenderAdapter,
    FFmpegAdapter,
    RenderError,
    RenderPlan,
    ScenePlan,
    card,
)
from newsflow.video.service import RenderBusy, VideoCoordinator, VideoError
from newsflow.video.tts import FakeTTS, TTSError, WindowsTTS, wav_duration


@pytest.fixture
def video(app):
    with app.state.sessions.begin() as session:
        session.add(
            NewsArticle(
                title="한국어 영상 제작 합성 뉴스",
                summary="합성 뉴스 요약",
                url="https://example.com/1",
                canonical_url="https://example.com/1",
                source_id=1,
                publisher="합성 언론",
            )
        )
    ai = IntelligenceService(app.state.sessions)
    draft_id = ai.generate(ai.analyze([1]), 30)
    app.state.video.engine = FakeRenderAdapter()
    app.state.video.tts = FakeTTS()
    yield app.state.video, draft_id
    app.state.video.close()


def wait(video):
    coordinator, _ = video
    coordinator.future.result(timeout=10)


@pytest.mark.parametrize("duration", [30, 45, 60])
def test_project_scene_audio_subtitles_snapshot(video, app, duration):
    coordinator, draft_id = video
    identifier = coordinator.start(draft_id, duration, reviewed=True)
    wait(video)
    with app.state.sessions() as session:
        job = session.get(RenderJob, identifier)
        project = session.get(VideoProject, job.project_id)
        scenes = list(session.scalars(select(Scene).order_by(Scene.position)))
        assert scenes[0].start_ms == 0 and scenes[-1].end_ms == duration * 1000
        assert all(a.end_ms == b.start_ms for a, b in pairwise(scenes))
        assert project.sources["articles"][0]["sources"][0]["url"] == "https://example.com/1"
        assert project.snapshot["draft_revision"] == 1
        assert session.scalar(select(SubtitleTrack)).cues[-1]["end_ms"] == duration * 1000
        assert session.scalar(select(AudioTrack)).status == "simulated"
        assert job.status == "simulated" and job.progress == 100 and not job.metadata_json["playable"]
    assert not list(coordinator.temporary.iterdir())


@pytest.mark.parametrize(
    "params",
    [
        {"duration": 29},
        {"reviewed": False},
        {"voice": "not-installed"},
        {"font_size": 5},
        {"subtitle_y": 1890},
        {"images": ["a.png"]},
        {"draft_id": 999},
    ],
)
def test_invalid_video_input(video, params):
    coordinator, draft_id = video
    options = {"draft_id": draft_id, "duration": 30, "reviewed": True}
    options.update(params)
    with pytest.raises((VideoError, RenderError)):
        coordinator.start(**options)
    assert not coordinator.guard.locked() and not coordinator.lock.is_locked


def test_fake_tts_and_wave_timing(tmp_path):
    fake = FakeTTS()
    path = tmp_path / "공백 포함 음성.wav"
    fake.synthesize("한국어 합성", path, "offline-silence", 1.5)
    assert wav_duration(path) == 1.5 and fake.calls == ["한국어 합성"]
    with pytest.raises(TTSError):
        fake.synthesize("x", path, "unknown", 1)
    path.write_bytes(b"bad")
    with pytest.raises(TTSError):
        wav_duration(path)


@pytest.mark.parametrize("error", [RuntimeError("SECRET"), RenderError("SECRET"), TimeoutError("SECRET")])
def test_render_failure_safe_log_cleanup(video, app, error):
    coordinator, draft_id = video
    coordinator.engine = FakeRenderAdapter(error)
    identifier = coordinator.start(draft_id, 30, reviewed=True)
    wait(video)
    with app.state.sessions() as session:
        job = session.get(RenderJob, identifier)
        assert job.status == "failed" and job.finished_at and "SECRET" not in job.message
        assert not coordinator.output_path(job.output_name).exists()
        assert session.scalar(select(AudioTrack)).status == "failed"
    assert not list(coordinator.temporary.iterdir())


def test_tts_failure_safe_log(video, app):
    coordinator, draft_id = video
    coordinator.tts = FakeTTS(TTSError("SECRET"))
    identifier = coordinator.start(draft_id, 30, reviewed=True)
    wait(video)
    with app.state.sessions() as session:
        job = session.get(RenderJob, identifier)
        assert job.status == "failed" and "음성 생성" in job.message and "SECRET" not in job.message


def test_disk_space_before_creating_job(video, app):
    coordinator, draft_id = video
    with (
        patch("newsflow.video.service.shutil.disk_usage", return_value=SimpleNamespace(free=0)),
        pytest.raises(VideoError),
    ):
        coordinator.start(draft_id, 30, reviewed=True)
    with app.state.sessions() as session:
        assert session.scalar(select(RenderJob)) is None
    assert not coordinator.guard.locked()


def test_existing_output_never_overwritten(video, app):
    coordinator, draft_id = video
    existing = coordinator.outputs / ("video-" + "a" * 32 + ".mp4")
    existing.write_bytes(b"USER_EXISTING_VIDEO")
    with patch.object(coordinator, "output_path", return_value=existing):
        identifier = coordinator.start(draft_id, 30, reviewed=True)
        wait(video)
    assert existing.read_bytes() == b"USER_EXISTING_VIDEO"
    with app.state.sessions() as session:
        assert session.get(RenderJob, identifier).status == "failed"


@pytest.mark.parametrize(
    "name", ["../secret.png", "C:\\file.jpg", "http://evil/image.jpg", "a/b.png", "a\x00.png"]
)
def test_local_asset_paths_reject_traversal(video, name):
    with pytest.raises(VideoError):
        video[0].asset(name)


def test_local_asset_permission_and_korean_space_path(video, app):
    coordinator, draft_id = video
    Image.new("RGB", (120, 120), "blue").save(coordinator.assets / "허가된 이미지.png")
    images = ["허가된 이미지.png", "", ""]
    with pytest.raises(VideoError):
        coordinator.start(draft_id, 30, images=images, reviewed=True)
    identifier = coordinator.start(draft_id, 30, images=images, reviewed=True, asset_permission=True)
    wait(video)
    with app.state.sessions() as session:
        assert session.get(RenderJob, identifier).status == "simulated"
        assert session.scalar(select(Scene).where(Scene.position == 0)).material == "허가된 이미지.png"
    assert "허가된 이미지.png" in coordinator.assets_list()


def test_fake_image_and_symlink_rejected(video):
    coordinator, _ = video
    path = coordinator.assets / "fake.png"
    path.write_text("<svg>not png</svg>")
    with pytest.raises(VideoError):
        coordinator.asset(path.name)
    with patch.object(Path, "is_symlink", return_value=True), pytest.raises(VideoError):
        coordinator.asset("allowed.png")


def test_same_and_other_coordinator_limit_and_active_recovery(video, app):
    coordinator, draft_id = video
    entered, released = Event(), Event()

    class Waiting(FakeRenderAdapter):
        def render(self, *args):
            entered.set()
            assert released.wait(10)
            return super().render(*args)

    coordinator.engine = Waiting()
    identifier = coordinator.start(draft_id, 30, reviewed=True)
    assert entered.wait(3)
    second = VideoCoordinator(app.state.sessions, app.state.config.data_dir, FakeRenderAdapter())
    try:
        with pytest.raises(RenderBusy):
            coordinator.start(draft_id, 30, reviewed=True)
        with pytest.raises(RenderBusy):
            second.start(draft_id, 30, reviewed=True)
        second.recover()
        coordinator.recover()
        with app.state.sessions() as session:
            assert session.get(RenderJob, identifier).status == "running"
    finally:
        released.set()
        wait(video)
        second.close()


def test_restart_interrupted_job_and_own_temp_cleanup(video, app):
    coordinator, draft_id = video
    identifier = coordinator.start(draft_id, 30, reviewed=True)
    wait(video)
    with app.state.sessions.begin() as session:
        job = session.get(RenderJob, identifier)
        job.status = "running"
        session.scalar(select(AudioTrack)).status = "pending"
    orphan = coordinator.temporary / "job-1-abcd"
    orphan.mkdir()
    (orphan / "unfinished.mp4").write_bytes(b"partial")
    keep = coordinator.temporary / "user-folder"
    keep.mkdir()
    coordinator.recover()
    with app.state.sessions() as session:
        job = session.get(RenderJob, identifier)
        assert job.status == "interrupted" and job.finished_at
        assert session.scalar(select(AudioTrack)).status == "interrupted"
    assert not orphan.exists() and keep.exists()


def test_unique_output_names_and_preview_fake_denial(video, client, app):
    coordinator, draft_id = video
    identifiers = []
    for _ in range(2):
        identifiers.append(coordinator.start(draft_id, 30, reviewed=True))
        wait(video)
    with app.state.sessions() as session:
        names = [session.get(RenderJob, i).output_name for i in identifiers]
    assert len(set(names)) == 2
    assert client.get(f"/video/jobs/{identifiers[0]}/file").status_code == 404


def test_video_gui_post_status_csrf_and_no_key(video, client, monkeypatch):
    _coordinator, draft_id = video
    monkeypatch.setenv("NEWSFLOW_AI_API_KEY", "SECRET-KEY-SENTINEL")
    response = client.get(f"/video?draft_id={draft_id}")
    assert response.status_code == 200 and "音声" not in response.text and "Offline · 무음" in response.text
    assert "SECRET-KEY-SENTINEL" not in response.text
    assert (
        client.post(
            "/video/render", data={"draft_id": draft_id, "duration": 30, "reviewed": "true"}
        ).status_code
        == 403
    )
    token = csrf(client)
    assert (
        client.post(
            "/video/render",
            data={"csrf_token": token, "draft_id": draft_id, "duration": 30, "reviewed": "true"},
            headers={"Origin": "null"},
        ).status_code
        == 403
    )
    response = client.post(
        "/video/render", data={"csrf_token": token, "draft_id": draft_id, "duration": 30, "reviewed": "true"}
    )
    assert response.status_code == 200
    wait(video)
    assert client.get("/api/video/jobs/1").json()["status"] == "simulated"
    assert "실제 MP4가 아니며" in client.get("/video?job_id=1").text
    assert client.get("/video?draft_id=999").status_code == 404
    assert client.get("/api/video/jobs/999").status_code == 404


def test_ffmpeg_arguments_no_shell_interpolation(tmp_path):
    binary = tmp_path / "ffmpeg.exe"
    scene = ScenePlan(2, "ignored $(cmd) text", "한글;caption")
    command = FFmpegAdapter.command(
        binary, scene, tmp_path / "공백 ' 이미지.png", tmp_path / "소리.wav", tmp_path / "clip.mp4"
    )
    assert command[0] == str(binary)
    assert "-n" in command and "-y" not in command
    assert str(tmp_path / "공백 ' 이미지.png") in command
    assert scene.narration not in command and scene.caption not in command
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"


def test_missing_and_invalid_ffmpeg_version(tmp_path):
    with pytest.raises(RenderError):
        FFmpegAdapter(tmp_path / "missing.exe").check()
    binary = tmp_path / "ffmpeg.exe"
    binary.touch()
    with (
        patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=b"Not ffmpeg")),
        pytest.raises(RenderError),
    ):
        FFmpegAdapter(binary, binary).check()


def test_ffmpeg_nonzero_exit_and_cancel(tmp_path):
    result = SimpleNamespace(returncode=1, poll=lambda: 1)
    result.__enter__ = lambda _: result
    from unittest.mock import MagicMock

    process = MagicMock()
    process.__enter__.return_value = process
    process.poll.return_value = 1
    process.returncode = 1
    with patch("subprocess.Popen", return_value=process) as call, pytest.raises(RenderError):
        FFmpegAdapter.execute(["ffmpeg", "args"], tmp_path, Event())
    assert call.call_args.kwargs["shell"] is False
    event = Event()
    event.set()
    process.poll.return_value = None
    with patch("subprocess.Popen", return_value=process), pytest.raises(RenderError):
        FFmpegAdapter.execute(["ffmpeg"], tmp_path, event)
    process.kill.assert_called_once()


@pytest.mark.parametrize(
    "payload",
    [
        {"streams": [], "format": {"duration": "3"}},
        {
            "streams": [
                {"codec_type": "video", "codec_name": "vp9", "width": 1080, "height": 1920},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": "3"},
        },
    ],
)
def test_bad_output_probe_rejected(tmp_path, payload):
    with (
        patch(
            "subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=json.dumps(payload).encode())
        ),
        pytest.raises(RenderError),
    ):
        FFmpegAdapter.inspect(tmp_path / "probe", tmp_path / "out.mp4", 3)


def test_caption_safe_area_and_title_as_pixels(tmp_path, monkeypatch):
    # Use installed font only in this unit fixture; no dependency on an OS font installation.
    from PIL import ImageFont

    fakefont = ImageFont.load_default(size=20)
    plan = RenderPlan(
        "<script>title</script>", [ScenePlan(1, "narration", "자막")], [], font_size=48, subtitle_y=1420
    )
    with patch("newsflow.video.engine.ImageFont.truetype", return_value=fakefont):
        card(plan, plan.scenes[0], 0, tmp_path / "card.png", tmp_path / "font.ttf")
    with Image.open(tmp_path / "card.png") as image:
        assert image.size == (1080, 1920) and image.format == "PNG"
    plan = RenderPlan("title", [ScenePlan(1, "text", "x" * 150)], [], font_size=64, subtitle_y=1500)
    font = ImageFont.load_default(size=64)
    with patch("newsflow.video.engine.ImageFont.truetype", return_value=font), pytest.raises(RenderError):
        card(plan, plan.scenes[0], 0, tmp_path / "unsafe.png", tmp_path / "font.ttf")


def test_windows_tts_command_safe_and_platform_guard(tmp_path, monkeypatch):
    provider = WindowsTTS()
    with (
        patch("newsflow.video.tts.sys.platform", "win32"),
        patch(
            "subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=b'["Installed synthetic voice"]'),
        ) as call,
    ):
        assert provider.voices() == ["Installed synthetic voice"]
    assert call.call_args.kwargs["shell"] is False
    assert call.call_args.args[0] == [sys.executable, "-m", "newsflow.video.windows_sapi", "-ListVoices"]
    assert not any("powershell" in part.lower() for part in call.call_args.args[0])
    with patch("newsflow.video.tts.sys.platform", "linux"), pytest.raises(TTSError):
        provider.voices()


def test_filename_traversal_and_cancelled_start(video):
    coordinator, draft_id = video
    for name in ["../x.mp4", "C:/file.mp4", "video-bad.mp4"]:
        with pytest.raises(VideoError):
            coordinator.output_path(name)
    coordinator.close()
    with pytest.raises(VideoError):
        coordinator.start(draft_id, 30, reviewed=True)


def test_close_during_render_is_interrupted(video, app):
    coordinator, draft_id = video
    entered = Event()

    class UntilCancelled(FakeRenderAdapter):
        def render(self, plan, work, tts, progress, cancel):
            entered.set()
            assert cancel.wait(5)
            return super().render(plan, work, tts, progress, cancel)

    coordinator.engine = UntilCancelled()
    identifier = coordinator.start(draft_id, 30, reviewed=True)
    assert entered.wait(3)
    coordinator.close()
    with app.state.sessions() as session:
        job = session.get(RenderJob, identifier)
        assert job.status == "interrupted" and job.progress < 100
        assert not coordinator.output_path(job.output_name).exists()
    assert not list(coordinator.temporary.iterdir())


def test_child_process_secrets_removed(monkeypatch):
    from newsflow.video.tts import local_process_env

    monkeypatch.setenv("NEWSFLOW_AI_API_KEY", "SYNTHETIC-SECRET")
    monkeypatch.setenv("GITHUB_TOKEN", "SYNTHETIC-TOKEN")
    monkeypatch.setenv("NEWSFLOW_SECRET_KEY", "SYNTHETIC-SESSION")
    monkeypatch.setenv("PATH", "local-tools")
    env = local_process_env()
    assert not {"NEWSFLOW_AI_API_KEY", "GITHUB_TOKEN", "NEWSFLOW_SECRET_KEY"} & env.keys()
    assert env["PATH"] == "local-tools"


def test_lock_permission_failure_releases_guard(video):
    coordinator, draft_id = video
    with (
        patch.object(coordinator.lock, "acquire", side_effect=OSError("SYNTHETIC-SECRET")),
        pytest.raises(VideoError),
    ):
        coordinator.start(draft_id, 30, reviewed=True)
    assert not coordinator.guard.locked()


def test_cleanup_completes_before_success(video, app):
    from tempfile import TemporaryDirectory

    coordinator, draft_id = video
    observed = []

    class ObservedTemporary(TemporaryDirectory):
        def __exit__(self, *args):
            with app.state.sessions() as session:
                observed.append(session.scalar(select(RenderJob)).status)
            return super().__exit__(*args)

    with patch("newsflow.video.service.TemporaryDirectory", ObservedTemporary):
        coordinator.start(draft_id, 30, reviewed=True)
        wait(video)
    assert observed == ["running"]


# --- Phase 5C.1 package C: FFmpeg audio-fit branch and Video Studio voice labels ---

from newsflow.video.engine import AUDIO_TAIL_SECONDS
from newsflow.video.tts import TTSPolicyError


class KoreanFitTTS(FakeTTS):
    def voices(self):
        return ["Fake Korean"]

    def synthesize(self, text, target, voice, seconds, speech=None):
        assert voice == "Fake Korean"
        FakeTTS.synthesize(self, text, target, "offline-silence", seconds, speech)


def fit_patches(tmp_path):
    from PIL import ImageFont

    return (
        patch.object(FFmpegAdapter, "check", return_value=(tmp_path / "ffmpeg", tmp_path / "ffprobe", "7.0")),
        patch.object(FFmpegAdapter, "execute"),
        patch.object(FFmpegAdapter, "inspect", return_value={"adapter": "ffmpeg", "playable": True, "duration": 30.0}),
        patch("newsflow.video.engine.font_path", return_value=tmp_path / "font.ttf"),
        patch("newsflow.video.engine.ImageFont.truetype", return_value=ImageFont.load_default(size=20)),
    )


def test_ffmpeg_audio_fit_measures_narration_first_and_keeps_total(tmp_path):
    scenes = [ScenePlan(10, "첫 장면 내레이션입니다.", "자막 1"), ScenePlan(10, "둘째 장면입니다.", "자막 2"),
              ScenePlan(10, "셋째 장면입니다.", "자막 3")]
    plan = RenderPlan("제목", scenes, [], voice="Fake Korean", fit_audio=True)
    tts = KoreanFitTTS(seconds_per_call=2.0)
    check, execute, inspect, font, truetype = fit_patches(tmp_path)
    with check, execute as run, inspect, font, truetype:
        final, metadata = FFmpegAdapter().render(plan, tmp_path, tts, lambda value: None, Event())
    assert final == tmp_path / "result.mp4" and run.call_count == 4  # three clips and the concat
    assert metadata["audio_fit"] is True and metadata["audio"] == "voice"
    timings = metadata["scene_timings"]
    assert len(timings) == 3 and abs(sum(t["seconds"] for t in timings) - 30) < 0.01
    assert all(t["seconds"] >= t["audio_seconds"] + AUDIO_TAIL_SECONDS - 0.001 for t in timings)
    assert all(abs(t["audio_seconds"] - 2.0) < 0.01 for t in timings)
    assert tts.calls == [s.narration for s in scenes]  # synthesized once per scene, raw narration text


def test_ffmpeg_audio_fit_overflow_stops_before_rendering(tmp_path):
    scenes = [ScenePlan(10, "첫 장면.", "자막 1"), ScenePlan(10, "둘째 장면.", "자막 2"), ScenePlan(10, "셋째.", "자막 3")]
    plan = RenderPlan("제목", scenes, [], voice="Fake Korean", fit_audio=True)
    check, execute, inspect, font, truetype = fit_patches(tmp_path)
    with check, execute as run, inspect, font, truetype, pytest.raises(RenderError, match="초과"):
        FFmpegAdapter().render(plan, tmp_path, KoreanFitTTS(seconds_per_call=12.0), lambda value: None, Event())
    assert run.call_count == 0 and not list(tmp_path.glob("*.png"))


def test_quality_settings_persist_without_new_schema(video, app):
    from newsflow.video.tts import SpeechSettings

    coordinator, draft_id = video
    job_id = coordinator.start(draft_id, 30, reviewed=True, theme='culture',
                               subtitle_style='outline', speech=SpeechSettings(-1, 400))
    wait(video)
    with app.state.sessions() as session:
        job = session.get(RenderJob, job_id)
        project = session.get(VideoProject, job.project_id)
        assert project.snapshot['quality'] == {'theme': 'culture', 'subtitle_style': 'outline'}
        assert project.snapshot['speech']['rate'] == -1
        assert project.snapshot['speech']['pause_ms'] == 400


def test_measured_caption_render_keeps_audio_input_and_stored_cues(tmp_path):
    class TimedTTS(KoreanFitTTS):
        def synthesize(self, text, target, voice, seconds, speech=None):
            super().synthesize(text, target, voice, seconds, speech)
            target.with_suffix('.cues.json').write_text(json.dumps([
                {'start': 0.0, 'end': 0.7, 'text': '첫 문장.'},
                {'start': 1.0, 'end': 2.0, 'text': '둘째 문장.'},
            ]), encoding='utf-8')

    plan = RenderPlan('제목', [ScenePlan(30, '첫 문장. 둘째 문장.', '장면 요약')], [],
                      voice='Fake Korean', fit_audio=True)
    check, execute, inspect, font, truetype = fit_patches(tmp_path)
    with check, execute as run, inspect, font, truetype:
        _, metadata = FFmpegAdapter().render(plan, tmp_path, TimedTTS(seconds_per_call=2), lambda _: None, Event())
    command = run.call_args_list[0].args[0]
    inputs = [command[i + 1] for i, value in enumerate(command) if value == '-i']
    assert inputs == [str(tmp_path / 'captions-000.txt'), str(tmp_path / 'scene-000.wav')]
    assert 'fps=30,fade=t=in:st=0:d=0.12' in command
    assert metadata['subtitle_cues'][1] == {'start_ms': 1000, 'end_ms': 2000, 'text': '둘째 문장.', 'scene': 0}


def test_video_studio_labels_voices_with_culture_and_never_preselects_non_korean(video, client, monkeypatch):
    _coordinator, draft_id = video
    monkeypatch.setattr("newsflow.gui.video_routes.sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(WindowsTTS, "voice_details", lambda self: [
        {"name": "Zira", "culture": "en-US"}, {"name": "Heami", "culture": "ko-KR"},
    ])
    text = client.get(f"/video?draft_id={draft_id}").text
    assert '<option value="offline-silence" selected>Offline · 무음' in text
    assert '<option value="Heami">Windows · Heami · ko-KR</option>' in text
    assert '<option value="Zira">Windows · Zira · en-US (한국어 아님 · 한국어 대본 읽기 품질 미보장)</option>' in text
    assert text.index('value="Heami"') < text.index('value="Zira"')
    assert not re.search(r'<option value="(Heami|Zira)"[^>]*selected', text)  # only the silent option is selected

    def blocked(self):
        raise TTSPolicyError("정책")

    monkeypatch.setattr(WindowsTTS, "voice_details", blocked)
    text = client.get(f"/video?draft_id={draft_id}").text
    assert "실행 정책" in text and "Windows · " not in text
