"""Local image reuse: fake network only, no operational assets."""
from copy import deepcopy
import json
from decimal import Decimal
from pathlib import Path
import pytest
from test_character_precision import precision
from test_precision_visual import prepare, make, all_images
from newsflow.character import precision_visual as visual
from newsflow.character.precision_contract import INSTRUCTION, image_prompt
from newsflow.publishing.service import PublishingError

def edited(p):
    w=make(p,prepare(p),[1]);original=deepcopy(w['scenes'][0]['versions'][0])
    scenario=deepcopy(w['scenario']);scenario['scenes'][0]['description']='이미 보이는 행동으로 사건을 설명한다.'
    return p.s.edit(w['id'],w['revision'],scenario),original

def test_local_reuse_preserves_original_billing_asset_and_other_scenes(precision):
    p=precision;w,original=edited(p);others=deepcopy(w['scenes'][1:])
    before=p.images.asset(original['asset']).read_bytes()
    assert not visual.matches(w,w['scenes'][0],original)
    with pytest.raises(ValueError):p.s.confirm(w['id'],w['revision'],1,1,True)
    w=p.s.reuse_image(w['id'],w['revision'],1,1,True)
    row=w['scenes'][0];v=row['versions'][-1]
    assert row['versions'][0]==original and w['scenes'][1:]==others
    assert v['kind']=='local_reuse' and v['source_version']==1
    assert v['asset']==original['asset'] and p.images.asset(v['asset']).read_bytes()==before
    assert v['reserve_usd']==v['observed_usd']=='0' and 'usage' not in v and 'run_id' not in v
    assert row['confirmed']['version']==2 and visual.matches(w,row,v)
    assert len(p.adapter.calls)==1 and not p.video.sent
    # Next scene uses exactly the reviewed, reused bytes as its set reference.
    q=p.s.quote(w['id'],w['revision'],[2])
    assert q['quote']['bounds'][0]['visual_anchor']['version']==2
    assert len(p.adapter.calls)==1

@pytest.mark.parametrize('reason',['no_review','stale_revision','tamper','unknown','changed_cast','pending'])
def test_reuse_rejects_unsafe_state_without_mutation(precision,reason):
    p=precision;w,original=edited(p)
    if reason=='tamper':p.images.asset(original['asset']).write_bytes(b'broken synthetic asset')
    if reason=='unknown':w['scenes'][0]['versions'][0]['state']='unknown';p.s.save(w)
    if reason=='changed_cast':w['scenes'][0]['plan']['characters']=p.ids[:1];p.s.save(w)
    if reason=='pending':w['state']='generating';p.s.save(w)
    snapshot=p.s.read(w['id'])
    with pytest.raises((ValueError,PublishingError)):
        p.s.reuse_image(w['id'],w['revision']-1 if reason=='stale_revision' else w['revision'],1,1,reason!='no_review')
    assert p.s.read(w['id'])==snapshot and len(p.adapter.calls)==1

def test_changed_set_reference_cannot_be_accepted_by_reuse(precision):
    p=precision;w=all_images(p);w=make(p,w,[1],True)
    w=p.s.confirm(w['id'],w['revision'],1,2,True);before=deepcopy(w)
    with pytest.raises(ValueError):p.s.reuse_image(w['id'],w['revision'],2,1,True)
    assert p.s.read(w['id'])==before and len(p.adapter.calls)==6

def test_reused_image_reaches_existing_video_handoff_without_new_image_calls(precision):
    p=precision;w=all_images(p);original=deepcopy(w['scenes'][2]['versions'][0])
    scenario=deepcopy(w['scenario']);scenario['scenes'][2]['description']='기존 이미지의 행동을 명확히 설명'
    w=p.s.edit(w['id'],w['revision'],scenario)
    w=p.s.reuse_image(w['id'],w['revision'],3,1,True)
    w=p.s.handoff(w['id'],w['revision'])
    assert p.owner.read(w['video_job_id'])['precision']['images'][2]['asset']==original['asset']
    assert len(p.adapter.calls)==5 and not p.video.sent

def test_clarity_instructions_are_generic_and_start_state_only(precision):
    p=precision;w=prepare(p);text=image_prompt(w['common'],w['cast'],w['scenes'][0]['plan'])
    assert 'Do not make the story depend solely on a tiny mark' in INSTRUCTION
    assert 'user explicitly requires a small clue' in INSTRUCTION
    assert 'phone screen' in text and 'do not invent evidence' in text
    assert 'No subtitles' in text and w['scenes'][0]['plan']['caption'] not in text
    assert '토토' not in INSTRUCTION and '루루' not in INSTRUCTION
    assert not p.adapter.calls

def test_reuse_route_requires_auth_and_both_action_catalogs(client):
    assert client.post('/api/studio/character-precision/'+'a'*32+'/reuse-image',
        data={'revision':1,'number':1,'version':1,'reviewed':True}).status_code==403
    root=Path(__file__).resolve().parents[1]
    entries=[next(x for x in json.loads((root/f).read_text(encoding='utf8')) if x['id']=='character_precision_reuse_image')
        for f in ['src/newsflow/studio/actions.json','frontend/src/legacy-actions.json']]
    assert entries[0]==entries[1] and entries[0]['risk']=='local'
