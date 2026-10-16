"""Local PCM preparation and bounded reading units, never word alignment."""
from __future__ import annotations

import re
from array import array


def reading_units(text: str, limit: int = 42) -> list[str]:
    """Break at sentence/clause or whitespace boundaries; never split a number/token."""
    result = []
    for sentence in re.split(r'(?<=[.!?。！？])\s+|(?<=[,;:])\s+(?!\d)', ' '.join(text.split())):
        current = ''
        for word in sentence.split():
            if current and len(current) + len(word) + 1 > limit:
                result.append(current)
                current = ''
            current = f'{current} {word}'.strip()
        if current:
            result.append(current)
    return result


def prepare_pcm(raw: bytes, sample_rate: int = 16000) -> bytes:
    """Trim only outer silence, keep 80ms handles; peak-normalize with bounded gain.

    This detects signal boundaries, not phonemes or word timestamps. Internal pauses stay.
    """
    samples = array('h')
    samples.frombytes(raw)
    if not samples:
        raise ValueError('empty speech')
    peak = max(abs(v) for v in samples)
    threshold = max(16, min(64, peak // 100))
    active = [i for i, value in enumerate(samples) if abs(value) > threshold]
    if not active:
        raise ValueError('silent speech')
    handle = sample_rate * 80 // 1000
    samples = samples[max(0, active[0] - handle):min(len(samples), active[-1] + handle + 1)]
    gain = min(4.0, 24575 / peak)
    return array('h', (max(-24575, min(24575, round(v * gain))) for v in samples)).tobytes()
