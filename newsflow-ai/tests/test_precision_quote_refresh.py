"""Explicit renewal never regenerates images or submits videos."""
from copy import deepcopy
import pytest
from playwright.sync_api import expect
from test_precision_video_preview import precision, handoff, dist, browser, local_server, browser_context
from test_character_quote_expiry_review import expired
from newsflow.character.schema import CharacterError
from newsflow.character.quote_review import quote_review
from newsflow.character.service import now

def setup(f):
    jid=handoff(f);f.owner.prepare(jid,consent=True,script_reviewed=True)
    return jid,expired(f.owner,jid)

def test_expired_precision_quote_renews_frozen_images_and_invalidates_old_approval(precision):
    f=precision;jid,old=setup(f);calls=len(f.adapter.calls)
    f.owner.prepare(jid,consent=True,script_reviewed=True)
    fresh=f.owner.read(jid)
    assert quote_review(fresh,now())['quoteStatus']=='ready'
    assert fresh['quote_hash']!=old['quote_hash']
    assert fresh['quote_history'][-1]['quote_hash']==old['quote_hash']
    assert fresh['quote_history'][-1]['scenes']==old['scenes']
    for key in ('precision','script','prompts','plan_hash','studio_selection','episode_limit'):
        assert fresh[key]==old[key]
    assert not f.video.sent and len(f.adapter.calls)==calls and not fresh.get('quote_approvals')
    with pytest.raises(CharacterError) as e:f.owner.submit(jid,consent=True,quote_hash=old['quote_hash'])
    assert e.value.code=='quote_changed' and not f.video.sent

@pytest.mark.parametrize('case',['consent','review','unknown','reserved','handle','approved'])
def test_renewal_requires_consent_and_no_submission_evidence(precision,case):
    f=precision;jid,job=setup(f)
    if case=='unknown':job['state']='submission_unknown'
    if case=='reserved':job['scenes'][0]['reserved_usd']='0.1'
    if case=='handle':job['scenes'][0]['handle']={'request_id':'existing'}
    if case=='approved':job['quote_approvals']=[{'day':'2026-11-05','usd':'0.5'}]
    f.owner.save(job);before=f.owner.read(jid)
    with pytest.raises(CharacterError):f.owner.prepare(jid,consent=case!='consent',script_reviewed=case!='review')
    assert f.owner.read(jid)==before and not f.video.sent

def test_renewal_failure_preserves_old_quote_and_blocks_stale_submit(precision):
    f=precision;jid,old=setup(f)
    def fail(payload):raise RuntimeError('synthetic estimate failed')
    f.video.estimate=fail
    with pytest.raises(CharacterError):f.owner.prepare(jid,consent=True,script_reviewed=True)
    failed=f.owner.read(jid)
    assert failed['state']=='prepare_failed' and 'quote_hash' not in failed
    assert failed['quote_history'][-1]['quote_hash']==old['quote_hash']
    assert failed['precision']==old['precision'] and not f.video.sent
    with pytest.raises(CharacterError):f.owner.submit(jid,consent=True,quote_hash=old['quote_hash'])

def test_expired_quote_refresh_opens_confirmation_without_generation(precision,browser,monkeypatch):
    f=precision;jid,old=setup(f)
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();posts=[];errors=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(origin+'/studio/characters?job_id='+jid)
        page.get_by_role('button',name='영상 생성하기',exact=True).click()
        dialog=page.get_by_role('dialog')
        expect(dialog.get_by_role('button',name='견적 승인 후 장면 생성',exact=True)).to_be_disabled()
        dialog.get_by_role('button',name='최신 견적 확인',exact=True).click()
        dialog=page.get_by_role('dialog',name='장면 공식 견적 조회',exact=True)
        expect(dialog).to_be_visible()
        assert not posts and f.owner.read(jid)==old and not f.video.sent
        # Explicit local fake renewal; do not approve video generation.
        for box in dialog.get_by_role('checkbox').all():box.check()
        dialog.get_by_role('button',name='장면 공식 견적 조회',exact=True).click()
        expect(dialog).not_to_be_visible(timeout=15000)
        page.get_by_role('button',name='영상 생성하기',exact=True).click()
        dialog=page.get_by_role('dialog')
        expect(dialog.get_by_text('견적 유효시간이 지났습니다. 최신 견적을 확인하세요.',exact=True)).to_have_count(0)
        for box in dialog.get_by_role('checkbox').all():box.check()
        expect(dialog.get_by_role('button',name='견적 승인 후 장면 생성',exact=True)).to_be_enabled()
        assert len(posts)==1 and posts[0].endswith('/prepare') and not errors and not f.video.sent
        context.close()
