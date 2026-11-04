"""Local free editing only: reviewed normalized video + byte-preserved mixed audio.

Never loads a provider/key or starts NewsFlow. The source final and its metadata
are preserved before an explicitly requested completed-job revision is published.
"""
from pathlib import Path
import json,os,sys,hashlib,shutil,subprocess
sys.dont_write_bytecode=True
from newsflow.character.compose import run,digest
from newsflow.video.ai.clips import probe_clip
from newsflow.video.engine import FFmpegAdapter
from newsflow.video_models.catalog import CONFIG
from newsflow.character.editing import _ass_time
from newsflow.character.schema import CharacterError
from newsflow.distribution.windows_profile import private_directory

def escaped(text):
    if not isinstance(text,str) or not 1<=len(text)<=40:raise CharacterError('media')
    return ''.join(' ' if ord(c)<32 else {'\\':'＼','{':'｛','}':'｝'}.get(c,c) for c in text)

def caption_line(parts):
    if not isinstance(parts,list) or not 1<=len(parts)<=2:raise CharacterError('media')
    if any(len(p)>14 for p in parts):raise CharacterError('media')
    return r'\N'.join((r'{\c&H00FFFFFF&}' if i==0 else r'{\c&H0000E7FF&}')+escaped(p) for i,p in enumerate(parts))

