"""Local downloaded-file recovery and explicit tool wiring; no vendor/native execution."""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_api_settings import sessions,store
from test_character_kling_studio import studio,story
from test_character_single_video import seeded
from newsflow.character.kling import check,snapshot
from newsflow.character.schema import CharacterError
from newsflow.character.studio_story import StudioStoryboard,prompts
from newsflow.video.ai.contracts import ClipInvalidError

RAW=b'only-synthetic-mp4-test-data'
SHA=hashlib.sha256(RAW).hexdigest()


def failed_download(studio):
    service=studio.service
    identifier,_,_=seeded(studio)
    job=service.read(identifier)
    settings={**check(job['studio_selection']),'sound':'on'}
    job['studio_selection']=snapshot(settings)
    script=StudioStoryboard.model_validate(story(15,'on'))
    job['script']=script.model_dump()
    job['prompts']=prompts(script,settings,job['character'])
    job['plan_hash']=service.plan_hash(job)
    job.update(state='status_or_download_failed',quote_total_usd='1.890',
        quote_hash='d'*64,quote_approvals=[{'day':'2026-10-29','usd':'1.890','scope':'initial'}],
        last_failure={'stage':'local_validation','code':'local_media_validation_failed'})
    job['scenes']=[{'position':1,'state':'downloading','attempt':1,'quote_usd':'1.890',
        'idempotency_key':'e'*32,'payload':{'duration':15,'sound':'on'},
        'handle':{'request_id':'f'*32,'status_url':'https://api.higgsfield.ai/requests/'+('f'*32)+'/status'}}]
    service.save(job)
    path=service.folder(identifier)/'scene-1.mp4'
    path.write_bytes(RAW)
    service.ffprobe=path.parent/'explicit-ffprobe.exe'
    service.ffmpeg=path.parent/'explicit-ffmpeg.exe'
    service.video_for=lambda _:(pytest.fail('No provider use during local recovery'))
    return service,identifier,path


def media(**changes):
    return {'duration':15.042,'has_audio':True,'bytes':len(RAW),'width':720,'height':1280,
            'format':'mov','video_codec':'h264',**changes}


def test_existing_audio_clip_recovers_once_without_supplier_or_budget_changes(studio,monkeypatch):
    service,identifier,path=failed_download(studio)
    original=service.read(identifier)
    calls=[]
    monkeypatch.setattr('newsflow.character.service.probe_clip',
        lambda actual,probe:(calls.append((actual,probe)) or media()))
    result=service.recover_local_download(identifier,consent=True,expected_sha256=SHA,expected_bytes=len(RAW))
    assert calls==[(path,service.ffprobe)] and result['providerCalls']==0
    recovered=service.read(identifier)
    assert recovered['state']=='clips_review' and recovered['scenes'][0]['state']=='downloaded'
    assert recovered['scenes'][0]['handle']==original['scenes'][0]['handle']
    assert recovered['scenes'][0]['idempotency_key']==original['scenes'][0]['idempotency_key']
    for key in ('quote_hash','quote_total_usd','quote_approvals','plan_hash','script','last_failure'):
        assert recovered[key]==original[key]
    assert path.read_bytes()==RAW
    assert recovered['local_recoveries'][0]['from_job_state']=='status_or_download_failed'
    assert recovered['local_recoveries'][0]['from_scene_state']=='downloading'
    with pytest.raises(CharacterError):
        service.recover_local_download(identifier,consent=True,expected_sha256=SHA,expected_bytes=len(RAW))
    assert len(calls)==1


