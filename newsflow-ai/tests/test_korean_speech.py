"""Korean narration estimates, script review findings, audio-fit timing and TTS data contracts."""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from newsflow.intelligence.korean import assess_script, speech_plan, speech_seconds, split_sentences
from newsflow.video.engine import AUDIO_TAIL_SECONDS, RenderError, fit_timings
from newsflow.video.tts import SpeechSettings, TTSError, WindowsTTS, wav_has_signal

EVIDENCE = {"articles": [{
    "id": 1, "title": "시청, 2026년 자전거 도로 12km 추가 계획 발표",
    "summary": "시는 내년까지 자전거 전용 도로를 12km 늘리고 보행 안전 구간 30곳을 정비한다고 밝혔다. 예산은 확정되지 않았다.",
    "published_at": "2026-10-01T00:00:00+00:00", "sources": [{"publisher": "합성", "url": "https://example.com/1"}],
}]}


def script(narrations: list[str], seconds: list[int], **extra) -> dict:
    return {
        "title": "자전거 도로 12km 추가", "hook": "시청이 자전거 도로 확대 계획을 발표했습니다.",
        "summary": "자전거 도로 12km와 보행 안전 구간 30곳이 대상입니다.", "closing": "자세한 내용은 원문에서 확인하세요.",
        "scenes": [{"seconds": s, "narration": n, "caption": "자막", "material": "카드"} for n, s in zip(narrations, seconds)],
        **extra,
    }


def test_sentence_split_and_estimate_scale_with_rate_and_pause():
    text = "첫 문장입니다. 두 번째 문장입니다! 세 번째?"
    assert split_sentences(text) == ["첫 문장입니다.", "두 번째 문장입니다!", "세 번째?"]
    normal = speech_seconds(text)
    assert 2.0 < normal < 6.0
    assert speech_seconds(text, rate=3) < normal < speech_seconds(text, rate=-3)
    assert speech_seconds(text, pause_ms=600) > speech_seconds(text, pause_ms=0)
    assert speech_seconds("") == 0.0


def test_speech_plan_flags_scenes_that_do_not_fit():
    long = "이 문장은 아주 길어서 장면에 배정된 시간 안에 읽을 수 없습니다. " * 6
    plan = speech_plan(script([long, "짧은 문장입니다."], [5, 25]), 30)
    assert plan["scenes"][0]["fits"] is False and plan["scenes"][1]["fits"] is True
    assert plan["fits"] is False and plan["duration"] == 30


def test_assess_script_reports_unknown_numbers_and_short_sources_but_never_rewrites():
    content = script(["도로 12km와 안전 구간 30곳을 정비합니다.", "예산 500억 원이 투입됩니다."], [15, 15])
    notes = assess_script(content, EVIDENCE, 30)
    codes = {note["code"] for note in notes}
    assert "numbers_not_in_source" in codes
    assert any("500" in note["message"] for note in notes)
    assert "insufficient_source_text" not in codes
    thin = {"articles": [{**EVIDENCE["articles"][0], "summary": "", "published_at": None}]}
    codes = {note["code"] for note in assess_script(content, thin, 30)}
    assert {"insufficient_source_text", "unknown_publication_date"} <= codes
    assert content["scenes"][1]["narration"] == "예산 500억 원이 투입됩니다."  # untouched


def test_assess_script_is_quiet_for_faithful_script():
    content = script(["시청이 2026년까지 자전거 도로 12km를 늘린다고 밝혔습니다.", "보행 안전 구간 30곳도 정비합니다."], [15, 15])
    assert assess_script(content, EVIDENCE, 30) == []


def test_fit_timings_preserves_total_and_rejects_overflow():
    fitted = fit_timings([3.0, 6.0, 2.0], [10, 10, 10], 30)
    assert len(fitted) == 3 and abs(sum(fitted) - 30) < 0.001
    assert all(f >= a + AUDIO_TAIL_SECONDS - 0.001 for f, a in zip(fitted, [3.0, 6.0, 2.0]))
    with pytest.raises(RenderError, match="초과"):
        fit_timings([12.0, 12.0, 8.0], [10, 10, 10], 30)
    with pytest.raises(RenderError):
        fit_timings([1.0], [10, 10], 20)


def test_speech_settings_bounds():
    assert SpeechSettings(3, 400).rate == 3
    for rate, pause in ((6, 250), (-6, 250), (0, 5000), ("1", 250), (0, True)):
        with pytest.raises(TTSError):
            SpeechSettings(rate, pause)  # type: ignore[arg-type]


def test_windows_tts_spec_is_data_only_with_sentences_and_settings(tmp_path):
    spec = WindowsTTS.spec("첫 문장. 둘째 문장.", "Korean Voice", tmp_path / "a.wav", SpeechSettings(2, 400))
    assert spec["sentences"] == ["첫 문장.", "둘째 문장."] and spec["rate"] == 2 and spec["pause_ms"] == 400
    assert json.dumps(spec, ensure_ascii=False)
    script_text = Path(WindowsTTS().script).read_text(encoding="utf-8")
    assert "PromptBuilder" in script_text and "AppendBreak" in script_text and "Invoke-Expression" not in script_text
    assert "$speaker.Rate" in script_text


def test_wav_signal_detection(tmp_path):
    silent, voiced = tmp_path / "s.wav", tmp_path / "v.wav"
    for path, frames in ((silent, b"\0\0" * 1600), (voiced, b"\0\0" * 800 + b"\x10\x10" * 800)):
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(frames)
    assert not wav_has_signal(silent) and wav_has_signal(voiced)
    assert not wav_has_signal(tmp_path / "missing.wav")
