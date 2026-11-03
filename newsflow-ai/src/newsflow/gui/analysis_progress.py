"""Read-only status for the exact stored curation claim; never invokes AI."""
from datetime import datetime, timezone
import hashlib
import json
from fastapi import HTTPException
from newsflow.db.models import AppSetting, IntelligenceRun
from newsflow.intelligence.curation import WORKSPACE_TOP_K, CURATION_TIMEOUT_SECONDS

def status(sessions, ctx, collection_context_id):
    if collection_context_id != ctx['run_id']:
        raise HTTPException(409, '수집 회차가 바뀌었습니다. 이전 요청의 작업 기록을 확인하세요.')
    ai=ctx['ai']
    identity=['analysis',ctx['run_id'],sorted(a.id for a in ctx['articles']),ai['provider'],ai['model'],WORKSPACE_TOP_K]
    key='curation_once:'+hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:36]
    now=datetime.now(timezone.utc)
    result={'state':'pending','runId':None,'elapsedSeconds':0,'checkedAt':now.isoformat()}
    with sessions() as session:
        claim=session.get(AppSetting,key)
        if not claim:return result
        try:record=json.loads(claim.value)
        except (TypeError,ValueError):return {**result,'state':'unknown'}
        run=session.get(IntelligenceRun,record['run_id']) if record.get('run_id') else None
        if not run:return {**result,'state':'failed' if record.get('status')=='failed' else 'unknown'}
        start=run.created_at.replace(tzinfo=timezone.utc) if run.created_at.tzinfo is None else run.created_at
        end=run.finished_at or now
        if end.tzinfo is None:end=end.replace(tzinfo=timezone.utc)
        elapsed=max(0,int((end-start).total_seconds()))
        state={'running':'running','success':'success','failed':'failed','unknown':'unknown'}.get(run.status,'unknown')
        if state=='running' and elapsed>CURATION_TIMEOUT_SECONDS+30:state='delayed'
        # Fixed reason text only. Do not return response bodies, prompts, credentials or exception messages.
        reason=(run.result or {}).get('analysis_failure',{}).get('failure_reason')
        detail=('AI 응답을 받았지만 결과 형식 검사를 통과하지 못했습니다.'
                if reason in {'analysis_schema','curation_schema','result_json'} else
                '분석을 완료하지 못했습니다. 저장된 실패 기록을 확인하세요.') if state=='failed' else ''
        return {**result,'state':state,'runId':run.id,'elapsedSeconds':elapsed,
                'startedAt':start.isoformat(),'finishedAt':end.isoformat() if run.finished_at else None,'detail':detail}
