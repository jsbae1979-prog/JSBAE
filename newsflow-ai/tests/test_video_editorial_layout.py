"""Bounded title/source/voice attribution layout without voice or provider requests."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from PIL import Image, ImageDraw

from newsflow.shortform import Shortform
from newsflow.video.engine import RenderError, RenderPlan, ScenePlan, card, draw_title, overlay
from newsflow.video.tts import FakeTTS

FONT = Path('C:/Windows/Fonts/malgun.ttf')


@pytest.mark.parametrize('mode', ['card', 'overlay', 'shortform'])
def test_credit_and_reference_hosts_are_independent_of_title(monkeypatch, tmp_path, mode):
    plan = RenderPlan('어린이집 운영 중단 후속 보도', [ScenePlan(30, '합성 음성', '')],
                      [{'publisher': '합성 언론', 'url': 'https://news.example.com/story'}],
                      voice='elevenlabs', voice_attribution=True)
    if mode == 'shortform':
        plan = replace(plan, shortform=Shortform(enabled=True))
    before = deepcopy(plan)
    records = []
    original = ImageDraw.ImageDraw.text

    def record(draw, xy, text, *args, **kwargs):
        records.append((xy, text, kwargs.get('font')))
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', record)
    target = tmp_path / 'review.png'
    (overlay if mode == 'overlay' else card)(plan, plan.scenes[0], 0, target, FONT)
    assert plan == before
    assert Image.open(target).size == (1080, 1920)
    credits = [(xy, text) for xy, text, _font in records if 'elevenlabs.io' in text]
    assert credits == [((108, 596), '음성 제공 · elevenlabs.io')]
    assert any('어린이집' in text and 'elevenlabs' not in text for _xy, text, _font in records)
    draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    assert all(90 <= xy[0] and xy[0] + draw.textlength(text, font=font) <= 991
               for xy, text, font in records if xy[1] >= 1800)
    if mode != 'shortform':
        assert any('news.example.com' in text for _xy, text, _font in records)


def test_title_that_cannot_fit_returns_to_review_instead_of_truncating():
    draw = ImageDraw.Draw(Image.new('RGB', (1080, 1920)))
    with pytest.raises(RenderError, match='제목'):
        draw_title(draw, '매우 긴 합성 제목 ' * 100, FONT, 230)


def test_provider_credit_is_carried_to_visual_without_rewriting_title(monkeypatch, tmp_path):
    from newsflow.video import engine

    plan = RenderPlan('보존할 제목', [ScenePlan(1, '합성 음성', '')], [], voice='elevenlabs')
    voice = FakeTTS()
    voice.attribution_required = True
    voice.synthesize = lambda text, target, selected, seconds, speech: FakeTTS.synthesize(
        voice, text, target, 'offline-silence', seconds, speech)
    rendered = []
    monkeypatch.setattr(engine.FFmpegAdapter, 'check', lambda self: (tmp_path / 'ffmpeg', tmp_path / 'ffprobe', 'fixture'))
    monkeypatch.setattr(engine.FFmpegAdapter, 'execute', lambda *args: None)
    monkeypatch.setattr(engine.FFmpegAdapter, 'inspect', lambda *args: {'playable': False})
    monkeypatch.setattr(engine, 'font_path', lambda: FONT)
    monkeypatch.setattr(engine, 'card', lambda actual, *args: rendered.append(actual))
    _, metadata = engine.FFmpegAdapter().render(plan, tmp_path, voice, lambda value: None, Event())
    assert rendered[0].title == plan.title and rendered[0].voice_attribution
    assert not plan.voice_attribution
    assert metadata['attribution_required'] and metadata['non_commercial_only']
