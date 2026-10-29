"""Retire bundled examples without changing existing user copies or generation history."""
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from PIL import Image
from sqlalchemy import select
from test_api_settings import sessions
from newsflow.db.models import AppSetting
from newsflow.samples.catalog import PREFIX,SampleError,Samples,safe_path

def png():
    buf=io.BytesIO();Image.new('RGB',(128,192),'navy').save(buf,format='PNG');return buf.getvalue()

def copied(sessions,folder,identifier='character-cat',data=None,extension='.png'):
    data=png() if data is None else data
    digest=hashlib.sha256(data).hexdigest()
    target=folder/'sample-copies'/'v1'/identifier/(digest+extension)
    target.parent.mkdir(parents=True);target.write_bytes(data)
    with sessions.begin() as db:
        db.add(AppSetting(key=PREFIX+'copy:'+identifier,value=json.dumps({'id':identifier,'sha256':digest,'sample':True,'version':1})))
    return target,digest

@pytest.mark.parametrize('root_state',['missing','poisoned','ordinary'])
def test_no_default_content_is_loaded_or_registered(sessions,tmp_path,root_state):
    root=tmp_path/'old-package'
    if root_state!='missing':
        root.mkdir();(root/'manifest.json').write_text('{broken' if root_state=='poisoned' else json.dumps({'version':1,'assets':[{'id':'must-not-load'}]}))
    data=tmp_path/'user-data';data.mkdir();sentinel=data/'user-project.txt';sentinel.write_text('keep')
    before=list(data.rglob('*'))
    service=Samples(sessions,data,None,root=root)
    assert service.catalog()==([], '')
    assert service.listing()=={'schemaVersion':1,'sample':False,'removed':True,'assets':[],'warning':''}
    assert service.listing()==service.listing() and list(data.rglob('*'))==before and sentinel.read_text()=='keep'
    with sessions() as db:assert list(db.scalars(select(AppSetting)))==[]

@pytest.mark.parametrize('action',['get','copy','hide','checked'])
def test_retired_sample_mutations_cannot_create_files_or_settings(sessions,tmp_path,action):
    service=Samples(sessions,tmp_path/'profile',None)
    with pytest.raises(SampleError):
        if action=='hide':service.hide('character-cat',True)
        else:getattr(service,action)('character-cat')
    assert not (tmp_path/'profile').exists()
    with sessions() as db:assert list(db.scalars(select(AppSetting)))==[]

def test_existing_user_copy_remains_previewable_without_any_package_manifest(sessions,tmp_path):
    target,digest=copied(sessions,tmp_path/'profile')
    before=(target.read_bytes(),target.stat().st_mtime_ns)
    s=Samples(sessions,tmp_path/'profile',None,root=tmp_path/'removed-package')
    row,path=s.copied_file('character-cat')
    assert path==target and row['sha256']==digest and row['mime']=='image/png'
    refs=s.owned_references()
    assert len(refs)==1 and refs[0]['referenceOnly'] and refs[0]['technicalStatus']=='stored'
    assert refs[0]['kind']=='image' and '샘플' not in refs[0]['title']
    assert refs[0]['mediaUrl']=='/api/samples/character-cat/copy-file'
    assert (target.read_bytes(),target.stat().st_mtime_ns)==before
    with sessions() as db:assert len(list(db.scalars(select(AppSetting))))==1

def test_user_copy_is_not_treated_as_an_editable_video_project(sessions,tmp_path):
    copied(sessions,tmp_path/'profile','character-short-cat',b'synthetic immutable media bytes','.mp4')
    ref=Samples(sessions,tmp_path/'profile',None).owned_references()[0]
    assert ref['kind']=='reference' and ref['referenceOnly'] and not ref.get('href')
    assert ref['technicalStatus']=='stored' and ref['publishApprovalStatus']=='separate_approval_required'

@pytest.mark.parametrize('identifier',['../outside','c:/private','C:\\private','character-cat/other','', 'A'*49])
def test_invalid_reference_identifiers_are_rejected_before_access(sessions,tmp_path,identifier):
    with pytest.raises(SampleError):Samples(sessions,tmp_path,None).copied_file(identifier)

def test_modified_user_copy_is_never_deleted_repaired_or_overwritten(sessions,tmp_path):
    target,_=copied(sessions,tmp_path/'profile');target.write_bytes(b'user-edited-reference')
    s=Samples(sessions,tmp_path/'profile',None)
    with pytest.raises(SampleError):s.copied_file('character-cat')
    assert s.owned_references()==[] and target.read_bytes()==b'user-edited-reference'

def test_copy_requires_same_profile_metadata_and_file(sessions,tmp_path):
    copied(sessions,tmp_path/'user-one')
    # Even with the same metadata DB, the selected profile cannot resolve another user's file.
    with pytest.raises(SampleError):Samples(sessions,tmp_path/'user-two',None).copied_file('character-cat')
    assert not (tmp_path/'user-two').exists()

def test_reparse_or_symbolic_user_copy_path_is_denied(sessions,tmp_path,monkeypatch):
    target,_=copied(sessions,tmp_path/'profile');original=Path.is_symlink
    monkeypatch.setattr(Path,'is_symlink',lambda p: p==target or original(p))
    with pytest.raises(SampleError):Samples(sessions,tmp_path/'profile',None).copied_file('character-cat')
    assert target.is_file()

def test_retired_routes_and_read_only_owned_copy_compatibility(sessions,tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from newsflow.samples.routes import router
    target,digest=copied(sessions,tmp_path/'profile')
    app=FastAPI();app.state.sessions=sessions;app.state.config=SimpleNamespace(data_dir=tmp_path/'profile');app.state.image_studio=None
    app.include_router(router);client=TestClient(app)
    assert client.get('/api/samples').json()['assets']==[]
    for action in ['file','poster']:assert client.get('/api/samples/character-cat/'+action).status_code==404
    for action in ['copy','visibility']:assert client.post('/api/samples/character-cat/'+action,data={}).status_code==404
    response=client.get('/api/samples/character-cat/copy-file')
    assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==digest
    assert response.headers['content-type']=='image/png'
    ranged=client.get('/api/samples/character-cat/copy-file',headers={'Range':'bytes=0-7'})
    assert ranged.status_code==206 and ranged.content==target.read_bytes()[:8]
    assert 'attachment' in client.get('/api/samples/character-cat/copy-file?download=true').headers['content-disposition']

def test_product_contains_no_bundle_or_gallery_and_keeps_voice_preview_controls():
    root=Path(__file__).parents[1]
    assert not list((root/'src/newsflow/assets/samples').rglob('*.*'))
    assert 'assets/samples/' not in (root/'pyproject.toml').read_text(encoding='utf8')
    frontend=root/'frontend/src'
    assert not (frontend/'studio/SampleGallery.tsx').exists()
    assert not (frontend/'studio/samples.css').exists()
    assert not (frontend/'studio/core/CharacterReferenceSamples.tsx').exists()
    for file in frontend.rglob('*.tsx'):
        source=file.read_text(encoding='utf8')
        assert '<SampleGallery' not in source and '<CharacterReferenceSamples' not in source
    library=(frontend/'studio/management/Library.tsx').read_text(encoding='utf8')
    assert '/api/samples' not in library and '샘플' not in library
    assert 'referenceOnly' in library
    # Real ElevenLabs/local voice audition is independent of the removed bundled gallery.
    work=(frontend/'studio/Workbench.tsx').read_text(encoding='utf8')
    assert 'ElevenLabs · 저장된 공개 샘플' in work
