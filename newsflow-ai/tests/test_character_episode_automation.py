"""Offline episode tests: synthetic profiles, Fake authoring/video, local FFmpeg."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import io
import json
import shutil

from PIL import Image
import pytest
from pydantic import ValidationError

from newsflow.character.episode_story import (EpisodeScript, base_scene_count, scene_range,
    validate_episode, scene_prompt, script_input)
from newsflow.character.kling import DEFAULTS, O3, KlingClient
from newsflow.character.service import CharacterService, generation_rows
from newsflow.character.registry import CharacterRegistry
from newsflow.character.schema import CharacterError
from newsflow.creation.image_studio import ImageStudio
from newsflow.video_models.catalog import CATALOG
from newsflow.video.engine import FFmpegAdapter
from newsflow.video.ai.contracts import ClipStatus
from newsflow.character.compose import run


from test_character_episode_schema import image, profile, script


class FakeAuthoring:
    response_received=True
    last_estimated_usd='0'
    def __init__(self):self.calls=[]
    def generate(self,instruction,payload,schema,options,**kwargs):
        assert kwargs['consent'] and 'image_bytes' not in kwargs
        assert 'no dialogue' in instruction.lower()
        self.calls.append(deepcopy(payload))
        return schema.model_validate(script(payload['target_seconds'],payload['character']['name_ko']))


class FakeVideo:
    credential=staticmethod(lambda:'synthetic-only')
    def __init__(self,settings,folder,ffmpeg):
        self.client=KlingClient(self.credential,settings)
        self.sent=[];self.uploads=[];self.folder=folder;self.ffmpeg=ffmpeg
        self.fail=False;self.unknown=False
    def payload(self,*args):return self.client.payload(*args)
    def upload_reference(self,path):
        self.uploads.append(str(path));return 'https://example.com/'+Path(path).name
    def estimate(self,payload):return '0.10'
    def submit_scene(self,payload,key):
        self.sent.append((deepcopy(payload),key))
        if self.unknown:raise TimeoutError('synthetic')
        return {'request_id':key,'status_url':'https://api.higgsfield.ai/requests/'+key+'/status'}
    def check(self,handle):
        return ClipStatus('failed' if self.fail else 'completed')
    def fetch(self,status,path,cancel):
        no=int(path.stem.split('-')[1]);payload=self.sent[no-1][0]
        run([str(self.ffmpeg),'-nostdin','-n','-v','error','-f','lavfi','-i','color=c=blue:s=144x256:r=30',
             '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t',str(payload['duration']),
             '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac',str(path)],path.parent)


def setup_episode(tmp_path,target=15,name='별',species='rabbit',model='claude-sonnet-4-6'):
    images=ImageStudio(None,tmp_path,None)
    registry=CharacterRegistry(tmp_path,images)
    asset=images.asset_bytes(image())
    saved=registry.save(profile(name,species),asset)
    ffmpeg=FFmpegAdapter.executable('ffmpeg',None)
    ffprobe=FFmpegAdapter.executable('ffprobe',None)
    settings={**DEFAULTS,'video_model':O3,'native_resolution':'std','duration':target,'sound':'on','script_model':model}
    video=FakeVideo(settings,tmp_path,ffmpeg)
    service=CharacterService(tmp_path,None,SimpleNamespace(key=lambda:'fake'),video=video,
                             ffmpeg=ffmpeg,ffprobe=ffprobe)
    service.authoring=FakeAuthoring()
    identifier,_=service.create_episode('정원의 아침','5',reference=images.asset(asset).read_bytes(),
                                       settings=settings,request_id=uuid4().hex,profile=saved)
    return service,video,identifier,registry,saved


@pytest.mark.parametrize('target,name,species,model',[(15,'별','rabbit','claude-sonnet-4-6'),
    (35,'달','penguin','gpt-4.1-mini'),(60,'별','rabbit','claude-sonnet-4-6')])
def test_fake_pipeline_to_real_mp4(tmp_path,target,name,species,model):
    s,v,i,registry,p=setup_episode(tmp_path,target,name,species,model)
    s.write(i,consent=True)
    assert s.read(i)['script']['title'].startswith(name)
    with pytest.raises(CharacterError):s.prepare(i,consent=True)
    assert not v.sent and not v.uploads
    s.prepare(i,consent=True,script_reviewed=True)
    job=s.read(i)
    assert len(generation_rows(job))==len(script(target)['scenes'])
    s.submit(i,consent=True,quote_hash=job['quote_hash'])
    assert len(v.sent)==1  # Continues wait for downloaded parent, not just accepted request.
    for _ in range(len(job['scenes'])+1):
        if s.read(i)['state']=='clips_review':break
        s.check(i,consent=True)
    job=s.read(i)
    assert job['state']=='clips_review' and len(v.sent)==len(job['scenes'])
    for row in job['scenes'][1:]:
        assert row['dependency']['clip_sha256']==job['scenes'][row['from']-1]['sha256']
        assert row['payload']['first_frame_url'].endswith('-last.png')
        assert row['payload']['image_urls']==[row['quoted_reference']]
    before=len(v.sent)
    output=s.render(i,reviewed=True)
    completed=s.read(i)
    info=completed['output']['media']
    assert output.exists() and abs(info['duration']-target)<=.1
    assert (info['width'],info['height'])==(1080,1920) and info['has_audio']
    assert s.render(i,reviewed=True)==output and len(v.sent)==before
    registry.delete(p['id'],p['revision'])
    assert s.read(i)['character']['name_ko']==name and output.exists()
    assert len(s.authoring.calls)==1


def test_approval_edit_revision_and_unknown_never_replayed(tmp_path):
    s,v,i,registry,p=setup_episode(tmp_path)
    s.write(i,consent=True)
    value=s.read(i)['script']
    with pytest.raises(CharacterError):s.edit_episode(i,value,'stale')
    s.prepare(i,consent=True,script_reviewed=True)
    old=s.read(i)['quote_hash']
    s.edit_episode(i,value,s.read(i)['script_hash'])
    assert s.read(i)['state']=='script_review' and 'script_approval' not in s.read(i)
    with pytest.raises(CharacterError):s.submit(i,consent=True,quote_hash=old)
    s.prepare(i,consent=True,script_reviewed=True)
    v.unknown=True
    with pytest.raises(CharacterError):s.submit(i,consent=True,quote_hash=s.read(i)['quote_hash'])
    assert s.read(i)['state']=='submission_unknown' and len(v.sent)==1
    s.check(i,consent=True)
    assert len(v.sent)==1 and s.read(i)['state']=='submission_unknown'


def test_duration_change_requires_new_script_and_preserves_snapshot(tmp_path):
    s,v,i,registry,p=setup_episode(tmp_path)
    s.write(i,consent=True);before=deepcopy(s.read(i))
    from newsflow.character.kling import check
    with pytest.raises(CharacterError):
        s.update_studio_settings(i,{**check(before['studio_selection']),'duration':35},'5')
    assert s.read(i)==before
