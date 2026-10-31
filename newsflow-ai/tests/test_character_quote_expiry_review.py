from copy import deepcopy
from datetime import timedelta
import pytest
from newsflow.character.quote_review import quote_review
from newsflow.character.service import now, fingerprint
from newsflow.character.schema import CharacterError
from newsflow.character.kling import check
from test_character_episode_automation import setup_episode

@pytest.fixture
def quoted(tmp_path):
    s,v,i,_,_=setup_episode(tmp_path)
    s.write(i,consent=True)
    s.prepare(i,consent=True,script_reviewed=True)
    return s,v,i

@pytest.mark.parametrize('age,status',[(0,'ready'),(900,'ready'),(901,'expired'),(-1,'changed')])
def test_exact_lifetime_without_key_or_network(quoted,age,status):
    s,v,i=quoted;job=s.read(i)
    from datetime import datetime
    stamp=datetime.fromisoformat(job['quoted_at'])
    before=deepcopy(job)
    assert quote_review(job,stamp+timedelta(seconds=age))['quoteStatus']==status
    assert s.read(i)==before and not v.sent

@pytest.mark.parametrize('stamp',['not-a-date','2026-10-31T00:00:00',None])
def test_invalid_quote_metadata_closed(quoted,stamp):
    s,v,i=quoted;job=s.read(i);job['quoted_at']=stamp
    assert quote_review(job,now())['quoteStatus']=='changed'
    assert not v.sent

def expired(s,i):
    job=s.read(i);job['quoted_at']=(now()-timedelta(minutes=16)).isoformat()
    job['quote_hash']=fingerprint([job['plan_hash'],job['scenes'],job['quoted_at'],job['quote_key_id']])
    s.save(job);return job

def test_expired_submit_specific_reason_no_key_decryption_or_submit(quoted):
    s,v,i=quoted;job=expired(s,i)
    v.credential=lambda:pytest.fail('Expired quote must not read a key')
    with pytest.raises(CharacterError) as error:s.submit(i,consent=True,quote_hash=job['quote_hash'])
    assert error.value.code=='quote_expired' and '최신 견적' in str(error.value)
    assert s.read(i)==job and not v.sent

def test_explicit_quote_refresh_keeps_history_and_needs_new_approval(quoted):
    s,v,i=quoted;old=expired(s,i)
    s.update_studio_settings(i,check(old['studio_selection']),old['episode_limit'])
    changed=s.read(i)
    assert changed['state']=='script_review' and changed['quote_history'][-1]['quote_hash']==old['quote_hash']
    assert not v.sent and len(s.authoring.calls)==1
    s.prepare(i,consent=True,script_reviewed=True)
    fresh=s.read(i)
    assert fresh['quote_hash']!=old['quote_hash'] and not fresh.get('quote_approvals') and not v.sent
    with pytest.raises(CharacterError) as error:s.submit(i,consent=True,quote_hash=old['quote_hash'])
    assert error.value.code=='quote_changed' and not v.sent

def test_unknown_outcome_remains_blocked_and_cannot_refresh(quoted):
    s,v,i=quoted;v.unknown=True
    with pytest.raises(CharacterError):s.submit(i,consent=True,quote_hash=s.read(i)['quote_hash'])
    before=s.read(i)
    with pytest.raises(CharacterError):s.submit(i,consent=True,quote_hash=before['quote_hash'])
    with pytest.raises(CharacterError):s.update_studio_settings(i,check(before['studio_selection']),before['episode_limit'])
    assert before['state']=='submission_unknown' and s.read(i)==before and len(v.sent)==1
