"""Explicit one-scene retry through operating adapter; Fake IO only."""
from copy import deepcopy
from datetime import timedelta
import pytest
from bat_distribution import character_manual_execution as m
from newsflow.character.schema import CharacterError
from newsflow.character.service import now, fingerprint
from newsflow.video.ai.contracts import ClipStatus
from test_character_retry_quote import failed_episode, post
from test_character_manual_execution import execution
from test_api_settings import sessions, store
from test_character_kling_studio import studio

@pytest.fixture
def quoted_retry(failed_episode):
    x=failed_episode
    assert post(x)==200
    x.before_retry=deepcopy(x.service.read(x.identifier))
    return x

def retry(x, **kwargs):
    kwargs.setdefault('quote_hash',x.before_retry['retry_hash'])
    return x.post('retry-scene',job_id=x.identifier,**kwargs)

def test_exact_single_retry_preserves_history_and_other_scenes(quoted_retry):
    x=quoted_retry;old=x.before_retry
    assert retry(x)==200
    job=x.service.read(x.identifier);scene=job['scenes'][0]
    assert job['state']=='generating' and scene['state']=='submitted'
    assert scene['attempt']==2 and scene['payload']==old['scenes'][0]['payload']
    assert scene['history']==[old['scenes'][0]]
    assert job['scenes'][1:]==old['scenes'][1:]
    assert job['quote_approvals'][:-1]==old['quote_approvals']
    assert job['quote_approvals'][-1]['usd']=='0.448'
    assert job['episode_limit']==old['episode_limit']
    assert x.state.calls==[('submit',f'{x.identifier}-s1-t2',scene['payload'])]
    assert retry(x)==409 and len(x.state.calls)==1
    x.state.status='in_progress'
    assert x.post('check',job_id=x.identifier)==200
    assert [c[0] for c in x.state.calls]==['submit','check']
    assert m._REQUEST.get() is None and m._ACTIVE.get() is None

@pytest.mark.parametrize('kwargs',[{'auth':False},{'csrf':False},{'origin':'https://example.com'},
                                   {'consent':False},{'quote_hash':''},{'quote_hash':'wrong'}])
def test_missing_permission_never_sends_or_mutates(quoted_retry,kwargs):
    x=quoted_retry;before=deepcopy(x.service.read(x.identifier))
    assert retry(x,**kwargs) in {403,409}
    assert x.service.read(x.identifier)==before and x.state.calls==[]

@pytest.mark.parametrize('mutation',['expired','key','budget','payload','reference','unknown',
                                    'submitted','mismatch','receipt','attempts','plan'])
def test_invalid_quote_or_state_does_not_submit(quoted_retry,mutation):
    x=quoted_retry;j=x.service.read(x.identifier)
    if mutation=='expired':j['retry']['at']=(now()-timedelta(minutes=16)).isoformat()
    elif mutation=='key':j['retry']['key_id']='different-key'
    elif mutation=='budget':
        j['episode_limit']='0.01';j['plan_hash']=x.service.plan_hash(j);j['approved_plan_hash']=j['plan_hash']
    elif mutation=='payload':j['scenes'][0]['payload']['prompt']+=' modified'
    elif mutation=='reference':(x.service.folder(x.identifier)/'reference.png').write_bytes(b'changed')
    elif mutation in {'unknown','submitted'}:j['scenes'][1]['state']=mutation
    elif mutation=='mismatch':j['scenes'][0]['status_diagnostics']={'observed_state':'completed','state_mismatch':True}
    elif mutation=='receipt':j['scenes'][0].pop('handle')
    elif mutation=='attempts':j['scenes'][0]['attempt']=3
    elif mutation=='plan':j['plan_hash']='changed'
    if mutation in {'expired','key'}:j['retry_hash']=fingerprint(j['retry'])
    x.service.save(j)
    before_bytes=(x.service.folder(x.identifier)/'jobs.json').read_bytes()
    assert retry(x,quote_hash=j['retry_hash'])==409
    assert x.state.calls==[] and (x.service.folder(x.identifier)/'jobs.json').read_bytes()==before_bytes

def test_unknown_retry_keeps_reservation_and_never_replays(quoted_retry):
    x=quoted_retry;x.state.fail='submit'
    assert retry(x)==409
    j=x.service.read(x.identifier)
    assert j['state']=='submission_unknown' and j['scenes'][0]['state']=='unknown'
    assert j['scenes'][0]['history']==[x.before_retry['scenes'][0]]
    assert j['quote_approvals'][-1]['usd']=='0.448'
    assert retry(x)==409 and post(x)==409 and len(x.state.calls)==1

def test_retry_scope_cannot_expand_or_resubmit(quoted_retry):
    x=quoted_retry
    def inside(scope):
        client=m._Client(scope,x.state.clients[-1])
        row=x.service.read(x.identifier)['scenes'][0]
        for method,args in [('submit_scene',(row['payload'],row['idempotency_key'])),
                            ('submit_scene',(row['payload'],'different-idempotency-key')),
                            ('estimate',(row['payload'],)),('upload_reference',(x.profile/'fake.png',)),
                            ('check',({},)),('diagnose',({},)),
                            ('fetch',(ClipStatus('completed'),x.profile/'fake.mp4',None))]:
            with pytest.raises(CharacterError):getattr(client,method)(*args)
    x.state.inside=inside
    assert retry(x)==200 and len(x.state.calls)==1
