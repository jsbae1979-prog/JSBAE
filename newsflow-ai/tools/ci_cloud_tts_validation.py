"""Fake API -> actual WAV/FFmpeg MP4. No cloud credential/network; tone is not neural speech."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import wave
from array import array
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

from newsflow.db.session import make_engine, migrate, session_factory
from newsflow.video.cloud_tts import MODELS, AccountUsage, CloudTTS, usage_rows
from newsflow.video.engine import FFmpegAdapter, RenderPlan, ScenePlan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    engine = make_engine(root / 'synthetic.sqlite')
    migrate(engine)
    sessions = session_factory(engine)
    key = 'synthetic-tts-key-not-a-real-credential'
    options = {'provider': 'google', 'voice': MODELS['google'][0], 'region': 'koreacentral',
               'approved_at': datetime.now(UTC).isoformat(), 'monthly_char_limit': 10000,
               'price_per_million': '30', 'job_usd_limit': '1', 'monthly_usd_limit': '5'}

    def verifier(provider, voice, credential):
        now = datetime.now(UTC)
        return AccountUsage(provider, voice, hashlib.sha256(credential.encode()).hexdigest(), now,
                            now.strftime('%Y-%m'), 0, 1000000, True, True)

    def requester(*args):
        raw = io.BytesIO()
        with wave.open(raw, 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(array('h', (int(8000 * math.sin(i * .1)) for i in range(8000))).tobytes())
        return 200, json.dumps({'audioContent': base64.b64encode(raw.getvalue()).decode()}).encode()

    tts = CloudTTS(sessions, options, lambda: key, scope='synthetic-render', confirmed=True,
                   verifier=verifier, requester=requester)
    plan = RenderPlan('[합성] Fake API 렌더 검증 · 실제 Neural 음성 아님',
                      [ScenePlan(30, '첫 번째 합성 문장입니다. 두 번째 합성 문장입니다.', 'Fake 응답 · 톤 오디오')],
                      [], voice=options['voice'], fit_audio=True)
    target, metadata = FFmpegAdapter().render(plan, root, tts, lambda _: None, Event())
    assert metadata['playable'] and len(metadata['subtitle_cues']) == 2
    assert abs(metadata['duration'] - 30) < .1
    assert all(r['status'] == 'success' for r in usage_rows(sessions))
    result = {'technical': 'PASS', 'mode': 'injected-Fake-only', 'actual_api_calls': 0,
              'neural_voice_quality': 'NOT VERIFIED (synthetic tone)', 'file': target.name, 'metadata': metadata}
    (root / 'fake-cloud.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    engine.dispose()


if __name__ == '__main__':
    main()
