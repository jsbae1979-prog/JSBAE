"""Local, config-driven editing for version 3 character episodes.

No provider, speech synthesizer or network is used. Legacy studio jobs keep
their original plain composition path. All filter text and intermediate file
names are code-owned; captions are encoded into ASS data, never filter code.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import struct
import wave
from pathlib import Path

from newsflow.video.ai.clips import FORMAT_WHITELIST, probe_clip
from newsflow.video.engine import FFmpegAdapter
from newsflow.video_models.catalog import CONFIG

from .compose import digest, run
from .schema import CharacterError


from .episode_policy import (
    _get, load_edit_presets, load_sfx_map, playback_seconds, total_playback_seconds,
)


def edit_timeline(story, target_seconds, presets=None):
    """Quantize at 30 fps; preserve natural timing for newly accepted boundary cases."""
    presets = presets or load_edit_presets()
    scenes = _get(story, 'scenes', [])
    if type(target_seconds) is not int or target_seconds not in range(15, 61, 5) or not scenes:
        raise CharacterError('media')
    total = total_playback_seconds(story, presets)
    from .episode_policy import valid_playback_seconds
    if not valid_playback_seconds(total,target_seconds):
        raise CharacterError('media')
    if _get(scenes[-1], 'freeze_end') not in {'medium', 'strong'}:
        raise CharacterError('media')
    # A near-boundary script is usable as-is, not an instruction to invent a longer hold.
    output_frames=round(total*30) if total < target_seconds-2 else target_seconds*30
    result, cursor = [], 0
    for index, scene in enumerate(scenes):
        speed = presets['fast'][_get(scene, 'fast_intensity')] if _get(scene, 'speed') == 'fast' else 1
        content = _get(scene, 'seconds') / speed
        frames = round(playback_seconds(scene, presets) * 30)
        if index == len(scenes) - 1:
            frames = output_frames - cursor
        duration = frames / 30
        if duration < content - 1 / 30:
            raise CharacterError('media')
        result.append({'no': index + 1, 'start': cursor / 30, 'seconds': duration,
                       'source_seconds': _get(scene, 'seconds'), 'speed': speed,
                       'content_seconds': min(content, duration),
                       'freeze_seconds': max(0, duration - content)})
        cursor += frames
    return result


def synthesize_sfx(target, recipe):
    """Generate original non-melodic 48k PCM. Fixed seed keeps provenance reproducible."""
    count, phase, state = round(recipe['seconds'] * 48000), 0., 1729
    samples = bytearray()
    for index in range(count):
        fraction = index / count
        frequency = recipe['start_hz'] + (recipe['end_hz'] - recipe['start_hz']) * fraction
        phase += 2 * math.pi * frequency / 48000
        signal = math.sin(phase)
        if recipe['wave'] == 'noise':
            state = (1664525 * state + 1013904223) & 0xFFFFFFFF
            signal *= state / 0x7FFFFFFF - 1
        elif recipe['wave'] == 'pulse':
            signal *= max(0, math.sin(2 * math.pi * 32 * index / 48000))
        envelope = min(1, index / 120) * math.exp(-recipe['decay'] * fraction)
        envelope *= min(1, (count - index - 1) / 240)
        samples.extend(struct.pack('<h', round(16000 * signal * envelope)))
    with wave.open(str(target), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(samples)


def _ass_time(seconds):
    centiseconds = round(seconds * 100)
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    sec, cs = divmod(remainder, 100)
    return f'{hours}:{minutes:02}:{sec:02}.{cs:02}'


def _caption(value):
    if not isinstance(value, str) or len(value) > 20:
        raise CharacterError('media')
    # ASS overrides and new dialogue rows cannot be injected by user/AI caption data.
    return ''.join(' ' if ord(c) < 32 else {'\\': '＼', '{': '｛', '}': '｝'}.get(c, c) for c in value)


def write_captions(target, story, timeline, presets):
    caption = presets['caption']
    margin = round(1920 * caption['top_margin_ratio'])
    lines = ['[Script Info]', 'ScriptType: v4.00+', 'PlayResX: 1080', 'PlayResY: 1920',
             'WrapStyle: 0', 'ScaledBorderAndShadow: yes', '', '[V4+ Styles]',
             'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, '
             'BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, '
             'BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
             f'Style: Main,{caption["family"]},{caption["size"]},&H00FFFFFF,&H00FFFFFF,&H00000000,'
             f'&H80000000,-1,0,0,0,100,100,0,0,1,{caption["outline"]},0,8,65,65,{margin},1',
             '', '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    total = timeline[-1]['start'] + timeline[-1]['seconds']
    hook, ending = _caption(_get(story, 'hook_caption', '')), _caption(_get(story, 'end_caption', ''))
    events = []
    if hook:
        events.append((0, min(2, total), hook))
    for scene, row in zip(_get(story, 'scenes'), timeline):
        text = _caption(_get(scene, 'caption', ''))
        start = max(row['start'], 2 if hook else 0)
        end = min(row['start'] + row['seconds'], total - 2 if ending else total)
        if text and end > start:
            events.append((start, end, text))
    if ending:
        events.append((max(0, total - 2), total, ending))
    lines.extend(f'Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Main,,0,0,0,,{text}'
                 for start, end, text in events)
    target.write_text('\n'.join(lines) + '\n', encoding='utf-8-sig')
    return len(events)


def audio_join_filters(timeline, crossfade):
    """Overlap audible tails while keeping every incoming clip at its video cut.

    Reflect the outgoing track's final bounded audio window beyond the cut.
    Reversing that window starts with its last sample, avoiding a jump back to
    the beginning of a repeated buffer. The extension is faded against the
    next clip's first window, so acrossfade removes only added tail time.
    Original samples and every next clip's start retain their video timing.
    """
    filters = []
    for index, row in enumerate(timeline):
        audio = f'[{index}:a]atrim=duration={row["seconds"]:.6f},asetpts=PTS-STARTPTS'
        if crossfade and index < len(timeline) - 1:
            if row['seconds'] < crossfade:
                raise CharacterError('media')
            filters.append(audio + f',asplit=2[body{index}][tail_source{index}]')
            filters.append(f'[tail_source{index}]atrim=start={row["seconds"]-crossfade:.6f}:'
                           f'end={row["seconds"]:.6f},areverse,asetpts=PTS-STARTPTS[tail{index}]')
            filters.append(f'[body{index}][tail{index}]concat=n=2:v=0:a=1[a{index}]')
        else:
            filters.append(audio + f'[a{index}]')
    previous = 'a0'
    for index in range(1, len(timeline)):
        operation = f'acrossfade=d={crossfade}:c1=tri:c2=tri' if crossfade else 'concat=n=2:v=0:a=1'
        filters.append(f'[{previous}][a{index}]{operation}[join{index}]')
        previous = f'join{index}'
    return filters, previous


def compose_episode(folder, story, clips, *, settings, ffmpeg=None, ffprobe=None):
    """Edit reviewed v3 clips without any external calls or additional speech."""
    presets, effects = load_edit_presets(), load_sfx_map()
    scenes, target = _get(story, 'scenes'), settings.get('duration')
    requested_target=target
    timeline = edit_timeline(story, target, presets)
    target=round(sum(row['seconds'] for row in timeline),6)
    if (len(clips) != len(scenes) or settings.get('aspect_ratio') != '9:16'
            or settings.get('sound') not in {'on', 'off'}):
        raise CharacterError('media')
    folder = Path(folder)
    if folder.is_symlink() or folder.is_junction() or (folder / 'final.mp4').exists():
        raise CharacterError('media')
    binary = str(FFmpegAdapter.executable('ffmpeg', ffmpeg))
    work = folder / 'compose'
    work.mkdir(exist_ok=False)
    sfx_events, generated = [], {}
    # Validate every SFX before decoding or generating media.
    for scene, row in zip(scenes, timeline):
        requests = _get(scene, 'sfx', [])
        if not isinstance(requests, list) or len(requests) > 2:
            raise CharacterError('media')
        for request in requests:
            key, at = _get(request, 'key'), _get(request, 'at')
            if key not in effects or at not in {'start', 'end'}:
                raise CharacterError('media')
            sfx_events.append({'key': key, 'seconds': row['start'] +
                               (row['content_seconds'] if at == 'end' else 0)})
    font = CONFIG.parent / presets['caption']['font']
    if not font.is_file() or font.is_symlink() or font.is_junction():
        raise CharacterError('media')
    (work / 'fonts').mkdir()
    shutil.copyfile(font, work / 'fonts' / 'NotoSansKR.ttf')
    caption_count = write_captions(work / 'captions.ass', story, timeline, presets)
    normalized = []
    for index, (clip, scene, row) in enumerate(zip(clips, scenes, timeline)):
        clip = Path(clip)
        info = probe_clip(clip, ffprobe)
        if info['duration'] < row['source_seconds'] - .1:
            raise CharacterError('media')
        source_audio = settings['sound'] == 'on' and info['has_audio']
        dest = work / f'scene-{index}.mp4'
        args = [binary, '-nostdin', '-n', '-v', 'error', '-protocol_whitelist', 'file',
                '-format_whitelist', FORMAT_WHITELIST, '-i', str(clip.resolve())]
        if not source_audio:
            args += ['-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000']
        video = (f'trim=duration={row["source_seconds"]},setpts=PTS-STARTPTS,'
                 f'setpts=PTS/{row["speed"]},fps=30,'
                 'scale=1080:1920:force_original_aspect_ratio=decrease,'
                 'pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,'
                 f'tpad=stop_mode=clone:stop_duration={row["freeze_seconds"]:.6f}')
        audio = f'atrim=duration={row["source_seconds"]},asetpts=PTS-STARTPTS,atempo={row["speed"]}'
        if _get(scene, 'speed') == 'fast' and _get(scene, 'fast_intensity') == 'strong':
            if presets['fast_strong_audio'] == 'mute':
                audio += ',volume=0'
            elif presets['fast_strong_audio'] == 'duck':
                audio += f',volume={presets["fast_strong_duck_db"]}dB'
        audio += f',apad,atrim=duration={row["seconds"]:.6f},asetpts=PTS-STARTPTS'
        run(args + ['-map', '0:v:0', '-map', '0:a:0' if source_audio else '1:a:0',
                    '-vf', video, '-af', audio, '-t', f'{row["seconds"]:.6f}',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '22', '-threads', '2',
                    '-c:a', 'aac', '-ar', '48000', '-ac', '2', str(dest.resolve())], work)
        normalized.append(dest)
    args = [binary, '-nostdin', '-n', '-v', 'error']
    for clip in normalized:
        args += ['-protocol_whitelist', 'file', '-i', str(clip.resolve())]
    for key in dict.fromkeys(event['key'] for event in sfx_events):
        path = work / f'sfx-{key}.wav'
        synthesize_sfx(path, effects[key])
        generated[key] = {'path': path, 'sha256': digest(path), 'input': len(normalized) + len(generated)}
        args += ['-protocol_whitelist', 'file', '-f', 'wav', '-i', str(path.resolve())]
    filters = []
    for index, row in enumerate(timeline):
        filters.append(f'[{index}:v]trim=duration={row["seconds"]:.6f},setpts=PTS-STARTPTS[v{index}]')
    filters.append(''.join(f'[v{i}]' for i in range(len(timeline))) +
                   f'concat=n={len(timeline)}:v=1:a=0[vjoined]')
    filters.append('[vjoined]subtitles=captions.ass:fontsdir=fonts[vout]')
    audio_filters, previous = audio_join_filters(timeline, presets['scene_audio_crossfade'])
    filters.extend(audio_filters)
    audio_labels = [f'[{previous}]']
    # Split reused sound inputs explicitly so one key can appear in multiple scenes.
    for key, details in generated.items():
        indexes = [index for index, event in enumerate(sfx_events) if event['key'] == key]
        labels = ''.join(f'[effect{index}]' for index in indexes)
        filters.append(f'[{details["input"]}:a]asplit={len(indexes)}{labels}')
    for index, event in enumerate(sfx_events):
        delay = round(event['seconds'] * 1000)
        filters.append(f'[effect{index}]aformat=sample_rates=48000:channel_layouts=stereo,'
                       f'volume={presets["sfx_volume_db"]}dB,adelay={delay}:all=1[sfx{index}]')
        audio_labels.append(f'[sfx{index}]')
    filters.append(''.join(audio_labels) + f'amix=inputs={len(audio_labels)}:normalize=0,'
                   f'apad,atrim=duration={target},loudnorm=I={presets["loudness_lufs"]}:TP=-1.5:LRA=11,'
                   'aresample=48000[aout]')
    (work / 'edit-filter.txt').write_text(';\n'.join(filters), encoding='utf-8')
    candidate = work / 'final-candidate.mp4'
    run(args + ['-filter_complex_threads', '1', '-filter_complex', ';'.join(filters),
                '-map', '[vout]', '-map', '[aout]', '-t', str(target), '-r', '30',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '22', '-threads', '2',
                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-ac', '2',
                '-movflags', '+faststart', str(candidate.resolve())], work)
    info = probe_clip(candidate, ffprobe)
    if ((info['width'], info['height'], info['video_codec']) != (1080, 1920, 'h264')
            or abs(info['duration'] - target) > .1 or not info['has_audio']):
        raise CharacterError('media')
    run([binary, '-nostdin', '-v', 'error', '-protocol_whitelist', 'file',
         '-i', str(candidate.resolve()), '-f', 'null', '-'], work)
    output = folder / 'final.mp4'
    candidate.rename(output)
    evidence = {'schema_version': 1, 'target_seconds': requested_target, 'output_seconds': target, 'timeline': timeline,
                'presets': presets, 'sfx_events': sfx_events,
                'sfx_sha256': {key: value['sha256'] for key, value in generated.items()},
                'sfx_provenance': 'original mathematical oscillators / CC0-1.0',
                'source_audio_classification': 'human review required',
                'audio_crossfade': 'reflected outgoing tail / incoming original start / video cuts unchanged',
                'actual_media': info}
    (work / 'edit-evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'file': 'final.mp4', 'sha256': digest(output), 'media': info,
            'captions_added': bool(caption_count), 'sfx_added': bool(sfx_events),
            'voice_added': False, 'music_added': False, 'ai_label_burned_in': False,
            'audio_source': 'model_and_local_effects' if settings['sound'] == 'on' else 'local_effects_only',
            'output_quality': '1080p', 'timeline': timeline, 'human_quality': 'NOT VERIFIED'}
