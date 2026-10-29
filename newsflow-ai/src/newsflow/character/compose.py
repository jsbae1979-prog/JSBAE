"""Local character composition; add no text, voices or sound effects."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from newsflow.video.ai.clips import FORMAT_WHITELIST, probe_clip
from newsflow.video.engine import FFmpegAdapter
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
    work = folder/'compose'
    work.mkdir(exist_ok=False)
    durations, normalised, source_audio = [], [], []
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
        args = [binary, '-nostdin', '-n', '-v', 'error', '-protocol_whitelist', 'file',
             '-format_whitelist', FORMAT_WHITELIST, '-i', str(clip.resolve()), '-vf', vf,
             '-map', '0:v:0', '-t', str(seconds), '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '22',
             '-threads', '2']
        if info['has_audio']:
            args += ['-map', '0:a:0', '-af', f'atrim=duration={scene.seconds},asetpts=PTS-STARTPTS',
                     '-c:a', 'aac', '-ar', '48000', '-ac', '2']
        run(args + [str(dest.resolve())], work)
        durations.append(seconds)
        normalised.append(dest)
        source_audio.append(info['has_audio'])
    args = [binary, '-nostdin', '-n', '-v', 'error']
    for path in normalised:
        args += ['-protocol_whitelist','file','-i',str(path.resolve())]
    filters, prev, offset = [], '0:v', 0.0
    for i in range(1, len(clips)):
        offset += durations[i-1] - .2
        filters.append(f'[{prev}][{i}:v]xfade=transition=fade:duration=0.2:offset={offset}[x{i}]')
        prev = f'x{i}'
    filters.append(f'[{prev}]null[v]')
    # Historical callers may still pass sfx_root. Never read or add its contents.
    audio, start_ms = [], 0
    for i, scene in enumerate(story.scenes):
        if source_audio[i]:
            filters.append(f'[{i}:a]atrim=duration={scene.seconds},asetpts=PTS-STARTPTS,'
                           f'adelay={start_ms}|{start_ms}[a{i}]')
            audio.append(f'[a{i}]')
        start_ms += scene.seconds * 1000
    if audio:
        filters.append(''.join(audio)+f'amix=inputs={len(audio)}:normalize=0,apad[a]')
    output = folder/'final.mp4'
    args += ['-filter_complex_threads','1','-filter_complex',';'.join(filters),'-map','[v]']
    if audio:
        args += ['-map','[a]','-c:a','aac']
    args += [
             '-t','30','-r','30','-c:v','libx264','-preset','ultrafast','-crf','22','-threads','2',
             '-pix_fmt','yuv420p','-movflags','+faststart',str(output.resolve())]
    run(args, work)
    info = probe_clip(output, ffprobe)
    if (info['width'],info['height'],info['video_codec']) != (1080,1920,'h264') or abs(info['duration']-30)>.04:
        raise CharacterError('media')
    if info['has_audio'] != bool(audio):
        raise CharacterError('media')
    run([binary,'-nostdin','-v','error','-protocol_whitelist','file','-i',str(output.resolve()),
         '-f','null','-'], work)
    return {'file':'final.mp4','sha256':digest(output),'media':info,'effects':[],
            'captions_added':False,'voice_added':False,'ai_label_burned_in':False,
            # These flags mean no added dialogue/music; source audio is unclassified.
            'dialogue':False,'music':False,'audio_source':'model_output' if audio else 'none',
            'human_quality':'NOT VERIFIED'}