@pytest.mark.parametrize('kind',['hash','bytes','audio','duration','state','reparse'])
def test_unsafe_or_unproven_local_recovery_preserves_original(studio,monkeypatch,kind):
    service,identifier,path=failed_download(studio)
    if kind=='state':
        job=service.read(identifier);job['state']='submission_unknown';service.save(job)
    original=service.read(identifier)
    monkeypatch.setattr('newsflow.character.service.probe_clip',
        lambda *args:media(has_audio=False) if kind=='audio' else media(duration=3) if kind=='duration' else media())
    if kind=='reparse':
        original_lstat=Path.lstat
        def lstat(actual,*args,**kwargs):
            value=original_lstat(actual,*args,**kwargs)
            if actual==path:
                return SimpleNamespace(st_mode=value.st_mode,st_size=value.st_size,st_file_attributes=0x400)
            return value
        monkeypatch.setattr(Path,'lstat',lstat)
    with pytest.raises(CharacterError):
        service.recover_local_download(identifier,consent=True,
            expected_sha256='0'*64 if kind=='hash' else SHA,expected_bytes=1 if kind=='bytes' else len(RAW))
    assert service.read(identifier)==original and path.read_bytes()==RAW


def test_explicit_probe_check_and_local_failure_stage(studio,monkeypatch):
    service,identifier,path=failed_download(studio)
    job=service.read(identifier);job['state']='generating';job['scenes'][0]['state']='submitted';service.save(job)
    calls=[]
    provider=SimpleNamespace(check=lambda handle:SimpleNamespace(state='completed'),fetch=lambda *args:None)
    service.video_for=lambda _:provider
    def broken_probe(actual,probe):
        calls.append((actual,probe));raise ClipInvalidError(sent=False)
    monkeypatch.setattr('newsflow.character.service.probe_clip',broken_probe)
    with pytest.raises(CharacterError) as caught:service.check(identifier,consent=True)
    assert caught.value.code=='media' and calls==[(path,service.ffprobe)]
    assert service.read(identifier)['last_failure']=={'stage':'local_validation','code':'local_media_validation_failed'}


def test_studio_composer_receives_both_explicit_bundled_tools(studio,monkeypatch):
    service,identifier,path=failed_download(studio)
    job=service.read(identifier)
    job['state']='clips_review';job['scenes'][0].update(state='downloaded',file=path.name,sha256=SHA,media=media())
    service.save(job)
    calls=[]
    def compose(folder,story,clips,**kwargs):
        calls.append((folder,clips,kwargs))
        (folder/'final.mp4').write_bytes(b'synthetic composed output')
        return {'file':'final.mp4','sha256':hashlib.sha256((folder/'final.mp4').read_bytes()).hexdigest(),'media':media()}
    monkeypatch.setattr('newsflow.character.compose_studio.compose_studio',compose)
    assert service.render(identifier,reviewed=True)==path.parent/'final.mp4'
    assert calls[0][1]==[path]
    assert calls[0][2]['ffmpeg']==service.ffmpeg and calls[0][2]['ffprobe']==service.ffprobe


def test_factory_and_bat_wire_only_explicit_program_tools_without_process_start():
    root=Path(__file__).parents[1]
    factory=ast.parse((root/'src/newsflow/main.py').read_text(encoding='utf8'))
    create=next(node for node in factory.body if isinstance(node,ast.FunctionDef) and node.name=='create_app')
    names=[arg.arg for arg in create.args.kwonlyargs]
    defaults=dict(zip(names,create.args.kw_defaults))
    assert all(isinstance(defaults[name],ast.Constant) and defaults[name].value is None
               for name in ('character_ffmpeg','character_ffprobe'))
    service_call=next(node for node in ast.walk(create) if isinstance(node,ast.Call)
                      and isinstance(node.func,ast.Name) and node.func.id=='CharacterService')
    keywords={item.arg:ast.unparse(item.value) for item in service_call.keywords}
    assert keywords['ffmpeg']=='character_ffmpeg' and keywords['ffprobe']=='character_ffprobe'
    live=ast.parse((root/'tools/bat_distribution/windows_live.py').read_text(encoding='utf8'))
    call=next(node for node in ast.walk(live) if isinstance(node,ast.Call)
              and isinstance(node.func,ast.Name) and node.func.id=='create_app')
    keywords={item.arg:ast.unparse(item.value) for item in call.keywords}
    assert keywords['character_ffmpeg']=="config.program / 'tools/ffmpeg.exe'"
    assert keywords['character_ffprobe']=="config.program / 'tools/ffprobe.exe'"
