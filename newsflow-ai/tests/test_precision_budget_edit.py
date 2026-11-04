from copy import deepcopy
import pytest
from test_character_precision import precision, scripted

def test_budget_edit_preserves_story_and_invalidates_quote_without_calls(precision):
 p=precision;w=scripted(p);w=p.s.quote(w['id'],w['revision'],[1,2,3,4,5]);before=deepcopy(w)
 w=p.s.edit(w['id'],w['revision'],w['scenario'],'1.520960')
 assert w['image_limit']=='1.520960' and 'quote' not in w
 assert w['scenes']==before['scenes'] and w['scenario']==before['scenario']
 assert w['cast']==before['cast'] and w['story_attempts']==before['story_attempts']
 assert w['events'][-1]['kind']=='image_budget_changed'
 assert not p.adapter.calls and not p.writer.calls
 with pytest.raises(ValueError):p.s.edit(w['id'],before['revision'],w['scenario'],'2')

@pytest.mark.parametrize('value',['0','-1','NaN','Infinity','10001'])
def test_invalid_budget_does_not_modify_work(precision,value):
 p=precision;w=scripted(p)
 with pytest.raises(ValueError):p.s.edit(w['id'],w['revision'],w['scenario'],value)
 assert p.s.read(w['id'])==w and not p.adapter.calls

def test_standing_limit_still_blocks_generation(precision):
 p=precision;w=scripted(p);w=p.s.edit(w['id'],w['revision'],w['scenario'],'2')
 p.readiness.limit='0.001';w=p.s.quote(w['id'],w['revision'],[1])
 with pytest.raises(ValueError):p.s.generate(w['id'],w['quote']['hash'],True,True)
 assert not p.adapter.calls

def test_busy_and_existing_exposure_cannot_be_bypassed(precision):
 p=precision;w=scripted(p);w['state']='generating';p.s.save(w)
 with pytest.raises(ValueError):p.s.edit(w['id'],w['revision'],w['scenario'],'2')
 w['state']='images';w['scenes'][0]['versions']=[{'reserve_usd':'2','state':'unknown'}];p.s.save(w)
 with pytest.raises(ValueError):p.s.edit(w['id'],w['revision'],w['scenario'],'1')
 assert p.s.read(w['id'])==w and not p.adapter.calls
