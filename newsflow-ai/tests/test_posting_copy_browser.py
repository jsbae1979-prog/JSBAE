"""Visible UI flow with synthetic content and Fake AI review only."""
from hashlib import sha256
from uuid import uuid4
import re
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_library_visibility import mixed
from test_posting_copy import VALUE
from newsflow.db.models import ImagePost
from newsflow.publishing.posting_copy import PostingCopy,Suggestion

def test_copy_review_apply_and_image_platform_filter(app,browser,monkeypatch,tmp_path):
    ids,_=mixed(app)
    with app.state.sessions.begin() as s:
        post=s.get(ImagePost,int(ids[2].split(':')[1]));raw=b'SYNTHETIC IMAGE ONLY'
        post.filename='image-'+uuid4().hex+'.jpg';post.sha256=sha256(raw).hexdigest()
        app.state.image_posts.outputs.mkdir(parents=True,exist_ok=True)
        (app.state.image_posts.outputs/post.filename).write_bytes(raw)
    class AI:
        calls=[]
        def generate(self,instruction,payload,schema,options,**kwargs):
            self.calls.append((payload,kwargs))
            return Suggestion(**{**VALUE,'title':'검토한 게시 제목','notes':['합성 API 검토']})
    ai=AI();app.state.posting_copy=PostingCopy(app.state,ai=ai)
    monkeypatch.setattr('newsflow.publishing.posting_copy.APIBudgetService.readiness',lambda *a,**k:{'ready':True})
    with local_server(app) as origin:
        ctx=browser.new_context(viewport={'width':1366,'height':768})
        ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page=ctx.new_page();posts=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/publishing')
        candidates=page.locator('.mg-publish-list');candidates.get_by_role('button').filter(has_text='합성 게시물').click()
        platforms=page.locator('.mg-publish-platforms')
        expect(platforms.get_by_role('checkbox')).to_have_count(1)
        expect(platforms.get_by_role('checkbox',name='Instagram 피드 검토 대상')).to_be_visible()
        expect(platforms).not_to_contain_text('YouTube')
        page.get_by_label('게시 제목',exact=True).fill('합성 게시 제목')
        page.get_by_label('게시 설명',exact=True).fill('저장할 설명')
        page.get_by_role('button',name='문구 형식 검사',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='형식을 확인했습니다.')).to_be_visible()
        page.get_by_role('button',name='게시 문구 저장',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='게시 문구를 저장했습니다.')).to_be_visible()
        page.get_by_role('button',name='AI 제목·설명·해시태그 검토',exact=True).click()
        dialog=page.get_by_role('dialog',name='AI 게시 문구 검토',exact=True)
        dialog.get_by_role('button',name='취소',exact=True).click();assert not ai.calls
        page.get_by_role('button',name='AI 제목·설명·해시태그 검토',exact=True).click()
        dialog.get_by_role('button',name='검토 요청 · 유료',exact=True).click()
        expect(page.locator('.mg-copy-suggestion')).to_contain_text('검토한 게시 제목')
        expect(page.get_by_label('게시 제목',exact=True)).to_have_value('합성 게시 제목')
        assert len(ai.calls)==1
        page.screenshot(path=str(tmp_path/'posting-copy-suggestion.png'),full_page=True)
        page.get_by_role('button',name='수정안 적용·저장',exact=True).click()
        expect(page.get_by_label('게시 제목',exact=True)).to_have_value('검토한 게시 제목')
        page.reload();expect(page.get_by_role('button',name='게시 문구 저장',exact=True)).to_be_enabled()
        candidates.get_by_role('button').filter(has_text='합성 게시물').click()
        expect(page.get_by_label('게시 제목',exact=True)).to_have_value('검토한 게시 제목')
        for width,height in [(1366,768),(1920,1080)]:
            page.set_viewport_size({'width':width,'height':height})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(tmp_path/f'posting-copy-{width}.png'),full_page=True)
        candidates.get_by_role('button').filter(has_text='합성 뉴스 영상').click()
        expect(platforms.get_by_role('checkbox')).to_have_count(4)
        expect(platforms.get_by_role('checkbox',name='Instagram Reels 검토 대상')).to_be_visible()
        platforms.get_by_role('checkbox',name='YouTube Shorts 검토 대상').check()
        candidates.get_by_role('button').filter(has_text='합성 게시물').click()
        expect(platforms.get_by_role('checkbox')).to_have_count(1)
        expect(platforms.get_by_role('checkbox')).not_to_be_checked()
        expect(platforms).not_to_contain_text('YouTube')
        expect(page.get_by_role('button',name='게시 문구 저장',exact=True)).to_be_enabled()
        pending=[]
        page.route('**/api/studio/publishing/copy/save',lambda r:pending.append(r))
        page.get_by_role('button',name='게시 문구 저장',exact=True).click()
        page.wait_for_timeout(100)
        assert len(pending)==1
        page.get_by_label('게시 제목',exact=True).fill('저장 요청 뒤 입력한 제목')
        pending[0].fulfill(json={'revision':3,'copy':{**VALUE,'title':'검토한 게시 제목'},'approval':False})
        expect(page.get_by_role('status').filter(has_text='이후 입력한 변경 내용은 아직 저장하지 않았습니다.')).to_be_visible()
        expect(page.get_by_label('게시 제목',exact=True)).to_have_value('저장 요청 뒤 입력한 제목')
        assert len(posts)==5 and all('/api/studio/publishing/copy/' in p for p in posts)
        assert len(ai.calls)==1
        ctx.close()
