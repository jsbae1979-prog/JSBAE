"""Pure configuration and timing policy shared by script validation and local editing."""
import math
from pathlib import Path
import re

from newsflow.video_models.catalog import CONFIG, load_document
from .schema import CharacterError


def _get(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def load_edit_presets(path=None):
    """Read bounded effect values from the existing JSON-compatible YAML format."""
    value = load_document(Path(path or CONFIG / 'edit_presets.yaml'))
    expected = {'schema_version', 'fast', 'freeze', 'sfx_volume_db', 'scene_audio_crossfade',
                'fast_strong_audio', 'fast_strong_duck_db', 'loudness_lufs', 'caption'}
    if not isinstance(value, dict) or set(value) != expected or value['schema_version'] != 1:
        raise CharacterError('media')
    for field, low, high in (('fast', 1.01, 4), ('freeze', .01, 3)):
        row = value[field]
        if (not isinstance(row, dict) or set(row) != {'weak', 'medium', 'strong'}
                or any(not _number(n, low, high) for n in row.values())
                or not row['weak'] <= row['medium'] <= row['strong']):
            raise CharacterError('media')
    caption = value['caption']
    if (not _number(value['sfx_volume_db'], -40, 0)
            or not _number(value['scene_audio_crossfade'], 0, .5)
            or value['fast_strong_audio'] not in {'keep', 'duck', 'mute'}
            or not _number(value['fast_strong_duck_db'], -40, 0)
            or not _number(value['loudness_lufs'], -24, -10)
            or not isinstance(caption, dict)
            or set(caption) != {'font', 'family', 'size', 'outline', 'top_margin_ratio'}
            or caption['font'] != 'character/assets/NotoSansKR.ttf'
            or not isinstance(caption['family'], str)
            or not re.fullmatch(r'[A-Za-z0-9 _-]{1,60}', caption['family'])
            or not _number(caption['size'], 36, 100)
            or not _number(caption['outline'], 1, 12)
            or not _number(caption['top_margin_ratio'], .05, .2)):
        raise CharacterError('media')
    return value


def load_sfx_map(path=None):
    """Return only original, bounded oscillator recipes, never arbitrary paths."""
    value = load_document(Path(path or CONFIG / 'sfx_map.yaml'))
    if (not isinstance(value, dict)
            or set(value) != {'schema_version', 'source', 'license', 'effects'}
            or value['schema_version'] != 1 or value['license'] != 'CC0-1.0'
            or not isinstance(value['effects'], dict) or not 1 <= len(value['effects']) <= 20):
        raise CharacterError('media')
    for key, row in value['effects'].items():
        if (not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', key)
                or not isinstance(row, dict)
                or set(row) != {'wave', 'start_hz', 'end_hz', 'seconds', 'decay'}
                or row['wave'] not in {'sine', 'noise', 'pulse'}
                or not _number(row['start_hz'], 30, 8000) or not _number(row['end_hz'], 30, 8000)
                or not _number(row['seconds'], .05, 1) or not _number(row['decay'], 1, 20)):
            raise CharacterError('media')
    return value['effects']


def playback_seconds(scene, presets=None):
    """Calculate playback from trusted numeric presets, never an AI estimate."""
    presets = presets or load_edit_presets()
    seconds, speed = _get(scene, 'seconds'), _get(scene, 'speed', 'normal')
    intensity, freeze = _get(scene, 'fast_intensity'), _get(scene, 'freeze_end', 'none')
    if not _number(seconds, 1, 120) or speed not in {'normal', 'fast'}:
        raise CharacterError('media')
    if speed == 'fast' and intensity not in presets['fast']:
        raise CharacterError('media')
    if freeze not in {'none', *presets['freeze']}:
        raise CharacterError('media')
    factor = presets['fast'][intensity] if speed == 'fast' else 1
    return seconds / factor + (presets['freeze'][freeze] if freeze != 'none' else 0)


def total_playback_seconds(story, presets=None):
    presets = presets or load_edit_presets()
    return sum(playback_seconds(scene, presets) for scene in _get(story, 'scenes', []))


