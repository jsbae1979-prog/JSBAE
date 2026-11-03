from copy import deepcopy
import pytest
from newsflow.character.episode_story import EpisodeScript, prompts
from newsflow.character.editing import write_captions, edit_timeline, load_edit_presets
from test_character_story_format import script, profile, FORMAT, FormatAuthoring

def test_single_incident_forces_all_cut_dependencies_only_when_frozen():
    value=script([5,5,5,5])
    for row in value['scenes']: row.update(continuity='cut', **{'from':None})
    story=EpisodeScript.model_validate(value);original=deepcopy(story)
    legacy=prompts(story,{'sound':'on'},profile(),FORMAT)
    rows=prompts(story,{'sound':'on'},profile(),FORMAT,'single_incident_v1')
    assert all(r['continuity']=='cut' for r in legacy)
    assert [r['from'] for r in rows]==[None,1,2,3]
    assert all(r['continuity']=='continue' for r in rows[1:])
    assert all('No dialogue' in r['prompt'] for r in rows)
    assert all('Previous action (context, do not replay)' in r['prompt'] for r in rows[1:])
    assert story==original

@pytest.mark.story_format
def test_new_job_dependency_payload_and_one_submit_per_scene(tmp_path):
    from test_character_episode_automation import setup_episode
    s,v,i,_,_=setup_episode(tmp_path,20);s.authoring=FormatAuthoring()
    assert s.read(i)['continuity_policy']=='single_incident_v1'
    s.write(i,consent=True);s.prepare(i,consent=True,script_reviewed=True)
    s.submit(i,consent=True,quote_hash=s.read(i)['quote_hash'])
    assert len(v.sent)==1
    for _ in range(5):
        if s.read(i)['state']=='clips_review':break
        s.check(i,consent=True)
    job=s.read(i)
    assert job['state']=='clips_review' and len(v.sent)==4
    for index,row in enumerate(job['scenes'][1:],1):
        assert row['dependency']['clip_sha256']==job['scenes'][index-1]['sha256']
        assert row['payload']['first_frame_url'].endswith('-last.png')
    assert len(s.authoring.calls)==1

def test_social_captions_short_emphasis_safe_and_classic_available(tmp_path):
    value=script([5,5,5,5]);value['scenes'][0]['caption']=value['hook_caption']
    story=EpisodeScript.model_validate(value);timeline=edit_timeline(story,20);presets=load_edit_presets()
    path=tmp_path/'social.ass';write_captions(path,story,timeline,presets)
    text=path.read_text(encoding='utf-8-sig')
    assert 'Style: Hook,Noto Sans KR,104' in text and 'Style: Beat,Noto Sans KR,96' in text
    assert 'Style: Payoff' in text and r'\fad(80,100)' in text and r'\pos(510,1370)' in text
    assert text.count(story.hook_caption)==1
    assert '0:00:02.60' in text and text.count('Dialogue:')==4
    presets['caption']['preset']='classic'
    write_captions(path,story,timeline,presets)
    assert 'Style: Hook' not in path.read_text(encoding='utf-8-sig')
