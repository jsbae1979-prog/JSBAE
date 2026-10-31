"""Existing authenticated reference GET only; no provider requests or media rewriting."""
import hashlib
import os
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_episode_schema import image
from newsflow.character.kling import DEFAULTS
from newsflow.character.compose import run
from newsflow.video.engine import FFmpegAdapter

CAPTURE_DIR=Path(os.environ["NEWSFLOW_CHARACTER_CAPTURE_DIR"]) if os.environ.get("NEWSFLOW_CHARACTER_CAPTURE_DIR") else None


def test_character_cards_use_owned_reference_without_inventing_final_media(app,browser,tmp_path):
    service=app.state.character
    cases={}
    for label,state in [('합성 초안','needs_script'),('합성 장면 검토','clips_review'),('합성 완성 영상','completed'),('참조 없음','needs_script')]:
        identifier,_=service.create_studio(label,'5',reference=image(),
            settings={**DEFAULTS,'duration':15,'clip_seconds':3},request_id=uuid4().hex)
        job=service.read(identifier);job['state']=state
        if state=='completed':
            output=service.folder(identifier)/'final.mp4'
            run([str(FFmpegAdapter.executable('ffmpeg',None)),'-nostdin','-n','-v','error','-f','lavfi','-i',
                 'color=c=blue:s=144x256:r=30','-t','1','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',str(output)],output.parent)
            job['output']={'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
        service.save(job)
        if label=='참조 없음':(service.folder(identifier)/'reference.png').unlink()
        cases[label]=identifier
    originals={row['id']:service.read(row['id']) for row in service.listing()}
    with local_server(app) as origin:
        context=browser.new_context(viewport={'width':1366,'height':768})
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page=context.new_page();posts=[];errors=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(origin+'/studio/library')
        for label,identifier in cases.items():
            card=page.locator(f'[data-content-id="own-character:{identifier}"]')
            expect(card).to_be_visible()
            if label=='참조 없음':
                expect(card.get_by_text('미리보기 없음',exact=True)).to_be_visible()
            else:
                picture=card.get_by_role('img',name=label+' · 참조 이미지',exact=True)
                expect(picture).to_have_class('asset-thumb-img loaded')
                expect(picture).to_have_attribute('src',f'/api/studio/characters/{identifier}/reference')
                expect(card.get_by_text('참조 이미지',exact=True)).to_be_visible()
            card.click();detail=page.locator('.mg-library-detail')
            if label=='합성 완성 영상':
                expect(detail.locator('video')).to_have_attribute('src',f'/character/{identifier}/file')
                expect(detail.get_by_role('link',name='다운로드',exact=True)).to_be_visible()
            else:
                expect(detail.locator('video')).to_have_count(0)
                expect(detail.get_by_text('미리보기 파일 없음',exact=True)).to_be_visible()
                expect(detail.get_by_role('link',name='다운로드',exact=True)).to_have_count(0)
        out=CAPTURE_DIR or tmp_path/'captures'
        out.mkdir(parents=True,exist_ok=True)
        for width,height in ((1920,1080),(1366,768)):
            page.set_viewport_size({'width':width,'height':height})
            page.screenshot(path=str(out/f'character-library-preview-{width}x{height}.png'),full_page=True)
        page.goto(origin+'/studio/dashboard')
        for label,identifier in cases.items():
            card=page.locator('button.project').filter(has=page.locator('strong',has_text=label))
            expect(card).to_be_visible()
            if label=='참조 없음':expect(card.get_by_text('미리보기 없음',exact=True)).to_be_visible()
            else:
                expect(card.locator('img')).to_have_attribute('src',f'/api/studio/characters/{identifier}/reference')
                expect(card.locator('img')).to_have_class('asset-thumb-img loaded')
            expect(card.locator('.type-tag')).to_contain_text('참조 이미지')
        page.screenshot(path=str(out/'character-home-preview-1366x768.png'),full_page=True)
        assert not posts and not errors
        assert originals=={row['id']:service.read(row['id']) for row in service.listing()}
        context.close()
