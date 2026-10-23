"""Local, voice-bound writing guidance. Never authorizes a call or replaces WAV checks."""

import hashlib
import json
import math
import re
from pathlib import Path

from newsflow.intelligence.korean import speech_seconds

from .tts import TTSError, wav_duration, wav_has_signal


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def key_tag(keys):
    """Encrypted-file identity only; planning never decrypts a key or uses environment keys."""
    path = getattr(keys, 'path', None)
    if path is None:
        return None
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 8192:
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_voice(value):
    if value is None:
        return None
    if not isinstance(value, dict) or value.get('provider') not in {'elevenlabs', 'windows', 'supertonic'}:
        raise ValueError('이번 대본의 음성 선택을 확인하세요.')
    voice = value.get('voice_id')
    if not isinstance(voice, str) or not 0 < len(voice) <= 200 or any(ord(c) < 32 for c in voice):
        raise ValueError('이번 대본의 음성 선택을 확인하세요.')
    result = {'provider': value['provider'], 'voice_id': voice}
    if value['provider'] == 'elevenlabs':
        from .elevenlabs_tts import MODELS

        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', voice) or value.get('model') not in MODELS:
            raise ValueError('이번 대본의 ElevenLabs 음성·모델을 확인하세요.')
        result['model'] = value['model']
    return result  # Never accept a ratio/proof supplied as part of a voice selection.


def selected_voice(sessions, voice=None, config=None):
    from newsflow.easy_setup import preview_preferences

    from .elevenlabs_tts import settings
    from .voice_engines import provider_name

    voice = voice or preview_preferences(sessions)[0]
    provider = provider_name(voice)
    if provider == 'offline':
        return None
    if provider == 'elevenlabs':
        config = config if config is not None else settings(sessions)
        if not config.get('voice_id') or not config.get('model'):
            return None  # Incomplete voice setup does not block writing or select another engine.
        return validate_voice({'provider': provider, 'voice_id': config['voice_id'], 'model': config['model']})
    return validate_voice({'provider': provider, 'voice_id': voice})


def measurement(text, config, speech, keys, audio, credits):
    """Called only after a validated response; local text is needed to check its statistics."""
    tag = key_tag(keys)
    if tag is None or type(credits) is not int or credits < 0 or not wav_has_signal(audio):
        return None
    value = {'version': 1, 'voice': validate_voice({'provider': 'elevenlabs', 'voice_id': config['voice_id'],
                                                  'model': config['model']}),
             'speech': {'rate': speech.rate, 'pause_ms': speech.pause_ms}, 'key_tag': tag,
             'text': text, 'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
             'wav_sha256': hashlib.sha256(audio.read_bytes()).hexdigest(),
             'seconds': wav_duration(audio), 'reported_credits': credits}
    return {**value, 'checksum': digest(value)}


def load_profile(root, voice, speech, *, sample_checksums=None, keys=None):
    """Read matching completed receipts and WAVs. Legacy/unknown/missing evidence is not inferred."""
    voice = validate_voice(voice)
    if root is None or not voice or voice['provider'] != 'elevenlabs':
        return None
    from .elevenlabs_tts import ElevenLabsKeys

    directory = Path(root) / 'tts-elevenlabs'
    ledger_path = directory / 'ledger.json'
    try:
        wanted = set(sample_checksums) if sample_checksums is not None else None
        if wanted is not None and (not 3 <= len(wanted) <= 12
                                   or any(not isinstance(s, str) or not re.fullmatch(r'[a-f0-9]{64}', s) for s in wanted)):
            return None
        if not directory.resolve().is_relative_to(Path(root).resolve()):
            return None
        tag = key_tag(keys if keys is not None else ElevenLabsKeys(Path(root)))
        if (not tag or ledger_path.is_symlink() or not ledger_path.is_file()
                or ledger_path.stat().st_size > 4_000_000):
            return None
        ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
        if not isinstance(ledger, dict) or len(ledger) > 4096:
            return None
        historical = directory / 'narration-measurements.json'
        extras = {}
        if historical.is_file() and not historical.is_symlink() and historical.stat().st_size <= 4_000_000:
            extras = json.loads(historical.read_text(encoding='utf-8'))
            if not isinstance(extras, dict):
                return None
        samples, seen = [], set()
        for name, row in reversed(list(ledger.items())):
            if not re.fullmatch(r'[a-f0-9]{64}', name) or not isinstance(row, dict) or row.get('state') != 'completed':
                continue
            item = row.get('narration_measurement', extras.get(name))
            if not isinstance(item, dict):
                continue
            if wanted is not None and item.get('checksum') not in wanted:
                continue
            body = {k: v for k, v in item.items() if k != 'checksum'}
            if (item.get('version') != 1 or item.get('voice') != voice or item.get('speech') != speech
                    or item.get('key_tag') != tag or item.get('checksum') != digest(body)):
                continue
            text, credits = item.get('text'), item.get('reported_credits')
            if (not isinstance(text, str) or not 1 <= len(text) <= 400 or type(credits) is not int or credits < 0
                    or row.get('reported_credits') != credits
                    or hashlib.sha256(text.encode()).hexdigest() != item.get('text_sha256')
                    or item['text_sha256'] in seen):
                continue
            audio = directory / (name + '.wav')
            if audio.is_symlink() or not audio.is_file() or not 44 <= audio.stat().st_size <= 6_000_000:
                continue
            if hashlib.sha256(audio.read_bytes()).hexdigest() != item.get('wav_sha256') or row.get('sha256') != item['wav_sha256']:
                continue
            if not wav_has_signal(audio):
                continue
            actual, generic = wav_duration(audio), speech_seconds(text, **speech)
            recorded_seconds = item.get('seconds')
            if (type(recorded_seconds) not in (int, float) or not math.isfinite(recorded_seconds)
                    or not 2 <= generic <= 120 or abs(actual - recorded_seconds) > .001):
                continue
            if not .65 <= actual / generic <= 1.4:
                continue
            seen.add(item['text_sha256'])
            samples.append((actual, generic, item['checksum']))
            if len(samples) == 12:
                break
        if (len(samples) < 3 or sum(s[1] for s in samples) < 12
                or wanted is not None and len(samples) != len(wanted)):
            return None
        ratio = sum(s[0] for s in samples) / sum(s[1] for s in samples)
        if not math.isfinite(ratio):
            return None
        return {'ratio': round(ratio, 6), 'sample_count': len(samples), 'proof': digest(samples),
                'sample_checksums': [s[2] for s in samples],
                'basis': 'matching_completed_voice_measurements', 'quality': 'NOT VERIFIED'}
    except (OSError, ValueError, TypeError, KeyError, TTSError):
        return None


def planning(root, voice, speech, *, keys=None):
    voice = validate_voice(voice)
    return {'voice': voice, 'profile': load_profile(root, voice, speech, keys=keys)} if voice else None
