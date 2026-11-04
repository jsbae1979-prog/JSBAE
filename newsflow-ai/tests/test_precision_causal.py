"""Synthetic five-scene EP01: state continuity, review gates, never paid traffic."""
from copy import deepcopy
import pytest
from test_character_precision import precision, confirmed
from test_character_precision_continuity import connected
from newsflow.character.precision_causal import POLICY, review_clip, pending_review, INSTRUCTION
from newsflow.character.precision_contract import motion_rows, image_prompt
from newsflow.character.schema import CharacterError
from newsflow.character.kling import check

def causal(p):
    connected(p)
    p.w['continuity_policy']=POLICY;p.s.save(p.w)
    for i,row in enumerate(p.story['scenes']):
        row.update(cause=f'Visible situation {i}', result=f'Visible situation {i+1}',
            prop_states=[{'id':'plate','before':f'1 plate at table position {i}',
              'after':f'1 plate at table position {i+1}','change':'The character visibly slides the plate.'}])
    return p

def submitted(p):
    w=confirmed(p);w=p.s.handoff(w['id'],w['revision']);jid=w['video_job_id']
    p.owner.prepare(jid,consent=True,script_reviewed=True)
    p.owner.submit(jid,consent=True,quote_hash=p.owner.read(jid)['quote_hash'])
    return jid

def accept(p,jid):
    pending=pending_review(p.owner.read(jid));assert pending
    review_clip(p.owner,jid,pending['position'],pending['clip_sha256'],True)

def test_new_work_has_causal_policy_and_writer_contract(precision):
    assert precision.create()['continuity_policy']==POLICY
    p=causal(precision);w=p.s.write_story(p.w['id'],1,True)
    assert w['state']=='images' and len(w['scenario']['scenes'])==5
    assert 'whole objects' in INSTRUCTION and 'visible action' in INSTRUCTION
    assert not p.adapter.calls and not p.video.sent

@pytest.mark.parametrize('mutation',[
 lambda r:r[1].update(cause='unrelated incident'),
 lambda r:r[1]['prop_states'][0].update(before='many whole cookies'),
 lambda r:r[1]['prop_states'][0].update(change=''),
 lambda r:r[2].update(prop_states=[]),
 lambda r:r[2]['prop_states'].append(deepcopy(r[2]['prop_states'][0])),
 lambda r:r[2].pop('result'),
 lambda r:r[2].update(start_state='teleport'),
])
def test_conflict_blocks_before_any_generation(precision,mutation):
    p=causal(precision);mutation(p.story['scenes'])
    with pytest.raises(ValueError):p.s.edit(p.w['id'],1,p.story)
    assert not p.adapter.calls and not p.video.sent

def test_still_contains_only_initial_prop_state_and_video_contains_cause(precision):
    p=causal(precision);w=p.s.edit(p.w['id'],1,p.story)
    still=image_prompt(w['common'],w['cast'],w['scenario']['scenes'][0])
    assert '1 plate at table position 0' in still and '1 plate at table position 1' not in still
    rows=motion_rows(w['common'],w['cast'],w['scenario']['scenes'],check(w['video_settings']),POLICY)
    assert 'Cause: Visible situation 1' in rows[1]['prompt']
    assert 'No dialogue, no voices, no music.' in rows[1]['prompt']

@pytest.mark.parametrize('intentional_cut',[False,True])
def test_five_clips_require_hash_bound_review_before_each_next(precision,intentional_cut):
    p=causal(precision)
    if intentional_cut:p.story['scenes'][1].update(connection='cut',transition_reason='Establish the same table from another angle')
    jid=submitted(p);assert len(p.video.sent)==1
    for n in range(1,6):
        p.owner.check(jid,consent=True);job=p.owner.read(jid)
        assert len(p.video.sent)==n
        if n==5:break
        assert job['state']=='scene_review' and pending_review(job)['position']==n
        p.owner.check(jid,consent=True);assert len(p.video.sent)==n
        accept(p,jid);assert len(p.video.sent)==n
        p.owner.check(jid,consent=True);assert len(p.video.sent)==n+1
    assert job['state']=='clips_review'
    assert p.owner.render(jid,reviewed=True).is_file()
    assert len(p.adapter.calls)==5 and len(p.video.sent)==5

@pytest.mark.parametrize('bad',['no_consent','wrong_hash','wrong_position','tamper','repeat'])
def test_review_cannot_release_wrong_or_unreviewed_clip(precision,bad):
    p=causal(precision);jid=submitted(p);p.owner.check(jid,consent=True)
    r=pending_review(p.owner.read(jid))
    if bad=='repeat':accept(p,jid)
    if bad=='tamper':(p.owner.folder(jid)/'scene-1.mp4').write_bytes(b'changed synthetic media')
    with pytest.raises(CharacterError):review_clip(p.owner,jid,2 if bad=='wrong_position' else r['position'],
        '0'*64 if bad=='wrong_hash' else r['clip_sha256'],bad!='no_consent')
    assert len(p.video.sent)==1

def test_reviewed_quote_increase_preserves_clip_without_submit(precision):
    p=causal(precision);jid=submitted(p);p.owner.check(jid,consent=True)
    accept(p,jid);p.video.estimate=lambda payload:'0.11'
    with pytest.raises(CharacterError):p.owner.check(jid,consent=True)
    assert len(p.video.sent)==1 and p.owner.read(jid)['scenes'][0]['state']=='downloaded'

def test_review_endpoint_requires_csrf_and_is_catalogued(client):
    import json
    from pathlib import Path
    response=client.post('/character/'+'a'*32+'/review-clip',data={'position':1,'clip_sha256':'b'*64,'consent':True})
    assert response.status_code==403
    root=Path(__file__).resolve().parents[1]
    entries=[next(x for x in json.loads((root/path).read_text(encoding='utf8')) if x['id']=='character_review_clip')
        for path in ['src/newsflow/studio/actions.json','frontend/src/legacy-actions.json']]
    assert entries[0]==entries[1] and entries[0]['risk']=='local'

@pytest.mark.parametrize('failure',['failed','unknown'])
def test_failed_or_unknown_does_not_offer_review_or_dispatch(precision,failure):
    p=causal(precision)
    if failure=='unknown':
        p.video.unknown=True
        with pytest.raises(CharacterError):submitted(p)
        jid=p.w['id']
    else:
        jid=submitted(p);p.video.fail=True
    p.owner.check(jid,consent=True)
    assert pending_review(p.owner.read(jid)) is None and len(p.video.sent)==1

def test_operating_wrapper_allows_only_local_review_with_csrf(precision):
    from starlette.testclient import TestClient
    from bat_distribution.operation import OperatingRequests
    p=causal(precision);jid=submitted(p);p.owner.check(jid,consent=True)
    p.app.state.character=p.owner;p.app.state.image_studio=p.images
    r=pending_review(p.owner.read(jid))
    with TestClient(OperatingRequests(p.app),base_url='http://127.0.0.1') as client:
        client.get('/studio/characters')
        values={'position':r['position'],'clip_sha256':r['clip_sha256'],'consent':'true'}
        url='/character/'+jid+'/review-clip'
        assert client.post(url,data=values).status_code==403
        values['csrf_token']=client.cookies.get('newsflow_csrf')
        response=client.post(url,data=values)
        assert response.status_code==200,response.text[:200]
        assert len(p.video.sent)==1
