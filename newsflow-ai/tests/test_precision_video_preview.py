"""Pinned still previews use local assets; no provider dispatch from viewing."""
from copy import deepcopy
from pathlib import Path
import os
import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_news_collection_controls_browser import browser_context
from test_character_precision import precision, confirmed
from newsflow.studio.read_models import character_rows


@pytest.fixture(autouse=True)
def dist(monkeypatch):
    monkeypatch.setattr('newsflow.studio.resources.studio_dist_root',lambda:Path(os.environ['EDITORIAL_TEST_DIST']))


def handoff(f):
    w=confirmed(f);w=f.s.handoff(w['id'],w['revision'])
    f.app.state.character=f.owner;f.app.state.image_studio=f.images
    return w['video_job_id']


def test_read_model_uses_pinned_images_without_modifying_job(precision):
    f=precision;jid=handoff(f)
    job=f.owner.read(jid);before=deepcopy(job)
    row=next(r for r in character_rows(f.app.state) if r['id']==jid)
    assert row['precisionImages']==[{'position':r['no'],'imageUrl':'/image-studio/assets/'+r['asset']} for r in job['precision']['images']]
    assert len(row['precisionImages'])==5 and not f.video.sent
    assert f.owner.read(jid)==before


def test_five_stills_open_then_downloaded_video_takes_priority(precision,browser,monkeypatch,tmp_path):
    f=precision;jid=handoff(f)
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    f.owner.prepare(jid,consent=True,script_reviewed=True)
    before=f.owner.read(jid)
    monkeypatch.setattr('newsflow.studio.resources.studio_dist_root',lambda:Path(os.environ['EDITORIAL_TEST_DIST']))
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();posts=[];errors=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(origin+'/studio/characters?job_id='+jid)
        grid=page.locator('.kling-character-scene-grid')
        expect(grid.locator('img')).to_have_count(5)
        expect(grid.get_by_text('영상 생성 전',exact=True)).to_have_count(5)
        urls=[grid.locator('img').nth(i).get_attribute('src') for i in range(5)]
        assert len(set(urls))==5
        for i in range(5):
            grid.locator('button').nth(i).click()
            dialog=page.get_by_role('dialog',name=f'장면 {i+1} · 확정 이미지')
            expect(dialog).to_be_visible()
            expect(dialog.locator('img')).to_have_attribute('src',urls[i])
            assert dialog.locator('img').evaluate('(el)=>el.complete && el.naturalWidth>0')
            dialog.get_by_role('button',name=f'장면 {i+1} · 확정 이미지 닫기',exact=True).click()
        assert not posts and not f.video.sent and f.owner.read(jid)==before
        # Explicit synthetic generation only; opening the cards never submitted it.
        f.owner.submit(jid,consent=True,quote_hash=before['quote_hash']);f.owner.check(jid,consent=True)
        page.reload();expect(grid.locator('video')).to_have_count(5)
        expect(grid.locator('img')).to_have_count(0)
        grid.locator('button').nth(0).click()
        expect(page.get_by_role('dialog').locator('video')).to_be_visible()
        assert not errors and not posts
        page.screenshot(path=str(tmp_path/'scene-preview.png'))
        context.close()
