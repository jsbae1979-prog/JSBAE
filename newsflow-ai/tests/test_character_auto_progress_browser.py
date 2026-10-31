"""Automatic follow-up of approved synthetic receipts; every HTTP side effect is Fake."""
from pathlib import Path
import hashlib
import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_episode_automation import setup_episode
from test_character_story_feedback_browser import NoSecret
from newsflow.video.engine import FFmpegAdapter

def prepared(app,monkeypatch):
    monkeypatch.setattr(FFmpegAdapter,'executable',staticmethod(lambda *a:Path('synthetic-tool.exe')))
    s,v,i,_,_=setup_episode(app.state.config.data_dir)
    s.write(i,consent=True);s.prepare(i,consent=True,script_reviewed=True)
    s.submit(i,consent=True,quote_hash=s.read(i)['quote_hash'])
    s.sessions=app.state.sessions;s._manual_character_execution_enabled=True
    app.state.character=s;app.state.character_authoring=s.authoring
    app.state.api_keys={'claude_api':NoSecret()}
    return s,i

def downloaded(service,identifier,row):
    path=service.folder(identifier)/f'scene-{row["position"]}.mp4'
    path.write_bytes(b'owned Fake provider bytes')
    row.update(state='downloaded',file=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
               media={'duration':row['seconds'],'width':720,'height':1280,'has_audio':True})

def context(browser,origin):
    ctx=browser.new_context(viewport={'width':1366,'height':768})
    ctx.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
    page=ctx.new_page();page.clock.install()
    return ctx,page

def test_approved_job_follows_saves_and_finishes_without_clicking_each_scene(app,browser,monkeypatch):
    s,i=prepared(app,monkeypatch);checks=[];posts=[]
    with local_server(app) as origin:
        ctx,page=context(browser,origin)
        def check(route):
            assert route.request.method=='POST' and 'consent=true' in route.request.post_data
            assert 'csrf_token=' in route.request.post_data
            checks.append(1);job=s.read(i)
            downloaded(s,i,job['scenes'][len(checks)-1])
            if len(checks)==1:job['scenes'][1]['state']='submitted'
            else:job['state']='clips_review'
            s.save(job);route.fulfill(status=303,headers={'Location':'/character?job_id='+i})
        page.route('**/character/'+i+'/check',check)
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters?job_id='+i)
        panel=page.get_by_role('region',name='영상 제작 진행',exact=True)
        expect(panel).to_contain_text('완료 0/2')
        expect(page.get_by_text('장면 생성 중 · 자동 확인',exact=True)).to_be_visible()
        page.clock.fast_forward(11000)
        expect(panel).to_contain_text('완료 1/2');expect(panel).to_contain_text('50%')
        expect(page.get_by_role('progressbar',name='장면 저장 진행률',exact=True)).to_have_attribute('value','1')
        page.clock.fast_forward(11000)
        expect(panel).to_contain_text('완료 2/2');expect(panel).to_contain_text('100%')
        expect(panel).to_contain_text('장면 검토 준비 완료')
        expect(page.get_by_role('button',name='검토 후 영상 합성',exact=True)).to_be_enabled()
        page.clock.fast_forward(60000)
        assert len(checks)==2 and len(posts)==2 and all(url.endswith('/check') for url in posts)
        for width,height in ((1366,768),(1920,1080)):
            page.set_viewport_size({'width':width,'height':height})
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
            page.screenshot(path=str(Path(r'C:/Codex/NewsFlowAI/character_automation_operating')/f'auto-progress-{width}x{height}.png'),full_page=True)
        ctx.close()

@pytest.mark.parametrize('failure',['http','failed','unknown','not_sent'])
def test_any_failed_check_or_scene_stops_automatic_followup_without_replay(app,browser,monkeypatch,failure):
    s,i=prepared(app,monkeypatch);checks=[]
    with local_server(app) as origin:
        ctx,page=context(browser,origin)
        def check(route):
            checks.append(1)
            if failure=='http':return route.fulfill(status=409,json={'detail':'Synthetic stopped'})
            job=s.read(i);job['scenes'][0]['state']=failure
            job['state']='scene_review' if failure=='failed' else 'submission_unknown' if failure=='unknown' else 'submission_not_sent'
            s.save(job);route.fulfill(status=303,headers={'Location':'/character?job_id='+i})
        page.route('**/character/'+i+'/check',check)
        page.goto(origin+'/studio/characters?job_id='+i)
        expect(page.get_by_role('region',name='영상 제작 진행')).to_be_visible()
        page.clock.fast_forward(11000)
        if failure=='http':expect(page.get_by_role('button',name='진행 확인 재개',exact=True)).to_be_visible()
        else:expect(page.get_by_role('region',name='영상 제작 진행')).to_contain_text('확인 필요')
        page.clock.fast_forward(60000)
        assert len(checks)==1
        ctx.close()

def test_caption_sfx_review_matches_v3_and_does_not_compose_automatically(app,browser,monkeypatch):
    s,i=prepared(app,monkeypatch);job=s.read(i)
    for row in job['scenes']:downloaded(s,i,row)
    job['state']='clips_review';s.save(job)
    with local_server(app) as origin:
        ctx,page=context(browser,origin);posts=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters?job_id='+i)
        button=page.get_by_role('button',name='검토 후 영상 합성',exact=True)
        expect(button).to_be_enabled();page.clock.fast_forward(60000);assert not posts
        button.click();dialog=page.get_by_role('dialog')
        expect(dialog).to_contain_text('자막·코믹 효과음을 더하고')
        expect(dialog).to_contain_text('새 음성·나레이션은 추가하지 않습니다.')
        assert not posts
        ctx.close()
