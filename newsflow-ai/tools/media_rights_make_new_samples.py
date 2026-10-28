"""Create separate replacement candidates; never writes the live sample catalog."""
import argparse,hashlib,json,os,shutil,subprocess,time
from pathlib import Path
from PIL import Image

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--ffmpeg',type=Path,required=True);ap.add_argument('--ffprobe',type=Path,required=True);ap.add_argument('--font',type=Path,required=True);a=ap.parse_args()
    root=a.root.resolve();catalog=root/'new-samples'
    if catalog.name!='new-samples' or not root.is_dir():raise ValueError('Owned new candidate directory required')
    record=json.loads((root/'ART_GENERATION_RECORDS.json').read_text(encoding='utf8'))
    font=catalog/'fonts/NotoSansKR.ttf';font.parent.mkdir(exist_ok=True)
    shutil.copyfile(a.font,font)
    for d in ('raw','images','videos','render-work'):(catalog/d).mkdir(exist_ok=True)
    env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','PROCESSOR_ARCHITECTURE','OS','PATH'}}
    env.update(TEMP=str(catalog/'render-work'),TMP=str(catalog/'render-work'))
    commands=[];assets=[];checks=[]
    def run(args,cwd=catalog):
        commands.append([str(x) for x in args])
        r=subprocess.run([str(x) for x in args],cwd=cwd,env=env,capture_output=True,timeout=180)
        if r.returncode:raise RuntimeError(r.stderr.decode('utf8','replace')[-1500:])
        return r.stdout
    def check(name,ok):
        checks.append({'name':name,'status':'PASS' if ok else 'FAIL'})
        if not ok:raise AssertionError(name)
    rights={'rightsVerified':False,'commercialRedistribution':'CONDITIONAL: source/provenance and published OpenAI output terms recorded; publisher/account governing-agreement evidence not supplied',
        'termsUrl':'https://openai.com/policies/terms-of-use/','thirdPartyInputUsed':False,
        'visualReview':'No obvious third-party logo, real person or identifiable named character in selected outputs; not a legal clearance or exclusivity guarantee',
        'publicReleaseApproved':False}
    for row in record['records']:
        identity=row['id'];raw=catalog/'raw'/(identity+'.png')
        shutil.copyfile(Path(row['source_path']),raw)
        with Image.open(raw) as im:
            im.load();raw_size=im.size;raw_mode=im.mode
        target=(1080,1350) if identity.startswith('top3-') else (720,1080)
        # Deterministic resize/crop/PNG export only; no semantic repainting.
        exported=catalog/'images'/(identity+'-normalized.png')
        filt=f'scale={target[0]}:{target[1]}:force_original_aspect_ratio=increase:flags=lanczos,crop={target[0]}:{target[1]}'
        run([a.ffmpeg,'-nostdin','-n','-v','error','-protocol_whitelist','file','-i',raw,'-vf',filt,
             '-frames:v','1','-pix_fmt','rgba' if raw_mode=='RGBA' else 'rgb24',exported])
        with Image.open(exported) as im:
            im.load();check(identity+'_decode_dimensions',im.size==target)
        assets.append({'id':identity,'path':exported.relative_to(catalog).as_posix(),'sha256':sha(exported),
            'bytes':exported.stat().st_size,'dimensions':list(target),'type':'character' if identity.startswith('character') else 'top3-image' if identity.startswith('top3') else 'standalone-image',
            'source':{'raw':raw.relative_to(catalog).as_posix(),'sha256':sha(raw),'dimensions':raw_size,'mode':raw_mode,'prompt':row['prompt'],'generation':'built-in image_gen','modelId':'NOT EXPOSED'},
            'sample':True,'version':2,'providerGenerated':True,'activeInProduct':False,**rights})
    specs=[('news-short-v2',['top3-ai-v2','top3-ev-v2','top3-economy-v2'],'가상의 뉴스 이미지 예제'),
           ('character-short-robot-v2',['character-robot-v2']*3,'로봇 참조 이미지 예제'),
           ('character-short-cat-v2',['character-cat-v2']*3,'고양이 참조 이미지 예제')]
    for identity,inputs,title in specs:
        work=catalog/'render-work'/identity;work.mkdir(exist_ok=False)
        ass=work/'label.ass'
        ass.write_text('[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Noto Sans KR,42,&H00FFFFFF,&H00FFFFFF,&H00111C35,&H80000000,0,0,0,0,100,100,0,0,3,2,0,2,60,60,90,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:00.00,0:00:12.00,Default,,0,0,0,,샘플 미리보기 · 무음\\N'+title+'\n',encoding='utf-8-sig')
        for i,asset_id in enumerate(inputs):
            image=catalog/next(x['path'] for x in assets if x['id']==asset_id)
            dest=work/f'scene-{i}.mp4'
            vf='scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920,setsar=1'
            run([a.ffmpeg,'-nostdin','-n','-v','error','-loop','1','-framerate','30','-protocol_whitelist','file','-i',image,
                 '-t','4','-vf',vf,'-an','-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-r','30',dest])
        (work/'concat.txt').write_text(''.join(f"file 'scene-{i}.mp4'\n" for i in range(3)),encoding='utf8')
        output=catalog/'videos'/(identity+'.mp4')
        relative_font=Path(os.path.relpath(font.parent,work)).as_posix()
        run([a.ffmpeg,'-nostdin','-n','-v','error','-protocol_whitelist','file,pipe','-f','concat','-safe','1','-i','concat.txt',
             '-vf','ass=label.ass:fontsdir='+relative_font,'-t','12','-an','-c:v','libx264','-preset','veryfast','-crf','20',
             '-pix_fmt','yuv420p','-r','30','-movflags','+faststart',output],cwd=work)
        info=json.loads(run([a.ffprobe,'-v','error','-show_streams','-show_format','-of','json',output]))
        video=next(s for s in info['streams'] if s['codec_type']=='video')
        check(identity+'_format',video['codec_name']=='h264' and video['pix_fmt']=='yuv420p' and (video['width'],video['height'])==(1080,1920))
        check(identity+'_duration_audio',abs(float(info['format']['duration'])-12)<.05 and all(s['codec_type']!='audio' for s in info['streams']))
        run([a.ffmpeg,'-nostdin','-v','error','-protocol_whitelist','file','-i',output,'-f','null','-'])
        check(identity+'_full_decode',True)
        assets.append({'id':identity,'path':output.relative_to(catalog).as_posix(),'sha256':sha(output),'bytes':output.stat().st_size,
            'dimensions':[1080,1920],'duration':float(info['format']['duration']),'fps':video['r_frame_rate'],'audio':False,
            'sample':True,'version':2,'providerGenerated':False,'type':'news-video' if identity.startswith('news') else 'character-video',
            'construction':'Three 4-second still-image sections; no narration, generated character movement or editable original project',
            'inputs':[{'id':v,'sha256':next(x['sha256'] for x in assets if x['id']==v)} for v in inputs],
            'activeInProduct':False,**rights})
    manifest={'schemaVersion':1,'version':2,'candidateOnly':True,'activeInProduct':False,'assets':assets,
              'originalCatalogModified':False,'generationRecord':'../ART_GENERATION_RECORDS.json',
              'font':{'path':'fonts/NotoSansKR.ttf','sha256':sha(font),'license':'SIL OFL1.1; existing licensed Noto Sans KR source'},
              'externalPaidRestOrSdkCalls':0,'builtInImageGenerationCalls':10,'rejectedGenerationCount':1}
    (catalog/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    (catalog/'processing-commands.json').write_text(json.dumps(commands,ensure_ascii=False,indent=2),encoding='utf8')
    (root/'NEW_SAMPLE_TEST_RESULTS.json').write_text(json.dumps({'checks':checks,'pass':len(checks),'fail':0,'browser_playback':'NOT VERIFIED','original_samples_rechecked':False,'originals_modified':False},indent=2),encoding='utf8')
    print(json.dumps({'assets':len(assets),'images':9,'videos':3,'PASS':len(checks),'FAIL':0,'rightsVerified':False,'catalogActivated':False}))

if __name__=='__main__':main()
