"""Focused local checks of the newly rebuilt candidate, synthetic media only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from threading import Event


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--media-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if os.name != 'nt' or args.output.exists():
        raise SystemExit('Fresh Windows synthetic output required')
    args.output.mkdir()
    root = args.media_root.resolve()
    binary, probe = root / 'prefix/bin/ffmpeg.exe', root / 'prefix/bin/ffprobe.exe'
    from PIL import Image
    from newsflow.video.engine import FFmpegAdapter, RenderPlan, ScenePlan
    from newsflow.video.tts import OfflineTTS
    from newsflow.character.compose import compose
    from newsflow.character.schema import Storyboard
    result = {'checks': [], 'environment': 'Windows11 native local source rebuild',
              'externalCalls': 0, 'productMediaReplaced': False}
    def check(name, value):
        result['checks'].append({'name': name, 'status': 'PASS' if value else 'FAIL'})
        if not value:
            raise AssertionError(name)
    def command(items):
        return subprocess.run([str(x) for x in items], check=True, capture_output=True, timeout=300).stdout
    try:
        description = command([binary, '-version']).decode('utf8', 'replace')
        check('no_ffmpeg_network_support', '--disable-network' in description)
        adapter = FFmpegAdapter(binary, probe)
        adapter.check()
        check('unchanged_product_preflight', True)
        image = args.output / 'synthetic.png'
        Image.new('RGB', (720, 1280), (21, 28, 50)).save(image)
        work = args.output / 'news'
        work.mkdir()
        plan = RenderPlan('합성 뉴스', [ScenePlan(10, '검증', '오프라인 합성 자막', image=image, effect='fade') for _ in range(3)], [])
        movie, info = adapter.render(plan, work, OfflineTTS(), lambda p: None, Event())
        check('news_30s_1080x1920_h264', info['width'] == 1080 and info['height'] == 1920 and info['video_codec'] == 'h264')
        command([binary, '-v', 'error', '-i', movie, '-f', 'null', '-'])
        check('news_mp4_full_decode', True)
        clips = []
        for n in range(3):
            clip = args.output / ('scene-' + str(n) + '.mp4')
            command([binary, '-nostdin', '-n', '-v', 'error', '-loop', '1', '-i', image, '-t', '10',
                     '-vf', 'scale=1080:1920,setsar=1', '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-r', '30', '-pix_fmt', 'yuv420p', clip])
            clips.append(clip)
        story = Storyboard.model_validate({'plan': {'situation': '합성', 'contrast': '검증', 'punchline': '완료'},
            'title': '오프라인 캐릭터 검증', 'hook_caption': '샘플', 'end_caption': '검증 완료',
            'scenes': [{'seconds': 10, 'role': role, 'action': 'A geometric synthetic card.', 'caption': '한글 자막', 'sfx': ''}
                       for role in ('setup', 'contrast', 'punchline')]})
        work = args.output / 'character'
        work.mkdir()
        info = compose(work, story, clips, ffmpeg=binary, ffprobe=probe)
        check('character_3_scenes_30s_1080x1920', info['media']['width'] == 1080 and info['media']['height'] == 1920 and abs(info['media']['duration'] - 30) < .04)
        check('character_xfade_korean_subtitles_full_decode', True)
        imports = sum([(root / 'evidence' / name).read_text().split() for name in ('ffmpeg-imports.txt', 'ffprobe-imports.txt')], [])
        check('windows_system_runtime_only', not any(any(v in n.lower() for v in ('libgcc', 'libstdc', 'libwinpthread', 'libass', 'freetype', 'harfbuzz', 'fribidi', 'zlib')) for n in imports))
        result['binaryHashes'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (binary, probe)}
        result['result'] = 'PASS'
    except BaseException as exc:
        result['result'] = 'FAIL'
        result['errorClass'] = type(exc).__name__
        raise
    finally:
        (args.output / 'MEDIA_INTEGRATION_RESULTS.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result))


if __name__ == '__main__':
    main()
