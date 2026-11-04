"""Cancelled direct entry: story-only UI; historical data stays readable."""
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_story_feedback_browser import setup
from test_character_operating_authoring import connected
from test_character_automation_routes import gui
from test_api_settings import sessions


def test_character_studio_exposes_only_original_story_flow(app,browser):
    saved=setup(app)
    with local_server(app) as origin:
        ctx=browser.new_context(viewport={'width':1366,'height':768})
        ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page=ctx.new_page();posts=[];page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters')
        expect(page.get_by_role('button',name='이미지·주제 제작',exact=True)).to_have_count(0)
        expect(page.get_by_role('button',name='스토리로 제작',exact=True)).to_have_count(0)
        expect(page.get_by_role('button',name='스토리 자동 생성하기',exact=False)).to_be_visible()
        expect(page.get_by_label('대본 AI',exact=True)).to_be_visible()
        page.get_by_text('주제 자동 생성·기록',exact=True).click()
        expect(page.get_by_role('button',name='주제 자동 생성',exact=True)).to_be_visible()
        assert not posts
        # Historical direct output remains playable without presenting its
        # technical execution plan as an AI-authored story or sending a POST.
        from uuid import uuid4
        from hashlib import sha256
        from newsflow.character.kling import DEFAULTS, O3
        from newsflow.character.compose import run
        from newsflow.video.engine import FFmpegAdapter
        from test_character_episode_schema import image
        service=app.state.character
        identifier,_=service.create_episode('합성 보관 영상','5',reference=image(),
            profile=saved,settings={**DEFAULTS,'video_model':O3,'native_resolution':'std','duration':30},
            request_id=uuid4().hex,direct_video=True,direct_extension=True)
        clip=service.folder(identifier)/'scene-1.mp4'
        run([str(FFmpegAdapter.executable('ffmpeg',None)),'-nostdin','-n','-v','error',
             '-f','lavfi','-i','color=c=blue:s=144x256:r=30','-t','15','-c:v','libx264',
             '-preset','ultrafast','-pix_fmt','yuv420p',str(clip)],clip.parent)
        job=service.read(identifier);job['state']='submission_unknown'
        job['scenes']=[{'position':1,'state':'downloaded','seconds':15,'file':clip.name,
                        'sha256':sha256(clip.read_bytes()).hexdigest()},
                       {'position':2,'state':'unknown','seconds':15}]
        service.save(job);before=service.folder(identifier).joinpath('jobs.json').read_bytes()
        page.goto(origin+'/studio/characters?job_id='+identifier)
        cards=page.locator('.kling-character-scene-grid').get_by_role('button')
        expect(cards).to_have_count(2);expect(cards.nth(0)).to_be_enabled()
        expect(cards.nth(1)).to_be_disabled();cards.nth(0).click()
        preview=page.get_by_role('dialog',name='장면 1 · 15초',exact=True)
        expect(preview).to_be_visible()
        expect(preview.locator('video')).to_have_attribute('src',f'/character/{identifier}/clips/1')
        expect(preview.locator('video')).to_have_js_property('videoWidth',144)
        preview.locator('video').evaluate('(video)=>video.play()')
        expect(preview.locator('video')).to_have_js_property('paused',False)
        expect(preview.locator('video')).to_have_js_property('error',None)
        assert service.folder(identifier).joinpath('jobs.json').read_bytes()==before and not posts
        ctx.close()


def test_cancelled_direct_creation_request_is_rejected_before_provider(connected):
    c=connected;before=c.service.listing()
    import json
    from uuid import uuid4
    from newsflow.character.kling import check
    result=c.post('/character',creation_mode='direct',topic='합성 주제',episode_limit='5',
        request_id=uuid4().hex,reference_asset=c.gui.asset,
        studio_settings=json.dumps(check(c.service.read(c.identifier)['studio_selection'])))
    assert result.status_code==410
    assert c.service.listing()==before and not c.state.calls and not c.state.decryptions