def write_shortform(path,events,total):
    lines=['[Script Info]','ScriptType: v4.00+','PlayResX: 1080','PlayResY: 1920','WrapStyle: 2','ScaledBorderAndShadow: yes','',
      '[V4+ Styles]','Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
      'Style: Social,Noto Sans KR,112,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,7,2,2,100,180,390,1','',
      '[Events]','Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    previous=0
    for start,end,parts in events:
        if not (previous<=start<end<=total):raise CharacterError('media')
        text=caption_line(parts)
        lines.append(f'Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Social,,0,0,0,,'+
                     r'{\fad(70,70)\fscx104\fscy104\t(0,100,\fscx100\fscy100)}'+text)
        previous=end
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8-sig')

def compose(folder,work,events,*,ffmpeg,ffprobe):
    folder=Path(folder);work=Path(work)
    if folder.is_symlink() or folder.is_junction() or work.exists():raise CharacterError('media')
    job=json.loads((folder/'jobs.json').read_bytes())
    if job['state']!='completed' or job.get('automation_version')!=1:raise CharacterError('blocked')
    source=folder/'final.mp4'
    if digest(source)!=job['output']['sha256']:raise CharacterError('media')
    clips=[];timeline=job['output']['timeline']
    for index,(scene,row) in enumerate(zip(job['scenes'],timeline,strict=True)):
        if scene['state']!='downloaded' or digest(folder/scene['file'])!=scene['sha256']:raise CharacterError('media')
        clip=folder/'compose'/f'scene-{index}.mp4'
        if clip.is_symlink() or clip.is_junction():raise CharacterError('media')
        info=probe_clip(clip,ffprobe)
        if (info['width'],info['height'])!=(1080,1920) or abs(info['duration']-row['seconds'])>.1:raise CharacterError('media')
        clips.append(clip)
    private_directory(work);(work/'fonts').mkdir()
    font=CONFIG.parent/'character/assets/NotoSansKR.ttf'
    shutil.copyfile(font,work/'fonts/NotoSansKR.ttf')
    total=job['duration'];write_shortform(work/'social.ass',events,total)
    binary=str(FFmpegAdapter.executable('ffmpeg',ffmpeg));args=[binary,'-nostdin','-n','-v','error']
    for clip in clips:args+=['-protocol_whitelist','file','-i',str(clip.resolve())]
    args+=['-protocol_whitelist','file','-i',str(source.resolve())]
    filters=[]
    for i,row in enumerate(timeline):filters.append(f'[{i}:v]trim=duration={row["seconds"]:.6f},setpts=PTS-STARTPTS[v{i}]')
    filters.append(''.join(f'[v{i}]' for i in range(len(clips)))+f'concat=n={len(clips)}:v=1:a=0[plain]')
    filters.append('[plain]subtitles=social.ass:fontsdir=fonts[vout]')
    output=work/'final-social.mp4'
    run(args+['-filter_complex_threads','1','-filter_complex',';'.join(filters),'-map','[vout]','-map',f'{len(clips)}:a:0',
      '-t',str(total),'-r','30','-c:v','libx264','-preset','ultrafast','-crf','22','-threads','2','-pix_fmt','yuv420p',
      '-c:a','copy','-movflags','+faststart',str(output.resolve())],work)
    info=probe_clip(output,ffprobe)
    if (info['width'],info['height'],info['duration'],info['has_audio'])!=(1080,1920,float(total),True):raise CharacterError('media')
    run([binary,'-nostdin','-v','error','-protocol_whitelist','file','-i',str(output.resolve()),'-f','null','-'],work)
    # Exact AAC packet payloads must match, including all reviewed environmental sound/SFX.
    hashes=[]
    from newsflow.video.tts import local_process_env
    for path in [source,output]:
        p=subprocess.run([binary,'-nostdin','-v','error','-protocol_whitelist','file','-i',str(path.resolve()),'-map','0:a:0',
          '-c:a','copy','-f','hash','-hash','sha256','-'],capture_output=True,check=True,env=local_process_env())
        hashes.append(p.stdout.strip().decode('ascii'))
    if hashes[0]!=hashes[1]:raise CharacterError('media')
    result={'sourceSha256':digest(source),'file':'final.mp4','sha256':digest(output),'media':info,
       'captions_added':True,'caption_style':'shortform_bold_two_line_safe_area',
       'sfx_added':job['output']['sfx_added'],'voice_added':False,'music_added':False,
       'sourceAudioPacketHash':hashes[0],'audioPacketHashUnchanged':True,'additionalPaidCalls':0}
    (work/'VARIANT_RESULT.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    return result

def publish(folder,work):
    # Explicit local editing revision only; preserve provider receipts, script and source clips.
    from newsflow.character.service import CharacterService
    folder=Path(folder);work=Path(work)
    service=CharacterService(folder.parent.parent,None,None,writer=object(),video=object(),budget=object())
    result=json.loads((work/'VARIANT_RESULT.json').read_bytes())
    with service.lock():
        job=service.read(folder.name);original=(folder/'jobs.json').read_bytes()
        review_path=folder/'review.json';review_before=review_path.read_bytes()
        final=folder/'final.mp4'
        assert job['state']=='completed' and job['output']['sha256']==result['sourceSha256']==digest(final)
        assert digest(work/'final-social.mp4')==result['sha256']
        archive=folder/'local-edits/shortform-captions-20261031'
        assert not archive.exists()
        private_directory(archive.parent)
        private_directory(archive)
        shutil.copy2(final,archive/'previous-final.mp4')
        (archive/'jobs.before.private.json').write_bytes(original)
        (archive/'review.before.private.json').write_bytes(review_before)
        shutil.copy2(work/'social.ass',archive/'social.ass')
        staging=folder/'final.local-caption-edit.mp4';assert not staging.exists()
        shutil.copy2(work/'final-social.mp4',staging)
        old_output=dict(job['output']);job.setdefault('local_edit_history',[]).append({
          'kind':'shortform_caption_style','previousOutput':old_output,'archive':'local-edits/shortform-captions-20261031/previous-final.mp4',
          'additionalPaidCalls':0,'audioPacketHashUnchanged':True})
        job['output']={**old_output,**{k:result[k] for k in ('file','sha256','media','captions_added','caption_style')},'human_quality':'NOT VERIFIED'}
        try:
            os.replace(staging,final);service.save(job)
            review=json.loads(review_before);review.update(output=job['output'],human_review='NOT VERIFIED')
            temp=archive/'review.new.json';temp.write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf8')
            os.replace(temp,review_path)
        except BaseException:
            if digest(final)==result['sha256']:
                shutil.copy2(archive/'previous-final.mp4',staging);os.replace(staging,final)
            (folder/'jobs.restore.tmp').write_bytes(original);os.replace(folder/'jobs.restore.tmp',folder/'jobs.json')
            review_path.write_bytes(review_before)
            raise
        assert digest(final)==service.read(folder.name)['output']['sha256']==result['sha256']
        assert digest(archive/'previous-final.mp4')==result['sourceSha256']
    return {'published':True,'previousFinalPreserved':True,'additionalPaidCalls':0,'restartCount':0,'sha256':result['sha256']}
