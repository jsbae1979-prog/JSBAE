import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect
from conftest import app, fake, rss
from test_cloud_workspace_flow import local_server
from test_usability_browser import visual, studio_ui, unified, youtube_ui, instagram_ui, youtube_media, browser
from test_youtube_gui import forbid_external_calls
from test_studio_dashboard_polish import records
from test_single_workspace import stored_values
from test_dashboard_cohesion import seed_archive

OUT=Path(os.environ['UX_EVIDENCE'])/os.environ.get('UX_PHASE','after')


def test_all_screens(visual,browser):
    app,(draft,render,failure)=visual
    article, task = seed_archive(app, draft)
    OUT.mkdir(parents=True,exist_ok=True)
    before=records(app),stored_values(app)
    media={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in app.state.video.outputs.glob('*') if p.is_file()}
    paths=[('home','/'),('create','/create'),('workspace',f'/?task={task}#workspace-detail'),
           ('news','/news'),('script',f'/ai?draft_id={draft}'),('voices','/voices'),
           ('video',f'/video?draft_id={draft}'),('ai-video',f'/video/ai?draft_id={draft}'),
           ('ai-video-settings','/video-ai-settings'),('library','/videos'),
           ('publish',f'/?video={render}&publish_platform=unified#publish-workspace'),
           ('feed','/image-posts'),('feed-selected',f'/image-posts?article_id={article}'),
           ('settings','/simple-settings'),('error',f'/video?job_id={failure}'),('queue','/queue')]
    external,posts,errors=[],[],[]
    audit=[]
    with local_server(app) as origin:
        context=browser.new_context(locale='ko-KR',reduced_motion='reduce')
        def guard(route):
            if urlsplit(route.request.url).netloc!=urlsplit(origin).netloc:
                external.append(route.request.url);route.abort()
            elif route.request.method!='GET':
                posts.append(route.request.url);route.abort()
            else:route.continue_()
        context.route('**/*',guard)
        page=context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        for width,height in [(1366,768),(1920,1080),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            for name,path in paths:
                response=page.goto(origin+path,wait_until='networkidle')
                assert response.status==200
                expect(page.locator('h1').first).to_be_attached()
                overflow=page.evaluate('document.documentElement.scrollWidth-innerWidth')
                audit.append({'screen':name,'viewport':f'{width}x{height}','overflow':overflow})
                assert overflow<=2,(name,width,overflow)
                if name == 'error':
                    notice = page.locator('.studio-error')
                    expect(notice).to_contain_text('음성')
                    notice.scroll_into_view_if_needed()
                    actions=page.locator('.studio-recovery-actions a')
                    boxes=[actions.nth(i).bounding_box() for i in range(actions.count())]
                    for first,second in zip(boxes,boxes[1:]):
                        assert second['y'] >= first['y']+first['height']+8 or second['x'] >= first['x']+first['width']+8
                audit[-1]['images']=page.locator('img').evaluate_all('(els)=>els.map(e=>({src:e.getAttribute("src"),alt:e.alt,loaded:e.complete&&e.naturalWidth>0,visible:!!e.getClientRects().length}))')
                audit[-1]['h1']=page.locator('h1').first.inner_text()
                page.screenshot(path=str(OUT/f'{name}-{width}.png'),animations='disabled')
                if name in ('voices','ai-video','ai-video-settings','feed-selected') and width==1366:
                    page.screenshot(path=str(OUT/f'{name}-{width}-full.png'),animations='disabled',full_page=True)
        context.close()
    assert not external and not posts and not errors
    assert before==(records(app),stored_values(app))
    assert media=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in app.state.video.outputs.glob('*') if p.is_file()}
    (OUT/'audit.json').write_text(json.dumps({'screens':audit,'external':external,'posts':posts,'errors':errors,'records_settings_media_preserved':True,'source_sha':'a3e9bad7ca46abc9a390166272a02f7c0f292f87','environment':'Cloud Chromium; synthetic DB; GET only'},ensure_ascii=False,indent=2))


def test_empty_states(app,browser):
    OUT.mkdir(parents=True,exist_ok=True)
    with local_server(app) as origin:
        context=browser.new_context(locale='ko-KR',reduced_motion='reduce')
        external=[]
        def guard(route):
            if route.request.url.startswith(origin+'/') and route.request.method=='GET': route.continue_()
            else: external.append(route.request.url);route.abort()
        context.route('**/*',guard)
        page=context.new_page()
        for width,height in [(1366,768),(1920,1080),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            for label,path in [('library','/videos'),('queue','/queue')]:
                page.goto(origin+path,wait_until='networkidle')
                expect(page.locator('.gentle-empty').first).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+2')
                page.screenshot(path=str(OUT/f'empty-{label}-{width}.png'),animations='disabled')
            page.locator('.gentle-empty a[href="/videos"]').click()
            expect(page.locator('.library-empty .button')).to_be_visible()
            page.locator('.library-empty .button').focus()
            page.keyboard.press('Enter')
            expect(page.locator('#quick-production')).to_be_visible()
        context.close()
        assert not external


def test_analysis_entry_and_result(visual, browser):
    from newsflow.db.models import IntelligenceRun
    app, (draft, _, _) = visual
    article, _ = seed_archive(app, draft)
    with app.state.sessions.begin() as session:
        run=IntelligenceRun(kind='analysis',status='success',provider='offline',options={'model':'offline'},message='합성 시각 감사 fixture',
            evidence={'articles':[{'id':article,'title':'[합성 감사] 기사 선택 예시','summary':'실제 뉴스·분석이 아닌 화면 감사용 합성 자료입니다.',
                'sources':[{'url':'https://example.com/audit','publisher':'합성 출처'}]}]},
            result={'overview':'[합성 감사] 결과 요약의 배치만 확인합니다. 실제 AI 분석 결과가 아닙니다.','comparisons':[]})
        session.add(run);session.flush();identifier=run.id
    before=records(app),stored_values(app)
    audit=[];blocked=[]
    with local_server(app) as origin:
        context=browser.new_context(locale='ko-KR',reduced_motion='reduce')
        def guard(route):
            if urlsplit(route.request.url).netloc==urlsplit(origin).netloc and route.request.method=='GET':route.continue_()
            else:blocked.append(route.request.url);route.abort()
        context.route('**/*',guard)
        page=context.new_page()
        for width,height in [(1366,768),(1920,1080),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            for name,path in [('analysis-entry','/ai'),('analysis-result',f'/ai?analysis_id={identifier}')]:
                response=page.goto(origin+path,wait_until='networkidle')
                assert response.status==200
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
                graphic=page.locator('img[src$="script-workflow.svg"]')
                if width <= 760:
                    expect(graphic).to_be_hidden()  # existing script-modern.css: keep mobile focused on inputs
                else:
                    expect(graphic).to_be_visible()
                assert graphic.evaluate('(e)=>e.complete&&e.naturalWidth>0')
                page.screenshot(path=str(OUT/f'{name}-{width}.png'))
                audit.append({'screen':name,'viewport':f'{width}x{height}','http':response.status,'workflow_svg_loaded':True,'workflow_svg_visible':width>760})
        context.close()
    assert not blocked and before==(records(app),stored_values(app))
    (OUT/'analysis-audit.json').write_text(json.dumps({'screens':audit,'blocked':blocked,'records_preserved':True},ensure_ascii=False,indent=2))
