"""Existing receipts only: failures never authorize further paid scenes."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from newsflow.character.schema import CharacterError
from newsflow.character.status_diagnostics import dependency_stop_reason
from newsflow.video.ai.contracts import ClipStatus
from test_character_episode_recovery import quoted, synthetic_downloads


def mixed(tmp_path):
    s,v,i=quoted(tmp_path)
    s.submit(i,consent=True,quote_hash=s.read(i)['quote_hash'])
    job=s.read(i)
    third=deepcopy(job['scenes'][0]);third.update(position=3)
    third['handle']={'request_id':'synthetic-third','status_url':'https://api.higgsfield.ai/requests/synthetic-third/status'}
    job['scenes'].append(third);s.save(job)
    return s,v,i


def test_pending_receipt_remains_observable_after_other_scene_fails(tmp_path):
    s,v,i=mixed(tmp_path);calls=[];old=deepcopy(s.read(i))
    def check(handle):
        calls.append(handle['request_id'])
        return ClipStatus('failed' if len(calls)==1 else 'in_progress',facts={'error_message':'Synthetic failure'})
    v.check=check
    s.check(i,consent=True)
    job=s.read(i)
    assert [r['state'] for r in job['scenes']]==['failed','waiting_dependency','submitted']
    assert job['state']=='scene_review'
    assert job['scenes'][0]['status_diagnostics']['error_message']=='Synthetic failure'
    v.check=lambda h: (calls.append(h['request_id']) or ClipStatus('failed'))
    s.check(i,consent=True)
    after=s.read(i)
    assert len(calls)==3 and len(v.sent)==1
    assert [r['state'] for r in after['scenes']]==['failed','waiting_dependency','failed']
    for before,row in zip(old['scenes'],after['scenes']):
        for key in ('attempt','payload','handle','idempotency_key','quote_usd'):
            assert before.get(key)==row.get(key)
    assert after['quote_total_usd']==old['quote_total_usd']


def test_completed_receipt_is_saved_but_no_dependency_dispatched_after_failure(tmp_path,monkeypatch):
    s,v,i=mixed(tmp_path);synthetic_downloads(monkeypatch,v)
    job=s.read(i);job['scenes'][0]['state']='failed'
    # Dependency on a successfully downloaded other parent is also held.
    job['scenes'][1]['from']=3;s.save(job)
    uploads=len(v.uploads)
    v.check=lambda h:ClipStatus('completed')
    s.check(i,consent=True)
    after=s.read(i)
    assert after['scenes'][2]['state']=='downloaded'
    assert after['scenes'][1]['state']=='waiting_dependency'
    assert len(v.sent)==1 and len(v.uploads)==uploads
    assert dependency_stop_reason(after,after['scenes'][1])=='job_failed'


def test_projection_identifies_direct_and_transitive_parent_failure_without_mutation():
    job={'automation_version':1,'scenes':[{'position':1,'state':'failed'},
         {'position':2,'state':'waiting_dependency','from':1},
         {'position':3,'state':'waiting_dependency','from':2}]}
    before=deepcopy(job)
    assert dependency_stop_reason(job,job['scenes'][1])=='parent_failed'
    assert dependency_stop_reason(job,job['scenes'][2])=='parent_failed'
    assert job==before
    job['scenes'][0]['state']='submitted'
    assert dependency_stop_reason(job,job['scenes'][2])==''


def test_episode_diagnosis_with_unsent_dependency_is_get_only_and_redacted(tmp_path,app):
    s,v,i=mixed(tmp_path);job=s.read(i);job['state']='scene_review'
    job['scenes'][0]['state']='failed';s.save(job);before=deepcopy(job);calls=[]
    v.diagnose=lambda h,protected=(): (calls.append(h) or ClipStatus('failed',facts={'error_message':'Bad input '+job['topic']}))
    with pytest.raises(CharacterError):s.diagnose(i,consent=False)
    assert not calls
    s.diagnose(i,consent=True);after=s.read(i)
    assert len(calls)==1 and len(v.sent)==1
    assert job['topic'] not in after['scenes'][0]['status_diagnostics']['error_message']
    s.sessions=app.state.sessions
    from newsflow.studio.read_models import character_rows
    projected=next(row for row in character_rows(SimpleNamespace(character=s)) if row['id']==i)
    assert projected['scenes'][1]['dependencyStopReason']=='parent_failed'
    for row in after['scenes']:row.pop('status_diagnostics',None)
    assert before==after


@pytest.mark.parametrize('mutation',['handle','self_parent','legacy'])
def test_invalid_waiting_companion_blocks_before_diagnostic_get(tmp_path,mutation):
    s,v,i=mixed(tmp_path);job=s.read(i);job['state']='scene_review';job['scenes'][0]['state']='failed'
    if mutation=='handle':job['scenes'][1]['handle']=job['scenes'][0]['handle']
    elif mutation=='self_parent':job['scenes'][1]['from']=2
    else:job.pop('automation_version')
    s.save(job);calls=[]
    v.diagnose=lambda *a,**kw:calls.append(1)
    with pytest.raises(CharacterError):s.diagnose(i,consent=True)
    import json
    assert calls==[] and json.loads((s.folder(i)/'jobs.json').read_text(encoding='utf8'))==job
