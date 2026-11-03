from pathlib import Path
import os,base64
import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_news_collection_controls_browser import browser_context

@pytest.fixture(autouse=True)
def dist(monkeypatch):monkeypatch.setattr('newsflow.studio.resources.studio_dist_root',lambda:Path(os.environ['EDITORIAL_TEST_DIST']))

def test_new_image_text_preview_and_single_consent(app,browser,tmp_path):
    with local_server(app) as origin:
        c=browser_context(browser,origin);p=c.new_page();posts=[];errors=[]
        p.on('pageerror',lambda e:errors.append(str(e)))
        image='/image-studio/5/file'
        rows=[{'id':5,'title':'기존 이미지','prompt':'기존 프롬프트','status':'success','outputId':51,'mediaUrl':image,'selection':{'model':'gpt-image-1','size':'1024x1024','quality':'low'}}]
        def module(route):
            data=route.fetch().json();data['commandsAvailable']=True;data['collections']['drafts']=rows
            data['catalog']['imageDefaults']={'provider':'openai','model':'gpt-image-1','size':'1024x1024','quality':'low'}
            route.fulfill(json=data)
        p.route('**/api/studio/modules/images',module)
        p.route(origin+image,lambda r:r.fulfill(content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="400" height="500"><rect width="400" height="500" fill="orange"/></svg>'))
        def post(route):
            posts.append((route.request.url,route.request.post_data))
            if route.request.url.endswith('/drafts'):
                rows.insert(0,{'id':6,'title':'새 이미지','prompt':'새 프롬프트','status':'draft','outputId':None,'selection':rows[0]['selection']})
                route.fulfill(json={'draft_id':6});return
            route.fulfill(status=303,headers={'Location':'/image-studio'},body='')
        p.route(origin+'/image-studio/drafts',post);p.route(origin+'/image-studio/6/generate',post)
        p.goto(origin+'/studio/images?mode=ai')
        p.get_by_role('button',name='생성 이미지 크게 보기',exact=True).click()
        preview=p.get_by_role('dialog',name='AI 이미지 크게 보기')
        expect(preview.get_by_role('img')).to_have_attribute('src',image)
        assert preview.bounding_box()['height']<=768
        p.keyboard.press('Escape');expect(preview).not_to_be_visible();assert not posts
        p.get_by_role('button',name='새로 만들기',exact=True).click()
        expect(p.get_by_label('이미지 프롬프트',exact=True)).to_be_focused()
        expect(p.get_by_role('button',name='생성 조건 확인',exact=True)).to_have_count(0)
        p.get_by_label('이미지 프롬프트',exact=True).fill('푸른 바다 위 작은 배')
        expect(p.get_by_label('이미지 문구 만들기')).to_have_value('auto')
        p.get_by_label('이미지 문구 만들기').select_option('manual')
        p.get_by_label('이미지에 넣을 짧은 문구',exact=True).fill('오늘도 나답게')
        p.get_by_role('button',name='이미지 만들기',exact=True).click()
        d=p.get_by_role('dialog',name='승인 후 이미지 1회 생성',exact=True)
        from urllib.parse import parse_qs
        assert '오늘도 나답게' in parse_qs(posts[0][1])['prompt'][0]
        assert 'reference' not in parse_qs(posts[0][1])
        expect(d.get_by_role('checkbox')).to_have_count(1)
        button=d.get_by_role('button',name='승인 후 이미지 1회 생성',exact=True)
        expect(button).to_be_disabled();assert len(posts)==1
        d.get_by_role('checkbox').check();expect(button).to_be_enabled()
        assert d.bounding_box()['height']<500
        p.screenshot(path=str(tmp_path/'single-image-consent.png'))
        button.click();expect(d).not_to_be_visible()
        assert len(posts)==2 and posts[-1][0].endswith('/6/generate')
        assert 'consent=true' in posts[-1][1] and 'reviewed=true' in posts[-1][1]
        assert rows[-1]['id']==5 and rows[-1]['mediaUrl']==image and not errors
        p.unroute_all(behavior="wait");c.unroute_all(behavior='wait');c.close()

@pytest.mark.parametrize('can_retry',[True,False])
def test_retry_confirmation_is_explicit_and_never_replays(app,browser,can_retry):
    with local_server(app) as origin:
        c=browser_context(browser,origin);p=c.new_page();posts=[]
        def module(route):
            data=route.fetch().json();data['catalog']['newsAnalysis']={'provider':'claude_api','model':'claude-sonnet-4-6','collectionReady':True,'collectionContextId':21,'candidateCount':60};route.fulfill(json=data)
        p.route('**/api/studio/modules/news',module)
        p.route('**/api/curation/analysis-status?*',lambda r:r.fulfill(json={'state':'failed','runId':93,'canRetry':can_retry,'detail':'형식 검사 실패'}))
        def submit(route):posts.append(route);route.fulfill(status=422,json={'detail':'새 요청 실패'})
        p.route(origin+'/news/curation/analyze',submit)
        p.goto(origin+'/studio/news');p.get_by_label('뉴스 분석 범위',exact=True).select_option('collection')
        p.get_by_role('button',name='TOP 3 분석 · 승인',exact=True).click()
        d=p.get_by_role('dialog',name='기사 분석',exact=True)
        expect(d.get_by_role('status',name='요청 진행 상태')).to_contain_text('분석 실패')
        retry=d.get_by_role('button',name='다시 분석하기',exact=True)
        if not can_retry:expect(retry).to_have_count(0);assert not posts;c.unroute_all(behavior='wait');c.close();return
        retry.click();expect(d.get_by_text('같은 기사로 다시 분석할까요?',exact=True)).to_be_visible()
        d.get_by_role('button',name='취소',exact=True).click();assert not posts
        retry.click();d.get_by_role('button',name='동의하고 다시 분석',exact=True).click()
        expect(d.get_by_role('alert')).to_contain_text('새 요청 실패')
        assert len(posts)==1
        body=posts[0].request.post_data
        assert 'retry_failed_run_id=93' in body and 'consent=true' in body
        p.unroute_all(behavior="wait");c.unroute_all(behavior='wait');c.close()


def test_result_description_uses_requested_theme_without_internal_instructions(app,browser,tmp_path):
    with local_server(app) as origin:
        c=browser_context(browser,origin);p=c.new_page();posts=[]
        p.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        prompt=('직장인들의 일상 (반복되고 지친 하루)\n시각 스타일: 3D 애니메이션\n'
          '주제에 어울리는 짧은 한국어 문구 한 개를 직접 만들고 이미지와 함께 디자인하세요. 읽기 쉬운 한글 타이포그래피, 충분한 여백, 배경과 대비되는 강조색을 사용하고 주요 피사체를 가리지 마세요. 문구는 간결하게, 근거 없는 사실·수치·인용은 추가하지 마세요.')
        def module(route):
            data=route.fetch().json();data['collections']['drafts']=[{'id':7,'title':prompt,'prompt':prompt,'status':'success','outputId':8,'mediaUrl':'/image-studio/7/file','selection':{}}];route.fulfill(json=data)
        p.route('**/api/studio/modules/images',module)
        p.route(origin+'/image-studio/7/file',lambda r:r.fulfill(content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="blue"/></svg>'))
        p.goto(origin+'/studio/images?mode=ai');display=p.locator('.core-saved-selection')
        expect(display.locator('strong')).to_have_text('직장인들의 일상')
        expect(display).to_contain_text('제작 의도 · 반복되고 지친 하루 · 3D 애니메이션')
        expect(display).not_to_contain_text('근거 없는 사실')
        display.get_by_text('입력한 내용',exact=True).click()
        expect(display.locator('details p')).to_have_text('직장인들의 일상 (반복되고 지친 하루)')
        expect(p.locator('.core-recent-panel .feed-image-history-card strong')).to_have_text('직장인들의 일상')
        assert not posts
        display.screenshot(path=str(tmp_path/'description.png'))
        p.unroute_all(behavior='wait');c.unroute_all(behavior='wait');c.close()
