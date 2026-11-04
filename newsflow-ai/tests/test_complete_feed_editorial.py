"""Frozen factual prompts and local photo editing; no network/production data."""
from copy import deepcopy
import json
from hashlib import sha256
from PIL import Image, ImageChops
from newsflow.creation.complete_feed import INSTRUCTION, STYLE, plan, request_prompt
from newsflow.creation.feed_designs import FeedDesigns
from newsflow.creation.catalog import DEFAULTS
from newsflow.creation.top_three_feeds import prompt_for
from newsflow.publishing.sensitive_topics import protect
from test_top_three_selection import feeds
from test_photo_feed_editor import photo


def source(name='가상 연구소', rank=1):
    return {'rank':rank,'title':f'{name}, 새 관측 장비 공개 예정',
            'body':f'{name}는 2026년 11월 3일 20km 구간 관측 계획을 발표했다. 시행 여부는 검토 중이다.',
            'references':[{'publisher':'합성 과학지','url':'https://example.com/science'}]}


def content(s):
    return {'title':s['title'],'body':s['body'],'hashtags':'#합성'}


def test_new_copy_uses_frozen_full_facts_not_extracted_render_copy():
    s=source(); original=deepcopy(s); c=content(s); p=plan(s,c)
    assert p['editorial_revision']==3 and p['copy_mode']=='rewrite_from_facts'
    data={'plan':c,'rank':1,'references':s['references']}
    prompt=request_prompt(data,p)
    payload=json.loads(prompt[prompt.index('{'):])
    assert payload['news_reference']['summary']==original['body']
    assert 'plan' not in payload and 'requested_copy' not in payload
    assert 'ORIGINAL concise Korean headline' in prompt
    assert 'No invented statistics, percentages' in prompt
    assert 'SAME supported value, unit, subject and context' in prompt
    assert 'Rewording or attribution alone does not establish permission' in prompt
    assert 'Do not copy article sentences' in prompt and '확인 필요' in prompt
    assert s==original
    s['references'][0]['publisher']='다른 출처'
    assert p['news_reference']['references'][0]['publisher']=='합성 과학지'


def test_two_news_plans_do_not_mix_people_or_facts():
    a,b=source('가상 관측소 A',1),source('가상 관측소 B',2)
    pa,pb=plan(a,content(a)),plan(b,content(b))
    for s,p,other in [(a,pa,'가상 관측소 B'),(b,pb,'가상 관측소 A')]:
        text=prompt_for(s,content(s),5,1,feed_style=STYLE,creative_plan=p)
        assert s['body'] in text and other not in text


def test_real_person_news_does_not_request_generated_lookalike():
    s=source('가상 배우 한서연');c=content(s)
    text=prompt_for(s,c,5,1,feed_style=STYLE,creative_plan=plan(s,c))
    assert 'Do not invent or approximate the likeness of a named real person' in text
    assert 'NOT a request for a generated portrait' in text
    assert 'Rights-cleared real photos belong to the separate local photo editor' in text


def test_legacy_prompt_is_byte_for_byte_unchanged():
    s=source();c=content(s);p=plan(s,c)
    for k in ('editorial_revision','copy_mode','news_reference'):p.pop(k)
    data={'batch_id':5,'rank':1,'attempt':2,'plan':c,'references':s['references']}
    expected=protect(INSTRUCTION+json.dumps({**data,'creative_plan':p},ensure_ascii=False,sort_keys=True),{'source':s,'plan':c})
    assert prompt_for(s,c,5,2,feed_style=STYLE,creative_plan=p)==expected


def test_user_edited_copy_is_exact_and_does_not_replace_source():
    s=source();p=plan(s,content(s))
    p.update(copy_mode='exact_user_copy',headline='관측 계획\n검토 중',key_fact='2026년 계획 발표')
    text=request_prompt({'plan':content(s)},p)
    data=json.loads(text[text.index('{'):])
    assert data['requested_copy']=={'title':'관측 계획\n검토 중','description':'2026년 계획 발표'}
    assert data['news_reference']['summary']==s['body']
    assert 'render requested_copy exactly, including line breaks' in text


def test_complete_feed_can_use_local_photo_without_ai_or_changing_other_results(feeds):
    batch=feeds.create(42,DEFAULTS['image'],feed_style=STYLE)
    before=deepcopy(feeds.get(batch).result)
    def forbidden(*a,**k):raise AssertionError('Local photo edit must not call a provider')
    feeds.generation._generate=forbidden
    svc=FeedDesigns(feeds);raw=photo();digest=sha256(raw).hexdigest()
    state=svc.upload(batch,1,0,raw,'photo','직접 제작한 테스트 이미지')
    d={**state['draft'],'title':'관측 계획 검토 중','description':'2026년 관측 예정',
       'caption':'사용자가 작성한 별도 게시 문구'}
    preview=svc.preview(batch,1,state['revision'],state['background'],d)
    saved=svc.save(batch,1,state['revision'],state['background'],d,export=True)
    v=saved['versions'][0]
    assert svc.path(v['filename'],v['sha256']).read_bytes()==preview
    from io import BytesIO
    original=Image.open(BytesIO(raw)).convert('RGB')
    frozen=Image.open(svc.path(v['background']['filename'],v['background']['sha256'])).convert('RGB')
    assert ImageChops.difference(original,frozen).getbbox() is None
    assert sha256(raw).hexdigest()==digest
    assert v['background']['kind']=='photo' and v['background']['credit']=='직접 제작한 테스트 이미지'
    assert saved['draft']['caption']=='사용자가 작성한 별도 게시 문구'
    assert feeds.get(batch).result==before
    assert svc.view(batch,2)['versions']==svc.view(batch,3)['versions']==[]
