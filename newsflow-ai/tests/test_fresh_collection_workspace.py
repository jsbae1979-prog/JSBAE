from concurrent.futures import Future
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from newsflow.db.models import NewsArticle, NewsSource, CollectionRun, NewsListState
from newsflow.news.collector import CollectedArticle
from newsflow.news.service import NewsService, CollectionCoordinator
from newsflow.news.lifecycle import visible_news
from newsflow.news.collection_workspace import begin_collection,reveal_current
from test_workspace_cleanup import articles

def visible(app):
    with app.state.sessions() as db:return set(db.scalars(select(NewsArticle.id).where(visible_news())))

def new_run(app):
    with app.state.sessions.begin() as db:
        db.get(NewsSource,1).enabled=True
        run=CollectionRun();db.add(run);db.flush();return run.id

def test_begin_clears_only_workspace_before_any_external_request(app):
    ids=articles(app)
    with app.state.sessions.begin() as db:
        db.add(NewsListState(article_id=ids[0],hidden=False,used=True))
    class Collector:
        def collect(self,*args):
            assert visible(app)==set()
            with app.state.sessions() as db:assert all(db.get(NewsArticle,i) is not None for i in ids)
            return [CollectedArticle('Fresh unique example','https://example.com/new-round','Fixture','New',None)]
    result=NewsService(app.state.sessions,Collector()).collect(new_run(app))
    assert visible(app)==set(result['article_ids'])
    with app.state.sessions() as db:
        assert db.get(NewsArticle,ids[0]) is not None and db.get(NewsListState,ids[0]).used

@pytest.mark.parametrize('outcome',['failed','empty'])
def test_failed_or_empty_new_round_never_redisplays_old_news_but_retains_originals(app,outcome):
    ids=articles(app)
    class Collector:
        def collect(self,*args):
            assert not visible(app)
            if outcome=='failed':raise RuntimeError('synthetic feed failure')
            return []
    NewsService(app.state.sessions,Collector()).collect(new_run(app))
    assert not visible(app)
    with app.state.sessions() as db:assert all(db.get(NewsArticle,i) is not None for i in ids)

def test_partial_round_shows_only_fresh_ids_and_keeps_previous_raw_records(app):
    ids=articles(app)
    with app.state.sessions.begin() as db:db.add(NewsSource(name='Failed source',url='https://example.org/feed',enabled=True))
    class Collector:
        def collect(self,url,*args):
            if url=='https://example.org/feed':raise RuntimeError('synthetic')
            return [CollectedArticle('Fresh distinct source item','https://example.com/partial-new','Fixture','New',None)]
    run_id=new_run(app);result=NewsService(app.state.sessions,Collector()).collect(run_id)
    assert result['failed']==1 and result['succeeded']==1 and visible(app)==set(result['article_ids'])
    with app.state.sessions() as db:
        assert db.get(CollectionRun,run_id).status=='partial'
        assert all(db.get(NewsArticle,i) is not None for i in ids)

def test_receiving_an_existing_article_again_reveals_it_without_losing_used_flag(app):
    ids=articles(app)
    with app.state.sessions.begin() as db:
        db.add(NewsListState(article_id=ids[0],used=True,hidden=False))
    with app.state.sessions.begin() as db:begin_collection(db)
    assert not visible(app)
    with app.state.sessions.begin() as db:reveal_current(db,[ids[0],ids[0]])
    assert visible(app)=={ids[0]}
    with app.state.sessions() as db:
        assert db.get(NewsListState,ids[0]).used and all(db.get(NewsArticle,i) is not None for i in ids)

def test_coordinator_clears_previous_workspace_before_returning_accepted(app,monkeypatch):
    ids=articles(app);coordinator=app.state.coordinator;queued=[]
    def queue(*args):queued.append(args);return Future()
    monkeypatch.setattr(coordinator.executor,'submit',queue)
    try:
        identifier=coordinator.start()
        assert identifier and queued and not visible(app)
        with app.state.sessions() as db:assert all(db.get(NewsArticle,i) is not None for i in ids)
    finally:
        if queued:queued[0][2].release()

def test_first_round_reset_keeps_newly_remembered_video_reference_without_duplicate_state(app):
    from test_workspace_cleanup import video_fixture
    from newsflow.db.models import VideoProject
    ids=articles(app);fixture=video_fixture(app,'Saved source reference')
    with app.state.sessions.begin() as db:
        db.get(VideoProject,fixture['project_id']).sources={'articles':[{'id':ids[0]}]}
    with app.state.sessions.begin() as db:begin_collection(db)
    assert not visible(app)
    with app.state.sessions() as db:
        assert db.get(NewsListState,ids[0]).used
        assert all(db.get(NewsArticle,i) is not None for i in ids)
