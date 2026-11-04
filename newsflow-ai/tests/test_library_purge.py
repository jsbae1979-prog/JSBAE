"""Synthetic files only; actual media unlink and ledger-preserving tombstones."""
from pathlib import Path
from uuid import uuid4
import hashlib,json
import pytest
from sqlalchemy import select
from filelock import FileLock
from newsflow.db.models import WorkspaceRemoval,ImagePost,IntelligenceRun,PublishDraft
from newsflow.studio.library_purge import LibraryPurge,PurgeError
from newsflow.studio.library_visibility import LibraryVisibility
from test_library_visibility import mixed,character,post,markers
from conftest import csrf

def purge(client,ids,**extra):
    return client.post('/api/studio/library/purge',data={'items':json.dumps(ids),'confirm':'true','csrf_token':csrf(client),**extra})

def ready(app):
    ids,files=mixed(app)
    with app.state.sessions.begin() as session:
        postrow=session.get(ImagePost,int(ids[2].split(':')[1]));raw=b'SYNTHETIC IMAGE'
        postrow.filename='image-'+uuid4().hex+'.jpg';postrow.sha256=hashlib.sha256(raw).hexdigest()
        app.state.image_posts.outputs.mkdir(parents=True,exist_ok=True)
        (app.state.image_posts.outputs/postrow.filename).write_bytes(raw)
        output=IntelligenceRun(kind='feed_image',status='success',provider='offline',options={'style':'studio','draft_id':int(ids[1].split(':')[1])},
            evidence={},result={},message='Synthetic');session.add(output);session.flush()
        name=f'generated-{output.id}.jpg';output.result={'filename':name,'sha256':hashlib.sha256(raw).hexdigest()}
        app.state.image_generation.outputs.mkdir(parents=True,exist_ok=True);(app.state.image_generation.outputs/name).write_bytes(raw)
    LibraryVisibility(app.state.sessions,app.state.character).change(ids,hidden=True)
    return ids

def test_all_five_types_purge_media_keep_audit_and_cannot_restore(app,client):
    ids=ready(app);folder=app.state.character.folder(ids[3].split(':')[1]);job=(folder/'jobs.json').read_bytes()
    before=set(markers(app));response=purge(client,ids)
    assert response.status_code==200 and response.json()=={'purged':ids,'recoverable':False,'historicalRecordsPreserved':True}
    assert set(markers(app))==before and all(markers(app)['library:'+i]['state']=='purged' for i in ids)
    assert (folder/'jobs.json').read_bytes()==job and not (folder/'reference.png').exists()
    assert not list(app.state.image_posts.outputs.glob('image-*.jpg'))
    assert not list(app.state.image_generation.outputs.glob('generated-*.jpg'))
    assert not list((app.state.config.data_dir/'sample-copies').rglob('*.png'))
    assert client.get('/api/studio/modules/library').json()['collections']['libraryRemoved']==[]
    assert client.get('/api/studio/workspace').json()['projects']==[]
    assert client.get('/api/studio/modules/characters').json()['collections']['jobs']==[]
    for item in ids:assert post(client,'restore',[item]).status_code==409
    assert purge(client,ids).status_code==200

@pytest.mark.parametrize('items',[[],['news:1','news:1'],['archive:../secret'],['character:BAD'],['archive:video:9999999999999999999'],['reference:../key'],[True]])
def test_invalid_items_no_file_or_row_change(app,client,items):
    before=markers(app);assert purge(client,items).status_code==422;assert markers(app)==before

def test_only_trashed_and_whole_selection_validate_before_unlink(app,client):
    ids=ready(app);before=markers(app)
    untrashed=character(app)
    files={p:p.read_bytes() for p in app.state.config.data_dir.rglob('*') if p.is_file() and p.suffix not in {'.db','-shm','-wal'} and not p.name.endswith('.lock')}
    assert purge(client,[ids[0],untrashed]).status_code==409
    assert markers(app)==before and all(p.read_bytes()==v for p,v in files.items())
    assert purge(client,[ids[0]],confirm='false').status_code==422

def test_published_or_prepared_video_blocks_all_files(app,client):
    ids=ready(app);render=int(ids[0].split(':')[1])
    with app.state.sessions.begin() as session:
        session.add(PublishDraft(render_job_id=render,platform='youtube',title='Synthetic',description='',hashtags=[],sources={},media_sha256='a'*64))
    before=markers(app)
    response=purge(client,[ids[3],ids[0]])
    assert response.status_code==409 and markers(app)==before

def test_unknown_or_active_character_cannot_purge(app,client):
    item=character(app,'submission_unknown','unknown');LibraryVisibility(app.state.sessions,app.state.character).change([item],hidden=True)
    assert purge(client,[item]).status_code==409
    job=app.state.character.read(item.split(':')[1]);job['state']='composing';job['scenes']=[];app.state.character.save(job)
    assert purge(client,[item]).status_code==409

