"""Initial synthetic records only. Never opens an operating database or provider."""
from pathlib import Path
import json
from uuid import uuid4

def populate(app):
    from newsflow.db.models import NewsSource, NewsArticle, IntelligenceRun, ContentDraft
    with app.state.sessions.begin() as db:
        source=NewsSource(name='합성 테스트 출처',url='https://example.invalid/rss',enabled=False)
        db.add(source);db.flush();articles=[]
        for n,title in enumerate(['합성 도서관 운영 안내','합성 버스 노선 안내','합성 과학 전시 안내'],1):
            url=f'https://example.invalid/news/{n}'
            a=NewsArticle(title=title,summary=f'합성 요약 {n}번입니다. 실제 사건이 아닙니다.',publisher='테스트 출처',url=url,canonical_url=url,source_id=source.id)
            db.add(a);db.flush();articles.append(a)
        evidence={'curation_contract':{'top_k':3},'articles':[{'id':a.id,'title':a.title,'summary':a.summary,'url':a.url,'publisher':a.publisher} for a in articles]}
        analysis=IntelligenceRun(kind='analysis',status='success',provider='claude_api',options={},evidence=evidence,result={'ranking':[{'rank':n,'title':a.title,'summary':a.summary,'article_ids':[a.id]} for n,a in enumerate(articles,1)]},message='synthetic fixture; no API call')
        db.add(analysis);db.flush()
        script=IntelligenceRun(kind='script',status='success',provider='claude_api',options={'analysis_run_id':analysis.id,'selected_article_ids':[articles[0].id]},evidence={},result={},message='synthetic fixture; no API call')
        db.add(script);db.flush()
        draft=ContentDraft(run_id=script.id,duration=30,content={'title':'합성 통합 대본','hook':'합성 자료 안내','summary':'실제 사건이 아닌 검증용 자료입니다.','closing':'출처를 검토하세요.','scenes':[{'seconds':10,'narration':f'합성 장면 {i}입니다.','caption':f'합성 장면 {i}','material':'기본 카드'} for i in range(1,4)]},sources={'articles':[evidence['articles'][0]]},revision=1,review_status='review_required',review_notes=[])
        db.add(draft);db.flush()
        facts={'analysis_id':analysis.id,'draft_id':draft.id,'article_ids':[a.id for a in articles]}
    # Real local saved history, no generation/approval/POST/vendor request.
    from newsflow.creation.catalog import DEFAULTS
    batch_id=app.state.top_three_feeds.create(facts['analysis_id'],DEFAULTS['image'])
    batch=app.state.top_three_feeds.view(batch_id)
    facts['feed_batch_id']=batch_id
    facts['feed_batch_snapshot']={'id':batch['id'],'status':batch['status'],'revision':batch['revision'],'items':[(i['rank'],i['status']) for i in batch['items']]}
    # Saved storyboard fixture, not a successful generated/paid project.
    from newsflow.character.schema import load_character, Storyboard, prompts, Character
    from newsflow.character.higgsfield_client import MODEL
    from newsflow.character.service import now
    service=app.state.character;identifier=uuid4().hex
    folder=service.folder(identifier);folder.mkdir(parents=True)
    samples=Path(__file__).resolve().parents[2]/'src/newsflow/assets/samples'
    reference=(samples/'characters/CHAR_S01_robot.png').read_bytes()
    (folder/'reference.png').write_bytes(reference)
    import hashlib
    story=Storyboard.model_validate({'title':'합성 GUI 스토리','plan':{'situation':'합성 사무실','contrast':'바쁨과 여유','punchline':'조용한 결말'},'hook_caption':'합성 시작','end_caption':'합성 끝','scenes':[{'seconds':10,'caption':f'합성 {i}','action':f'The character walks through synthetic room {i}.','role':['setup','build','punchline'][i-1],'sfx':''} for i in range(1,4)]})
    job={'id':identifier,'created_at':now().isoformat(),'state':'submission_unknown','topic':'검증용 로봇 이야기','model':MODEL,'claude_model':'claude-sonnet-4-6','character':load_character().model_dump(),'script':story.model_dump(),'reference_sha256':hashlib.sha256(reference).hexdigest(),'episode_limit':'1','day_limit':'3','events':[],'scenes':[{'position':i,'state':v} for i,v in enumerate(['downloaded','failed','unknown'],1)],'reported_billed_usd':None,'duration':30,'made_for_kids':False}
    job['prompts']=prompts(story,Character.model_validate(job['character']));job['plan_hash']=service.plan_hash(job)
    service.save(job);facts['character_id']=identifier
    app.state.studio_synthetic=True
    return facts
