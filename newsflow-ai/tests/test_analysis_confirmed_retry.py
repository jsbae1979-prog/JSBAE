import hashlib,json
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from newsflow.db.models import AppSetting,IntelligenceRun,utcnow
from newsflow.gui.analysis_progress import retryable_run
from newsflow.gui.curation_routes import _once

@pytest.mark.parametrize("reason,expected",[("analysis_schema",True),("result_json",True),("curation_schema",True),("timeout",False),("response_incomplete",False),(None,False)])
def test_only_definite_failures_retry(reason,expected):
    run=SimpleNamespace(kind="analysis",status="failed",finished_at=utcnow(),result={"dispatch_state":"sent_or_unknown","analysis_failure":{"failure_reason":reason}})
    assert retryable_run(run) is expected
    run.finished_at=None
    assert not retryable_run(run)
    run.finished_at=utcnow();run.status="running"
    assert not retryable_run(run)

@pytest.mark.parametrize("phase",["failed","running","unknown"])
def test_confirmed_retry_retains_claim_and_prevents_duplicate(app,phase):
    identity=["analysis",21,[1,2],"claude_api","model",3]
    key="curation_once:"+hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:36]
    sessions=app.state.sessions
    with sessions.begin() as db:
        run=IntelligenceRun(kind="analysis",provider="claude_api",status=phase,finished_at=utcnow(),message="synthetic",result={"analysis_failure":{"failure_reason":"analysis_schema"}},evidence={},options={})
        db.add(run);db.flush();old=run.id
        db.add(AppSetting(key=key,value=json.dumps({"status":phase,"run_id":old})))
    request=SimpleNamespace(app=app);calls=[]
    def fake(remember):calls.append(True);remember(999);return {"run_id":999}
    for wrong in [None,old+100]:
        with pytest.raises(HTTPException) as err:_once(request,identity,fake,retry_failed_run_id=wrong)
        assert err.value.status_code==409 and not calls
    if phase!="failed":
        with pytest.raises(HTTPException):_once(request,identity,fake,retry_failed_run_id=old)
        assert not calls;return
    assert _once(request,identity,fake,retry_failed_run_id=old)["run_id"]==999
    assert _once(request,identity,fake,retry_failed_run_id=old)["run_id"]==999
    assert len(calls)==1
    with sessions() as db:
        record=json.loads(db.get(AppSetting,key).value)
        assert record["history"]==[{"status":"failed","run_id":old}]
        assert db.get(IntelligenceRun,old).status=="failed"

def test_new_failure_needs_new_confirmation(app):
    identity=["analysis",22,[],"claude_api","model",3];calls=[]
    request=SimpleNamespace(app=app)
    def fail(remember):
        with app.state.sessions.begin() as db:
            row=IntelligenceRun(kind="analysis",provider="claude_api",status="failed",finished_at=utcnow(),message="synthetic",result={"analysis_failure":{"failure_reason":"analysis_schema"}},evidence={},options={})
            db.add(row);db.flush();identifier=row.id
        calls.append(identifier);remember(identifier);raise ValueError("synthetic schema error")
    with pytest.raises(ValueError):_once(request,identity,fail)
    first=calls[0]
    with pytest.raises(ValueError):_once(request,identity,fail,retry_failed_run_id=first)
    with pytest.raises(HTTPException):_once(request,identity,fail,retry_failed_run_id=first)
    assert len(calls)==2 and calls[0]!=calls[1]
