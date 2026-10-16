import json
import sys
import wave
from pathlib import Path
from threading import Event, Timer

import pytest
from conftest import csrf
from sqlalchemy import select

from newsflow.db.models import ContentDraft, NewsArticle, NewsSource
from newsflow.intelligence.claude_code import ClaudeCodeProvider, ProviderCancelled, cli_env
from newsflow.intelligence.provider import (
    OfflineProvider,
    Options,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from newsflow.intelligence.schema import Script
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.intelligence.settings import usage_this_month
from newsflow.video.engine import RenderError, RenderPlan, ScenePlan, prepare_audio, write_ass
from newsflow.video.tts import SpeechSettings, WindowsTTS, wav_duration


def wav(path, seconds):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * round(seconds * 16000))


@pytest.fixture
def cli(monkeypatch, tmp_path):
    provider = ClaudeCodeProvider()
    monkeypatch.setattr(provider, "status", lambda: {"ready": True})
    monkeypatch.setattr("newsflow.intelligence.claude_code.cli_path", lambda: Path(sys.executable))
    script = tmp_path / "fake_cli.py"

    def configure(code):
        script.write_text(code, encoding="utf-8")
        monkeypatch.setattr(provider, "command", lambda *_args: [sys.executable, str(script)])
        return provider

    return configure


def test_cli_structured_response_and_usage(cli):
    result = OfflineProvider().complete({"articles": [{"title": "합성 시험"}]}, 30, Options())
    envelope = {"structured_output": result, "usage": {"input_tokens": 10, "output_tokens": 20}}
    provider = cli("import json,sys\nassert json.load(sys.stdin)['duration']==30\nprint(" + repr(json.dumps(envelope)) + ")")
    assert provider.complete({}, 30, Options()) == result
    assert provider.last_usage["total_tokens"] == 30


@pytest.mark.parametrize("text,error", [("rate limit", ProviderRateLimitError), ("auth failed", ProviderAuthError)])
def test_cli_errors_sanitized(cli, text, error):
    provider = cli("print(" + repr(json.dumps({"is_error": True, "result": text + " PRIVATE"})) + ")")
    with pytest.raises(error) as caught:
        provider.complete({}, 30, Options())
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("response", ['{"structured_output":{}}', 'not json'])
def test_cli_bad_response(cli, response):
    provider = cli("print(" + repr(response) + ")")
    with pytest.raises(ProviderResponseError):
        provider.complete({}, 30, Options())


def test_cli_timeout_and_cancel(cli):
    provider = cli("import time\ntime.sleep(10)")
    with pytest.raises(ProviderTimeoutError):
        provider.complete({}, 30, Options(timeout=1))
    timer = Timer(0.2, provider.cancel)
    timer.start()
    try:
        with pytest.raises(ProviderCancelled):
            provider.complete({}, 30, Options())
    finally:
        timer.join()
    assert provider.cancel() is False


def test_cli_security_flags_and_env(monkeypatch):
    args = ClaudeCodeProvider.command(Path("claude.exe"), Script.model_json_schema(), "fixed", "sonnet")
    assert args[args.index("--tools") + 1] == ""
    assert "--restricted" in args and "--strict-mcp-config" in args
    assert "--no-session-persistence" in args and "--dangerously-skip-permissions" not in args
    monkeypatch.setenv("ANTHROPIC_API_KEY", "private")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "private")
    assert "ANTHROPIC_API_KEY" not in cli_env() and "CLAUDE_CODE_OAUTH_TOKEN" not in cli_env()


def test_timed_sapi_joins_actual_sentence_wavs(tmp_path, monkeypatch):
    tts = WindowsTTS()
    monkeypatch.setattr(tts, "_speak", lambda text, path, *_: wav(path, 1 if text == "첫 문장." else 2))
    output = tmp_path / "voice.wav"
    cues = tts.synthesize_timed("첫 문장. 두 번째 문장.", output, "Heami", 30, SpeechSettings(pause_ms=250))
    assert wav_duration(output) == 3.25
    assert cues == [{"start_ms": 0, "end_ms": 1000, "text": "첫 문장."},
                    {"start_ms": 1250, "end_ms": 3250, "text": "두 번째 문장."}]


