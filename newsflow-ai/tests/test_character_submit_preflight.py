"""Synthetic HTTP receipts only; real adapter path is not replaced by a Fake submit."""
from copy import deepcopy
import hashlib,json
from datetime import timedelta
from pathlib import Path
from newsflow.video.engine import FFmpegAdapter
import pytest
from newsflow.character.higgsfield_client import HiggsfieldVideoClient,SceneNotSent
from newsflow.character.schema import CharacterError
from newsflow.character.service import fingerprint,now
from newsflow.video.ai.higgsfield import _NotSent
from bat_distribution.legacy_unsent_recovery import recover,REJECTOR_SHA256
from test_character_episode_automation import setup_episode

@pytest.fixture(autouse=True)
def synthetic_tools(monkeypatch):
    monkeypatch.setattr(FFmpegAdapter,'executable',staticmethod(lambda *a:Path('synthetic-tool.exe')))


@pytest.mark.parametrize('key',['a'*32,'a'*32+'-1','a'*32+'-s1-t1','b'*32+'-s12-t3'])
def test_real_client_accepts_legacy_and_exact_episode_keys(key):
    calls=[]
    def request(host,method,path,body,headers,timeout):
        calls.append((method,headers['Idempotency-Key']))
        return 200,json.dumps({'request_id':'synthetic-request','status':'queued',
            'status_url':'https://api.higgsfield.ai/requests/synthetic-request/status'}).encode()
    client=HiggsfieldVideoClient(lambda:'synthetic-only',requester=request)
    assert client.submit_scene({'prompt':'synthetic'},key)['request_id']=='synthetic-request'
    assert calls==[('POST',key)]

@pytest.mark.parametrize('key',[None,'','x'*32+'-s1-t1','a'*32+'-s0-t1','a'*32+'-s1-t0',
                              'a'*32+'-s1-t1\r\nHeader: invalid','a'*32+'-s1-t1-extra'])
def test_bad_key_is_provably_not_sent_and_does_not_read_key(key):
    calls=[]
    client=HiggsfieldVideoClient(lambda:calls.append('credential'),requester=lambda *a:calls.append('http'))
    with pytest.raises(SceneNotSent):client.submit_scene({},key)
    assert calls==[]

@pytest.mark.parametrize('kind',['local_key','connect','ambiguous'])
def test_dispatch_distinguishes_notsent_without_replay(tmp_path,kind):
    service,video,i,_,_=setup_episode(tmp_path)
    service.write(i,consent=True);service.prepare(i,consent=True,script_reviewed=True)
    attempts=[]
    def submit(payload,key):
        attempts.append(key)
        if kind=='local_key':raise SceneNotSent()
        if kind=='connect':raise _NotSent()
        raise TimeoutError('synthetic unknown')
    video.submit_scene=submit
    with pytest.raises(CharacterError):service.submit(i,consent=True,quote_hash=service.read(i)['quote_hash'])
    job=service.read(i)
    assert job['state']==('submission_unknown' if kind=='ambiguous' else 'submission_not_sent')
    assert job['scenes'][0]['state']==('unknown' if kind=='ambiguous' else 'not_sent')
    if kind!='ambiguous':assert job['scenes'][0]['submit_diagnostics']['dispatched'] is False
    assert len(attempts)==1
    with pytest.raises(CharacterError):service.submit(i,consent=True,quote_hash=job['quote_hash'])
    assert len(attempts)==1

def legacy(tmp_path):
    s,v,i,_,_=setup_episode(tmp_path);s.write(i,consent=True);s.prepare(i,consent=True,script_reviewed=True)
    job=s.read(i);job['quote_approvals']=[{'usd':job['quote_total_usd'],'scope':'initial'}]
    job['approved_plan_hash']=job['plan_hash'];job['state']='submission_unknown'
    for row in job['scenes']:
        row['approved_template_hash']=fingerprint(row['payload'])
        row['state']='unknown' if row['continuity']=='cut' else 'waiting_dependency'
        if row['state']=='unknown':row['submitted_at']=now().isoformat()
    return job

def test_pinned_legacy_recovery_retains_history_and_requires_new_quote(tmp_path):
    job=legacy(tmp_path);before=deepcopy(job)
    result=recover(job,consent=True,expected_job_hash=fingerprint(job),rejected_client_sha256=REJECTOR_SHA256)
    assert job==before and result['state']=='script_review' and result['scenes']==[]
    assert 'quote_hash' not in result and 'quote_approvals' not in result
    assert result['script']==job['script']
    assert result.get('text_reservations')==job.get('text_reservations')
    history=result['submission_history'][-1]
    assert history['record']['scenes']==job['scenes'] and history['proof']['dispatched'] is False

@pytest.mark.parametrize('fault',['client','job_hash','consent','handle','http','key','payload','time','state'])
def test_legacy_recovery_never_reclassifies_unproven_unknown(tmp_path,fault):
    job=legacy(tmp_path);options=dict(consent=True,expected_job_hash=fingerprint(job),rejected_client_sha256=REJECTOR_SHA256)
    if fault=='client':options['rejected_client_sha256']='0'*64
    elif fault=='job_hash':options['expected_job_hash']='0'*64
    elif fault=='consent':options['consent']=False
    else:
        row=job['scenes'][0]
        if fault=='handle':row['handle']={'request_id':'synthetic-received'}
        elif fault=='http':row['submit_diagnostics']={'http_status':500}
        elif fault=='key':row['idempotency_key']='a'*32
        elif fault=='payload':row['payload']['prompt']='changed'
        elif fault=='time':row['submitted_at']=(now()+timedelta(days=1)).isoformat()
        else:row['state']='submitted'
        options['expected_job_hash']=fingerprint(job)
    before=deepcopy(job)
    with pytest.raises(CharacterError):recover(job,**options)
    assert job==before
