"""Reversible Library-only selection removal: synthetic records, never providers."""
import hashlib
import json
from uuid import uuid4

import pytest
from filelock import FileLock
from sqlalchemy import select
from starlette.testclient import TestClient

from bat_distribution.operation import OperatingRequests
from conftest import csrf
from newsflow.character.kling import DEFAULTS
from newsflow.db.models import AppSetting, ImagePost, IntelligenceRun, NewsArticle, NewsSource, WorkspaceRemoval
from newsflow.distribution.local_access import LaunchSession, LocalAccess
from newsflow.studio.library_visibility import LibraryVisibility, LibraryVisibilityError, parse_items
from test_character_episode_schema import image
from test_single_workspace import video_fixture


def character(app, state='needs_script', scene_state=None):
    service = app.state.character
    identifier, _ = service.create_studio('합성 캐릭터 작업', '5', reference=image(),
        settings={**DEFAULTS, 'duration': 15, 'clip_seconds': 3}, request_id=uuid4().hex)
    job = service.read(identifier)
    job['state'] = state
    if scene_state:
        job['scenes'] = [{'position': 1, 'state': scene_state, 'request_id': 'retained-request', 'quote_usd': '0.5'}]
    service.save(job)
    return 'character:' + identifier


def markers(app):
    with app.state.sessions() as session:
        return {row.key: row.detail for row in session.scalars(select(WorkspaceRemoval))}


def post(client, action, identifiers, **extra):
    return client.post('/api/studio/library/' + action, data={
        'items': json.dumps(identifiers), 'confirm': 'true', 'csrf_token': csrf(client), **extra})


def mixed(app):
    video = video_fixture(app, '합성 뉴스 영상')
    with app.state.sessions.begin() as session:
        source = NewsSource(name='Synthetic', url='https://example.com/library-synthetic', enabled=False)
        session.add(source); session.flush()
        article = NewsArticle(source_id=source.id, title='합성 기사', publisher='Synthetic',
            url='https://example.com/library-story', canonical_url='https://example.com/library-story')
        session.add(article); session.flush()
        draft = IntelligenceRun(kind='image_draft', status='success', provider='offline', options={},
            evidence={}, result={'prompt': '합성 이미지 초안'}, message='Synthetic only')
        artwork = ImagePost(article_id=article.id, title='합성 게시물', caption='', sources={},
            filename='synthetic.png', sha256='a'*64, ai_disclosure='AI')
        session.add_all([draft, artwork]); session.flush()
        image_id, post_id = draft.id, artwork.id
        data = image(); digest = hashlib.sha256(data).hexdigest()
        session.add(AppSetting(key='sample_content:v1:copy:owned-ref', value=json.dumps({
            'id': 'owned-ref', 'version': 1, 'sha256': digest})))
        session.add(WorkspaceRemoval(key='activity:historic', detail={'title': '기존 보관 활동', 'state': 'hidden'}))
    reference = app.state.config.data_dir/'sample-copies/v1/owned-ref'/f'{digest}.png'
    reference.parent.mkdir(parents=True); reference.write_bytes(data)
    ids = [f"news:{video['id']}", f'image:{image_id}', f'post:{post_id}', character(app), 'reference:owned-ref']
    files = [app.state.video.outputs/video['output_name'], reference,
             *app.state.character.folder(ids[3].split(':')[1]).glob('*')]
    return ids, {path: path.read_bytes() for path in files if path.is_file()}


def test_all_types_hide_active_workspace_restore_and_preserve_every_original(app, client):
    ids, files = mixed(app)
    workspace = client.get('/api/studio/workspace').json()['projects']
    before = client.get('/api/studio/modules/library').json()
    assert before['libraryRemovalAvailable'] is True
    assert len(before['collections']['ownedReferences']) == 1
    assert {x['id'] for x in before['projects']} == set(ids[:-1])
    result = post(client, 'remove', ids)
    assert result.status_code == 200 and result.json() == {
        'removed': ids, 'recoverable': True, 'historicalRecordsPreserved': True}
    after = client.get('/api/studio/modules/library').json()
    assert after['projects'] == [] and after['collections']['ownedReferences'] == []
    assert {x['id'] for x in after['collections']['libraryRemoved']} == set(ids)
    assert all(set(x) == {'id','title','kind','updatedAt','technicalStatus'}
               and x['technicalStatus'] == 'hidden' for x in after['collections']['libraryRemoved'])
    assert after['collections']['removed'] == before['collections']['removed']
    assert all('library:' not in row['key'] for row in after['collections']['removed'])
    assert 'library:' not in client.get('/workspace/trash').text
    assert client.get('/api/studio/workspace').json()['projects'] == []
    assert client.get('/api/studio/modules/publishing').json()['projects'] == []
    assert client.get('/api/studio/modules/shorts').json()['projects'] == workspace
    assert 'libraryRemovalAvailable' not in client.get('/api/studio/modules/shorts').json()
    assert files == {path: path.read_bytes() for path in files}
    first_markers = markers(app)
    assert post(client, 'remove', ids).status_code == 200 and markers(app) == first_markers
    result = post(client, 'restore', ids)
    assert result.status_code == 200 and result.json() == {'restored': ids, 'historicalRecordsPreserved': True}
    assert post(client, 'restore', ids).status_code == 200
    restored = client.get('/api/studio/modules/library').json()
    assert restored['projects'] == before['projects']
    assert restored['collections']['ownedReferences'] == before['collections']['ownedReferences']
    assert restored['collections']['libraryRemoved'] == []
    assert client.get('/api/studio/workspace').json()['projects'] == workspace
    assert markers(app) == {'activity:historic': {'title':'기존 보관 활동','state':'hidden'}}
    assert files == {path: path.read_bytes() for path in files}


