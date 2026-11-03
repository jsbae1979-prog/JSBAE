from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_top_three_selection import feeds
from newsflow.creation.catalog import DEFAULTS
from bat_distribution.operation import OperatingRequests

def test_news_preview_never_matches_two_absent_draft_ids_and_steps_align(app,browser,tmp_path):
    with local_server(app) as origin:
        c=browser.new_context(viewport={'width':1920,'height':1080})
        c.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        def module(r):
            d=r.fetch().json()
            d['projects']=[{'id':'character:synthetic','kind':'character','mediaUrl':'/character/synthetic/file'}]
            d['collections']['drafts']=[]
            r.fulfill(json=d)
        c.route('**/api/studio/modules/shorts',module)
        p=c.new_page();errors=[];posts=[]
        p.on('pageerror',lambda e:errors.append(str(e)))
        p.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        p.goto(origin+'/studio/shorts')
        expect(p.locator('.core-simple-video video')).to_have_count(0)
        expect(p.locator('.core-simple-video')).to_contain_text('완성 영상이 없습니다')
        p.goto(origin+'/studio/characters')
        expect(p.locator('.kling-character-steps > div')).to_have_count(3)
        for width in (1920,1366):
            p.set_viewport_size({'width':width,'height':1080})
            for index in range(3):
                step=p.locator('.kling-character-steps > div').nth(index).bounding_box()
                card=p.locator('.kling-character-columns > section').nth(index).bounding_box()
                assert abs(step['x']-card['x'])<1 and abs(step['width']-card['width'])<1
            player=p.locator('.kling-character-video-preview')
            assert player.evaluate('(e)=>Math.abs(e.querySelector(".core-media").getBoundingClientRect().width-e.clientWidth)<1')
            p.screenshot(path=str(tmp_path/f'character-layout-{width}.png'),full_page=True)
        assert not posts and not errors
        c.close()

def test_existing_image_job_button_does_not_claim_new_creation(app,feeds,browser):
    identifier=feeds.create(42,DEFAULTS['image'])
    with local_server(OperatingRequests(app)) as origin:
        c=browser.new_context(viewport={'width':1366,'height':768})
        c.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        def module(r):
            d=r.fetch().json();d['collections']['selections']=[{'id':42,'title':'합성 분석','status':'success',
                'ranking':[{'rank':n,'title':f'합성 {n}'} for n in (1,2,3)]}]
            r.fulfill(json=d)
        c.route('**/api/studio/modules/images',module)
        p=c.new_page();posts=[];p.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        p.goto(origin+'/studio/images?mode=top3')
        expect(p.get_by_role('button',name='저장된 작업 열기',exact=True)).to_be_enabled()
        p.get_by_role('button',name='저장된 작업 열기',exact=True).click()
        expect(p.locator('.core-notice').filter(has_text='저장된 작업을 열었습니다')).to_be_visible()
        assert not posts and len(feeds.recent())==1
        c.close()
