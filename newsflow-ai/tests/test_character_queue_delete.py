"""Queue-list deletion preserves all jobs and paid-request evidence; Fake only."""
from copy import deepcopy
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from bat_distribution.operation import OperatingRequests
from newsflow.character.queue import EpisodeQueue
from newsflow.character.registry import CharacterRegistry
from newsflow.character.schema import CharacterError
from newsflow.character.topics import TopicStore
from newsflow.distribution.local_access import LaunchSession, LocalAccess
from test_character_episode_queue import setup, Service
from test_character_automation_routes import gui, profile


def test_delete_only_hides_queue_and_is_idempotent(setup, tmp_path):
    queue, service, created, character, _ = setup
    (tmp_path/'synthetic-video.mp4').write_bytes(b'owned synthetic media')
    (tmp_path/'synthetic-ledger.json').write_text('{"reserved":"0.50"}', encoding='utf8')
    queue.run_scripts(created['id'], consent=True)
    approvals = [service.quote(row['job_id']) for row in created['rows']]
    queue.approve_videos(created['id'], approvals, '2', consent=True)
    before = queue.get(created['id'])
    jobs, topics = deepcopy(service.jobs), queue.topics.list(character['id'])
    files = {p:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert queue.delete(created['id'], consent=True) == {'deleted':True,'historicalJobsPreserved':True}
    archived = queue.get(created['id'])
    assert archived['archived_at'] and {k:v for k,v in archived.items() if k!='archived_at'}==before
    assert queue.list()==[] and service.jobs==jobs and queue.topics.list(character['id'])==topics
    for path, content in files.items():
        if path != queue._path(created['id']): assert path.read_bytes()==content
    assert not service.submits and not service.checks
    archive_bytes = queue._path(created['id']).read_bytes()
    assert queue.delete(created['id'], consent=True)['deleted'] is True
    assert queue._path(created['id']).read_bytes()==archive_bytes


def test_archived_queue_cannot_replay_any_creation_or_paid_command(setup, monkeypatch):
    queue, service, created, character, topic_ids = setup
    queue.delete(created['id'], consent=True)
    before = queue._path(created['id']).read_bytes()
    jobs = deepcopy(service.jobs)
    def forbidden(*args, **kwargs): raise AssertionError('Archived queue touched a reference asset')
    monkeypatch.setattr(queue.registry.images, 'asset', forbidden)
    commands = [
        lambda: queue.create(character['id'], topic_ids, {'duration':15}, '2', created['id']),
        lambda: queue.run_scripts(created['id'], consent=True),
        lambda: queue.approve_videos(created['id'], [{'job_id':created['rows'][0]['job_id'],'quote_hash':'synthetic'}], '2', consent=True),
        lambda: queue.advance_videos(created['id'], consent=True),
    ]
    for command in commands:
        with pytest.raises(CharacterError): command()
    assert service.jobs==jobs and not service.writes and not service.submits and not service.checks
    assert queue._path(created['id']).read_bytes()==before


@pytest.mark.parametrize('state', ['scripts_running', 'videos_running'])
def test_active_queue_state_is_not_hidden(setup, state):
    queue, service, created, _, _ = setup
    current = queue.get(created['id']); current['state']=state; queue._save(current)
    with pytest.raises(CharacterError) as blocked: queue.delete(created['id'], consent=True)
    assert blocked.value.code=='busy' and queue.list()==[current]
    assert queue.get(created['id'])==current and not service.submits


def test_delete_uses_nonblocking_existing_queue_lock(setup):
    queue, _, created, _, _ = setup
    lock = queue._lock(created['id'])
    with lock:
        with pytest.raises(CharacterError) as blocked: queue.delete(created['id'], consent=True)
        assert blocked.value.code=='busy'
    assert queue.get(created['id'])==created


def test_blocked_unknown_queue_hides_without_releasing_or_replaying_receipts(setup):
    queue, service, created, _, _ = setup
    queue.run_scripts(created['id'], consent=True)
    approvals = [service.quote(row['job_id']) for row in created['rows']]
    queue.approve_videos(created['id'], approvals, '2', consent=True)
    service.fail_submit=True
    with pytest.raises(CharacterError): queue.advance_videos(created['id'], consent=True)
    before = queue.get(created['id']); jobs = deepcopy(service.jobs)
    assert before['state']=='blocked' and len(service.submits)==1
    queue.delete(created['id'], consent=True)
    assert queue.list()==[] and service.jobs==jobs
    assert {k:v for k,v in queue.get(created['id']).items() if k!='archived_at'}==before
    assert len(service.submits)==1 and not service.checks


@pytest.mark.parametrize('identifier', ['../outside', 'A'*32, 'a'*31])
def test_delete_rejects_inexact_ids(setup, identifier):
    queue, _, created, _, _ = setup
    with pytest.raises(CharacterError): queue.delete(identifier, consent=True)
    assert queue.list()==[created]


def test_delete_requires_consent_and_own_queue(setup, tmp_path):
    queue, service, created, _, _ = setup
    with pytest.raises(CharacterError): queue.delete(created['id'])
    other = EpisodeQueue(tmp_path/'another-user', service, queue.registry)
    with pytest.raises(CharacterError): other.delete(created['id'], consent=True)
    assert queue.list()==[created]


def test_delete_route_keeps_local_auth_origin_csrf_and_consent(gui):
    registry = CharacterRegistry(gui.root, gui.app.state.image_studio)
    character = registry.save(profile(), gui.asset)
    topics = TopicStore(gui.root)
    topic = topics.add(character['id'], '합성 대기열 정리')
    service = Service()
    gui.app.state.character = service
    gui.app.state.character_authoring = object()  # The local delete must never call it.
    queue = EpisodeQueue(gui.root, service, registry, topics)
    created = queue.create(character['id'], [topic['id']], {'duration':15}, '2', uuid4().hex)
    target = '/api/studio/characters/queues/'+created['id']+'/delete'
    session = LaunchSession(18779)
    client = TestClient(OperatingRequests(LocalAccess(gui.app, session)), base_url=session.origin,
                        client=('127.0.0.1',11001))
    assert client.post(target, data={'consent':'true'}).status_code==403
    token = session.launch_url().split('#',1)[1]  # Synthetic token, never logged.
    assert client.post('/__local/claim', headers={'Origin':session.origin,'X-NewsFlow-Bootstrap':token}).status_code==204
    assert client.get('/api/studio/characters/queues').status_code==200
    csrf = client.cookies['newsflow_csrf']
    assert client.post(target, data={'consent':'true','csrf_token':'wrong'}, headers={'Origin':session.origin}).status_code==403
    assert client.post(target, data={'consent':'true','csrf_token':csrf}, headers={'Origin':'https://outside.invalid'}).status_code==403
    assert client.post(target, data={'consent':'false','csrf_token':csrf}, headers={'Origin':session.origin}).status_code==422
    assert queue.list()==[created]
    result = client.post(target, data={'consent':'true','csrf_token':csrf}, headers={'Origin':session.origin})
    assert result.status_code==200 and result.json()=={'deleted':True,'historicalJobsPreserved':True}
    assert client.get('/api/studio/characters/queues').json()=={'queues':[]}
    assert client.get('/api/studio/characters/queues/'+created['id']).json()['archived_at']
    assert len(service.jobs)==1 and not service.writes and not service.submits


@pytest.mark.parametrize('method,suffix,status', [
    ('POST','a'*32+'/delete',204), ('GET','a'*32+'/delete',403),
    ('DELETE','a'*32+'/delete',403), ('POST','A'*32+'/delete',403),
    ('POST','a'*31+'/delete',403), ('POST','a'*32+'/delete/extra',403),
    ('POST','a'*32+'/scripts',403), ('POST','a'*32+'/advance',403),
    ('POST','a'*32+'/approve-videos',403),
])
def test_delete_operation_boundary_is_one_exact_local_post(method, suffix, status):
    received=[]
    async def inner(scope, receive, send):
        received.append((scope['method'],scope['path']))
        await send({'type':'http.response.start','status':204,'headers':[]})
        await send({'type':'http.response.body','body':b''})
    target='/api/studio/characters/queues/'+suffix
    assert TestClient(OperatingRequests(inner)).request(method,target).status_code==status
    assert received==([(method,target)] if status==204 else [])
