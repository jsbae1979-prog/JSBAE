"""Stored news/analysis/script contract; memory-only DB, no provider/vault/process."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from newsflow.db.models import Base, NewsSource, NewsArticle, IntelligenceRun, ContentDraft, NewsListState, AppSetting
from newsflow.studio.core_context import production_context, public_reference

@pytest.fixture
def db():
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    with factory.begin() as s:
        source=NewsSource(name="Synthetic",url="https://example.invalid/rss",enabled=False);s.add(source);s.flush()
        articles=[]
        for n in range(1,4):
            a=NewsArticle(title=f"합성 기사 {n}",summary=f"합성 요약 {n}",publisher="합성 출처",url=f"https://example.invalid/{n}",canonical_url=f"https://example.invalid/{n}",source_id=source.id);s.add(a);s.flush();articles.append(a)
        now=datetime.now(timezone.utc)
        collection=IntelligenceRun(kind="trends",provider="google_trends",status="success",created_at=now-timedelta(minutes=1),options={},evidence={},result={},message="synthetic");s.add(collection)
        run=IntelligenceRun(kind="analysis",provider="claude_api",status="success",created_at=now,options={"model":"synthetic-model","secret":"NEVER-RETURN"},evidence={"curation_contract":{"top_k":3},"articles":[{"id":a.id,"url":a.url,"publisher":a.publisher} for a in articles]},result={"overview":"합성 분석", "ranking":[{"rank":i,"article_ids":[a.id],"title":a.title,"summary":a.summary,"reason":"합성 선정 근거"} for i,a in enumerate(articles,1)]},message="NEVER-RETURN");s.add(run);s.flush();analysis_id=run.id
        script=IntelligenceRun(kind="script",provider="claude_api",status="success",options={"analysis_run_id":run.id,"selected_article_ids":[articles[0].id]},evidence={},result={},message="synthetic");s.add(script);s.flush()
        s.add(ContentDraft(run_id=script.id,duration=30,content={"title":"저장 대본","scenes":[{"narration":"저장 대본 문장"}]},sources={"articles":[{"id":articles[0].id}]}))
        s.add(AppSetting(key="synthetic-secret",value="NEVER-RETURN"))
    yield factory,analysis_id
    engine.dispose()

def test_projection_reuses_rank_source_and_saved_script_without_writes(db):
    factory,aid=db
    with factory() as s:
        before=[(t.name,s.connection().exec_driver_sql(f'SELECT * FROM "{t.name}"').fetchall()) for t in Base.metadata.sorted_tables]
        value=production_context(s)
        after=[(t.name,s.connection().exec_driver_sql(f'SELECT * FROM "{t.name}"').fetchall()) for t in Base.metadata.sorted_tables]
        assert before==after
        assert value['selection']['id']==aid and not value['selection']['stale']
        assert [x['rank'] for x in value['top3']]==[1,2,3]
        assert value['top3'][0]['draftId'] and value['top3'][0]['body']=='저장 대본 문장'
        assert value['top3'][1]['draftId'] is None and value['top3'][1]['body']=='합성 요약 2'
        assert value['top3'][0]['summary']=='합성 요약 1'
        assert 'NEVER-RETURN' not in json.dumps(value)
        assert all(x['thumbnailUrl']==f"/news/{x['articleId']}/thumbnail" for x in value['top3'])

@pytest.mark.parametrize('mutation',['missing','unknown','hidden','duplicate','malformed','bad_source'])
def test_invalid_selection_never_invents_or_reanalyzes(db,mutation):
    factory,aid=db
    with factory.begin() as s:
        row=s.get(IntelligenceRun,aid)
        if mutation=='missing':s.delete(row)
        if mutation=='unknown':row.status='unknown'
        if mutation=='hidden':s.add(NewsListState(article_id=1,hidden=True,used=False))
        if mutation=='duplicate':
            result=deepcopy(row.result);result['ranking'][1]['article_ids']=[1];row.result=result
        if mutation=='malformed':row.result={'ranking':[None]}
        if mutation=='bad_source':
            ev=deepcopy(row.evidence);ev['articles'][0]['url']='file:///private';row.evidence=ev
    with factory() as s:
        value=production_context(s)
        assert not value['top3'] and value['selection'] is None and value['blockedReason']

def test_new_collection_is_explicitly_stale_and_does_not_replace_analysis(db):
    factory,aid=db
    with factory.begin() as s:
        s.add(IntelligenceRun(kind='trends',provider='google_trends',status='success',created_at=datetime.now(timezone.utc)+timedelta(minutes=1),options={},evidence={},result={},message='synthetic'))
    with factory() as s:
        value=production_context(s)
        assert value['selection']['id']==aid and value['selection']['stale'] and len(value['top3'])==3 and value['blockedReason']

@pytest.mark.parametrize('url',['file:///private','https://user:pass@example.invalid/','http://localhost/a','http://127.0.0.1/a','http://[::1]/','https://example.invalid:8765/a','http://169.254.169.254/a'])
def test_reference_projection_rejects_private_and_credential_urls(url):
    assert public_reference({'url':url}) is None
