"""Offline Phase 5F.3 sample: native SAPI, measured captions and a 30-second MP4.

Outputs stay local; human quality is never marked PASS. No application DB is opened.
"""
from __future__ import annotations

import argparse
import json
import wave
from array import array
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from threading import Event

from PIL import Image, ImageChops, ImageStat

from newsflow.video.engine import FFmpegAdapter, RenderPlan, ScenePlan
from newsflow.video.tts import SpeechSettings, WindowsTTS, wav_has_signal


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    tts = WindowsTTS()
    voices = tts.voice_details()
    korean = [v['name'] for v in voices if v['culture'].lower().startswith('ko-')]
    voice = korean[0] if korean else voices[0]['name']
    # Same three raw narration texts as the user-evaluated trial video.
    scenes = [
        ScenePlan(10, '선택한 보도 주제를 소개합니다. 상세한 사실은 원문 출처에서 확인해 주세요.',
                  '보도 내용 · 사실 확인 필요'),
        ScenePlan(10, '복수 출처가 같은 보도를 했는지 비교하고, 차이점을 검토합니다.',
                  '출처 비교 · 독립 검증 미완료'),
        ScenePlan(10, '미확인 정보는 단정하지 않습니다. 게시 전 사람이 원문과 이용 권한을 검토해야 합니다.',
                  '사람의 검토 필요'),
    ]
    if not korean:
        # Hosted Windows runners may lack Korean SAPI. Exercise native timing honestly,
        # without claiming English synthesis proves Korean pronunciation quality.
        english = ['This is a local sample. Please check the original source.',
                   'Compare independent sources. Review differences carefully.',
                   'Do not assume unknown facts. A person must review the final video.']
        scenes = [replace(scene, narration=text) for scene, text in zip(scenes, english)]
    plan = RenderPlan('[합성] 동네 도서관 독서 모임 운영 아이디어', scenes,
                      [{'publisher': 'NewsFlow 체험용 합성 뉴스 · 실제 보도 아님', 'url': 'https://example.com'}],
                      voice=voice, font_size=56, speech=SpeechSettings(-1, 250), fit_audio=True)
    target, metadata = FFmpegAdapter().render(plan, args.output, tts, lambda _: None, Event())
    cues = metadata['subtitle_cues']
    assert metadata['playable'] and abs(metadata['duration'] - 30) < 0.1
    assert len(cues) >= 5 and all(a['end_ms'] <= b['start_ms'] for a, b in pairwise(cues))
    assert ' '.join(c['text'] for c in cues) == ' '.join(s.narration for s in scenes)
    binary = FFmpegAdapter.executable('ffmpeg', None)
    frames = []
    for number, second in enumerate((1.0, cues[1]['start_ms'] / 1000 + 0.4)):
        frame = args.output / f'frame-{number}.png'
        FFmpegAdapter.execute([str(binary), '-v', 'error', '-nostdin', '-n', '-ss', str(second),
                               '-i', str(target), '-frames:v', '1', str(frame)], args.output, Event())
        with Image.open(frame) as image:
            assert sum(ImageStat.Stat(image.crop((90, 200, 990, 1000))).mean) > 50, 'Unexpected black frame'
            frames.append(image.crop((90, 1390, 990, 1610)))
    assert ImageChops.difference(*frames).getbbox(), 'Sentence subtitle did not change'
    for index, timing in enumerate(metadata['scene_timings']):
        wav = args.output / f'scene-{index:03d}.wav'
        assert wav_has_signal(wav)
        assert timing['audio_seconds'] + 0.34 <= timing['seconds']
        with wave.open(str(wav)) as audio:
            samples = array('h')
            samples.frombytes(audio.readframes(audio.getnframes()))
            assert max(map(abs, samples)) <= 24575
    # Numerals/IT sample exercises the existing meaning-preserving normalizer.
    sample = args.output / 'korean-reading.wav'
    reading = ('2026년 10월 15일 기준 AI 매출은 $1,250,000입니다. 3.5% 증가했습니다. ChatGPT를 확인합니다.'
               if korean else 'This is a native speech timing sample. Human quality remains unverified.')
    tts.synthesize(reading,
                   sample, voice, 30, SpeechSettings(-1, 250))
    result = {'technical': 'PASS', 'voice': voice, 'korean_voice': bool(korean),
              'human_listening': 'NOT VERIFIED', 'human_visual_quality': 'NOT VERIFIED',
              'paid_api_calls': 0, 'mp4': target.name, 'metadata': metadata}
    (args.output / 'quality.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
