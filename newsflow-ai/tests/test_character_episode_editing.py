"""Only original synthetic local media; no provider/operating profile is used."""
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace as NS
import wave

import pytest

from newsflow.character import editing
from newsflow.character.compose_studio import compose_studio
from newsflow.character.schema import CharacterError
from newsflow.video.ai.clips import probe_clip
from newsflow.video.engine import FFmpegAdapter
from newsflow.video.tts import local_process_env


def scene(seconds=10, **values):
    return NS(seconds=seconds, speed='normal', fast_intensity=None, freeze_end='none',
              sfx=[], caption='순간의 반전', **values)


def episode(target):
    if target == 15:
        rows = [NS(seconds=10, speed='fast', fast_intensity='strong', freeze_end='none',
                   sfx=[{'at': 'start', 'key': 'whoosh'}], caption='급한 시작'),
                NS(seconds=9, speed='normal', fast_intensity=None, freeze_end='medium',
                   sfx=[{'at': 'end', 'key': 'ding'}], caption='느긋한 반응')]
    else:
        durations = [8, 9, 9, 8] if target == 35 else [12, 12, 12, 12, 11]
        rows = [scene(seconds) for seconds in durations]
        rows[-1].freeze_end = 'medium'
        rows[-1].sfx = [{'at': 'end', 'key': 'ding'}]
    return NS(schema_version=3, hook_caption='시작부터 반전', scenes=rows, end_caption='다음 이야기도 함께')


def test_effect_values_and_sfx_are_config_owned():
    presets = editing.load_edit_presets()
    assert presets['fast']['strong'] == 2
    assert presets['freeze']['medium'] == 1
    assert presets['scene_audio_crossfade'] == .15
    assert len(editing.load_sfx_map()) == 8


def test_actual_speed_and_freeze_math():
    value = NS(seconds=10, speed='fast', fast_intensity='strong', freeze_end='none')
    assert editing.playback_seconds(value) == 5
    value.freeze_end = 'medium'
    assert editing.playback_seconds(value) == 6


@pytest.mark.parametrize('field,value', [('speed', 'turbo'), ('fast_intensity', 'verystrong'),
                                        ('freeze_end', 'infinite'), ('seconds', float('nan'))])
def test_unknown_effects_fail_before_media(field, value):
    item = NS(seconds=10, speed='fast', fast_intensity='strong', freeze_end='medium')
    setattr(item, field, value)
    with pytest.raises(CharacterError):
        editing.playback_seconds(item)


@pytest.mark.parametrize('target', [15, 35, 60])
def test_exact_frame_timeline_and_final_hold(target):
    timeline = editing.edit_timeline(episode(target), target)
    assert sum(row['seconds'] for row in timeline) == pytest.approx(target)
    assert timeline[-1]['freeze_seconds'] >= 1
    for previous, current in zip(timeline, timeline[1:]):
        assert current['start'] == pytest.approx(previous['start'] + previous['seconds'])


def test_only_final_hold_is_extended_and_oversize_script_is_rejected():
    story = episode(15)
    story.scenes[-1].seconds = 8
    timeline = editing.edit_timeline(story, 15)
    assert timeline[-1]['freeze_seconds'] == 2
    story.scenes[-1].seconds = 11
    with pytest.raises(CharacterError):
        editing.edit_timeline(story, 15)


def test_caption_override_and_newline_are_data(tmp_path):
    story = episode(15)
    story.hook_caption = '{\\pos(1,1)}\n한글'
    path = tmp_path / '자막.ass'
    events = editing.write_captions(path, story, editing.edit_timeline(story, 15), editing.load_edit_presets())
    content = path.read_text(encoding='utf-8-sig')
    assert '{\\pos' not in content and '｛＼pos(1,1)｝ 한글' in content
    assert content.count('Dialogue:') == events
    assert 'Noto Sans KR' in content and 'PlayResY: 1920' in content


def test_sfx_reproducible_original_pcm(tmp_path):
    recipe = editing.load_sfx_map()['ding']
    paths = [tmp_path / 'a.wav', tmp_path / 'b.wav']
    for path in paths:
        editing.synthesize_sfx(path, recipe)
    assert paths[0].read_bytes() == paths[1].read_bytes()
    with wave.open(str(paths[0])) as sound:
        assert sound.getframerate() == 48000 and sound.getnchannels() == 1
        assert sound.getnframes() / 48000 == pytest.approx(.3)


def test_sfx_path_injection_rejected_before_decode(tmp_path, monkeypatch):
    story = episode(15)
    story.scenes[0].sfx = [{'at': 'start', 'key': '../unapproved'}]
    monkeypatch.setattr(editing.FFmpegAdapter, 'executable', lambda *_: Path('ffmpeg'))
    monkeypatch.setattr(editing, 'probe_clip', lambda *_: pytest.fail('decoded invalid effect'))
    with pytest.raises(CharacterError):
        editing.compose_episode(tmp_path, story, [tmp_path/'missing.mp4'] * 2,
                                settings={'duration': 15, 'aspect_ratio': '9:16', 'sound': 'off'})


def test_version_three_dispatches_without_mutating_legacy_composer(tmp_path, monkeypatch):
    expected = {'file': 'final.mp4'}
    called = []
    def compose(*args, **kwargs):
        called.append((args, kwargs))
        return expected
    monkeypatch.setattr(editing, 'compose_episode', compose)
    assert compose_studio(tmp_path, episode(15), [], settings={'duration': 15}) == expected
    assert len(called) == 1
    assert called[0][1]['add_captions'] is False and called[0][1]['add_sfx'] is False


