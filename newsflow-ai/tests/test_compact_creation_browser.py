"""Only selected local context; modal confirmation and cancellation never call providers."""
from urllib.parse import parse_qs
from copy import deepcopy
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_saved_story_browser import ready


def test_news_script_selected_context_single_approval(app,browser,tmp_path):
    with local_server(app) as origin:
        ctx=browser.new_context(viewport={'width':1366,'height':768})
        ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        ctx.route('**/api/studio/production-context',lambda r:r.fulfill(json={
            'schemaVersion':1,'selection':{'id':42,'stale':False},'top3':[{'rank':2,'title':'합성 선택 기사','summary':'합성 요약','references':[]}]}))
        page=ctx.new_page();posts=[]
        page.route(origin+'/news/curation/generate',lambda r:(posts.append(parse_qs(r.request.post_data)),r.fulfill(status=303,headers={'Location':'/news'},body='')))
        page.goto(origin+'/studio/shorts?rank=2')
        page.get_by_role('button',name='AI 대본 생성',exact=True).click()
        d=page.get_by_role('dialog',name='선정 뉴스 대본 생성')
        expect(d).to_contain_text('합성 선택 기사')
        expect(d.get_by_role('spinbutton')).to_have_count(0)
        expect(d.get_by_role('checkbox')).to_have_count(1)
        expect(d).not_to_contain_text('저장된 분석')
        expect(d.get_by_role('button',name='선정 뉴스 대본 생성',exact=True)).to_be_disabled()
        page.screenshot(path=str(tmp_path/'selected-news-script.png'))
        d.get_by_role('checkbox').check();d.get_by_role('button',name='선정 뉴스 대본 생성',exact=True).click()
        expect(d).to_have_count(0)
        assert len(posts)==1 and posts[0]['analysis_id']==['42'] and posts[0]['rank']==['2']
        assert posts[0]['consent']==['true'] and posts[0]['duration']==['30']
        ctx.close()


def test_saved_story_requires_confirmation_then_exactly_one_fresh_request(app,browser,tmp_path):
    service,adapter,budget,identifier=ready(app,browser)
    before=deepcopy(service.read(identifier));source=service.folder(identifier)/before['script_responses'][0]['file'];raw=source.read_bytes()
    with local_server(app) as origin:
        ctx=browser.new_context(viewport={'width':1366,'height':768})
        ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        ctx.route('**/api/studio/characters/*/story-review',lambda r:r.fulfill(json={'ready':True,'review':{'token':'','count':0,'held_usd':'0'}}))
        requests=[]
        ctx.route('**/api/studio/characters/auto-story',lambda r:(requests.append(parse_qs(r.request.post_data)),r.fulfill(status=409,json={'error':'합성 응답 중단'})))
        page=ctx.new_page();page.goto(origin+'/studio/characters?job_id='+identifier)
        trigger=page.get_by_role('button',name='스토리 자동 생성하기',exact=False)
        expect(trigger).to_be_enabled();trigger.click()
        d=page.get_by_role('dialog',name='스토리를 다시 생성할까요?',exact=True)
        expect(d).to_contain_text('추가 비용');d.get_by_role('button',name='취소',exact=True).click()
        assert not requests and len(service.listing())==1
        trigger.click();expect(d).to_be_visible()
        page.screenshot(path=str(tmp_path/'stored-story-confirmation.png'))
        d.get_by_role('button',name='새 스토리 생성',exact=True).click()
        expect(page.locator('.kling-character-story > .kling-character-error')).to_contain_text('합성 응답 중단')
        assert len(requests)==1 and requests[0]['job_id']!=[identifier]
        assert len(service.listing())==2 and len(adapter.bodies)==1
        assert service.read(identifier)==before and source.read_bytes()==raw
        expect(trigger).to_be_disabled()
        ctx.close()
