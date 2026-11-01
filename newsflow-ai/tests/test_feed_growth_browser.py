from copy import deepcopy
from hashlib import sha256
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_photo_feed_editor import feeds, prepared, photo


def test_free_copy_and_manual_performance_browser(app,feeds,browser,tmp_path):
    designs,b,state,d=prepared(feeds)
    raw=photo();feeds.root.mkdir(exist_ok=True,parents=True)
    result=deepcopy(feeds.get(b).result)
    for item in result['items']:
        name=f'feed-{b}-{item["rank"]}-1.jpg';(feeds.root/name).write_bytes(raw)
        item.update(status='success',filename=name,sha256=sha256(raw).hexdigest(),generation_id=999)
    feeds._save(b,result)
    designs.save(b,1,state['revision'],state['background'],d,export=True)
    before=deepcopy(feeds.get(b).result)
    feeds.generation._generate=lambda *a,**k: (_ for _ in ()).throw(AssertionError('No paid calls'))
    with local_server(app) as origin:
        ctx=browser.new_context(viewport={'width':1920,'height':1080})
        ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        def module(route):
            data=route.fetch().json();data['collections']['selections']=[{'id':42,'status':'success','title':'합성 TOP 3 분석','ranking':[
                {'rank':n,'title':f'합성 뉴스 {n}','body':f'합성 요약 {n}','article_ids':[n]} for n in (1,2,3)]}]
            route.fulfill(json=data)
        ctx.route('**/api/studio/modules/images',module)
        ctx.route('**/news/*/thumbnail',lambda route:route.fulfill(content_type='image/png',body=photo()))
        page=ctx.new_page();errors=[];writes=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:writes.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/images?mode=top3')
        expect(page.get_by_label('피드 제목',exact=True)).to_have_value(d['title'])
        page.get_by_text('제목 후보 · 캡션 구성',exact=True).click()
        group=page.get_by_role('group',name='제목 후보 비교')
        expect(group.get_by_role('button')).to_have_count(3)
        group.get_by_role('button').filter(has_text='저장된 제목').click()
        expect(page.get_by_label('피드 제목',exact=True)).to_have_value('합성 뉴스 1')
        page.get_by_role('button',name='저장된 내용으로 구성 불러오기',exact=True).click()
        page.get_by_label('캡션 첫 문장',exact=True).fill('합성 관측 계획 공개')
        page.get_by_label('핵심 사실',exact=True).fill('추가 검토 중이며 확정되지 않았습니다.')
        page.get_by_label('독자에게 중요한 점 · 선택',exact=True).fill('관측 결과는 추후 확인할 수 있습니다.')
        page.get_by_role('button',name='캡션에 적용 · 무료',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='캡션에 적용했습니다')).to_be_visible()
        page.get_by_role('button',name='새 버전으로 저장',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='새 버전 저장 완료')).to_be_visible()
        page.reload();expect(page.get_by_label('피드 제목',exact=True)).to_have_value('합성 뉴스 1')
        page.get_by_text('제목 후보 · 캡션 구성',exact=True).click()
        expect(page.get_by_label('캡션 첫 문장',exact=True)).to_have_value('합성 관측 계획 공개')
        page.get_by_text('게시 후 성과 비교 · 직접 입력',exact=True).click()
        expect(page.get_by_role('button',name='성과 기록 저장',exact=True)).to_be_disabled()
        page.get_by_label('성과 이미지 버전',exact=True).select_option('2')
        page.get_by_label('Instagram 게시물 주소',exact=True).fill('https://www.instagram.com/p/FixtureOnly123/')
        page.get_by_label('게시 시각',exact=True).fill('2026-01-01T09:00')
        page.get_by_label('측정 시각',exact=True).fill('2026-01-02T09:00')
        page.get_by_label('도달 계정',exact=True).fill('1000')
        page.get_by_label('저장',exact=True).fill('25')
        page.get_by_label('공유',exact=True).fill('10')
        page.get_by_label('실제 게시한 이미지의 성과를 입력했습니다',exact=True).check()
        page.get_by_role('button',name='성과 기록 저장',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='성과 기록을 저장했습니다')).to_be_visible()
        table=page.get_by_role('table',name='버전별 성과 · 사용자 입력')
        expect(table).to_contain_text('2.5%');expect(table).to_contain_text('24시간');expect(table).to_contain_text('미확인 / —')
        for width,height in [(1920,1080),(1366,768)]:
            page.set_viewport_size({'width':width,'height':height})
            page.screenshot(path=str(tmp_path/f'feed-growth-{width}.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), page.evaluate("Array.from(document.querySelectorAll('body *')).filter(e=>e.getBoundingClientRect().right>innerWidth+2).slice(-8).map(e=>({tag:e.tagName,cls:e.className,width:e.getBoundingClientRect().width}))")
        page.get_by_role('button',name='TOP 2 결과 선택',exact=True).click()
        expect(page.get_by_label('피드 제목',exact=True)).to_have_value('합성 뉴스 2')
        page.get_by_text('게시 후 성과 비교 · 직접 입력',exact=True).click()
        expect(page.get_by_text('저장된 게시 성과가 없습니다.',exact=True)).to_be_visible()
        assert not errors
        assert writes and all(url.endswith(('/design','/design-performance')) for url in writes)
        ctx.close()
    assert feeds.get(b).result==before
    assert designs.state(b,1)['versions'][0]['design']['caption']==d['caption']
    assert len(designs.state(b,1)['versions'])==2 and designs.state(b,2)['versions']==[]
