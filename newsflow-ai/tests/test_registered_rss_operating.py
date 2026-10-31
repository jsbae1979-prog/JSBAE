from types import SimpleNamespace
import pytest
from sqlalchemy import select
from starlette.testclient import TestClient
from bat_distribution.registered_rss import install,public_feed
from bat_distribution.operation import OperatingRequests
from bat_distribution.local_work import FIXTURE,FIXTURE_URL
from newsflow.news.collector import Collector
from newsflow.news.rss_adapter import FakeRSSAdapter
from newsflow.news.service import NewsService
from newsflow.db.models import NewsSource,CollectionRun,NewsArticle
from newsflow.distribution.local_access import LaunchSession,LocalAccess
from newsflow.gui.routes import collect
from test_api_settings import sessions
from test_character_automation_routes import gui

@pytest.mark.parametrize('url',[FIXTURE_URL,'https://feeds.bbci.co.uk/korean/rss.xml'])
def test_public_registered_feed_policy(url):assert public_feed(url)

@pytest.mark.parametrize('url',['https://api.anthropic.com/v1/messages','https://serpapi.com/search.json',
    'https://api.openai.com/v1/models','https://api.higgsfield.ai/requests','https://api.elevenlabs.io/v1/user',
    'http://127.0.0.1/feed','https://private.internal/feed','https://example.com/feed?api_key=secret'])
def test_private_and_provider_sources_not_treated_as_rss(url):assert not public_feed(url)

@pytest.fixture
def rss(gui,sessions):
    adapter=FakeRSSAdapter({FIXTURE_URL:FIXTURE})
    original=NewsService(sessions,Collector(adapter));calls=[]
    def start():
        calls.append(True)
        with sessions.begin() as db:
            run=CollectionRun();db.add(run);db.flush();identifier=run.id
        return gui.app.state.coordinator.service.collect(identifier)
    gui.app.state.coordinator=SimpleNamespace(service=original,start=start)
    gui.app.add_api_route('/collection',collect,methods=['POST'])
    boundary=install(gui.app)
    launch=LaunchSession(18779);auth=LocalAccess(gui.app,launch)
    wrapped=boundary.wrap(OperatingRequests(auth),auth)
    client=TestClient(wrapped,base_url=launch.origin,client=('127.0.0.1',43210),follow_redirects=False)
    client.cookies.set(launch.cookie_name,launch.claim(launch.launch_url().split('#')[1]))
    client.get('/api/studio/characters/profiles')
    with sessions.begin() as db:
        db.add_all([NewsSource(name='Feed',url=FIXTURE_URL,enabled=True),
          NewsSource(name='Off',url='https://example.com/off',enabled=False),
          NewsSource(name='AI',url='https://api.anthropic.com/v1/messages',enabled=True),
          NewsSource(name='SerpApi',url='https://serpapi.com/google-news-api',enabled=True),
          NewsSource(name='Private',url='http://127.0.0.1/feed',enabled=True)])
    return SimpleNamespace(client=client,launch=launch,adapter=adapter,calls=calls,sessions=sessions,app=gui.app)

def test_registered_rss_works_without_opening_other_provider_routes(rss):
    r=rss.client.post('/collection',data={'csrf_token':rss.client.cookies.get('newsflow_csrf'),
        'url':'https://api.openai.com/v1/models'},headers={'Origin':rss.launch.origin})
    assert r.status_code==303 and rss.adapter.calls==[FIXTURE_URL] and len(rss.calls)==1
    with rss.sessions() as db:assert len(db.scalars(select(NewsArticle)).all())==1
    assert rss.client.post('/news/curation/serpapi').status_code==403
    assert rss.client.post('/ai/analyze',data={'provider':'claude_api'}).status_code==403

@pytest.mark.parametrize('mode',['csrf','origin','session'])
def test_registered_rss_keeps_authentication_and_csrf(rss,mode):
    body={'csrf_token':rss.client.cookies.get('newsflow_csrf')};headers={'Origin':rss.launch.origin}
    if mode=='csrf':body['csrf_token']='bad'
    if mode=='origin':headers['Origin']='https://outside.invalid'
    if mode=='session':rss.client.cookies.clear()
    assert rss.client.post('/collection',data=body,headers=headers).status_code in {401,403}
    assert not rss.calls and not rss.adapter.calls
