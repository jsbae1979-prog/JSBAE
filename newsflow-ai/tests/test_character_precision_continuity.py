"""No paid providers: versioned continuity, dependency dispatch and preserved originals."""
from copy import deepcopy
from uuid import uuid4
import pytest
from test_character_precision import precision, confirmed
from newsflow.character.precision_contract import CONTINUITY_POLICY, motion_rows, image_prompt, validate_scenario
from newsflow.character.kling import check
from newsflow.video_models.catalog import CATALOG
from newsflow.character.schema import CharacterError


def connected(p):
    p.w=p.create()
    p.w['continuity_policy']=CONTINUITY_POLICY
    p.s.save(p.w)
    # Same single character throughout this synthetic sequence.
    for i,row in enumerate(p.story['scenes']):
        row.update(characters=[p.ids[0]],connection='cut' if i==0 else 'continue',
            set_id='kitchen',environment='Rainy morning, soft light',
            start_state=f'Character at table, hand position {i}',
            end_state=f'Character at table, hand position {i+1}',transition_reason='')
    return p


def test_five_scenes_wait_for_verified_previous_frame_and_compose(precision):
    p=connected(precision);w=confirmed(p);w=p.s.handoff(w['id'],w['revision']);jid=w['video_job_id']
    initial=p.owner.read(jid)
    assert [r['from'] for r in initial['prompts']]==[None,1,2,3,4]
    assert 'Previous action:' in initial['prompts'][1]['prompt']
    assert 'Next scene starts:' in initial['prompts'][0]['prompt']
    assert 'Rainy morning' in initial['prompts'][1]['prompt']
    p.owner.prepare(jid,consent=True,script_reviewed=True);q=p.owner.read(jid)
    p.owner.submit(jid,consent=True,quote_hash=q['quote_hash'])
    assert len(p.video.sent)==1
    assert [r['state'] for r in p.owner.read(jid)['scenes']]==['submitted']+['waiting_dependency']*4
    for n in range(1,6):
        p.owner.check(jid,consent=True)
        job=p.owner.read(jid)
        assert len(p.video.sent)==min(n+1,5)
        if n<5:
            row=job['scenes'][n];parent=job['scenes'][n-1]
            assert row['payload']['first_frame_url'].endswith(f'scene-{n}-t1-last.png')
            assert row['dependency']['clip_sha256']==parent['sha256']
            assert row['dependency']['frame_sha256']==parent['last_frame_sha256']
            assert row['payload']['image_urls']==[row['quoted_reference']]
    assert job['state']=='clips_review'
    final=p.owner.render(jid,reviewed=True)
    assert final.is_file() and len(p.video.sent)==5 and len(p.adapter.calls)==5


@pytest.mark.parametrize('mutation',[
 lambda s:s[1].update(continuity=''),lambda s:s[1].update(environment='Sunny afternoon'),
 lambda s:s[1].update(location='Vending machine'),lambda s:s[1].update(start_state='Teleport'),
 lambda s:s[1].update(characters=[]),lambda s:s[0].update(connection='continue'),
 lambda s:s[2].update(connection='cut',transition_reason=''),
])
def test_bad_connection_rejected_before_images_or_video(precision,mutation):
    p=connected(precision);mutation(p.story['scenes'])
    with pytest.raises(ValueError):p.s.edit(p.w['id'],p.w['revision'],p.story)
    assert not p.adapter.calls and not p.video.sent and not p.video.uploads


def test_intentional_location_cut_is_explicit_and_not_a_dependency(precision):
    p=connected(precision)
    for r in p.story['scenes'][2:]:r.update(set_id='hall',location='Hall',environment='Same rainy morning')
    p.story['scenes'][2].update(connection='cut',transition_reason='After leaving the kitchen, establish the hall doorway.')
    w=p.s.edit(p.w['id'],1,p.story)
    rows=motion_rows(w['common'],w['cast'],w['scenario']['scenes'],check(w['video_settings']),CONTINUITY_POLICY)
    assert rows[2]['from'] is None and rows[3]['from']==3
    assert 'Transition: After leaving' in rows[2]['prompt']
    assert 'Next scene starts:' not in rows[1]['prompt']
    assert 'No dialogue, no voices, no music.' in rows[2]['prompt']
    prompt=image_prompt(w['common'],w['cast'],w['scenario']['scenes'][1])
    assert 'start_state' in prompt and 'Rainy morning' in prompt
    assert w['scenario']['scenes'][1]['caption'] not in prompt


