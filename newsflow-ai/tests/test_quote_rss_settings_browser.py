from datetime import timedelta
from pathlib import Path
import os
import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_episode_automation import setup_episode
from newsflow.character.service import now,fingerprint

@pytest.fixture
def quoted_app(app):
    s,v,i,_,_=setup_episode(app.state.config.data_dir)
    s.sessions=app.state.sessions
    app.state.character=s
    s.write(i,consent=True);s.prepare(i,consent=True,script_reviewed=True)
    return app,s,v,i

def context(browser,origin):
    c=browser.new_context(viewport={'width':1366,'height':768})
    c.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
    return c

def capture(page,name):
    output=os.environ.get('QUOTE_REVIEW_EVIDENCE')
    if output:
        folder=Path(output);folder.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(folder/name),full_page=False)

def test_expired_quote_offers_one_explicit_refresh_not_paid_submit(quoted_app,browser):
    app,s,v,i=quoted_app;job=s.read(i)
    job['quoted_at']=(now()-timedelta(minutes=16)).isoformat()
    job['quote_hash']=fingerprint([job['plan_hash'],job['scenes'],job['quoted_at'],job['quote_key_id']]);s.save(job)
    with local_server(app) as origin:
        c=context(browser,origin);p=c.new_page();errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
        p.goto(origin+'/studio/characters?job_id='+i)
        p.get_by_role('button',name='영상 생성하기',exact=True).click()
        dialog=p.get_by_role('dialog',name='견적 승인 후 장면 생성',exact=True)
        expect(dialog).to_contain_text('견적 유효시간이 지났습니다')
        expect(dialog.get_by_role('checkbox')).to_have_count(0)
        expect(dialog.get_by_role('button',name='견적 승인 후 장면 생성',exact=True)).to_be_disabled()
        capture(p,'expired-quote-1366x768.png')
        dialog.get_by_role('button',name='최신 견적 확인',exact=True).click()
        prepare=p.get_by_role('dialog',name='장면 공식 견적 조회',exact=True)
        # The saved script is retained; only an explicit free quote approval opens.
        expect(prepare).to_be_visible();expect(prepare.get_by_role('checkbox')).to_have_count(1)
        assert s.read(i)['state']=='script_review' and len(s.authoring.calls)==1 and not v.sent
        assert not errors;c.close()

def test_fresh_quote_uses_one_bound_cost_approval_at_both_sizes(quoted_app,browser):
    app,s,v,i=quoted_app
    with local_server(app) as origin:
        c=context(browser,origin);p=c.new_page();posts=[]
        p.on('request',lambda r:posts.append(r) if r.method=='POST' else None)
        p.goto(origin+'/studio/characters?job_id='+i)
        p.get_by_role('button',name='영상 생성하기',exact=True).click()
        dialog=p.get_by_role('dialog',name='견적 승인 후 장면 생성',exact=True)
        expect(dialog.get_by_role('checkbox')).to_have_count(1)
        approve=dialog.get_by_role('checkbox',name='표시된 견적과 검토한 내용으로 영상 생성 승인',exact=True)
        submit=dialog.get_by_role('button',name='견적 승인 후 장면 생성',exact=True)
        expect(submit).to_be_disabled()
        for w,h in [(1366,768),(1920,1080)]:
            p.set_viewport_size({'width':w,'height':h});expect(approve).to_be_visible()
            expect(dialog).to_contain_text('공식 영상 견적');expect(dialog).to_contain_text('US$'+s.read(i)['quote_total_usd'])
            assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
            capture(p,f'bound-quote-{w}x{h}.png')
        assert not posts and not v.sent
        approve.check();expect(submit).to_be_enabled();submit.click()
        expect(dialog).not_to_be_visible()
        assert any(r.url.endswith('/submit') for r in posts)
        assert s.read(i).get('quote_approvals') and len(v.sent)>=1
        c.close()

def test_registered_rss_has_no_paid_or_repeated_scope_checkbox(app,browser):
    with local_server(app) as origin:
        c=context(browser,origin);p=c.new_page();p.goto(origin+'/studio/news')
        p.get_by_role('button',name='등록 RSS 수집 · 확인',exact=True).click()
        d=p.get_by_role('dialog',name='등록 RSS 수집',exact=True)
        expect(d.get_by_role('checkbox')).to_have_count(0)
        expect(d).to_contain_text('등록·활성화된 공개 RSS')
        expect(d.get_by_role('button',name='등록 RSS 수집',exact=True)).to_be_enabled()
        capture(p,'registered-rss-1366x768.png');c.close()

def test_serpapi_registration_visible_and_blank_key_not_disclosed(app,browser):
    app.state.serpapi_registration_available=True
    with local_server(app) as origin:
        c=context(browser,origin);p=c.new_page();posts=[]
        p.on('request',lambda r:posts.append(r) if r.method=='POST' else None)
        p.goto(origin+'/studio/settings');p.get_by_role('tab',name='뉴스 수집',exact=True).click()
        section=p.get_by_role('region',name='SerpApi 뉴스 수집 설정',exact=True)
        expect(section).to_contain_text('키 미등록')
        section.get_by_role('button',name='SerpApi 키·수집 설정',exact=True).click()
        d=p.get_by_role('dialog',name='수집 연결 설정 저장',exact=True)
        key=d.get_by_label('SerpApi API 키 · 변경할 때만 입력',exact=True)
        expect(key).to_be_visible();expect(key).to_have_attribute('type','password');expect(key).to_have_value('')
        expect(d).to_contain_text('키를 비우면 기존 키를 유지합니다')
        expect(d.get_by_role('checkbox',name='SerpApi 뉴스 수집 사용',exact=True)).to_be_visible()
        capture(p,'serpapi-registration-1366x768.png')
        assert not posts;c.close()

def test_open_quote_dialog_expires_without_submitting_or_replaying(quoted_app,browser):
    app,s,v,i=quoted_app
    with local_server(app) as origin:
        c=context(browser,origin);p=c.new_page();p.clock.install()
        p.goto(origin+'/studio/characters?job_id='+i)
        p.get_by_role('button',name='영상 생성하기',exact=True).click()
        d=p.get_by_role('dialog',name='견적 승인 후 장면 생성',exact=True)
        d.get_by_role('checkbox').check()
        expect(d.get_by_role('button',name='견적 승인 후 장면 생성',exact=True)).to_be_enabled()
        p.clock.fast_forward(16*60*1000)
        expect(d).to_contain_text('견적 유효시간이 지났습니다')
        expect(d.get_by_role('button',name='견적 승인 후 장면 생성',exact=True)).to_be_disabled()
        assert s.read(i)['state']=='quoted' and not v.sent
        c.close()
