"""Existing failed receipt quote only; Fake IO and temporary profiles."""
from copy import deepcopy
import pytest
from bat_distribution import character_manual_execution as m
from newsflow.character.schema import CharacterError
from newsflow.video.ai.contracts import ClipStatus
from test_character_manual_execution import execution
from test_api_settings import sessions, store
from test_character_kling_studio import studio

@pytest.fixture
def failed_episode(execution, monkeypatch):
    from test_character_episode_automation import setup_episode
    x=execution
    service,video,identifier,_,_=setup_episode(x.profile,target=20)
    service.write(identifier,consent=True)
    service.prepare(identifier,consent=True,script_reviewed=True)
    service.submit(identifier,consent=True,quote_hash=service.read(identifier)['quote_hash'])
    job=service.read(identifier);job['state']='scene_review';row=job['scenes'][0]
    row['state']='failed'
    row['handle']={'request_id':'01234567-89ab-cdef-0123-456789abcdef',
                  'status_url':'https://api.higgsfield.ai/requests/01234567-89ab-cdef-0123-456789abcdef/status'}
    service.save(job)
    x.identifier=identifier;x.before=deepcopy(job);x.quotes=[];x.quote_failure=False;x.inside_quote=None
    def estimate(client,payload):
        assert client.credential()=='synthetic-only'
        x.quotes.append(deepcopy(payload))
        if x.inside_quote:x.inside_quote()
        if x.quote_failure:raise TimeoutError('synthetic quote timeout')
        return '0.448'
    monkeypatch.setattr(m.KlingClient,'estimate',estimate)
    return x

def post(x,**kwargs):
    return x.post('retry-quote',job_id=x.identifier,**kwargs)

def test_one_exact_quote_preserves_receipts_attempts_media_and_budget(failed_episode):
    x=failed_episode
    assert post(x)==200
    j=x.service.read(x.identifier)
    assert j['state']=='retry_quoted' and j['retry']['position']==1 and j['retry']['quote_usd']=='0.448'
    assert x.quotes==[x.before['scenes'][0]['payload']] and x.state.calls==[]
    assert {k:v for k,v in j.items() if k not in {'state','retry','retry_hash'}}=={k:v for k,v in x.before.items() if k!='state'}
    assert post(x)==409 and len(x.quotes)==1
    assert m._REQUEST.get() is None and m._ACTIVE.get() is None

@pytest.mark.parametrize('kwargs',[{'auth':False},{'csrf':False},{'origin':'https://example.com'},{'consent':False}])
def test_auth_and_consent_preserved(failed_episode,kwargs):
    x=failed_episode
    assert post(x,**kwargs) in {403,409}
    assert x.quotes==[] and x.state.native==0 and x.service.read(x.identifier)==x.before

@pytest.mark.parametrize('mutation',['unknown','submitted','attempts','reference','plan','observed_completed','no_receipt'])
def test_unready_or_changed_target_never_estimates(failed_episode,mutation):
    x=failed_episode;j=x.service.read(x.identifier)
    if mutation in {'unknown','submitted'}:j['scenes'][1]['state']=mutation
    elif mutation=='attempts':j['scenes'][0]['attempt']=3
    elif mutation=='reference':(x.service.folder(x.identifier)/'reference.png').write_bytes(b'changed fake image')
    elif mutation=='plan':j['plan_hash']='changed'
    elif mutation=='observed_completed':j['scenes'][0]['status_diagnostics']={'observed_state':'completed','state_mismatch':True}
    elif mutation=='no_receipt':j['scenes'][0].pop('handle')
    x.service.save(j)
    assert post(x)==409 and x.quotes==[]

def test_timeout_is_not_replayed(failed_episode):
    x=failed_episode;x.quote_failure=True
    assert post(x)==409
    assert x.service.read(x.identifier)['state']=='retry_quote_failed'
    assert post(x)==409 and len(x.quotes)==1 and x.state.calls==[]

def test_estimate_context_cannot_submit_upload_check_download_or_estimate_twice(failed_episode):
    x=failed_episode
    def inside():
        client=m._Client(x.manual,x.state.clients[-1])
        for name,args in [('submit_scene',({},'fake')),('upload_reference',(x.profile/'fake.png',)),
                          ('check',({},)),('diagnose',({},)),('fetch',(ClipStatus('completed'),x.profile/'fake.mp4',None)),
                          ('estimate',(x.before['scenes'][0]['payload'],))]:
            with pytest.raises(CharacterError):getattr(client,name)(*args)
    x.inside_quote=inside
    assert post(x)==200 and len(x.quotes)==1 and x.state.calls==[]
    assert x.post('retry-scene',job_id=x.identifier,quote_hash='')==409  # Missing quoted approval never sends.
    assert x.state.calls==[]
