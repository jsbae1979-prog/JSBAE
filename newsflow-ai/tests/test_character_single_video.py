"""One 15-second supplier submission, then local composition; no real provider."""
from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest
from test_api_settings import sessions,store
from test_character_kling_studio import studio,create,story

from newsflow.character.compose_studio import compose_studio
from newsflow.character.kling import DEFAULTS,K3,O3,check
from newsflow.character.schema import CharacterError
from newsflow.character.studio_story import StudioStoryboard,prompts
from newsflow.video.ai.clips import probe_clip
from newsflow.video.tts import local_process_env


def seeded(studio,*,duration=15,model=K3):
    s=studio.service
    identifier=create(studio,duration=duration,clip_seconds=duration//5,video_model=model,
                      sound='off',output_quality='720p')
    job=s.read(identifier)
    screenplay=StudioStoryboard.model_validate(story(duration,'off'))
    for n,scene in enumerate(screenplay.scenes,1):
        scene.action=f'The original reference character completes distinct story beat {n} in an office.'
    job['script']=screenplay.model_dump()
    job['prompts']=prompts(screenplay,check(job['studio_selection']),job['character'])
    job['plan_hash']=s.plan_hash(job)
    job['state']='script_review'
    s.save(job)
    provider=s.video_for(job)
    estimates=[]
    provider.estimate=lambda payload:(estimates.append(deepcopy(payload)) or '0.10')
    return identifier,provider,estimates


@pytest.mark.parametrize('model',[K3,O3])
def test_five_story_beats_become_exactly_one_15_second_estimate_and_submit(studio,model):
    s=studio.service
    identifier,provider,estimates=seeded(studio,model=model)
    original=s.read(identifier)
    s.prepare(identifier,consent=True,script_reviewed=True)
    quoted=s.read(identifier)
    assert len(estimates)==len(quoted['scenes'])==1
    payload=quoted['scenes'][0]['payload']
    assert payload['duration']==15 and payload['sound']=='off' and payload['multi_shots'] is False
    assert quoted['scenes'][0]['story_positions']==[1,2,3,4,5]
    assert all(f'distinct story beat {n}' in payload['prompt'] for n in range(1,6))
    assert all(f'{start}-{start+3} seconds:' in payload['prompt'] for start in range(0,15,3))
    assert len(payload['prompt'])<=4500
    assert quoted['prompts']==original['prompts'] and quoted['script']==original['script']
    assert quoted['plan_hash']==original['plan_hash'] and quoted['quote_total_usd']=='0.10'
    s.submit(identifier,consent=True,quote_hash=quoted['quote_hash'])
    assert provider.calls==1 and s.read(identifier)['state']=='generating'
    with pytest.raises(CharacterError):s.submit(identifier,consent=True,quote_hash=quoted['quote_hash'])
    assert provider.calls==1


def test_longer_than_model_max_preserves_existing_multi_clip_path(studio):
    s=studio.service
    identifier,provider,estimates=seeded(studio,duration=55)
    original=s.read(identifier)
    s.prepare(identifier,consent=True,script_reviewed=True)
    quoted=s.read(identifier)
    assert len(estimates)==len(quoted['scenes'])==5
    assert all(item['duration']==11 for item in estimates)
    assert quoted['script']==original['script'] and quoted['prompts']==original['prompts']
    assert quoted['plan_hash']==original['plan_hash']


def test_oversized_combined_prompt_stops_before_upload_or_quote_without_truncation(studio):
    s=studio.service
    identifier,provider,estimates=seeded(studio)
    job=s.read(identifier)
    for row in job['prompts']:row['prompt']='A distinct complete action. '+('x'*1200)
    job['plan_hash']=s.plan_hash(job)
    s.save(job)
    original=s.read(identifier)
    with pytest.raises(CharacterError):s.prepare(identifier,consent=True,script_reviewed=True)
    assert provider.uploads==0 and not estimates
    assert s.read(identifier)==original


def test_single_request_unknown_is_not_replayed(studio):
    s=studio.service
    identifier,provider,estimates=seeded(studio)
    s.prepare(identifier,consent=True,script_reviewed=True)
    quoted=s.read(identifier)
    provider.ambiguous=True
    with pytest.raises(CharacterError):s.submit(identifier,consent=True,quote_hash=quoted['quote_hash'])
    unknown=s.read(identifier)
    assert unknown['state']=='submission_unknown' and len(unknown['scenes'])==1
    assert unknown['scenes'][0]['state']=='unknown' and provider.calls==1
    with pytest.raises(CharacterError):s.submit(identifier,consent=True,quote_hash=quoted['quote_hash'])
    assert provider.calls==1


def test_single_15_second_local_mp4_keeps_all_seconds_and_five_caption_cues(tmp_path,monkeypatch):
    import newsflow.character.compose_studio as module
    ffmpeg=Path(r'C:\NewsFlowAI\tools\ffmpeg.exe')
    ffprobe=Path(r'C:\NewsFlowAI\tools\ffprobe.exe')
    assert ffmpeg.is_file() and ffprobe.is_file()
    clip=tmp_path/'synthetic-source-15s.mp4'
    subprocess.run([str(ffmpeg),'-nostdin','-n','-v','error','-f','lavfi','-i',
                    'testsrc2=size=144x256:rate=30:duration=15','-t','15','-an',
                    '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-threads','1',str(clip)],
                   check=True,capture_output=True,timeout=60,env=local_process_env())
    source_hash=hashlib.sha256(clip.read_bytes()).hexdigest()
    source_info=probe_clip(clip,ffprobe)
    assert abs(source_info['duration']-15)<.1
    commands=[]
    original_run=module.run
    def recorded(args,cwd):
        commands.append(list(args))
        return original_run(args,cwd)
    monkeypatch.setattr(module,'run',recorded)
    folder=tmp_path/'result'
    folder.mkdir()
    settings={**DEFAULTS,'video_model':K3,'duration':15,'clip_seconds':3,
              'output_quality':'720p','sound':'off'}
    result=compose_studio(folder,StudioStoryboard.model_validate(story(15,'off')),[clip],
                          settings=settings,ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert abs(result['media']['duration']-15)<.1 and not result['media']['has_audio']
    normalizations=[cmd for cmd in commands if str(cmd[-1]).endswith('scene-0.mp4')]
    assert len(normalizations)==1 and normalizations[0][normalizations[0].index('-t')+1]=='15'
    assert (folder/'compose/clips.txt').read_text(encoding='ascii').splitlines()==["file 'scene-0.mp4'"]
    cues=[line for line in (folder/'compose/captions.ass').read_text(encoding='utf-8-sig').splitlines()
          if line.startswith('Dialogue:')]
    assert len(cues)==5
    for n,line in enumerate(cues):
        assert f'0:00:{n*3:02d}.00' in line and f'0:00:{(n+1)*3:02d}.00' in line
    assert hashlib.sha256(clip.read_bytes()).hexdigest()==source_hash


def test_one_clip_cannot_fake_a_longer_than_supported_story(tmp_path):
    folder=tmp_path/'result'
    folder.mkdir()
    with pytest.raises(CharacterError):
        compose_studio(folder,StudioStoryboard.model_validate(story(55,'off')),[tmp_path/'not-real.mp4'],
                       settings={**DEFAULTS,'duration':55,'clip_seconds':11,'sound':'off'})
    assert not (folder/'compose').exists() and not (folder/'final.mp4').exists()
