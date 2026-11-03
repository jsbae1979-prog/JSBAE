"""Synthetic request tests; no OCR, live providers or claims of image compliance."""
from copy import deepcopy
from hashlib import sha256
import json
import pytest
from newsflow.creation.complete_feed import (
    EDITORIAL_INSTRUCTION, HEADLINE_INSTRUCTION, STYLE, plan, request_prompt,
)
from newsflow.creation.feed_costs import binding
from test_complete_feed_editorial import source, content
from test_complete_feed import complete, settings
from test_feed_budget import budget_setup, step
from test_top_three_selection import feeds


@pytest.mark.parametrize('name', ['가상 연구소 A', '가상 시청 B'])
def test_new_request_requires_rewrite_and_fact_check_in_same_request(name):
    s=source(name); p=plan(s,content(s)); before=deepcopy(p)
    text=request_prompt({'plan':content(s),'rank':1},p)
    payload=json.loads(text[text.index('{'):])
    assert p==before and p['editorial_revision']==3
    assert payload['news_reference']['title']==s['title']
    assert payload['news_reference']['summary']==s['body']
    assert not {'plan','requested_copy','headline','key_fact'} & payload.keys()
    assert 'Internally draft three DIFFERENT' in text
    assert 'a copied opening clause, a shortened extract' in text
    assert 'Change the sentence structure and editorial angle' in text
    assert 'Keep necessary proper names, technical terms and exact factual numbers' in text
    assert 'a pending election must not become an election result' in text
    assert 'never transfer its names, numbers or events' in text
    assert 'not the candidates or review notes' in text


def test_revision_two_prompt_and_budget_binding_are_stable():
    assert sha256(EDITORIAL_INSTRUCTION.encode()).hexdigest()=='79bf638acc0759f4f19c6ccac1a1cfcbaf8f576d92a6eeeb8a0a1d70b8f3fa2b'
    s=source();p=plan(s,content(s));p['editorial_revision']=2
    data={'plan':content(s),'rank':1}
    expected=EDITORIAL_INSTRUCTION+json.dumps({
        'rank':1,'news_reference':p['news_reference'],
        'copy_mode':'rewrite_from_facts','accent':'#ffb45c',
    },ensure_ascii=False,sort_keys=True)
    assert request_prompt(data,p)==expected
    assert HEADLINE_INSTRUCTION not in expected


def test_manual_title_is_not_rewritten_even_if_same_as_article_title():
    s=source();p=plan(s,content(s))
    p.update(copy_mode='exact_user_copy',headline=s['title'],key_fact='검토 중')
    text=request_prompt({'plan':content(s)},p)
    assert HEADLINE_INSTRUCTION not in text
    assert json.loads(text[text.index('{'):])['requested_copy']=={
        'title':s['title'],'description':'검토 중'}


def test_generation_and_explicit_regenerate_use_one_call_preserve_history(budget_setup):
    b=budget_setup;settings(b);complete(b)
    for _ in range(3):assert step(b).status_code==200
    assert len(b.calls)==3
    assert all(HEADLINE_INSTRUCTION in c['prompt'] for c in b.calls)
    s=b.service;row=s.get(b.id)
    # A persisted revision-2 item must remain unchanged until explicit regenerate.
    result=deepcopy(row.result)
    result['items'][0]['creative_plan']['editorial_revision']=2
    s._save(b.id,result)
    row=s.get(b.id);old=deepcopy(row.result['items'][0]);others=deepcopy(row.result['items'][1:])
    file=s.path(b.id,1);digest=sha256(file.read_bytes()).hexdigest()
    prior_binding=binding(row)
    s.view(b.id)
    assert len(b.calls)==3 and s.get(b.id).result['items'][0]==old
    response=b.post('change',{'revision':row.result['revision'],'action':'regenerate',
                              'rank':1,'consent':'true','reviewed':'true'})
    assert response.status_code==200,response.text
    fresh=s.get(b.id)
    assert binding(fresh)!=prior_binding
    assert len(b.calls)==3
    assert fresh.result['items'][0]['creative_plan']['editorial_revision']==3
    assert fresh.result['items'][0]['history'][-1]['creative_plan']['editorial_revision']==2
    assert step(b).status_code==200
    assert len(b.calls)==4 and HEADLINE_INSTRUCTION in b.calls[-1]['prompt']
    assert s.get(b.id).result['items'][1:]==others
    assert sha256(file.read_bytes()).hexdigest()==digest
    assert step(b).status_code==200 and len(b.calls)==4
