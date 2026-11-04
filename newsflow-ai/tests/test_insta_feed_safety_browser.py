"""Browser UI on synthetic localhost data, no provider or SNS traffic."""
from hashlib import sha256
from io import BytesIO
from PIL import Image
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_library_visibility import mixed
from newsflow.db.models import ImagePost
from newsflow.publishing.posting_copy import PostingCopy

def test_image_safety_on_posting_right_and_nonblocking_warning(app,browser,tmp_path):
    ids,_=mixed(app)
    raw=BytesIO();Image.new('RGB',(1080,1350),'#193f58').save(raw,'JPEG');raw=raw.getvalue()
    with app.state.sessions.begin() as s:
        post=s.get(ImagePost,int(ids[2].split(':')[1]))
        post.filename='image-'+'c'*32+'.jpg';post.sha256=sha256(raw).hexdigest()
        post.sources={'full_image':True,'generated_image_run_id':1,
            'articles':[{'title':'호주 의원 헬렌 헤인스 차량 공격','summary':'경찰 수사 중이다.'}]}
        app.state.image_posts.outputs.mkdir(parents=True,exist_ok=True)
        (app.state.image_posts.outputs/post.filename).write_bytes(raw)
    class Denied:
        def generate(self,*a,**kw):raise AssertionError('No paid API')
    app.state.posting_copy=PostingCopy(app.state,ai=Denied())
    with local_server(app) as origin:
        context=browser.new_context(viewport={'width':1366,'height':768})
        context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        p=context.new_page();errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
        p.goto(origin+'/studio/publishing')
        p.locator('.mg-publish-list').get_by_role('button').filter(has_text='합성 게시물').click()
        right=p.locator('.mg-publish-right');editor=p.locator('.mg-publish-editor')
        safe=right.get_by_role('checkbox',name='AI 이미지 안전 확인',exact=True)
        expect(safe).to_be_visible()
        expect(editor.get_by_role('checkbox',name='AI 이미지 안전 확인',exact=True)).to_have_count(0)
        expect(right).to_contain_text("인스타그램 게시 시 'AI 정보' 라벨을 켜세요")
        expect(right).to_contain_text('민감 주제')
        p.get_by_label('게시 설명',exact=True).fill('친팔레스타인 활동가로 지목')
        p.get_by_role('button',name='저장',exact=True).click()
        expect(p.locator('.mg-claim-warning').first).to_be_visible()
        expect(p.get_by_role('status').filter(has_text='게시 문구를 저장했습니다')).to_be_visible()
        right.get_by_role('checkbox',name='Instagram 피드 검토 대상').check()
        right.get_by_role('checkbox',name='콘텐츠·권리·출처 검토 완료').check()
        prepare=right.get_by_role('button',name='선택 플랫폼 게시 준비 저장')
        expect(prepare).to_be_disabled();safe.check();expect(prepare).to_be_enabled()
        prepare.click();expect(right).to_contain_text('저장된 준비')
        for width,height in [(1366,768),(1920,1080)]:
            p.set_viewport_size({'width':width,'height':height})
            assert p.evaluate('document.documentElement.scrollWidth <= innerWidth')
            p.screenshot(path=str(tmp_path/f'insta-safety-{width}.png'),full_page=True)
        assert not errors
        context.close()
