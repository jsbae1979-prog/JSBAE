"""Approved set-reference requests cross the real operating gate using Fakes only."""
from copy import deepcopy
import pytest
from test_character_precision import precision
from test_precision_operating_access import connected
from test_precision_visual import prepare
from newsflow.character.service import fingerprint

def reviewed_anchor(c):
    w=prepare(c.p)
    w=c.s.quote(w['id'],w['revision'],[1])
    result=c.request('generate',quote_hash=w['quote']['hash'],consent='true',reference_consent='true').json()
    assert result['scenes'][0]['state']=='review',result
    return c.s.confirm(w['id'],result['revision'],1,1,True)

def test_operating_five_scenes_use_exact_approved_set_reference(connected):
    c=connected;w=reviewed_anchor(c);first=deepcopy(w['scenes'][0])
    w=c.s.quote(w['id'],w['revision'],[2,3,4,5])
    result=c.request('generate',quote_hash=w['quote']['hash'],consent='true',reference_consent='true').json()
    assert [s['state'] for s in result['scenes']]==['confirmed']+['review']*4,result
    assert c.s.read(w['id'])['scenes'][0]==first
    assert [len(call['refs']) for call in c.adapter.calls]==[2,3,3,3,3]
    reference=c.owner.images.asset(first['versions'][0]['asset']).read_bytes()
    for call in c.adapter.calls[1:]:
        assert call['refs'][-1]==reference
        assert 'Image 3 is the user-approved set reference' in call['prompt']
    assert len(c.state.decryptions)==5 and not c.state.calls
    assert c.request('generate',quote_hash=w['quote']['hash'],consent='true',reference_consent='true').status_code==422
    assert len(c.adapter.calls)==5

@pytest.mark.parametrize('fault',['missing','extra','reordered','prompt','unconfirmed','journal_anchor','quote_anchor','quote_prompt','quote_refs'])
def test_anchor_tamper_is_blocked_before_decryption_and_transport(connected,monkeypatch,fault):
    c=connected;w=reviewed_anchor(c);w=c.s.quote(w['id'],w['revision'],[2])
    original=c.owner.images.execute
    def alter(identifier,**kw):
        if fault in {'missing','extra','reordered','prompt'}:
            from newsflow.db.models import IntelligenceRun
            with c.p.app.state.sessions.begin() as session:
                row=session.get(IntelligenceRun,identifier)
                refs=list(row.options['references'])
                if fault=='missing':refs=refs[:-1]
                if fault=='extra':refs.append(refs[0])
                if fault=='reordered':refs=list(reversed(refs))
                row.options={**row.options,'references':refs}
                if fault=='prompt':row.result={'prompt':'unapproved background'}
        else:
            saved=c.s.read(w['id'])
            if fault=='unconfirmed':saved['scenes'][0]['confirmed']=None
            elif fault=='journal_anchor':saved['scenes'][1]['versions'][-1]['visual_anchor']=None
            else:
                quote=saved['events'][-1]['quote'];bound=quote['bounds'][0]
                if fault=='quote_anchor':bound['visual_anchor']=None
                if fault=='quote_prompt':bound['prompt_hash']=fingerprint('unapproved')
                if fault=='quote_refs':bound['reference_hashes']=[]
                # Even a newly hashed quote cannot authorize a different request.
                quote['hash']=fingerprint({k:v for k,v in quote.items() if k!='hash'})
            c.s.save(saved)
        return original(identifier,**kw)
    monkeypatch.setattr(c.owner.images,'execute',alter)
    c.request('generate',quote_hash=w['quote']['hash'],consent='true',reference_consent='true')
    assert len(c.adapter.calls)==1 and len(c.state.decryptions)==1
    assert not c.state.calls
    saved=c.s.read(w['id'])
    assert saved['scenes'][1]['versions'][0]['state']=='unknown'
    assert all(not s['versions'] for s in saved['scenes'][2:])
