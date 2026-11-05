"""Synthetic set references and existing Fake-video/FFmpeg path; no live calls."""
from copy import deepcopy
import hashlib
import pytest
from test_character_precision import precision, generated, confirmed
from test_precision_causal import causal, accept
from newsflow.character import precision_visual as visual
from newsflow.character.service import fingerprint
from newsflow.gui.character_precision_routes import perform
from newsflow.publishing.service import PublishingError
from newsflow.character.kling import K3, O3, check, snapshot, KlingClient, CATALOG

def prepare(p):
    causal(p)
    if getattr(p,'requested_model',None):
        settings={**check(p.w['video_settings']),'video_model':p.requested_model,'native_resolution':CATALOG.model(p.requested_model)['default_resolution']}
        p.w['video_settings']=snapshot(settings,precise=True)
        p.video.client=KlingClient(p.video.credential,settings,precise=True)
    p.w['visual_reference_policy']=visual.POLICY
    p.w['prompt_version']='scene-still-v4'
    # Two generic registered identities, not a hardcoded product character.
    for row in p.story['scenes']:row['characters']=p.ids
    p.s.save(p.w)
    return p.s.edit(p.w['id'],p.w['revision'],p.story)

def make(p,w,numbers,regenerate=False):
    w=p.s.quote(w['id'],w['revision'],numbers,regenerate)
    return p.s.generate(w['id'],w['quote']['hash'],True,True)

def anchor(p):
    w=make(p,prepare(p),[1])
    return p.s.confirm(w['id'],w['revision'],1,1,True)

def all_images(p):
    w=make(p,anchor(p),[2,3,4,5])
    for no in range(2,6):w=p.s.confirm(w['id'],w['revision'],no,1,True)
    return w

def test_new_work_and_ui_require_first_set_review_without_auto_calls(precision):
    p=precision;assert p.create()['visual_reference_policy']==visual.POLICY
    w=prepare(p);view=perform(lambda:w)
    assert [s['image_ready'] for s in view['scenes']]==[True,False,False,False,False]
    assert [s.get('visual_anchor_scene') for s in view['scenes']]==[None,1,1,1,1]
    assert 'image_ready' not in w['scenes'][0]
    for numbers in ([2],[1,2,3,4,5]):
        with pytest.raises(ValueError):p.s.quote(w['id'],w['revision'],numbers)
    w=make(p,w,[1]);assert len(p.adapter.calls)==1
    with pytest.raises(ValueError):p.s.quote(w['id'],w['revision'],[2])
    assert w['scenes'][0]['confirmed'] is None

def test_five_images_use_approved_set_bytes_and_keep_character_roles(precision):
    p=precision;w=anchor(p);first=deepcopy(w['scenes'][0])
    q=p.s.quote(w['id'],w['revision'],[2,3,4,5])['quote']
    assert all(b['referenceCount']==3 and b['visual_anchor']['scene']==1 for b in q['bounds'])
    w=p.s.generate(w['id'],q['hash'],True,True)
    assert w['scenes'][0]==first and len(p.adapter.calls)==5
    expected=p.images.asset(first['versions'][0]['asset']).read_bytes()
    for row,call in zip(w['scenes'][1:],p.adapter.calls[1:]):
        assert call['refs'][-1]==expected
        assert call['refs'][:2]==[p.images.asset(w['cast'][cid]['asset']).read_bytes() for cid in p.ids]
        assert 'Reference roles: images 1 through 2' in call['prompt']
        assert 'Image 3 is the user-approved set reference' in call['prompt']
        assert 'Each attached reference corresponds in order to characters.' not in call['prompt']
        assert 'current before-state' in call['prompt'] and 'Do not mirror' in call['prompt']
        assert row['versions'][0]['visual_anchor']['sha256']==hashlib.sha256(expected).hexdigest()
        assert row['confirmed'] is None

def test_reference_cost_count_and_budget_stop_before_any_new_call(precision):
    p=precision;w=anchor(p);row=w['scenes'][1]
    with_anchor=p.s.estimate(w,row)
    legacy=deepcopy(w);legacy.pop('visual_reference_policy')
    without=p.s.estimate(legacy,row)
    assert float(with_anchor['reserveUsd'])>float(without['reserveUsd'])
    q=p.s.quote(w['id'],w['revision'],[2]);p.readiness.limit='0.001'
    with pytest.raises(ValueError):p.s.generate(w['id'],q['quote']['hash'],True,True)
    assert len(p.adapter.calls)==1

@pytest.mark.parametrize('consent,refs',[(False,True),(True,False),(False,False)])
def test_reference_and_cost_consent_required(precision,consent,refs):
    p=precision;w=anchor(p);q=p.s.quote(w['id'],w['revision'],[2])
    with pytest.raises(ValueError):p.s.generate(w['id'],q['quote']['hash'],consent,refs)
    assert len(p.adapter.calls)==1

