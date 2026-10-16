from array import array
from pathlib import Path

import pytest

from newsflow.video.engine import RenderError, RenderPlan, ScenePlan, caption_frames
from newsflow.video.speech_audio import prepare_pcm, reading_units
from newsflow.video.speech_text import normalize_for_speech


def test_units_preserve_numbers_and_all_original_words():
    text = '2026-10-15 기준 3.5% 상승했습니다. OpenAI의 매출은 $1,250,000이며, 원문을 확인해야 합니다.'
    units = reading_units(text, 30)
    assert ' '.join(units) == text
    assert any('3.5%' in unit for unit in units)
    assert any('$1,250,000이며,' in unit for unit in units)
    assert normalize_for_speech('OpenAI와 ChatGPT') == '오픈에이아이와 챗지피티'


def test_pcm_trim_preserves_internal_pause_handles_and_peak():
    raw = array('h', [0] * 16000 + [32000] * 1600 + [0] * 4000 + [-32000] * 1600 + [0] * 16000)
    output = array('h')
    output.frombytes(prepare_pcm(raw.tobytes()))
    assert len(output) == 1280 * 2 + 1600 * 2 + 4000
    assert max(map(abs, output)) == 24575
    assert output[2880:6880] == array('h', [0] * 4000)
    with pytest.raises(ValueError):
        prepare_pcm(b'\0\0' * 160)


def test_caption_manifest_uses_measured_intervals_and_retains_blank_gap(tmp_path, monkeypatch):
    from newsflow.video import engine

    calls = []
    monkeypatch.setattr(engine, 'card', lambda plan, scene, index, target, font, text: calls.append(text))
    plan = RenderPlan('제목', [ScenePlan(5, '첫 문장. 둘째 문장.', '요약')], [], voice='Heami')
    cues = [{'start': 0.0, 'end': 1.2, 'text': '첫 문장.'},
            {'start': 1.45, 'end': 3.1, 'text': '둘째 문장.'}]
    manifest = caption_frames(plan, plan.scenes[0], 0, tmp_path, Path('font'), cues)
    assert calls == ['첫 문장.', '', '둘째 문장.', '']
    durations = [float(line.split()[1]) for line in manifest.read_text().splitlines() if line.startswith('duration')]
    assert durations == pytest.approx([1.2, 0.25, 1.65, 1.9])
    assert sum(durations) == pytest.approx(5)
    with pytest.raises(RenderError):
        caption_frames(plan, plan.scenes[0], 0, tmp_path, Path('font'), [{'start': 0, 'end': 6, 'text': '넘침'}])


def test_quality_choices_are_closed_and_no_shell_options():
    with pytest.raises(RenderError):
        RenderPlan('title', [ScenePlan(5, 'n', 'c')], [], theme='unsafe;filter').validate()
    with pytest.raises(RenderError):
        RenderPlan('title', [ScenePlan(5, 'n', 'c')], [], subtitle_style='unsafe').validate()
