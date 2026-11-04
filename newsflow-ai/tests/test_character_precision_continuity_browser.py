"""Synthetic Chromium: preserved old work, local connection revision, no API dispatch."""
from copy import deepcopy
from pathlib import Path
import os
import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_news_collection_controls_browser import browser_context
from test_character_precision import precision, confirmed


@pytest.fixture(autouse=True)
def dist(monkeypatch):
    monkeypatch.setattr('newsflow.studio.resources.studio_dist_root',lambda:Path(os.environ['EDITORIAL_TEST_DIST']))

def test_connection_revision_opens_editor_and_requires_explicit_valid_plan(precision,browser,monkeypatch,tmp_path):
    f=precision;w=confirmed(f);w=f.s.handoff(w['id'],w['revision'])
    jid=w['video_job_id'];f.owner.prepare(jid,consent=True,script_reviewed=True)
    f.owner.submit(jid,consent=True,quote_hash=f.owner.read(jid)['quote_hash']);f.owner.check(jid,consent=True)
    before=f.s.path(w['id']).read_bytes();video_before=f.owner.read(w['video_job_id'])
    monkeypatch.setattr('newsflow.studio.resources.studio_dist_root',lambda:Path(os.environ['EDITORIAL_TEST_DIST']))
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    f.app.state.character=f.owner;f.app.state.image_studio=f.images
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();errors=[];posts=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters?precision='+w['id'])
        page.get_by_role('button',name='연결 보완 초안 · 무료',exact=True).click()
        dialog=page.get_by_role('dialog',name='장면 내용 수정')
        expect(dialog).to_be_visible()
        expect(dialog.get_by_label('장면 시작 상태',exact=True)).to_be_visible()
        expect(dialog.get_by_label('장면 끝 상태',exact=True)).to_be_visible()
        dialog.get_by_role('button',name='장면 저장 · 무료').click()
        expect(dialog.get_by_role('alert')).to_be_visible()
        assert sum(url.endswith('/revise-connection') for url in posts)==1
        assert not any(url.endswith(('/story','/quote','/generate','/edit')) for url in posts)
        assert f.s.path(w['id']).read_bytes()==before and f.owner.read(w['video_job_id'])==video_before
        assert len(f.adapter.calls)==5 and len(f.video.sent)==5 and not errors
        page.screenshot(path=str(tmp_path/'connection-editor.png'),full_page=True)
        context.close()
