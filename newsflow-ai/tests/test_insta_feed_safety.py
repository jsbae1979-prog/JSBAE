"""Synthetic data and Fake adapters only. No real credentials or provider/SNS I/O."""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace
import json
import re
import pytest
from newsflow.db.models import NewsArticle
from newsflow.publishing.sensitive_topics import classify, PROTECTION, MINIMAL_TEXT, claim_warnings, review_metadata
from newsflow.publishing.categories import news_hashtags
from newsflow.publishing.claude_cards import FULL_IMAGE_INSTRUCTION
from newsflow.publishing.image_generation import ImageGenerationService
from newsflow.publishing.preparation import validate_preparation
from newsflow.publishing.posting_copy import digest, INSTRUCTION
from newsflow.publishing.service import PublishingError
from newsflow.creation.top_three_feeds import prompt_for, content_for
from newsflow.creation.feed_costs import binding, fingerprint
from newsflow.creation.catalog import DEFAULTS
from test_full_image_pipeline import pipeline, plan, generate
from test_top_three_selection import feeds
from test_posting_copy import copy_service, VALUE

TITLE='호주 의원 헬렌 헤인스, 사무실 앞 고의 차량 공격에 중상'
BODY='경찰이 사건을 수사 중이다.'

@pytest.fixture(autouse=True)
def no_live(monkeypatch):
    def denied(*a,**kw): raise AssertionError('Real network is forbidden')
    monkeypatch.setattr('urllib.request.OpenerDirector.open',denied)
    monkeypatch.setattr('newsflow.publishing.instagram.MetaUploadTransport.request',denied)

@pytest.mark.parametrize('title,reason',[(TITLE,'violence'),(TITLE,'named_person'),
    ('MP Helen Haines car attack','named_person'),('폭우 사망자 수색','disaster'),
    ('아동 안전','children'),('성폭력 사건','sexual_crime'),('혐오 시위','protest_hate'),
    ('팔레스타인 분쟁','group_identity')])
def test_sensitive_rules(title,reason):
    result=classify(title,BODY)
    assert result['sensitive'] and reason in result['reasons']

def test_ordinary_economy_and_existing_prohibitions():
    assert classify('한국은행 기준금리 동결','금융통화위원회는 기준금리를 유지했다.')=={'sensitive':False,'reasons':[]}
    p=ImageGenerationService.prompt({'title':'기준금리 동결','summary':'합성 경제 뉴스'},'illustration')
    assert 'No human faces' not in p and 'Do not reconstruct a real incident' in p

def test_all_generation_paths_capture_protection_and_record_evidence(pipeline,app):
    cards,images,news=pipeline
    with app.state.sessions.begin() as s:
        a=s.get(NewsArticle,news);a.title=TITLE;a.summary=BODY
    background=images.generate(news,consent=True)
    assert PROTECTION in images.adapter.calls[-1]
    assert images.get(background).options['image_safety']['sensitive']
    cid=plan(cards,news);gid=generate(images,news,cid)
    assert PROTECTION in images.adapter.calls[-1] and MINIMAL_TEXT in images.adapter.calls[-1]
    assert images.get(gid).options['image_safety']['sensitive']
    captured=[]
    # Capture Codex's final submitted prompt at the provider boundary, no subprocess.
    images._generate=lambda *a,**kw: captured.append(a[5]) or 123
    images.generate_codex(news,title=TITLE,body=BODY,consent=True,reviewed=True)
    assert PROTECTION in captured[0] and MINIMAL_TEXT in captured[0]
    source={'rank':1,'title':TITLE,'body':BODY,'references':[]}
    p=prompt_for(source,content_for(source),1,1,local_title=True,safety_version=1)
    assert PROTECTION in p and MINIMAL_TEXT in p and 'No rank numbers' in p
    assert PROTECTION in FULL_IMAGE_INSTRUCTION and MINIMAL_TEXT in FULL_IMAGE_INSTRUCTION

def test_image_human_check_blocks_save_and_preserves_pixels(pipeline,app):
    cards,images,news=pipeline
    card=plan(cards,news);gid=generate(images,news,card);value=cards.get(card).result['plan']
    args=dict(title=value['title'],body=value['body'],generated_id=gid,reviewed=True,
        rights=True,sources_confirmed=True,ai_disclosure='disclose')
    before=sha256(images.path(gid).read_bytes()).hexdigest()
    for checked in (False,None,'true',1):
        with pytest.raises(PublishingError,match='AI 이미지 안전 확인'):
            app.state.image_posts.create(news,**args,image_safety_checked=checked)
    post=app.state.image_posts.create(news,**args,image_safety_checked=True)
    assert app.state.image_posts.get(post).sources['image_safety_checked'] is True
    assert sha256(images.path(gid).read_bytes()).hexdigest()==before

