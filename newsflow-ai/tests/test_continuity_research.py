"""No external calls: preserve legacy prompts, prove frame handoff and limits locally."""
from copy import deepcopy
import pytest
from PIL import Image
from newsflow.character.episode_story import EpisodeScript, prompts, script_input, script_instruction, validate_episode
from newsflow.character.scene_continuity import POLICY
from newsflow.character.kling import O3, K3, VIDEO_PROMPT_LIMIT
from newsflow.video_models.catalog import CATALOG
from newsflow.character.compose import run, digest
from test_character_story_format import FORMAT, FormatAuthoring, script, profile
from test_character_episode_automation import setup_episode


@pytest.mark.parametrize('seconds,lengths', [(15,[5]*3),(20,[5]*4),(30,[5]*6),(35,[5]*7),(60,[5]*12)])
def test_connected_beats_keep_duration_and_user_script(seconds,lengths):
    value=script(lengths)
    for row in value['scenes']: row.update(continuity='cut', **{'from':None})
    story=validate_episode(value,seconds,CATALOG.model(O3),True,FORMAT)
    before=deepcopy(story)
    rows=prompts(story,{'sound':'on'},profile(),FORMAT,POLICY)
    assert sum(r['seconds'] for r in rows)==seconds and len(rows)==len(lengths)
    assert [r['from'] for r in rows]==[None,*range(1,len(lengths))]
    assert all(r['continuity']=='continue' for r in rows[1:])
    assert story==before
    assert all('No dialogue, no voices, no music' in r['prompt'] for r in rows)
    assert 'Payoff reaction' in rows[-1]['prompt']


def test_long_valid_fields_are_not_truncated_or_blocked_by_boilerplate():
    hero=profile();hero.update(appearance='A'*400,style_lock='B'*600)
    value=script([5]*4)
    for row in value['scenes']:row.update(action='C'*300,camera='D'*120,sound='E'*100)
    rows=prompts(EpisodeScript.model_validate(value),{'sound':'on'},hero,FORMAT,POLICY)
    for row in rows:
        text=row['prompt']
        assert len(text)<=VIDEO_PROMPT_LIMIT
        for field in ['A'*400,'B'*600,'C'*300,'D'*120,'E'*100]:assert field in text
    assert 'Prior plan' not in rows[1]['prompt']
    assert 'supplied final frame' in rows[1]['prompt']


def test_only_new_policy_changes_writer_input_without_mutating_profiles():
    first=profile();second=profile();second.update(name_ko='두리',personality='신중함',appearance='Original purple otter')
    before=deepcopy([first,second])
    inputs=[script_input(p,'합성 주제',20,CATALOG.model(O3),True,(),FORMAT,POLICY) for p in [first,second]]
    assert [p['character']['name_ko'] for p in inputs]==['별','두리']
    assert [p['character']['personality'] for p in inputs]==['침착함','신중함']
    assert all('supporting_cast' not in p['character'] for p in inputs)
    assert 'supporting_cast' in script_input(first,'합성',20,CATALOG.model(O3),True,(),FORMAT)['character']
    assert [first,second]==before
    text=script_instruction(FORMAT,POLICY)
    assert 'Quick cuts:' not in text and 'Supporting cast:' not in text
    assert 'one achievable main action' in text and 'visibly picked up' in text
    assert 'ONLY the selected character' in text
    assert script_instruction(FORMAT,'single_incident_v1')==script_instruction(FORMAT)
    story=EpisodeScript.model_validate(script([5]*4))
    a=prompts(story,{'sound':'off'},first,FORMAT,POLICY)
    b=prompts(story,{'sound':'on'},second,FORMAT,POLICY)
    assert all(first['appearance'] in r['prompt'] and second['appearance'] not in r['prompt'] for r in a)
    assert all(second['appearance'] in r['prompt'] and first['appearance'] not in r['prompt'] for r in b)
    assert all('Silent video.' in r['prompt'] and 'Ambient effects only' not in r['prompt'] for r in a)


@pytest.mark.story_format
def test_story_handoff_uses_true_last_frame_with_identity_and_quote_unchanged(tmp_path):
    s,v,i,_,_=setup_episode(tmp_path,20);s.authoring=FormatAuthoring()
    s.write(i,consent=True);s.prepare(i,consent=True,script_reviewed=True)
    def fetch(status,path,cancel):
        run([str(v.ffmpeg),'-nostdin','-n','-v','error','-f','lavfi','-i',
             "color=c=blue:s=144x256:r=30:d=5,drawbox=color=red:t=fill:enable='eq(n,149)'",
             '-c:v','libx264','-crf','0','-pix_fmt','yuv420p',str(path)],path.parent)
    v.fetch=fetch
    before=deepcopy(s.read(i));s.submit(i,consent=True,quote_hash=before['quote_hash'])
    assert len(v.sent)==1
    s.check(i,consent=True);job=s.read(i)
    assert len(v.sent)==2 and len(s.authoring.calls)==1
    frame=s.folder(i)/'frames/scene-1-t1-last.png'
    with Image.open(frame) as picture:r,g,b=picture.convert('RGB').getpixel((72,128))
    assert r>200 and b<30
    assert job['scenes'][1]['dependency']['clip_sha256']==job['scenes'][0]['sha256']
    assert job['scenes'][1]['dependency']['frame_sha256']==digest(frame)
    assert job['scenes'][1]['payload']['image_urls']==before['scenes'][1]['payload']['image_urls']
    assert {k:x for k,x in job['scenes'][1]['payload'].items() if k!='first_frame_url'}=={
        k:x for k,x in before['scenes'][1]['payload'].items() if k!='first_frame_url'}
    assert job['episode_limit']==before['episode_limit']


@pytest.mark.story_format
@pytest.mark.parametrize('failure',['failed','unknown'])
def test_story_failed_parent_never_dispatches_or_retries_children(tmp_path,failure):
    from newsflow.character.schema import CharacterError
    s,v,i,_,_=setup_episode(tmp_path,20);s.authoring=FormatAuthoring()
    s.write(i,consent=True);s.prepare(i,consent=True,script_reviewed=True)
    v.unknown=failure=='unknown';v.fail=failure=='failed'
    if v.unknown:
        with pytest.raises(CharacterError):s.submit(i,consent=True,quote_hash=s.read(i)['quote_hash'])
    else:s.submit(i,consent=True,quote_hash=s.read(i)['quote_hash'])
    s.check(i,consent=True)
    assert len(v.sent)==1 and len(s.authoring.calls)==1
    assert all(row['state']=='waiting_dependency' for row in s.read(i)['scenes'][1:])
