"""Join reviewed clips locally; preserve selected model audio, add no text or voice."""
from .compose import digest, run
from .kling import validate, dimensions
from .schema import CharacterError
from newsflow.video.ai.clips import probe_clip, FORMAT_WHITELIST
from newsflow.video.engine import FFmpegAdapter

def compose_studio(folder, story, clips, *, settings, ffmpeg=None, ffprobe=None):
    settings=validate(settings)
    total=sum(s.seconds for s in story.scenes)
    if total!=settings['duration']: raise CharacterError('media')
    if len(clips)==1:
        from .kling import as_generation
        from newsflow.video_models.catalog import validate as validate_generation
        if validate_generation(as_generation(settings,total)):raise CharacterError('media')
        clip_durations=[total]
    elif len(clips)==len(story.scenes):
        clip_durations=[scene.seconds for scene in story.scenes]
    else:
        raise CharacterError('media')
    binary=str(FFmpegAdapter.executable('ffmpeg',ffmpeg))
    work=folder/'compose'
    work.mkdir(exist_ok=False)
    width,height=dimensions(settings)
    normalized=[]
    for i,(clip,seconds) in enumerate(zip(clips,clip_durations)):
        info=probe_clip(clip,ffprobe)
        if info['duration']<seconds-2 or (settings['sound']=='on' and not info['has_audio']):
            raise CharacterError('media')  # Never replace a requested voice with fabricated silence.
        target=work/f'scene-{i}.mp4'
        args=[binary,'-nostdin','-n','-v','error','-protocol_whitelist','file',
              '-format_whitelist',FORMAT_WHITELIST,'-i',str(clip.resolve()),'-vf',
              f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,'
              'setsar=1,fps=30,format=yuv420p,'
              f'tpad=stop_mode=clone:stop_duration={max(0,seconds-info["duration"]):.3f}',
              '-t',str(seconds),'-c:v','libx264','-preset','ultrafast','-crf','22','-threads','2']
        if settings['sound']=='on':
            args+=['-af',f'apad,atrim=duration={seconds},asetpts=PTS-STARTPTS',
                   '-c:a','aac','-ar','48000','-ac','2']
        else:
            args+=['-an']
        run(args+[str(target.resolve())],work)
        normalized.append(target)
    # Code-owned list entries only. No uploaded filename reaches this demuxer.
    (work/'clips.txt').write_text(''.join(f"file 'scene-{i}.mp4'\n" for i in range(len(clips))),encoding='ascii')
    joined=work/'joined.mp4'
    run([binary,'-nostdin','-n','-v','error','-f','concat','-safe','1',
         '-protocol_whitelist','file','-i','clips.txt','-c','copy',str(joined.resolve())],work)
    # Normalized clips contain only reviewed video and, when selected, their original
    # model audio. Remux the joined streams without subtitles, labels, TTS or SFX.
    # This does not remove text/audio already present inside a supplier's clip.
    output=folder/'final.mp4'
    args=[binary,'-nostdin','-n','-v','error','-protocol_whitelist','file','-i',str(joined.resolve()),
          '-map','0:v:0','-t',str(total),'-c:v','copy']
    args+=['-map','0:a:0','-c:a','copy'] if settings['sound']=='on' else ['-an']
    run(args+['-movflags','+faststart',str(output.resolve())],work)
    info=probe_clip(output,ffprobe)
    if ((info['width'],info['height'])!=(width,height) or abs(info['duration']-total)>.1
            or info['has_audio']!=(settings['sound']=='on')): raise CharacterError('media')
    run([binary,'-nostdin','-v','error','-protocol_whitelist','file','-i',str(output.resolve()),'-f','null','-'],work)
    return {'file':'final.mp4','sha256':digest(output),'media':info,'sound':settings['sound'],
            'audio_source':'model_output' if settings['sound']=='on' else 'none',
            'native_resolution':'not_verified','output_quality':settings['output_quality'],
            'captions_added':False,'voice_added':False,'ai_label_burned_in':False,
            'human_quality':'NOT VERIFIED'}
