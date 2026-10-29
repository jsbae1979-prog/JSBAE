"""Local-only v2 composition; preserve generated audio when selected, never synthesize a voice."""
from pathlib import Path
from .compose import digest, run
from .kling import validate, dimensions
from .schema import CharacterError
from newsflow.video.ai.clips import probe_clip, FORMAT_WHITELIST
from newsflow.video.engine import FFmpegAdapter, RenderPlan, write_ass

def compose_studio(folder, story, clips, *, settings, ffmpeg=None, ffprobe=None):
    settings=validate(settings)
    total=sum(s.seconds for s in story.scenes)
    if total!=settings['duration'] or len(clips)!=len(story.scenes): raise CharacterError('media')
    binary=str(FFmpegAdapter.executable('ffmpeg',ffmpeg))
    work=folder/'compose'
    work.mkdir(exist_ok=False)
    width,height=dimensions(settings)
    normalized=[]
    for i,(clip,scene) in enumerate(zip(clips,story.scenes)):
        info=probe_clip(clip,ffprobe)
        if info['duration']<scene.seconds-2 or (settings['sound']=='on' and not info['has_audio']):
            raise CharacterError('media')  # Never replace a requested voice with fabricated silence.
        target=work/f'scene-{i}.mp4'
        args=[binary,'-nostdin','-n','-v','error','-protocol_whitelist','file',
              '-format_whitelist',FORMAT_WHITELIST,'-i',str(clip.resolve()),'-vf',
              f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,'
              'setsar=1,fps=30,format=yuv420p,'
              f'tpad=stop_mode=clone:stop_duration={max(0,scene.seconds-info["duration"]):.3f}',
              '-t',str(scene.seconds),'-c:v','libx264','-preset','ultrafast','-crf','22','-threads','2']
        if settings['sound']=='on':
            args+=['-af',f'apad,atrim=duration={scene.seconds},asetpts=PTS-STARTPTS',
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
    font=Path(__file__).with_name('assets')/'NotoSansKR.ttf'
    if digest(font)!='194018e6b2b293a7964f037b25c0249ce1418bc9ab3c971060a03aa57861e252':
        raise CharacterError('media')
    import shutil
    (work/'fonts').mkdir()
    shutil.copy2(font,work/'fonts'/font.name)
    cues=[]
    start=0
    for s in story.scenes:
        cues.append({'start_ms':start,'end_ms':start+s.seconds*1000,'text':s.caption})
        start+=s.seconds*1000
    plan=RenderPlan(story.title,[],[],font_size=44,subtitle_y=1450)
    write_ass(work/'captions.ass',cues,plan,font)
    text=(work/'captions.ass').read_text(encoding='utf-8-sig')
    text=text.replace('PlayResX: 1080',f'PlayResX: {width}').replace('PlayResY: 1920',f'PlayResY: {height}')
    # Avoid relying on fixed portrait subtitle margins for landscape/square output.
    import re
    text=re.sub(r'(Style: Default,[^\n]*,2,90,90,)\d+',r'\g<1>60',text)
    (work/'captions.ass').write_text(text,encoding='utf-8-sig')
    write_ass(work/'label.ass',[{'start_ms':0,'end_ms':total*1000,'text':'AI 생성 · 가상 이야기'}],plan,font)
    label=(work/'label.ass').read_text(encoding='utf-8-sig').replace('PlayResX: 1080',f'PlayResX: {width}').replace('PlayResY: 1920',f'PlayResY: {height}')
    label=re.sub(r'(Style: Default,[^\n]*,)2,90,90,\d+',r'\g<1>8,40,40,30',label)
    (work/'label.ass').write_text(label,encoding='utf-8-sig')
    output=folder/'final.mp4'
    args=[binary,'-nostdin','-n','-v','error','-protocol_whitelist','file','-i',str(joined.resolve()),
          '-vf','ass=captions.ass:fontsdir=fonts,ass=label.ass:fontsdir=fonts','-t',str(total),
          '-c:v','libx264','-preset','ultrafast','-crf','22','-threads','2','-pix_fmt','yuv420p']
    args+=['-c:a','aac'] if settings['sound']=='on' else ['-an']
    run(args+['-movflags','+faststart',str(output.resolve())],work)
    info=probe_clip(output,ffprobe)
    if ((info['width'],info['height'])!=(width,height) or abs(info['duration']-total)>.1
            or info['has_audio']!=(settings['sound']=='on')): raise CharacterError('media')
    run([binary,'-nostdin','-v','error','-protocol_whitelist','file','-i',str(output.resolve()),'-f','null','-'],work)
    return {'file':'final.mp4','sha256':digest(output),'media':info,'sound':settings['sound'],
            'audio_source':'model_output' if settings['sound']=='on' else 'none',
            'native_resolution':'not_verified','output_quality':settings['output_quality'],
            'human_quality':'NOT VERIFIED'}
