"""Calls unchanged product command builders/composers with synthetic media only."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path
from threading import Event
from PIL import Image

def main():
    ap=argparse.ArgumentParser();ap.add_argument('workspace',type=Path);a=ap.parse_args()
    root=a.workspace.resolve()
    if os.environ.get('GITHUB_ACTIONS')!='true' or not root.is_relative_to(Path(os.environ['RUNNER_TEMP']).resolve()):
        raise SystemExit('Owned Windows CI only')
    binary=root/'prefix/bin/ffmpeg.exe';probe=root/'prefix/bin/ffprobe.exe'
    out=root/'functional';out.mkdir()
    results={'checks':[],'product_media_replaced':False,'paid_calls':0,'environment':'Windows Server native CI'}
    def check(name,ok):
        results['checks'].append({'name':name,'status':'PASS' if ok else 'FAIL'})
        if not ok:raise AssertionError(name)
    def command(args,cwd=out):
        r=subprocess.run([str(x) for x in args],cwd=cwd,capture_output=True,timeout=300)
        if r.returncode:
            # Only synthetic media and fixed args; no credentials in this child.
            raise RuntimeError(r.stderr.decode('utf8','replace')[-2000:])
        return r.stdout
    try:
        from newsflow.video.engine import FFmpegAdapter,RenderPlan,ScenePlan
        from newsflow.video.tts import OfflineTTS
        from newsflow.character.compose import compose
        from newsflow.character.schema import Storyboard
        version=command([binary,'-version']).decode('utf8','replace')
        results['version']=version.splitlines()[0]
        check('configured_gpl_static','--enable-gpl' in version and '--enable-static' in version)
        check('network_not_enabled','--disable-network' in version)
        enc=command([binary,'-hide_banner','-encoders']).decode('utf8','replace')
        filters=command([binary,'-hide_banner','-filters']).decode('utf8','replace')
        for n in ['libx264','aac','png']:
            check('encoder_'+n,n in enc)
        for n in ['ass','xfade','scale','crop','overlay','apad','amix','tpad','zoompan','drawbox']:
            check('filter_'+n,any(n==x.split()[1] for x in filters.splitlines() if len(x.split())>1))
        imports=[]
        for filename in ['ffmpeg-imports.txt','ffprobe-imports.txt']:
            imports+= (root/'evidence'/filename).read_text().split()
        results['import_dlls']=sorted(set(imports))
        check('no_external_runtime_dll',not any(any(v in n.lower() for v in ['libgcc','libstdc','libwinpthread','libass','freetype','harfbuzz','fribidi','zlib']) for n in imports))
        adapter=FFmpegAdapter(binary,probe)
        adapter.check();check('product_preflight',True)
        image=out/'synthetic.png';Image.new('RGB',(720,1280),(24,35,70)).save(image)
        news=out/'news';news.mkdir()
        plan=RenderPlan('합성 뉴스 검증',[ScenePlan(10,'합성 예제','검증용 자막',image=image,effect='fade') for _ in range(3)],[])
        movie,metadata=adapter.render(plan,news,OfflineTTS(),lambda p:None,Event())
        check('unchanged_news_render_30s',metadata['video_codec']=='h264' and metadata['width']==1080 and metadata['height']==1920)
        command([binary,'-v','error','-i',movie,'-f','null','-'])
        check('news_full_decode',True)
        clips=[]
        for i in range(3):
            p=out/f'clip-{i}.mp4'
            command([binary,'-nostdin','-n','-v','error','-loop','1','-i',image,'-t','10',
                     '-vf','scale=1080:1920,setsar=1','-an','-c:v','libx264','-preset','ultrafast','-r','30','-pix_fmt','yuv420p',p])
            clips.append(p)
        story=Storyboard.model_validate({'plan':{'situation':'예제','contrast':'검증','punchline':'완료'},
            'title':'합성 캐릭터 검증','hook_caption':'샘플','end_caption':'검증 완료',
            'scenes':[{'seconds':10,'role':role,'action':'A geometric reference moves gently.','caption':'검증용 자막','sfx':''} for role in ['setup','contrast','punchline']]})
        character=out/'character';character.mkdir()
        meta=compose(character,story,clips,ffmpeg=binary,ffprobe=probe)
        check('unchanged_character_compose_30s',meta['media']['width']==1080 and meta['media']['height']==1920 and abs(meta['media']['duration']-30)<.04)
        check('character_full_decode',True) # compose() itself performs the full decode
        clip_work=out/'clip-overlay';clip_work.mkdir()
        clip_plan=RenderPlan('합성 클립',[ScenePlan(2,'예제','검증',clip=clips[0],ai_generated=True)],[])
        adapter.render(clip_plan,clip_work,OfflineTTS(),lambda p:None,Event())
        check('unchanged_ai_clip_overlay',True)
        results['binary_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [binary,probe]}
        results['result']='PASS'
    except BaseException as exc:
        results['result']='FAIL';results['failure']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        (root/'evidence/FUNCTIONAL_RESULTS.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(results,ensure_ascii=True))

if __name__=='__main__':main()