@pytest.mark.parametrize('unknown',[False,True])
def test_failure_never_dispatches_dependent_scenes(precision,unknown):
    p=connected(precision);w=confirmed(p);w=p.s.handoff(w['id'],w['revision']);jid=w['video_job_id']
    p.owner.prepare(jid,consent=True,script_reviewed=True);q=p.owner.read(jid)
    p.video.unknown=unknown
    if unknown:
        with pytest.raises(CharacterError):p.owner.submit(jid,consent=True,quote_hash=q['quote_hash'])
    else:p.owner.submit(jid,consent=True,quote_hash=q['quote_hash']);p.video.fail=True
    p.owner.check(jid,consent=True)
    assert len(p.video.sent)==1
    assert all(r['state']=='waiting_dependency' for r in p.owner.read(jid)['scenes'][1:])


def test_dependency_quote_increase_stops_without_resubmit(precision):
    p=connected(precision);w=confirmed(p);w=p.s.handoff(w['id'],w['revision']);jid=w['video_job_id']
    p.owner.prepare(jid,consent=True,script_reviewed=True);q=p.owner.read(jid)
    p.owner.submit(jid,consent=True,quote_hash=q['quote_hash']);p.video.estimate=lambda payload:'0.11'
    with pytest.raises(CharacterError):p.owner.check(jid,consent=True)
    assert len(p.video.sent)==1
    assert p.owner.read(jid)['scenes'][1]['state']=='dependency_quote_changed'


def test_new_revision_preserves_source_assets_and_has_no_approvals(precision):
    p=precision;w=confirmed(p);before=p.s.path(w['id']).read_bytes()
    assets={v['asset']:p.images.asset(v['asset']).read_bytes() for s in w['scenes'] for v in s['versions']}
    request=uuid4().hex
    new=p.s.revise_connection(w['id'],w['revision'],request)
    assert new['id']!=w['id'] and new['state']=='connection_review'
    assert not new['story_attempts'] and not new.get('quote') and not new.get('video_job_id')
    assert all(not s['versions'] and s['confirmed'] is None for s in new['scenes'])
    assert new['reference_history']==w['scenes']
    assert p.s.revise_connection(w['id'],w['revision'],request)==new
    assert p.s.path(w['id']).read_bytes()==before
    assert all(p.images.asset(a).read_bytes()==raw for a,raw in assets.items())
    with pytest.raises(ValueError):p.s.quote(new['id'],1,[1])
    assert len(p.adapter.calls)==5 and not p.video.sent


def test_new_revision_cannot_bypass_pending_video(precision):
    p=precision;w=confirmed(p);w=p.s.handoff(w['id'],w['revision'])
    job=p.owner.read(w['video_job_id']);job['state']='submission_unknown';p.owner.save(job)
    with pytest.raises(ValueError):p.s.revise_connection(w['id'],w['revision'],uuid4().hex)


def test_new_route_requires_csrf(client):
    assert client.post('/api/studio/character-precision/'+'a'*32+'/revise-connection',
        data={'revision':'1','request_id':'b'*32}).status_code==403


def test_new_story_writer_receives_continuity_contract(precision):
    p=connected(precision);w=p.s.write_story(p.w['id'],1,True)
    assert w['state']=='images' and p.writer.calls[0]['work']['duration']==26
    assert [s['plan']['connection'] for s in w['scenes']]==['cut']+['continue']*4
    assert not p.adapter.calls and not p.video.sent


def test_changed_parent_cannot_be_submitted(precision):
    p=connected(precision);w=confirmed(p);w=p.s.handoff(w['id'],w['revision'])
    job=p.owner.read(w['video_job_id']);job['script']['scenes'][2]['from']=1
    from newsflow.character.precision_video import validate
    with pytest.raises(CharacterError):validate(job,job['script'])
    assert not p.video.sent


def test_kling3_replaces_image_url_with_previous_end_frame(precision):
    from newsflow.character.kling import K3, KlingClient, snapshot
    p=connected(precision)
    settings={**check(p.w['video_settings']),'video_model':K3,'native_resolution':'model_default'}
    p.w['video_settings']=snapshot(settings,precise=True);p.s.save(p.w)
    p.video.client=KlingClient(p.video.credential,settings,precise=True)
    w=confirmed(p);w=p.s.handoff(w['id'],w['revision']);jid=w['video_job_id']
    p.owner.prepare(jid,consent=True,script_reviewed=True)
    p.owner.submit(jid,consent=True,quote_hash=p.owner.read(jid)['quote_hash'])
    p.owner.check(jid,consent=True)
    assert len(p.video.sent)==2
    payload=p.video.sent[1][0]
    assert payload['image_url'].endswith('scene-1-t1-last.png')
    assert 'first_frame_url' not in payload
    assert 'Previous action:' in payload['prompt']