class MeasuredTTS:
    def __init__(self):
        self.calls = []

    def synthesize(self, text, path, *_):
        self.calls.append(text)
        wav(path, 4 * len(text.split(". ")))


def test_overflow_reduces_whole_sentence_regenerates_and_moves_next_scene(tmp_path):
    plan = RenderPlan("합성", [ScenePlan(3, "첫 사실. 부가 사실.", "이전 자막"),
                              ScenePlan(7, "둘째 사실.", "둘째")], [], voice="test", fit_audio=True)
    tts = MeasuredTTS()
    scenes, timings = prepare_audio(plan, tmp_path, tts, Event())
    assert tts.calls == ["첫 사실. 부가 사실.", "둘째 사실.", "첫 사실."]
    assert scenes[0].narration == "첫 사실." and timings[0]["shortened"]
    assert timings[1]["start_ms"] >= 4350
    assert abs(sum(s.seconds for s in scenes) - 10) < 0.001
    assert all(t["seconds"] >= t["audio_seconds"] + .349 for t in timings)
    assert plan.scenes[0].narration == "첫 사실. 부가 사실."  # original remains available for review


def test_unshortenable_audio_fails_without_cutting(tmp_path):
    plan = RenderPlan("합성", [ScenePlan(2, "하나의 사실.", "사실")], [], voice="test", fit_audio=True)
    with pytest.raises(RenderError, match="초과"):
        prepare_audio(plan, tmp_path, MeasuredTTS(), Event())
    assert wav_duration(tmp_path / "scene-000.wav") == 4


def test_ass_escapes_instruction_tags(tmp_path):
    font = Path("C:/Windows/Fonts/malgun.ttf")
    if not font.is_file():
        pytest.skip("Local Korean font unavailable")
    plan = RenderPlan("합성", [ScenePlan(3, "시험", "시험")], [])
    output = tmp_path / "cue.ass"
    write_ass(output, [{"start_ms": 0, "end_ms": 1200, "text": r"시험 {\pos(0,0)}"}], plan, font)
    text = output.read_text(encoding="utf-8-sig")
    assert r"{\pos" not in text and "0:00:01.20" in text


def test_fake_cli_service_preserves_sources_consent_and_separate_usage(app, client, monkeypatch):
    with app.state.sessions.begin() as session:
        source = session.scalar(select(NewsSource))
        article = NewsArticle(title="[합성] 시험 뉴스", summary="가상 기사입니다.",
                              url="https://example.com/synthetic", canonical_url="https://example.com/synthetic",
                              publisher="합성 출처", source_id=source.id)
        session.add(article)
        session.flush()
        identifier = article.id
    service = IntelligenceService(app.state.sessions)
    analysis = service.analyze([identifier])

    class FakeCLI(OfflineProvider):
        last_elapsed_ms = 1
        last_model = "sonnet"

        def __init__(self):
            self.last_usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

    monkeypatch.setattr("newsflow.intelligence.claude_code.CLAUDE_PROVIDER", FakeCLI())
    with pytest.raises(IntelligenceError, match="동의"):
        service.generate(analysis, 30, "claude_code", False)
    draft_id = service.generate(analysis, 30, "claude_code", True)
    with app.state.sessions() as session:
        draft = session.get(ContentDraft, draft_id)
        assert draft.sources["articles"][0]["sources"][0]["url"] == "https://example.com/synthetic"
        assert draft.review_status == "review_required"
    assert usage_this_month(app.state.sessions)["tokens"] == 0
    assert usage_this_month(app.state.sessions, "claude_code")["tokens"] == 30
    assert 'value="claude_code"' in client.get("/ai").text
    assert client.post("/ai/claude/cancel", data={"unused": "1"}).status_code == 403
    token = csrf(client)
    # Restore the actual adapter only for local cancel (no inference).
    monkeypatch.setattr("newsflow.intelligence.claude_code.CLAUDE_PROVIDER", ClaudeCodeProvider())
    response = client.post("/ai/claude/cancel", data={"csrf_token": token})
    assert response.status_code == 200 and response.json() == {"cancel_requested": False}