def test_changed_anchor_invalidates_dependants_without_deleting_outputs(precision):
    p=precision;w=all_images(p);old=deepcopy(w['scenes'][1:])
    w=make(p,w,[1],True);w=p.s.confirm(w['id'],w['revision'],1,2,True)
    assert w['scenes'][1:]==old
    view=perform(lambda:w)
    assert all(not s['confirmed_valid'] for s in view['scenes'][1:])
    with pytest.raises(ValueError):p.s.confirm(w['id'],w['revision'],2,1,True)
    with pytest.raises(ValueError):p.s.handoff(w['id'],w['revision'])
    assert not p.video.sent
    # Selecting the original anchor revalidates the original exact dependencies for free.
    w=p.s.confirm(w['id'],w['revision'],1,1,True)
    assert all(s['confirmed_valid'] for s in perform(lambda:w)['scenes'])
    assert len(p.adapter.calls)==6

def test_selected_regeneration_keeps_other_versions_and_reviews(precision):
    p=precision;w=all_images(p);others=deepcopy([s for s in w['scenes'] if s['plan']['no']!=3])
    w=make(p,w,[3],True)
    assert [s for s in w['scenes'] if s['plan']['no']!=3]==others
    assert len(w['scenes'][2]['versions'])==2 and w['scenes'][2]['confirmed'] is None

def test_reference_tamper_fails_before_execution_or_reservation(precision):
    p=precision;w=anchor(p);q=p.s.quote(w['id'],w['revision'],[2])
    p.images.asset(w['scenes'][0]['versions'][0]['asset']).write_bytes(b'synthetic broken image')
    before=p.s.read(w['id'])
    with pytest.raises(PublishingError):p.s.generate(w['id'],q['quote']['hash'],True,True)
    assert p.s.read(w['id'])==before and len(p.adapter.calls)==1

def test_anchor_cannot_be_quoted_with_its_dependants_even_when_confirmed(precision):
    p=precision;w=all_images(p)
    with pytest.raises(ValueError):p.s.quote(w['id'],w['revision'],[1,2],True)
    assert len(p.adapter.calls)==5

def test_reference_capacity_not_silently_expanded(precision,monkeypatch):
    p=precision;w=anchor(p)
    monkeypatch.setattr('newsflow.publishing.image_reference.reference_capacity',lambda model:2)
    with pytest.raises(ValueError):p.s.quote(w['id'],w['revision'],[2])
    assert len(p.adapter.calls)==1

def test_new_location_has_own_anchor_and_does_not_reuse_kitchen(precision):
    p=precision;w=prepare(p)
    changed=deepcopy(w['scenario'])
    for row in changed['scenes'][3:]:row.update(set_id='garden',location='garden',environment='sunlight')
    changed['scenes'][3].update(connection='cut',transition_reason='Establish garden after walking outside')
    w=p.s.edit(w['id'],w['revision'],changed)
    view=perform(lambda:w)
    assert [s['image_ready'] for s in view['scenes']]==[True,False,False,True,False]
    assert view['scenes'][4]['visual_anchor_scene']==4

def test_existing_work_has_original_reference_contract(precision):
    p=precision;w=generated(p)
    assert [len(c['refs']) for c in p.adapter.calls]==[1,2,2,1,2]
    assert all(v.get('visual_anchor') is None for s in w['scenes'] for v in s['versions'])

@pytest.mark.parametrize('model',[K3,O3])
def test_five_scene_fake_video_and_ffmpeg_after_set_review(precision,model):
    p=precision;p.requested_model=model;w=all_images(p);w=p.s.handoff(w['id'],w['revision']);jid=w['video_job_id']
    p.owner.prepare(jid,consent=True,script_reviewed=True)
    p.owner.submit(jid,consent=True,quote_hash=p.owner.read(jid)['quote_hash'])
    assert len(p.video.sent)==1
    for n in range(1,6):
        p.owner.check(jid,consent=True);job=p.owner.read(jid)
        assert len(p.video.sent)==n
        if n==5:break
        p.owner.check(jid,consent=True);assert len(p.video.sent)==n
        accept(p,jid)
        p.owner.check(jid,consent=True)
        next_row=p.owner.read(jid)['scenes'][n]
        assert next_row['dependency']['clip_sha256']==job['scenes'][n-1]['sha256']
    assert job['state']=='clips_review'
    final=p.owner.render(jid,reviewed=True)
    assert final.is_file() and len(p.video.sent)==5 and len(p.adapter.calls)==5
    assert job['model']==model
    from newsflow.video.ai.clips import probe_clip
    media=probe_clip(final,p.owner.ffprobe)
    assert media['duration']==pytest.approx(26,abs=0.2)
