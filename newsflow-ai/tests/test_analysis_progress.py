from datetime import timedelta
from types import SimpleNamespace
import hashlib,json
import pytest
from fastapi import HTTPException
from newsflow.db.models import AppSetting,IntelligenceRun,utcnow
from newsflow.gui.analysis_progress import status

@pytest.fixture
def progress(app):
    ctx={'run_id':21,'articles':[SimpleNamespace(id=2),SimpleNamespace(id=1)],'ai':{'provider':'claude_api','model':'claude-sonnet-4-6'}}
    key='curation_once:'+hashlib.sha256(json.dumps(['analysis',21,[1,2],'claude_api','claude-sonnet-4-6',3],sort_keys=True).encode()).hexdigest()[:36]
    return app.state.sessions,ctx,key

@pytest.mark.parametrize('phase',['running','failed','success','unknown','delayed'])
def test_status_reads_exact_claim_without_writes(progress,phase):
    sessions,ctx,key=progress
    with sessions.begin() as s:
        run=IntelligenceRun(kind='analysis',provider='claude_api',status='running' if phase=='delayed' else phase,
            created_at=utcnow()-timedelta(seconds=360 if phase=='delayed' else 35),
            finished_at=utcnow() if phase in {'failed','success'} else None,
            message='synthetic',result={'analysis_failure':{'failure_reason':'analysis_schema'},'secret':'must-not-return'},evidence={},options={})
        s.add(run);s.flush();identifier=run.id
        s.add(AppSetting(key=key,value=json.dumps({'status':phase,'run_id':identifier})))
    result=status(sessions,ctx,21)
    assert result['state']==phase and result['runId']==identifier and result['elapsedSeconds']>=34
    assert 'must-not-return' not in str(result)
    with sessions() as s:assert s.get(IntelligenceRun,identifier).status==('running' if phase=='delayed' else phase)

def test_no_request_and_different_context(progress):
    sessions,ctx,key=progress
    assert status(sessions,ctx,21)['state']=='pending'
    with pytest.raises(HTTPException) as error:status(sessions,ctx,22)
    assert error.value.status_code==409

def test_other_model_claim_is_not_current(progress):
    sessions,ctx,key=progress
    with sessions.begin() as s:s.add(AppSetting(key=key,value=json.dumps({'status':'failed'})))
    assert status(sessions,ctx,21)['state']=='failed'
    ctx['ai']['model']='different-model'
    assert status(sessions,ctx,21)['state']=='pending'


def test_status_route_local_auth_and_no_store(app,monkeypatch,progress):
    from starlette.testclient import TestClient
    from newsflow.distribution.local_access import LaunchSession,LocalAccess
    from bat_distribution.operation import OperatingRequests
    sessions,ctx,key=progress
    monkeypatch.setattr('newsflow.gui.curation_routes.context',lambda request:ctx)
    session=LaunchSession(18779)
    with TestClient(OperatingRequests(LocalAccess(app,session)),base_url=session.origin,client=('127.0.0.1',43210)) as c:
        url='/api/curation/analysis-status?collection_context_id=21'
        assert c.get(url).status_code==403
        c.cookies.set(session.cookie_name,session.claim(session.launch_url().split('#')[1]))
        r=c.get(url);assert r.status_code==200 and r.json()['state']=='pending'
        assert r.headers['cache-control']=='no-store'
        assert c.get('/api/curation/analysis-status?collection_context_id=22').status_code==409
