"""New core-studio integration coverage in the unchanged approved Windows fixture.

Uses real application routes/SQLite/files, synthetic inputs and injected Fake adapters.
Not a local desktop/browser/DPI certification. No full-app fixture or Guard changes.
"""
from copy import deepcopy
from io import BytesIO
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from PIL import Image
from test_full_app_forms import client as client, token
from test_top3_feed_integration import seed


def view(c, module):
    r=c.get('/api/studio/modules/'+module)
    assert r.status_code==200,r.text
    return r.json()


def script_sources(app, aid):
    from sqlalchemy import select
    from newsflow.db.models import ContentDraft, IntelligenceRun
    with app.state.sessions.begin() as s:
        analysis=s.get(IntelligenceRun,aid)
        identifiers=[x['article_ids'][0] for x in analysis.result['ranking']]
        draft=s.scalar(select(ContentDraft).join(IntelligenceRun, ContentDraft.run_id==IntelligenceRun.id).where(IntelligenceRun.options['analysis_run_id'].as_integer()==aid))
        content={'title':'합성 통합 대본','hook':'합성 자료의 변화를 살펴봅니다.','summary':'실제 사건을 주장하지 않는 합성 자료입니다.','closing':'출처 검토 후 제작합니다.','scenes':[{'seconds':10,'narration':f'합성 장면 {i}입니다.','caption':f'합성 장면 {i}','material':'기본 카드'} for i in range(1,4)]}
        draft.content=content;draft.revision=1;draft.review_status='review_required'
        return draft.id,identifiers,deepcopy(content)


def test_five_react_shells_and_assets_are_served_by_real_python_app(client):
    c,app=client
    assets=set()
    for path in ['/studio/shorts','/studio/characters','/studio/images','/studio/images?mode=top3','/studio/news']:
        r=c.get(path);assert r.status_code==200 and '<div id="root">' in r.text
        csp=r.headers['content-security-policy'];assert 'unsafe-inline' not in csp and 'unsafe-eval' not in csp
        assets.update(re.findall(r'(?:src|href)="(/studio/assets/[^"<>]+\.(?:js|css))"',r.text))
    assert any(x.endswith('.js') for x in assets) and any(x.endswith('.css') for x in assets)
    for path in assets:
        response=c.get(path);assert response.status_code==200 and len(response.content)>100
    assert all(view(c,m)['schemaVersion']==1 for m in ['shorts','characters','images','news'])
    print('WINDOWS_INTEGRATION: real Python served 5 shells, JS/CSS and module JSON; React execution NOT VERIFIED')


def test_saved_top3_analysis_to_script_edit_revision_and_reopen(client):
    c,app=client;aid=seed(app);did,ids,content=script_sources(app,aid);csrf=token(c)
    read=c.get('/api/studio/production-context').json()
    assert read['selection']['id']==aid and [x['rank'] for x in read['top3']]==[1,2,3]
    assert [x['articleId'] for x in read['top3']]==ids
    assert all(x['references'] and x['references'][0]['publisher']=='테스트 출처' for x in read['top3'])
    assert read['top3'][0]['draftId']==did and read['top3'][0]['draftRevision']==1
    assert set(ids).issubset({a['id'] for a in view(c,'news')['collections']['articles']})
    draft=next(x for x in view(c,'shorts')['collections']['drafts'] if x['id']==did)
    assert draft['sources']['articles'][0]['id']==ids[0]
    changed={**content,'title':'합성 통합 저장 후 재열기'}
    saved=c.post(f'/ai/drafts/{did}',data={'csrf_token':csrf,'revision':1,'content':json.dumps(changed,ensure_ascii=False)})
    assert saved.status_code==303,saved.text
    reopened=next(x for x in view(c,'shorts')['collections']['drafts'] if x['id']==did)
    assert reopened['revision']==2 and reopened['content']==changed and reopened['review_status']!='approved'
    assert c.get('/api/studio/production-context').json()['top3'][0]['draftRevision']==2
    conflict=c.post(f'/ai/drafts/{did}',data={'csrf_token':csrf,'revision':1,'content':json.dumps(content)})
    assert conflict.status_code==409 and next(x for x in view(c,'shorts')['collections']['drafts'] if x['id']==did)['content']==changed
    from sqlalchemy import select,func
    from newsflow.db.models import IntelligenceRun
    with app.state.sessions() as s:assert s.scalar(select(func.count()).select_from(IntelligenceRun).where(IntelligenceRun.kind=='analysis'))==1


