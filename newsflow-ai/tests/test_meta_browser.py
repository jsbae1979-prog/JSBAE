"""Independent headless browser, synthetic DB/media and Fake Meta only."""
from hashlib import sha256
from pathlib import Path
import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_library_visibility import mixed
from test_meta_accounts import Vault, grant, Graph, Delivery, jpeg
from newsflow.db.models import ImagePost
from newsflow.meta.service import MetaConnections, DEFAULTS
from newsflow.meta.publishing import MetaPublishing
from newsflow.meta.media import resolve_content

pytestmark=pytest.mark.usefixtures('synthetic_app_isolation')

@pytest.fixture
def connected(app):
    accounts=MetaConnections(app.state.sessions,app.state.config.data_dir,owner='a'*64,vault=Vault())
    ids=[accounts.accept(grant(),app_id=DEFAULTS['appId']),accounts.accept(grant('102','202'),app_id=DEFAULTS['appId'])]
    publisher=MetaPublishing(accounts,Graph(),lambda key:resolve_content(app.state,key),Delivery())
    app.state.meta_connections=accounts;app.state.meta_publishing=publisher
    return accounts,publisher,ids

def context(browser,origin):
    ctx=browser.new_context(viewport={'width':1366,'height':900})
    ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
    return ctx

def test_accounts_metadata_no_external_login_on_open(app,browser,connected,tmp_path):
    accounts,publisher,ids=connected
    with local_server(app) as origin:
        ctx=context(browser,origin);page=ctx.new_page();calls=[]
        page.on('request',lambda r:calls.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/settings?tab=accounts')
        panel=page.locator('section').filter(has=page.get_by_role('heading',name='Facebook · Instagram 연결',exact=True)).last
        expect(panel.get_by_text('Synthetic 101',exact=True)).to_be_visible()
        expect(panel.get_by_text('Synthetic 102',exact=True)).to_be_visible()
        expect(panel.get_by_role('button',name='Meta 로그인 · 계정 추가')).to_be_disabled()
        panel.get_by_text('권한 · 만료일',exact=True).first.click()
        expect(panel.get_by_text('페이지 토큰: 만료일 미지정 · 철회 시 무효',exact=True).first).to_be_visible()
        assert not calls and not publisher.graph.calls
        assert 'synthetic-user-' not in page.content() and 'synthetic-page-' not in page.content()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        panel.screenshot(path=str(tmp_path/'meta-accounts.png'))
        ctx.close()

def test_selected_account_and_image_publish_use_fake_only(app,browser,connected,tmp_path):
    accounts,publisher,ids=connected
    projects,_=mixed(app)
    with app.state.sessions.begin() as db:
        row=db.get(ImagePost,int(projects[2].split(':')[1]));row.filename='image-'+'a'*32+'.jpg';row.sha256=sha256(jpeg()).hexdigest()
        app.state.image_posts.outputs.mkdir(parents=True,exist_ok=True)
        (app.state.image_posts.outputs/row.filename).write_bytes(jpeg())
    with local_server(app) as origin:
        ctx=context(browser,origin);page=ctx.new_page()
        page.goto(origin+'/studio/publishing')
        page.locator('.mg-publish-list').get_by_role('button').filter(has_text='합성 게시물').click()
        panel=page.locator('section').filter(has=page.get_by_role('heading',name='Facebook · Instagram 다중 계정 게시',exact=True)).last
        expect(panel.get_by_role('checkbox',name='Facebook 페이지',exact=True)).to_have_count(2)
        panel.get_by_role('checkbox',name='Facebook 페이지',exact=True).first.check()
        button=panel.get_by_role('button',name='대상별 게시 준비 저장',exact=True)
        expect(button).to_be_disabled()
        panel.get_by_role('checkbox',name='선택 계정·콘텐츠·문구와 권리·출처·AI 표시를 확인했습니다.',exact=True).check()
        button.click()
        expect(panel.get_by_text('게시 준비',exact=True)).to_be_visible()
        assert len(publisher.list())==1 and not publisher.graph.calls
        page.on('dialog',lambda dialog:dialog.accept())
        panel.get_by_role('button',name='전송 승인 · 게시',exact=True).click()
        expect(panel.get_by_text('결과 확인 필요',exact=True)).to_be_visible()
        panel.get_by_role('button',name='처리 · 게시 결과 확인',exact=True).click()
        expect(panel.get_by_text('게시 완료',exact=True)).to_be_visible()
        assert len([r for r in publisher.graph.calls if r[0]=='POST'])==1
        selected=publisher.list()[0]['connectionId']
        expected=next(a['pageId'] for a in accounts.accounts() if a['id']==selected)
        assert publisher.graph.calls[0][1]==expected+'/photos'
        panel.screenshot(path=str(tmp_path/'meta-publish.png'))
        page.locator('.mg-publish-list').get_by_role('button').filter(has_text='합성 뉴스 영상').click()
        expect(panel.get_by_role('checkbox',name='Facebook 페이지',exact=True).first).not_to_be_checked()
        expect(button).to_be_disabled()
        ctx.close()
