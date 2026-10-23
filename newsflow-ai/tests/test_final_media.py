"""Four production combinations with real local FFmpeg and synthetic narration only."""
import base64
import json
import subprocess
import wave
from pathlib import Path

import pytest
from sqlalchemy import select
from test_final_production import full, new_plan, no_external, rev, rows
from test_voice_engines import Keys, config

from newsflow.db.models import AIVideoPlan, AudioTrack, ContentDraft, RenderJob, VideoProject
from newsflow.video.ai.production import completed_render, read_contract
from newsflow.video.ai.service import AIVideoError
from newsflow.video.elevenlabs_tts import ElevenLabsTTS, save_settings
from newsflow.video.engine import FFmpegAdapter
from newsflow.video.tts import FakeTTS

__all__=['full','no_external']


class LocalFakeVoice(FakeTTS):
    def __init__(self,seconds): self.seconds=seconds
    def voices(self): return ['Synthetic Korean']
    def synthesize(self,text,target,voice,seconds,speech=None):
        assert voice=='Synthetic Korean'
        with wave.open(str(target),'wb') as output:
            output.setparams((1,2,24000,0,'NONE','not compressed'))
            output.writeframes(b'\xe8\x03'*round(self.seconds*24000))


class TimedVoiceTransport:
    def __init__(self, seconds): self.seconds,self.posts=seconds,0
    def __call__(self,method,path,payload=None):
        if method=='GET':
            return {'status':'active','tier':'starter','character_count':0,'character_limit':10000,
                    'max_credit_limit_extension':0}
        self.posts+=1
        text=payload['text']
        return {'audio_base64':base64.b64encode(b'\xe8\x03'*round(self.seconds*24000)).decode(),
                'alignment':{'characters':list(text),
                    'character_start_times_seconds':[self.seconds*i/len(text) for i in range(len(text))],
                    'character_end_times_seconds':[self.seconds*(i+1)/len(text) for i in range(len(text))]}}


@pytest.mark.parametrize(('ai','voice','duration'),[(False,'local',30),(False,'elevenlabs',45),
                                                  (True,'local',60),(True,'elevenlabs',30)])
def test_four_combinations_local_mp4(full,monkeypatch,ai,voice,duration,tmp_path):
    chosen='elevenlabs' if voice=='elevenlabs' else 'Synthetic Korean'
    # Use the stored source/script fixture, frozen choices and six short visual scenes.
    plan=new_plan(full,duration,chosen)
    seconds=duration/6-.4
    audio_api=TimedVoiceTransport(seconds)
    full.app.state.video.engine=FFmpegAdapter()
    if voice=='elevenlabs':
        save_settings(full.app.state.sessions,**config())
        full.app.state.video.tts=None
        monkeypatch.setattr('newsflow.video.elevenlabs_tts.ElevenLabsTTS',lambda root,configuration,consent:
            ElevenLabsTTS(root,configuration,consent=consent,transport=audio_api,keys=Keys()))
    else:
        full.app.state.video.tts=LocalFakeVoice(seconds)
    if ai:
        full.service.confirm_generation(plan,rev(full,plan),'',True)
        for _ in range(10):
            full.service.tick()
            if all(s.status=='ready' for s in rows(full,plan)): break
        assert all(s.status=='ready' for s in rows(full,plan)),[(s.status,s.message) for s in rows(full,plan)]
        with pytest.raises(AIVideoError): full.service.approve_compose(plan,rev(full,plan),True)
        full.service.review(plan,rev(full,plan),set(range(6)),True)
        identifier=full.service.approve_compose(plan,rev(full,plan),True)
    else:
        identifier=full.app.state.video.start_preview(full.draft_id,duration,voice=chosen,
            external_tts_consent=voice=='elevenlabs',elevenlabs_config=config() if voice=='elevenlabs' else None)
    full.app.state.video.future.result(timeout=240)
    with full.app.state.sessions() as session:
        job=session.get(RenderJob,identifier)
        assert job.status=='success',job.message
        project=session.get(VideoProject,job.project_id)
        assert session.scalar(select(AudioTrack).where(AudioTrack.project_id==project.id)).voice==chosen
        assert project.duration==duration
        assert project.snapshot['speech']['strict_audio_fit'] or voice=='local' and not ai
        target=full.app.state.video.outputs/job.output_name
    binary,probe,_version=FFmpegAdapter().check()
    result=subprocess.run([str(probe),'-v','error','-show_streams','-show_format','-of','json',str(target)],
                          capture_output=True,check=True,timeout=30)
    info=json.loads(result.stdout)
    video=next(s for s in info['streams'] if s['codec_type']=='video')
    audio=next(s for s in info['streams'] if s['codec_type']=='audio')
    assert (video['width'],video['height'],video['codec_name'])==(1080,1920,'h264')
    assert audio['codec_name']=='aac' and abs(float(info['format']['duration'])-duration)<.15
    subprocess.run([str(binary),'-v','error','-i',str(target),'-f','null','-'],capture_output=True,check=True,timeout=60)
    if not ai: assert full.provider.calls==[]
    else:
        assert len([call for call in full.provider.calls if call[0]=='submit'])==6
        full.service.sync()
        with full.app.state.sessions() as s:
            assert s.get(AIVideoPlan,plan).status=='composed'
            contract=read_contract(s,plan)
            assert completed_render(s,full.draft_id,contract['production'],duration).id==identifier
            wrong={**contract['production'],'voice':'another-voice'}
            assert completed_render(s,full.draft_id,wrong,duration) is None
    if voice=='local': assert audio_api.posts==0
    else: assert 0<audio_api.posts<=6
    # A second local synthesis of identical text uses the saved WAV+alignment, no POST.
    if voice=='elevenlabs':
        provider=ElevenLabsTTS(full.app.state.config.data_dir,config(),consent=True,transport=audio_api,keys=Keys())
        with full.app.state.sessions() as s: text=s.get(ContentDraft,full.draft_id).content['scenes'][0]['narration']
        count=audio_api.posts
        provider.synthesize_timed(text,tmp_path/'reused.wav','elevenlabs',120)
        assert audio_api.posts==count
    evidence={'mode':'full_ai' if ai else 'basic','voice':voice,'seconds':float(info['format']['duration']),
              'resolution':[1080,1920],'video_codec':'h264','audio_codec':'aac','decoded':True,
              'voice_quality':'NOT VERIFIED - synthetic PCM','real_service_calls':0}
    output=Path(__import__('os').environ.get('NEWSFLOW_VALIDATION_OUTPUT',str(tmp_path)))
    output.mkdir(parents=True,exist_ok=True)
    (output/f'media-{ai}-{voice}-{duration}.json').write_text(json.dumps(evidence),encoding='utf-8')