def test_unapproved_paid_and_cross_origin_commands_cannot_dispatch(client):
    c,app=client;aid=seed(app);did,_ids,content=script_sources(app,aid);csrf=token(c)
    from sqlalchemy import select,func
    from newsflow.db.models import IntelligenceRun,RenderJob
    def counts():
        with app.state.sessions() as s:return (s.scalar(select(func.count()).select_from(IntelligenceRun)),s.scalar(select(func.count()).select_from(RenderJob)))
    before=counts()
    assert c.post('/news/curation/generate',data={'csrf_token':csrf,'analysis_id':aid,'rank':1,'duration':30}).status_code==422
    assert c.post('/video/render',data={'csrf_token':csrf,'draft_id':did,'duration':30,'voice':'offline-silence'}).status_code==422
    payload={'revision':1,'content':json.dumps(content)}
    assert c.post(f'/ai/drafts/{did}',data=payload).status_code==403
    assert c.post(f'/ai/drafts/{did}',data={**payload,'csrf_token':csrf},headers={'Origin':'https://outside.invalid'}).status_code==403
    assert c.get('/api/studio/production-context',headers={'Host':'outside.invalid'}).status_code in {400,403}
    assert before==counts() and not app.state.image_generation.adapter.calls


def test_character_png_story_scene_contract_and_unknown_preservation(client):
    c,app=client;csrf=token(c);raw=BytesIO();Image.new('RGB',(128,128),'navy').save(raw,'PNG');original=raw.getvalue()
    defaults=view(c,'characters')['catalog']['characterDefaults']
    saved=c.post('/character',data={'csrf_token':csrf,'topic':'합성 캐릭터 통합 주제','episode_limit':'5','day_limit':'20','script_model':defaults['script_model'],'video_model':defaults['video_model']},files={'reference':('synthetic.png',original,'image/png')})
    assert saved.status_code==303,saved.text
    row=view(c,'characters')['collections']['jobs'][0];identifier=row['id']
    assert row['topic']=='합성 캐릭터 통합 주제' and row['selection']['script_model']==defaults['script_model']
    assert hashlib.sha256(c.get(row['referenceUrl']).content).digest()==hashlib.sha256(original).digest()
    from newsflow.character.schema import Character,Storyboard,prompts
    service=app.state.character;job=service.read(identifier)
    story=Storyboard.model_validate({'title':'합성 스토리','plan':{'situation':'합성 사무실','contrast':'바쁨과 여유','punchline':'조용한 결말'},'hook_caption':'합성 시작','end_caption':'합성 끝','scenes':[{'seconds':10,'caption':f'합성 {i}','action':f'합성 동작 {i}','role':['setup','build','punchline'][i-1],'sfx':''} for i in range(1,4)]})
    job.update(state='submission_unknown',script=story.model_dump(),scenes=[{'position':i,'state':state} for i,state in enumerate(['downloaded','failed','unknown'],1)])
    job['prompts']=prompts(story,Character.model_validate(job['character']));job['plan_hash']=service.plan_hash(job);service.save(job)
    before=deepcopy(service.read(identifier));reopened=next(x for x in view(c,'characters')['collections']['jobs'] if x['id']==identifier)
    assert reopened['story']['title']=='합성 스토리' and [x['state'] for x in reopened['scenes']]==['downloaded','failed','unknown']
    assert all('status' not in x for x in reopened['scenes']) and reopened['state']=='submission_unknown'
    assert service.read(identifier)==before
    assert c.get(reopened['referenceUrl']).content==original
    print('CHARACTER_API_CONTRACT:'+json.dumps({'scene_states':[x['state'] for x in reopened['scenes']],'scene_status_field_present':False,'real_Claude_Higgsfield_calls':0}))


