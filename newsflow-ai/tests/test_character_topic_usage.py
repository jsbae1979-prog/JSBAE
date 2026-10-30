from copy import deepcopy
from types import SimpleNamespace
from newsflow.character.topics import TopicStore
from newsflow.character.service import fingerprint
from test_character_automation_routes import gui,profile
import json

def test_existing_single_episode_usage_is_readonly_and_isolated(tmp_path):
    store=TopicStore(tmp_path);a='char_'+'a'*32;b='char_'+'b'*32
    first=store.add(a,'작은 정원');store.add(a,'처음 쓰는 주제');store.add(b,'작은 정원')
    path=store._path(a);before=path.read_bytes()
    script={'title':'합성 스토리'}
    jobs=[{'character_id':a,'topic':'  작은  정원 ','script':script,'script_hash':fingerprint(script),'state':'quoted'},
          {'character_id':b,'topic':'처음 쓰는 주제','script':script,'script_hash':fingerprint(script),'state':'completed','output':{'sha256':'a'*64}}]
    rows=store.with_usage(a,jobs)
    assert [r['status'] for r in rows]==['scripted','new']
    assert path.read_bytes()==before and store.list(a)[0]['status']=='new'
    assert store.with_usage(b,jobs)[0]['status']=='new'

def test_attempt_is_not_unused_or_false_completion(tmp_path):
    store=TopicStore(tmp_path);a='char_'+'a'*32;store.add(a,'작은 정원')
    job={'character_id':a,'topic':'작은 정원','script_attempts':1,'state':'script_failed'}
    assert store.with_usage(a,[job])[0]['status']=='script_requested'
    job.update(script={'title':'합성'},script_hash='wrong',state='completed',output={'sha256':'a'*64})
    assert store.with_usage(a,[job])[0]['status']=='script_requested'
    job['script_hash']=fingerprint(job['script'])
    assert store.with_usage(a,[job])[0]['status']=='produced'

def test_topic_get_projects_job_without_writes_or_provider(gui):
    saved=gui.post('/api/studio/characters/profiles/save',profile=json.dumps(profile()),asset=gui.asset).json()
    store=TopicStore(gui.root);store.add(saved['id'],'작은 정원')
    script={'title':'합성'};jobs=[{'character_id':saved['id'],'topic':'작은 정원','script':script,'script_hash':fingerprint(script)}]
    gui.app.state.character=SimpleNamespace(listing=lambda:deepcopy(jobs))
    before=store._path(saved['id']).read_bytes()
    response=gui.client.get('/api/studio/characters/profiles/'+saved['id']+'/topics')
    assert response.status_code==200 and response.json()['topics'][0]['status']=='scripted'
    assert store._path(saved['id']).read_bytes()==before