def test_attribution_warnings_compare_original_source_not_caption():
    copy='용의자가 친팔레스타인 활동가로 지목됐다.'
    warnings=claim_warnings(copy,BODY)
    assert len(warnings)==3 and not claim_warnings(copy,copy)
    source={'id':'post:1','kind':'image','content':{'title':TITLE,'description':copy,
        'sources':{'generated_image_run_id':1,'articles':[{'summary':BODY}]}}}
    assert review_metadata(source)['claimWarnings']==warnings
    assert 'Flag in notes any claim about motive' in INSTRUCTION

def test_claim_warning_does_not_block_local_save(copy_service):
    svc,ai,source=copy_service
    source.update(id='post:1',kind='image',content={'title':TITLE,'sources':{'articles':[{'summary':BODY}]}})
    result=svc.save(source['id'],digest(source),0,{**VALUE,'description':'친팔레스타인 활동가로 지목'})
    assert result['claimWarnings'] and not ai.calls
    assert svc.view(source['id'])['copy']['description']=='친팔레스타인 활동가로 지목'

@pytest.mark.parametrize('title,tag',[(TITLE,'#호주'),('한국은행 기준금리 동결','#경제'),('파리 문화 행사','#프랑스')])
def test_topic_hashtags(title,tag):
    tags=news_hashtags(title,BODY).split()
    assert 3<=len(tags)<=5 and len(set(tags))==len(tags) and tag in tags
    assert all(re.fullmatch(r'#[\w]{1,30}',t) for t in tags)
    assert content_for({'title':title,'body':BODY})['hashtags']!='#뉴스 #뉴스요약'

def test_preparation_requires_human_check_for_ai_but_not_local_non_ai():
    source={'id':'post:1','kind':'image','content':{'sources':{'full_image':True}}}
    value={'platforms':['instagram'],'content_reviewed':True,'rights_reviewed':True,'sources_reviewed':True}
    with pytest.raises(PublishingError,match='AI 이미지 안전 확인'):validate_preparation(source,value)
    assert validate_preparation(source,{**value,'image_safety_checked':True})['image_safety_checked']
    source['content']['sources']={}
    assert validate_preparation(source,value)['status']=='prepared'

def test_new_prompt_version_is_bound_but_legacy_binding_is_unchanged(feeds):
    i=feeds.create(42,DEFAULTS['image']);row=feeds.get(i)
    assert all(x['safety_version']==1 for x in row.result['items'])
    modern=binding(row)
    for item in row.result['items']: item.pop('safety_version')
    historical={'id':row.id,'source':row.options['source_hash'],'selection':row.options['selection'],
        'items':[{k:x[k] for k in ('rank','attempt','content')} for x in row.result['items']],
        'title_layout':row.options['title_layout']}
    assert binding(row)==fingerprint(historical) and binding(row)!=modern
    for local in (False,True):
        source={'rank':1,'title':TITLE,'body':BODY,'references':[]};content=content_for(source)
        legacy=prompt_for(source,content,1,1,local_title=local)
        assert PROTECTION not in legacy and MINIMAL_TEXT not in legacy
        assert 'Keep the exact' in legacy

def test_route_contracts_have_explicit_safety_checkbox():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    for filename in ('src/newsflow/studio/actions.json','frontend/src/legacy-actions.json'):
        actions=json.loads((root/filename).read_text(encoding='utf-8'))
        for path in ('/image-posts/create','/api/feed-batches/{identifier}/items/{rank}/review'):
            action=next(a for a in actions if a['path']==path)
            field=next(f for f in action['fields'] if f['name']=='image_safety_checked')
            assert field['type']=='boolean' and field['default'] is False


@pytest.mark.parametrize('local,expected',[(False,'261ab421e06b3f9d62d438dbabee91b01e6a5aa0e395c692f7f297b8f0536a10'),(True,'fb9dffacce87a24590de81d530a2b3b03edb1b1e10979e1cdf504d385593ec37')])
def test_exact_historical_prompt_hashes(local,expected):
    source={'rank':1,'title':TITLE,'body':BODY,'references':[]}
    content={'title':'한국어 제목','body':'요약','hashtags':'#뉴스 #뉴스요약'}
    assert sha256(prompt_for(source,content,1,1,local_title=local).encode()).hexdigest()==expected