def test_independent_image_settings_snapshot_fake_result_and_reuse(client):
    c,app=client;csrf=token(c)
    from newsflow.creation.catalog import DEFAULTS
    initial=deepcopy(DEFAULTS['image']);char_before=view(c,'characters')['catalog']['characterDefaults']
    saved=c.post('/image-studio/drafts',data={'csrf_token':csrf,'prompt':'합성 이미지 저장 재열기','provider':'openai',**initial})
    assert saved.status_code==303,saved.text
    identifier=view(c,'images')['collections']['drafts'][0]['id']
    assert c.post('/image-studio/defaults',data={'csrf_token':csrf,**initial,'quality':'high'}).status_code==303
    row=next(x for x in view(c,'images')['collections']['drafts'] if x['id']==identifier)
    assert row['selection']==initial and view(c,'images')['catalog']['imageDefaults']['quality']=='high'
    assert view(c,'characters')['catalog']['characterDefaults']==char_before
    class Fake:
        calls=0
        def generate(self,prompt,key,*,selection):
            assert key=='synthetic-only-image-key';self.calls+=1
            raw=BytesIO();Image.new('RGB',(1024,1024),'teal').save(raw,'JPEG')
            return raw.getvalue(),{'input_tokens':1,'output_tokens':1,'total_tokens':2}
    fake=Fake();app.state.image_generation.adapter=fake;app.state.image_generation.keys=NS(key=lambda:'synthetic-only-image-key',status=lambda:{'configured':True})
    for _ in range(2):assert c.post(f'/image-studio/{identifier}/generate',data={'csrf_token':csrf,'consent':'true','reviewed':'true'}).status_code==303
    reopened=next(x for x in view(c,'images')['collections']['drafts'] if x['id']==identifier)
    assert fake.calls==1 and reopened['status']=='success' and reopened['selection']==initial
    response=c.get(reopened['mediaUrl']);assert response.status_code==200
    with Image.open(BytesIO(response.content)) as image:assert image.size==(1024,1024)
    assert c.post(f'/image-studio/{identifier}/reuse',data={'csrf_token':csrf,'reviewed':'true','target':'news'}).status_code==303
    assert fake.calls==1


@pytest.mark.parametrize('uncertain',[False,True])
def test_top3_batch_partial_results_reopen_and_no_replay(client,uncertain):
    c,app=client;aid=seed(app);csrf=token(c)
    from newsflow.creation.catalog import DEFAULTS
    from newsflow.creation.top_three_feeds import TopThreeFeeds
    from newsflow.publishing.image_generation import ImageGenerationError
    original=app.state.image_generation.adapter.generate;calls=[]
    def fake(prompt,key,**kw):
        calls.append(prompt)
        if '"rank": 2' in prompt:raise ImageGenerationError('synthetic-failure',uncertain=uncertain)
        return original(prompt,key,**kw)
    app.state.image_generation.adapter.generate=fake
    created=c.post('/api/feed-batches',data={'csrf_token':csrf,'analysis_id':aid,**DEFAULTS['image']})
    assert created.status_code==200,created.text
    batch=created.json();identifier=batch['id']
    for _ in range(2 if uncertain else 3):
        response=c.post(f'/api/feed-batches/{identifier}/step',data={'csrf_token':csrf,'consent':'true','reviewed':'true'})
        assert response.status_code==200,response.text
    app.state.top_three_feeds=TopThreeFeeds(app.state.sessions,app.state.config.data_dir,app.state.image_generation,simulation=True)
    reopened=next(x for x in c.get('/api/feed-batches').json()['batches'] if x['id']==identifier)
    assert [x['status'] for x in reopened['items']]==(['success','unknown','pending'] if uncertain else ['success','failed','success'])
    first=c.get(reopened['items'][0]['mediaUrl']);assert first.status_code==200
    with Image.open(BytesIO(first.content)) as image:assert image.size==(1080,1350)
    count=len(calls)
    attempted=c.post(f'/api/feed-batches/{identifier}/step',data={'csrf_token':csrf,'consent':'true','reviewed':'true'})
    assert attempted.status_code==(422 if uncertain else 200)
    assert len(calls)==count and c.get(reopened['items'][0]['mediaUrl']).content==first.content
    assert c.post(f'/api/feed-batches/{identifier}/items/1/review',data={'csrf_token':csrf,'reviewed':'true','rights':'true','sources_confirmed':'true','ai_disclosure':'disclose'}).status_code==422
