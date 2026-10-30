"""Stored source previews only; isolated Fake transport and no external requests."""
from io import BytesIO
import os
from pathlib import Path
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from playwright.sync_api import expect
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser

from bat_distribution.operation import OperatingRequests
from bat_distribution.restored_install import RestoredRequests
from newsflow.db.models import NewsArticle, NewsSource, ArticleThumbnail
from newsflow.news.rss_adapter import FeedError


CAPTURE_DIR=Path(os.environ['NEWSFLOW_NEWS_CAPTURE_DIR']) if os.environ.get('NEWSFLOW_NEWS_CAPTURE_DIR') else None


def seed(app, fake):
    with app.state.sessions.begin() as session:
        source=NewsSource(name='합성 뉴스 출처',url='https://source.example.org/feed',enabled=False)
        session.add(source);session.flush()
        ids={}
        for name in ('no-image','supplied','unavailable'):
            article=NewsArticle(title='합성 기사 '+name,url='https://source.example.org/'+name,
                canonical_url='https://source.example.org/'+name,source_id=source.id,
                publisher='합성 출처 '+name,summary='합성 보관 기사',category='IT·과학')
            session.add(article);session.flush();ids[name]=article.id
            if name!='no-image':
                session.add(ArticleThumbnail(article_id=article.id,
                    url='https://images.example.org/'+name+'.png',
                    source_article_url=article.url,publisher=article.publisher))
    data=BytesIO();Image.new('RGB',(480,270),'#165975').save(data,format='PNG')
    fake.feeds['https://images.example.org/supplied.png']=data.getvalue()
    fake.feeds['https://images.example.org/unavailable.png']=FeedError('synthetic source unavailable')
    return ids


def test_news_model_requests_only_stored_source_previews_without_fetch(app,fake):
    ids=seed(app,fake)
    with TestClient(OperatingRequests(app),base_url='http://127.0.0.1') as client:
        result=client.get('/api/studio/modules/news')
        assert result.status_code==200
        rows={r['id']:r for r in result.json()['collections']['articles']}
        assert rows[ids['no-image']]['thumbnailUrl'] is None
        for name in ('supplied','unavailable'):
            assert rows[ids[name]]['thumbnailUrl']==f'/news/{ids[name]}/thumbnail'
        assert 'images.example.org' not in result.text
        assert fake.calls==[]


def test_operating_source_preview_uses_existing_auth_raster_and_failure_cache(app,fake):
    ids=seed(app,fake)
    with TestClient(OperatingRequests(app),base_url='http://127.0.0.1') as client:
        url=f'/news/{ids["supplied"]}/thumbnail'
        # Passing the outer read gate still does not bypass the inner session checks.
        assert client.get(url).status_code==403
        assert fake.calls==[]
        client.get('/studio/news')
        assert client.get(url,headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
        assert client.get(url,headers={'Origin':'https://foreign.invalid'}).status_code==403
        assert fake.calls==[]
        response=client.get(url)
        assert response.status_code==200 and response.headers['content-type']=='image/jpeg'
        with Image.open(BytesIO(response.content)) as image:
            assert image.size==(320,180) and image.format=='JPEG'
        assert client.get(url).status_code==200
        assert client.get(f'/news/{ids["no-image"]}/thumbnail').status_code==404
        for _ in range(2):
            assert client.get(f'/news/{ids["unavailable"]}/thumbnail').status_code==404
        assert fake.calls==['https://images.example.org/supplied.png',
                            'https://images.example.org/unavailable.png']


@pytest.mark.parametrize('method,path',[
    ('POST','/news/1/thumbnail'),('HEAD','/news/1/thumbnail'),
    ('GET','/news/0/thumbnail'),('GET','/news/-1/thumbnail'),
    ('GET','/news/01/thumbnail'),('GET','/news/a/thumbnail'),
    ('GET','/news/1/thumbnail/'),('GET','/news/1/thumbnail.jpg'),
    ('GET','/news/https:external/thumbnail'),('POST','/collection'),
    ('POST','/publish/1'),('GET','/oauth/callback'),
])
def test_source_preview_delta_does_not_open_other_paths(method,path):
    calls=[]
    async def inner(scope,receive,send):
        calls.append(scope)
        await send({'type':'http.response.start','status':204,'headers':[]})
        await send({'type':'http.response.body','body':b''})
    client=TestClient(OperatingRequests(inner),base_url='http://127.0.0.1')
    try:
        assert client.request(method,path).status_code==403
    finally:
        client.close()
    assert calls==[]


def test_validation_mode_keeps_external_source_preview_blocked():
    async def inner(scope,receive,send):
        raise AssertionError('validation must not reach source preview')
    client=TestClient(RestoredRequests(inner),base_url='http://127.0.0.1')
    try:
        assert client.get('/news/1/thumbnail').status_code==403
    finally:
        client.close()


def test_news_gui_distinguishes_absent_and_unavailable_source_images(app,fake,browser,tmp_path):
    ids=seed(app,fake)
    with local_server(OperatingRequests(app)) as origin:
        context=browser.new_context(viewport={'width':1366,'height':768})
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page=context.new_page();requests=[];errors=[]
        page.on('request',lambda request:requests.append(request.url))
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(origin+'/studio/news')
        cards=page.locator('.core-news-list > button')
        expect(cards).to_have_count(3)
        absent=cards.filter(has=page.get_by_text('합성 기사 no-image',exact=True))
        available=cards.filter(has=page.get_by_text('합성 기사 supplied',exact=True))
        unavailable=cards.filter(has=page.get_by_text('합성 기사 unavailable',exact=True))
        expect(absent.locator('.core-news-source-fallback')).to_contain_text('출처 이미지 없음')
        expect(unavailable.locator('.core-news-source-fallback')).to_contain_text('이미지를 불러오지 못했습니다')
        expect(available.locator('.core-news-article-image img')).to_be_visible()
        assert available.locator('img').evaluate('(e)=>e.complete && e.naturalWidth>0')
        assert not any(url.endswith(f'/news/{ids["no-image"]}/thumbnail') for url in requests)
        captures=CAPTURE_DIR or tmp_path
        captures.mkdir(parents=True,exist_ok=True)
        for width,height in [(1920,1080),(1366,768)]:
            page.set_viewport_size({'width':width,'height':height})
            unavailable.click()
            expect(page.locator('.core-article-head .core-news-source-fallback')).to_contain_text('이미지를 불러오지 못했습니다')
            available.click()
            expect(page.locator('.core-article-head img')).to_be_visible()
            absent.click()
            expect(page.locator('.core-article-head .core-news-source-fallback')).to_contain_text('출처 이미지 없음')
            assert page.locator('.core-news-list .lucide-film').count()==0
            assert page.get_by_text('미리보기 없음',exact=True).count()==0
            page.screenshot(path=str(captures/f'news-source-preview-{width}x{height}.png'))
        assert errors==[]
        assert fake.calls.count('https://images.example.org/supplied.png')==1
        assert fake.calls.count('https://images.example.org/unavailable.png')==1
        context.close()