@pytest.mark.parametrize('items', [[], ['news:1','news:1'], ['news:0'], ['post:-1'], ['image:01'],
    ['news:9999999999999999999'], ['character:'+'A'*32], ['reference:../other'], ['own-news:1'],
    ['reference-x'], [True], ['news:1']*101, {}, 'invalid-json'])
def test_invalid_selection_rejected_before_storage(items):
    with pytest.raises(LibraryVisibilityError, match='invalid'):
        parse_items(items)


def test_atomic_batch_missing_and_active_preserves_all_markers(app, client):
    ready = character(app)
    busy = character(app, 'generating')
    for selection, code in [([ready, 'news:999999'],404), ([ready,busy],409),
                            ([ready,'news:9999999999999999999'],422), ([ready,ready],422)]:
        response = post(client, 'remove', selection)
        assert response.status_code == code and markers(app) == {}
    # A failed restore request may not restore the first valid item either.
    assert post(client,'remove',[ready]).status_code == 200
    baseline = markers(app)
    assert post(client,'restore',[ready,'post:999999']).status_code == 404
    assert markers(app) == baseline


@pytest.mark.parametrize('state,scene_state', [('writing',None),('preparing',None),('generating',None),
    ('retry_quoting',None),('composing',None),('status_or_download_failed','submitted'),
    ('clips_review','downloading'),('clips_review','submitting')])
def test_running_work_cannot_be_hidden(app,state,scene_state):
    item = character(app,state,scene_state)
    with pytest.raises(LibraryVisibilityError, match='busy'):
        LibraryVisibility(app.state.sessions,app.state.character).change([item],hidden=True)
    assert markers(app) == {}


def test_unknown_records_remain_recoverable_without_submit_or_evidence_changes(app,client):
    item = character(app,'submission_unknown','unknown')
    folder = app.state.character.folder(item.split(':')[1])
    before = {path:path.read_bytes() for path in folder.glob('*') if path.is_file()}
    assert post(client,'remove',[item]).status_code == 200
    assert markers(app)['library:'+item]['originalStatus'] == 'submission_unknown'
    assert post(client,'restore',[item]).status_code == 200
    assert before == {path:path.read_bytes() for path in before}
    assert app.state.character.read(item.split(':')[1])['scenes'][0]['request_id'] == 'retained-request'


def test_existing_character_lock_blocks_without_waiting_or_partial_change(app):
    item = character(app)
    with FileLock(str(app.state.character.root/'character.lock'), timeout=0):
        with pytest.raises(LibraryVisibilityError, match='busy'):
            LibraryVisibility(app.state.sessions,app.state.character).change([item],hidden=True)
    assert markers(app) == {}


def test_image_active_output_and_wrong_run_kind_rejected(app,client):
    with app.state.sessions.begin() as session:
        draft = IntelligenceRun(kind='image_draft', status='success', provider='offline',
            options={}, evidence={}, result={}, message='')
        session.add(draft); session.flush(); identifier=draft.id
        output = IntelligenceRun(kind='feed_image',status='running',provider='offline',
            options={'style':'studio','draft_id':identifier},evidence={},result={},message='')
        session.add(output); session.flush(); output_id=output.id
    assert post(client,'remove',[f'image:{identifier}']).status_code == 409
    assert post(client,'remove',[f'image:{output_id}']).status_code == 404
    assert markers(app) == {}


def test_exact_routes_retain_local_auth_origin_csrf_and_confirmation(app):
    item = character(app)
    launch = LaunchSession(18779)
    client = TestClient(OperatingRequests(LocalAccess(app,launch)),base_url=launch.origin,
        client=('127.0.0.1',11001))
    body={'items':json.dumps([item]),'confirm':'true'}
    assert client.post('/api/studio/library/remove',data=body).status_code == 403
    token=launch.launch_url().split('#',1)[1]
    assert client.post('/__local/claim',headers={'Origin':launch.origin,'X-NewsFlow-Bootstrap':token}).status_code == 204
    client.get('/api/studio/modules/library')
    body['csrf_token']=client.cookies['newsflow_csrf']
    assert client.post('/api/studio/library/remove',data={**body,'csrf_token':'bad'},headers={'Origin':launch.origin}).status_code==403
    assert client.post('/api/studio/library/remove',data=body,headers={'Origin':'https://outside.invalid'}).status_code==403
    assert client.post('/api/studio/library/remove',data={**body,'confirm':'false'},headers={'Origin':launch.origin}).status_code==422
    assert markers(app)=={}
    for action in ('remove','restore'):
        assert client.post('/api/studio/library/'+action,data=body,headers={'Origin':launch.origin}).status_code==200
    assert markers(app)=={}


@pytest.mark.parametrize('method,path,status', [
    ('POST','/api/studio/library/remove',204), ('POST','/api/studio/library/restore',204),
    ('GET','/api/studio/library/remove',403), ('DELETE','/api/studio/library/remove',403),
    ('POST','/api/studio/library/remove/extra',403), ('POST','/api/studio/library/purge',204),
    ('POST','/workspace/videos/1/remove',403), ('POST','/api/studio/library/restore-all',403)])
def test_only_exact_two_local_posts_enter_operating_boundary(method,path,status):
    reached=[]
    async def inner(scope,receive,send):
        reached.append(scope['path'])
        await send({'type':'http.response.start','status':204,'headers':[]})
        await send({'type':'http.response.body','body':b''})
    assert TestClient(OperatingRequests(inner)).request(method,path).status_code == status
    assert reached == ([path] if status == 204 else [])
