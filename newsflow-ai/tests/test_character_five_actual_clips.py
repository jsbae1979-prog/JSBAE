"""User-approved five actual provider clips; old accepted one-clip jobs stay renderable."""
from copy import deepcopy
import hashlib
from test_api_settings import sessions,store
from test_character_kling_studio import studio
from test_character_single_video import seeded
from newsflow.character.kling import K3,O3


def test_fifteen_seconds_quotes_and_submits_five_actual_three_second_clips_for_both_models(studio):
    for model in (K3,O3):
        service=studio.service
        identifier,provider,estimates=seeded(studio,model=model)
        before=service.read(identifier)
        service.prepare(identifier,consent=True,script_reviewed=True)
        quoted=service.read(identifier)
        assert len(estimates)==len(quoted['scenes'])==5
        assert [payload['duration'] for payload in estimates]==[3]*5
        assert sum(payload['duration'] for payload in estimates)==15
        assert [scene['position'] for scene in quoted['scenes']]==[1,2,3,4,5]
        assert quoted['quote_total_usd']=='0.50'
        for key in ('script','prompts','plan_hash'):assert quoted[key]==before[key]
        service.submit(identifier,consent=True,quote_hash=quoted['quote_hash'])
        assert provider.calls==5
    assert studio.writer.calls==0


def test_old_accepted_single_fifteen_second_clip_renders_without_payload_reshape(studio,monkeypatch):
    service=studio.service;identifier,provider,_=seeded(studio)
    job=service.read(identifier);folder=service.folder(identifier)
    path=folder/'scene-1.mp4';path.write_bytes(b'synthetic old full-length accepted clip')
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    job.update(state='clips_review',quote_total_usd='1.890',scenes=[{
        'position':1,'state':'downloaded','attempt':1,'quote_usd':'1.890',
        'file':path.name,'sha256':sha,'payload':{'duration':15,'sound':'off','prompt':'legacy accepted full-length clip'},
        'media':{'duration':15,'has_audio':False}}])
    service.save(job);old_scene=deepcopy(job['scenes'])
    seen=[]
    def compose(folder,story,clips,**settings):
        seen.append((len(story.scenes),list(clips)))
        (folder/'final.mp4').write_bytes(b'synthetic old clip composed')
        return {'file':'final.mp4','sha256':'a'*64,'media':{'duration':15,'has_audio':False}}
    monkeypatch.setattr('newsflow.character.compose_studio.compose_studio',compose)
    assert service.render(identifier,reviewed=True)==folder/'final.mp4'
    assert seen==[(5,[path])] and service.read(identifier)['scenes']==old_scene
    assert path.read_bytes()==b'synthetic old full-length accepted clip' and provider.calls==0