def test_failure_is_durable_manual_continuation_preserves_history(app,client,monkeypatch):
    ids=ready(app);real=Path.unlink;failed=[]
    def interrupt(path,*args,**kwargs):
        if path.suffix=='.png' and 'sample-copies' in path.parts and not failed:
            failed.append(path);raise PermissionError('Synthetic open file')
        return real(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',interrupt)
    assert purge(client,[ids[3],ids[4]]).status_code==409
    assert all(markers(app)['library:'+i]['state']=='purge_failed' for i in (ids[3],ids[4]))
    assert post(client,'restore',[ids[3]]).status_code==409
    monkeypatch.setattr(Path,'unlink',real)
    assert purge(client,[ids[3],ids[4]]).status_code==200
    assert all(markers(app)['library:'+i]['state']=='purged' for i in (ids[3],ids[4]))

def test_tampered_retry_manifest_cannot_delete_another_job_or_key(app,client):
    ids=ready(app);other=character(app);folder=app.state.character.folder(other.split(':')[1]);file=folder/'reference.png'
    assert file.is_file()
    with app.state.sessions.begin() as session:
        row=session.get(WorkspaceRemoval,'library:'+ids[3]);row.detail={**row.detail,'state':'purge_failed',
          'purgeFiles':[{'path':file.relative_to(app.state.config.data_dir).as_posix(),'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'bytes':file.stat().st_size}]}
    assert purge(client,[ids[3]]).status_code==409 and file.is_file()
    key=app.state.config.data_dir/'synthetic-key.dpapi';key.write_bytes(b'opaque')
    with app.state.sessions.begin() as session:
        row=session.get(WorkspaceRemoval,'library:'+ids[3]);row.detail={**row.detail,'purgeFiles':[{'path':key.name,'sha256':hashlib.sha256(key.read_bytes()).hexdigest(),'bytes':6}]}
    assert purge(client,[ids[3]]).status_code==409 and key.read_bytes()==b'opaque'

def test_cleanup_lock_blocks_immediately(app,client):
    ids=ready(app)
    with FileLock(str(app.state.config.data_dir/'library-purge.lock')):
        assert purge(client,[ids[0]]).status_code==409

def test_legacy_activity_purge_keeps_audit_row_but_removes_restore(app,client):
    with app.state.sessions.begin() as session:session.add(WorkspaceRemoval(key='activity:synthetic',detail={'title':'Synthetic','state':'hidden'}))
    assert purge(client,['archive:activity:synthetic']).status_code==200
    assert markers(app)['activity:synthetic']['state']=='purged'
    assert client.get('/api/studio/modules/library').json()['collections']['removed']==[]
    response=client.post('/workspace/trash/restore',data={'item':'activity:synthetic','confirm':'true','csrf_token':csrf(client)})
    assert response.status_code==409

def test_purge_origin_csrf_and_no_get_or_delete_backdoor(app):
    from starlette.testclient import TestClient
    from newsflow.distribution.local_access import LocalAccess,LaunchSession
    from bat_distribution.operation import OperatingRequests
    item=character(app);LibraryVisibility(app.state.sessions,app.state.character).change([item],hidden=True)
    launch=LaunchSession(18779)
    with TestClient(OperatingRequests(LocalAccess(app,launch)),base_url=launch.origin,client=('127.0.0.1',10010)) as c:
        body={'items':json.dumps([item]),'confirm':'true'}
        assert c.post('/api/studio/library/purge',data=body).status_code==403
        assert c.post('/__local/claim',headers={'Origin':launch.origin,'X-NewsFlow-Bootstrap':launch.launch_url().split('#')[1]}).status_code==204
        c.get('/api/studio/modules/library')
        assert c.post('/api/studio/library/purge',data=body,headers={'Origin':launch.origin}).status_code==403
        body['csrf_token']=c.cookies['newsflow_csrf']
        assert c.post('/api/studio/library/purge',data=body,headers={'Origin':'http://example.invalid'}).status_code==403
        assert c.get('/api/studio/library/purge').status_code==403
        assert c.delete('/api/studio/library/purge').status_code==403
        assert c.post('/api/studio/library/purge',data=body,headers={'Origin':launch.origin}).status_code==200

def test_native_path_refusal_is_constant_error_and_keeps_files(app,client,monkeypatch):
    ids=ready(app);before=markers(app)
    def refuse(*a,**k):raise ValueError('PRIVATE_NATIVE_PATH_MUST_NOT_ESCAPE')
    monkeypatch.setattr(LibraryPurge,'_plan',refuse)
    result=purge(client,[ids[3]])
    assert result.status_code==409 and 'PRIVATE' not in result.text and markers(app)==before
