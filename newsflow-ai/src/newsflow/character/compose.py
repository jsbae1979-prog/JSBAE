"""Silent character composition through existing FFmpeg/probe/subtitle helpers."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from PIL import ImageFont

from newsflow.video.ai.clips import FORMAT_WHITELIST, probe_clip
from newsflow.video.engine import FFmpegAdapter, RenderPlan, write_ass
from newsflow.video.tts import local_process_env

from .schema import CharacterError, Storyboard


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args, cwd):
    try:
        result = subprocess.run(args, cwd=cwd, shell=False, capture_output=True, timeout=300, check=False,
                                env=local_process_env())
        if result.returncode:
            raise ValueError
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise CharacterError('media') from None


def compose(folder: Path, story: Storyboard, clips: list[Path], *, sfx_root: Path | None = None,
            ffmpeg: Path | None = None, ffprobe: Path | None = None):
    if len(clips) != len(story.scenes):
        raise CharacterError('media')
    binary = str(FFmpegAdapter.executable('ffmpeg', ffmpeg))
    font = Path(__file__).with_name('assets')/'NotoSansKR.ttf'
    if not font.is_file() or digest(font) != '194018e6b2b293a7964f037b25c0249ce1418bc9ab3c971060a03aa57861e252':
        raise CharacterError('media')
    work = folder/'compose'
    work.mkdir(exist_ok=False)
    durations, normalised = [], []
    for i, (clip, scene) in enumerate(zip(clips, story.scenes)):
        info = probe_clip(clip, ffprobe)
        # Crossfades consume 0.2 s each. Add that overlap explicitly, never shorten the story.
        seconds = scene.seconds + (0.2 if i < len(clips)-1 else 0)
        if info['duration'] < scene.seconds-2:
            raise CharacterError('media')
        dest = work/f'scene-{i}.mp4'
        vf = ('scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,'
              'fps=30,format=yuv420p,settb=AVTB,setpts=PTS-STARTPTS,'
              f'tpad=stop_mode=clone:stop_duration={max(0,seconds-info["duration"]):.3f}')
        run([binary, '-nostdin', '-n', '-v', 'error', '-protocol_whitelist', 'file',
             '-format_whitelist', FORMAT_WHITELIST, '-i', str(clip.resolve()), '-vf', vf,
             '-t', str(seconds), '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '22',
             '-threads', '2', str(dest.resolve())], work)
        durations.append(seconds)
        normalised.append(dest)
    cues, start = [], 0
    for s in story.scenes:
        cues.append({'start_ms':start,'end_ms':start+s.seconds*1000,'text':s.caption})
        start += s.seconds*1000
    plan = RenderPlan(story.title, [], [], font_size=48, subtitle_y=1450)
    write_ass(work/'captions.ass', cues, plan, font)
    write_ass(work/'hook.ass', [{'start_ms':0,'end_ms':2000,'text':story.hook_caption}],
              RenderPlan(story.title, [], [], font_size=54, subtitle_y=1100), font)
    # Move the hook to the top; these are code-owned style edits, no injected override tags.
    hook = (work/'hook.ass').read_text(encoding='utf-8-sig').replace(',2,90,90,670', ',8,90,90,180')
    (work/'hook.ass').write_text(hook, encoding='utf-8-sig')
    write_ass(work/'ending.ass', [{'start_ms':28000,'end_ms':30000,'text':story.end_caption}],
              RenderPlan(story.title, [], [], font_size=48, subtitle_y=1100), font)
    write_ass(work/'label.ass', [{'start_ms':0,'end_ms':30000,'text':'AI 생성 · 가상 직장인 이야기'}],
              RenderPlan(story.title, [], [], font_size=36, subtitle_y=1100), font)
    label = (work/'label.ass').read_text(encoding='utf-8-sig').replace(',2,90,90,670', ',8,90,90,80')
    (work/'label.ass').write_text(label, encoding='utf-8-sig')
    family=ImageFont.truetype(str(font),48).getname()[0]
    if not re.fullmatch(r'[A-Za-z0-9 _-]{1,80}',family):
        raise CharacterError('media')
    (work/'fonts').mkdir()
    shutil.copy2(font,work/'fonts'/font.name)
    for name in ['captions','hook','ending','label']:
        ass=work/(name+'.ass')
        text=ass.read_text(encoding='utf-8-sig').replace(',Malgun Gothic,',','+family+',')
        ass.write_text(text,encoding='utf-8-sig')
    args = [binary, '-nostdin', '-n', '-v', 'error']
    for path in normalised:
        args += ['-protocol_whitelist','file','-i',str(path.resolve())]
    filters, prev, offset = [], '0:v', 0.0
    for i in range(1, len(clips)):
        offset += durations[i-1] - .2
        filters.append(f'[{prev}][{i}:v]xfade=transition=fade:duration=0.2:offset={offset}[x{i}]')
        prev = f'x{i}'
    filters.append(f'[{prev}]ass=captions.ass:fontsdir=fonts,ass=hook.ass:fontsdir=fonts,'
                   'ass=ending.ass:fontsdir=fonts,ass=label.ass:fontsdir=fonts[v]')
    # Optional local, individually licensed WAV effects. No remote fetch or music.
    effects, starts = [], 0
    library = {}
    if sfx_root and (sfx_root/'sfx_map.json').is_file():
        if (sfx_root/'sfx_map.json').stat().st_size > 16000:
            raise CharacterError('media')
        library = json.loads((sfx_root/'sfx_map.json').read_text(encoding='utf8'))
    for scene in story.scenes:
        entry = library.get(scene.sfx)
        if entry:
            if (not isinstance(entry, dict) or entry.get('commercial_use_confirmed') is not True
                    or not entry.get('license') or not re.fullmatch(r'[a-zA-Z0-9_-]{1,50}\.wav',entry.get('file',''))):
                raise CharacterError('media')
            path = sfx_root/entry['file']
            if path.is_symlink() or not 0 < path.stat().st_size <= 10*1024*1024:
                raise CharacterError('media')
            index = len(clips)+len(effects)
            args += ['-protocol_whitelist','file','-format_whitelist','wav','-i',str(path.resolve())]
            filters.append(f'[{index}:a]atrim=duration={scene.seconds},asetpts=PTS-STARTPTS,'
                           f'adelay={starts}|{starts}[a{index}]')
            effects.append({'index':index,'sha256':digest(path),'license':entry['license']})
        starts += scene.seconds*1000
    if effects:
        filters.append(''.join(f'[a{e["index"]}]' for e in effects)+f'amix=inputs={len(effects)},apad[a]')
    else:
        filters.append('anullsrc=r=48000:cl=stereo[a]')
    output = folder/'final.mp4'
    args += ['-filter_complex_threads','1','-filter_complex',';'.join(filters),'-map','[v]','-map','[a]',
             '-t','30','-r','30','-c:v','libx264','-preset','ultrafast','-crf','22','-threads','2',
             '-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(output.resolve())]
    run(args, work)
    info = probe_clip(output, ffprobe)
    if (info['width'],info['height'],info['video_codec']) != (1080,1920,'h264') or abs(info['duration']-30)>.04:
        raise CharacterError('media')
    run([binary,'-nostdin','-v','error','-protocol_whitelist','file','-i',str(output.resolve()),
         '-f','null','-'], work)
    return {'file':'final.mp4','sha256':digest(output),'media':info,'effects':effects,
            'dialogue':False,'music':False,'human_quality':'NOT VERIFIED'}