@pytest.fixture(scope='module')
def synthetic_sources(tmp_path_factory):
    folder = tmp_path_factory.mktemp('character-episode-synthetic')
    binary = str(FFmpegAdapter.executable('ffmpeg', None))
    sources = []
    for audio in (False, True):
        path = folder / f'clip-{audio}.mp4'
        args = [binary, '-nostdin', '-n', '-v', 'error', '-f', 'lavfi', '-i',
                'color=c=0x367BA3:s=144x256:r=30']
        if audio:
            args += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-c:a', 'aac']
        else:
            args += ['-an']
        args += ['-t', '12', '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(path)]
        subprocess.run(args, check=True, capture_output=True, timeout=60, env=local_process_env())
        sources.append(path)
    return sources


@pytest.mark.parametrize('target', [15, 35, 60])
def test_real_ffmpeg_variable_episode_is_exact_portrait_mp4(tmp_path, synthetic_sources, target):
    story = episode(target)
    # Alternate native sound and silent clips: output tracks must still line up.
    clips = [synthetic_sources[index % 2] for index in range(len(story.scenes))]
    before = [editing.digest(path) for path in synthetic_sources]
    result = compose_studio(tmp_path, story, clips,
                            settings={'duration': target, 'aspect_ratio': '9:16', 'sound': 'on'})
    info = probe_clip(tmp_path/'final.mp4')
    assert (info['width'], info['height'], info['video_codec']) == (1080, 1920, 'h264')
    assert abs(info['duration'] - target) <= .1 and info['has_audio']
    assert result['captions_added'] is False and result['sfx_added'] is False
    assert result['audio_source']=='model_output'
    assert not (tmp_path/'compose/captions.ass').exists()
    assert not (tmp_path/'compose/fonts').exists()
    assert not list((tmp_path/'compose').glob('sfx-*.wav'))
    assert result['voice_added'] is False and result['music_added'] is False
    assert result['human_quality'] == 'NOT VERIFIED'
    assert [editing.digest(path) for path in synthetic_sources] == before
    evidence = json.loads((tmp_path/'compose/edit-evidence.json').read_text(encoding='utf8'))
    assert evidence['target_seconds'] == target and not evidence['sfx_sha256']
    assert not evidence['sfx_events']
    filters = (tmp_path/'compose/edit-filter.txt').read_text(encoding='utf8')
    assert 'acrossfade=d=0.15' in filters and 'xfade=' not in filters
    assert 'loudnorm=I=-14' in filters and '[vjoined]null[vout]' in filters
    assert 'subtitles=' not in filters and '[effect' not in filters and 'adelay=' not in filters
    assert 'zoompan' not in filters and 'drawtext' not in filters
    binary = str(FFmpegAdapter.executable('ffprobe', None))
    probe = subprocess.run([binary, '-v', 'error', '-show_streams', '-of', 'json',
                            str(tmp_path/'final.mp4')], check=True, capture_output=True,
                           timeout=30, env=local_process_env())
    streams = json.loads(probe.stdout)['streams']
    lengths = [float(stream['duration']) for stream in streams if stream['codec_type'] in {'audio', 'video'}]
    assert max(lengths) - min(lengths) <= .1


def test_real_audio_crossfade_contains_both_sources_without_time_shift(tmp_path):
    from array import array
    import math
    import sys

    binary = str(FFmpegAdapter.executable('ffmpeg', None))
    timeline = [{'seconds': 1.0}, {'seconds': 1.0}]
    filters, output = editing.audio_join_filters(timeline, .15)
    target = tmp_path / 'crossfade.wav'
    subprocess.run([binary, '-nostdin', '-n', '-v', 'error',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
                    '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000:duration=1',
                    '-filter_complex', ';'.join(filters), '-map', f'[{output}]',
                    '-c:a', 'pcm_s16le', '-ac', '1', str(target)],
                   check=True, capture_output=True, timeout=30, env=local_process_env())
    with wave.open(str(target), 'rb') as sound:
        assert sound.getframerate() == 48000 and sound.getnchannels() == 1
        assert sound.getnframes() == 2 * 48000  # overlap never shortens the episode
        samples = array('h', sound.readframes(sound.getnframes()))
    if sys.byteorder != 'little':
        samples.byteswap()

    def amplitude(frequency, start):
        window = samples[round(start * 48000):round((start + .05) * 48000)]
        sine = sum(value * math.sin(2 * math.pi * frequency * i / 48000)
                   for i, value in enumerate(window))
        cosine = sum(value * math.cos(2 * math.pi * frequency * i / 48000)
                     for i, value in enumerate(window))
        return 2 * math.hypot(sine, cosine) / len(window) / 32768

    # Before the cut only the outgoing track is present. At the next video's
    # start both real tones overlap; a silent padding/fade-in substitute fails.
    assert amplitude(440, .90) > .10 and amplitude(880, .90) < .003
    assert amplitude(440, 1.05) > .025 and amplitude(880, 1.05) > .025
    assert amplitude(880, 1.20) > .10 and amplitude(440, 1.20) < .003


@pytest.mark.parametrize('flag', ['add_captions', 'add_sfx'])
def test_plain_mode_flags_are_booleans_before_any_media_io(tmp_path, monkeypatch, flag):
    monkeypatch.setattr(editing,'load_edit_presets',lambda:pytest.fail('read before flag validation'))
    with pytest.raises(CharacterError):
        editing.compose_episode(tmp_path,episode(15),[],settings={},**{flag:'false'})
