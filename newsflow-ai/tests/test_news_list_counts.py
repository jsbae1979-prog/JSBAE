"""Synthetic news lists: no collection, API request, or operating data."""
from playwright.sync_api import expect
from sqlalchemy import select, func
from newsflow.db.models import NewsArticle, NewsSource, NewsListState
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_news_collection_controls_browser import browser_context

def seed(app):
    with app.state.sessions.begin() as s:
        src=NewsSource(name="Synthetic",url="https://example.invalid/feed",enabled=False)
        s.add(src);s.flush()
        ids=[]
        for i in range(151):
            url=f"https://example.invalid/news/{i}"
            row=NewsArticle(title=f"합성 기사 {i:03d}",url=url,canonical_url=url,
                source_id=src.id,publisher="합성",category="문화" if i<60 else "스포츠")
            s.add(row);s.flush();ids.append(row.id)
        s.add(NewsListState(article_id=ids[-1],hidden=True))
    return ids

def test_news_returns_all_visible_rows_and_preserves_hidden_records(app,client,fake):
    ids=seed(app)
    response=client.get('/api/studio/modules/news')
    assert response.status_code==200
    articles=response.json()['collections']['articles']
    assert len(articles)==150
    assert {r['id'] for r in articles}==set(ids[:-1])
    assert sum(r['category']=='문화' for r in articles)==60
    assert len({r['id'] for r in articles})==150
    with app.state.sessions() as s:
        assert s.scalar(select(func.count()).select_from(NewsArticle))==151
    assert fake.calls==[]

def test_all_categories_search_and_more_are_available_without_network_posts(app,browser,fake):
    seed(app)
    with local_server(app) as origin:
        context=browser_context(browser,origin);page=context.new_page();posts=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/news')
        count=page.get_by_label('기사 목록 건수')
        expect(count).to_have_text('불러온 기사 150건 · 검색 결과 150건 · 현재 표시 50건')
        page.get_by_role('button',name='기사 더 보기 (50건)',exact=True).click()
        expect(count).to_contain_text('현재 표시 100건')
        page.get_by_role('combobox',name='기사 분야',exact=True).select_option('문화')
        expect(count).to_have_text('불러온 기사 150건 · 검색 결과 60건 · 현재 표시 50건')
        page.get_by_role('button',name='기사 더 보기 (10건)',exact=True).click()
        expect(count).to_contain_text('현재 표시 60건')
        page.get_by_role('textbox',name='보관 뉴스 검색').fill('합성 기사 000')
        expect(count).to_have_text('불러온 기사 150건 · 검색 결과 1건 · 현재 표시 1건')
        expect(page.locator('.core-news-list button')).to_have_count(1)
        page.get_by_role('textbox',name='보관 뉴스 검색').fill('없는 기사')
        expect(count).to_contain_text('검색 결과 0건')
        assert posts==[] and fake.calls==[]
        context.close()
