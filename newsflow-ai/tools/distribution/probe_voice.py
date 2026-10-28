"""Bounded offline SAPI probe. No external providers, playback or real text."""
import argparse,json,os
from pathlib import Path
import subprocess,sys,wave

def main():
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path);a=p.parse_args()
    root=Path(os.environ['NEWSFLOW_DISTRIBUTION_TEST_ROOT']).resolve()
    if not root.is_dir() or os.name!='nt' or sys.version_info[:3]!=(3,14,7):raise RuntimeError('Owned Windows probe required')
    work=root/'voice-probe'
    if work.exists():raise RuntimeError('Do not reuse probe output')
    work.mkdir()
    command=[str(a.exe.resolve()) if a.exe else sys.executable,'-m','newsflow.video.windows_sapi']
    env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','PATH','TEMP','TMP','COMSPEC','PATHEXT','LOCALAPPDATA','APPDATA','USERPROFILE','PYTHONPATH'}}
    result=subprocess.run(command+['-VoiceDetails'],capture_output=True,env=env,timeout=30)
    facts={'scope':'Frozen worker' if a.exe else 'Development Python worker','list_exit':result.returncode,'paid_calls':0,'app_server_launched':False,'voice_quality_human_review':'NOT VERIFIED'}
    if result.returncode==0:
        voices=json.loads(result.stdout);facts['voice_count']=len(voices);facts['korean_voice_count']=sum(v.get('culture','').lower()=='ko-kr' for v in voices)
        if voices:
            voice=next((v for v in voices if v.get('culture','').lower()=='ko-kr'),voices[0])
            target=work/'synthetic.wav';spec=work/'synthetic-spec.json'
            spec.write_text(json.dumps({'voice':voice['name'],'target':str(target),'sentences':['뉴스플로 합성 음성 검사입니다.' if voice.get('culture','').lower()=='ko-kr' else 'This is an offline synthetic NewsFlow voice check.'],'rate':0,'pause_ms':0},ensure_ascii=False),encoding='utf8')
            run=subprocess.run(command+['-Spec',str(spec)],capture_output=True,env=env,timeout=40)
            facts['synthesis_exit']=run.returncode
            if run.returncode==0 and target.is_file():
                with wave.open(str(target),'rb') as f:
                    frames=f.readframes(f.getnframes());facts.update(channels=f.getnchannels(),sample_width=f.getsampwidth(),sample_rate=f.getframerate(),seconds=f.getnframes()/f.getframerate(),has_signal=any(abs(int.from_bytes(frames[i:i+2],'little',signed=True))>64 for i in range(0,len(frames),2)))
    (root/'voice-results.json').write_text(json.dumps(facts,indent=2),encoding='utf8');print(json.dumps(facts))
    if not facts.get('has_signal'):raise SystemExit(1)
if __name__=='__main__':main()
