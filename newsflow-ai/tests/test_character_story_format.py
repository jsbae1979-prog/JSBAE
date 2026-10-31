"""Shorts story format: hook-first opening, loop ending, quick cuts and supporting cast looks."""
from copy import deepcopy

import pytest

from newsflow.character import editing
from newsflow.character.episode_policy import (
    LEGACY_STORY_FORMAT,
    check_story_format,
    job_story_format,
    load_story_format,
)
from newsflow.character.episode_story import (
    SCRIPT_INSTRUCTION,
    EpisodeScript,
    prompts,
    scene_prompt,
    scene_range,
    script_input,
    script_instruction,
    validate_episode,
)
from newsflow.character.kling import O3
from newsflow.character.schema import CharacterError
from newsflow.video_models.catalog import CATALOG, character_config

FORMAT = {'schema_version': 1, 'hook_first': True, 'loop_ending': True, 'short_scenes': True}


def profile():
    return {'name_ko': '별', 'species': 'rabbit', 'appearance': 'Original rabbit with a blue scarf',
            'personality': '침착함', 'comedy_formula': {'world': '사무실', 'setup': '바쁜 아침', 'reaction': '천천히 해결'},
            'style_lock': 'Original soft three dimensional animation',
            'supporting_cast': [{'id': 'team_lead', 'appearance': 'stressed tall flamingo manager in a gray suit'}],
            'audience': 'general', 'made_for_kids': False}


def script(lengths, freeze='none', end_caption=''):
    return {'schema_version': 3, 'plan': {'situation': '정원', 'escalation': '흩어짐', 'reaction': '해결', 'punchline': '꽃'},
            'title': '별의 정원', 'hook_caption': '이게 왜 날아와?', 'end_caption': end_caption,
            'upload': {'title': '별의 정원', 'description': '합성', 'hashtags': ['#코미디', '#창작', '#쇼츠']},
            'scenes': [{'no': i + 1, 'seconds': n, 'continuity': 'continue' if i else 'cut', 'from': i if i else None,
                        'action': 'The character catches a flying stapler.', 'camera': 'Fast push in',
                        'sound': 'Paper rustles', 'speed': 'normal', 'fast_intensity': None,
                        'freeze_end': freeze if i == len(lengths) - 1 else 'none', 'sfx': [], 'caption': '휙'}
                       for i, n in enumerate(lengths)]}


@pytest.mark.story_format
def test_config_defaults_are_on_and_strict():
    assert load_story_format() == FORMAT
    assert character_config()['target_duration']['default'] == 20
    for bad in ({**FORMAT, 'hook_first': 1}, {**FORMAT, 'extra': True}, {**FORMAT, 'schema_version': 2}):
        with pytest.raises(CharacterError):
            check_story_format(bad)
    assert job_story_format({}) is None and job_story_format({'story_format': FORMAT}) == FORMAT


def test_quick_cut_scene_range_and_legacy_range():
    model = CATALOG.model(O3)
    assert scene_range(20, model) == (2, 3) and scene_range(30, model) == (3, 4)
    assert scene_range(20, model, FORMAT) == (4, 6)
    assert scene_range(30, model, FORMAT) == (5, 9)
    lo, hi = scene_range(60, model, FORMAT)
    assert lo == 10 and 60 / hi >= 3


def test_loop_ending_accepts_short_final_beat_only_for_new_format():
    model = CATALOG.model(O3)
    value = script([5, 5, 5, 5])
    story = validate_episode(value, 20, model, True, FORMAT)
    assert story.scenes[-1].freeze_end == 'none' and story.end_caption == ''
    with pytest.raises(CharacterError):
        validate_episode(value, 20, model, True, None)  # legacy jobs still require a final hold
    legacy = script([10, 9], freeze='medium', end_caption='다음 이야기')
    assert validate_episode(legacy, 20, model, True, None).scenes[-1].freeze_end == 'medium'
    with pytest.raises(CharacterError):
        validate_episode(legacy, 20, model, True, FORMAT)  # two long scenes are not quick cuts


def test_loop_ending_timeline_has_no_added_hold():
    story = EpisodeScript.model_validate(script([5, 5, 5, 5]))
    rows = editing.edit_timeline(story, 20)
    assert sum(r['seconds'] for r in rows) == 20 and rows[-1]['freeze_seconds'] == 0


def test_instruction_adds_rules_only_for_new_format():
    assert script_instruction(None) == SCRIPT_INSTRUCTION
    text = script_instruction(FORMAT)
    assert 'Hook first' in text and 'Loop ending' in text and 'Quick cuts' in text and 'team_lead' in text
    assert 'must freeze_end medium or strong' not in text
    hook_only = script_instruction({**FORMAT, 'loop_ending': False, 'short_scenes': False})
    assert 'must freeze_end medium or strong' in hook_only and 'Quick cuts' not in hook_only


def test_opening_and_final_scene_directions():
    story = EpisodeScript.model_validate(script([5, 5, 5, 5]))
    new = prompts(story, {'sound': 'on'}, profile(), FORMAT)
    old = prompts(story, {'sound': 'on'}, profile(), None)
    assert 'no calm establishing shot' in new[0]['prompt'] and 'Establish the situation clearly.' in old[0]['prompt']
    assert 'so the video can loop' in new[-1]['prompt'] and 'hold the character' in old[-1]['prompt']
    assert [r['prompt'] for r in old] == [r['prompt'] for r in prompts(story, {'sound': 'on'}, profile())]


def test_supporting_cast_look_is_applied_for_natural_names():
    scene = EpisodeScript.model_validate(script([5, 5, 5, 5])).scenes[0]
    natural = scene.model_copy(update={'action': 'The panicking team lead runs in waving papers.'})
    assert 'flamingo' in scene_prompt(profile(), natural, True, 'hook', FORMAT)
    assert 'flamingo' not in scene_prompt(profile(), natural, True, 'setup', None)
    unrelated = scene.model_copy(update={'action': 'A steam lead pipe rattles.'})
    assert 'flamingo' not in scene_prompt(profile(), unrelated, True, 'hook', FORMAT)
    payload = script_input(profile(), '주제', 20, CATALOG.model(O3), True, (), FORMAT)
    assert payload['character']['supporting_cast'] == [
        {'id': 'team_lead', 'description': 'stressed tall flamingo manager in a gray suit'}]
    assert 'appearance' not in payload['character']
    assert (payload['min_scenes'], payload['max_scenes']) == (4, 6)
    legacy = script_input(profile(), '주제', 20, CATALOG.model(O3), True)
    assert legacy['character']['supporting_cast'] == [{'id': 'team_lead'}]
    assert LEGACY_STORY_FORMAT['loop_ending'] is False


class FormatAuthoring:
    response_received = True
    last_estimated_usd = '0'

    def __init__(self):
        self.calls = []

    def generate(self, instruction, payload, schema, options, **kwargs):
        self.calls.append((instruction, deepcopy(payload)))
        return schema.model_validate(script([5, 5, 5, 5]))


@pytest.mark.story_format
def test_new_job_freezes_format_and_reaches_loop_mp4(tmp_path, monkeypatch):
    from test_character_episode_automation import setup_episode

    from newsflow.character.service import generation_rows
    s, _, i, _, _ = setup_episode(tmp_path, 20)
    s.authoring = FormatAuthoring()
    assert s.read(i)['story_format'] == FORMAT
    s.write(i, consent=True)
    instruction, payload = s.authoring.calls[0]
    assert instruction == script_instruction(FORMAT) and (payload['min_scenes'], payload['max_scenes']) == (4, 6)
    # A later setting change does not invalidate the stored script or its prompts.
    from newsflow.character import episode_service
    monkeypatch.setattr(episode_service, 'load_story_format', lambda: {**FORMAT, 'loop_ending': False})
    s.prepare(i, consent=True, script_reviewed=True)
    job = s.read(i)
    rows = generation_rows(job)
    assert len(rows) == 4 and 'no calm establishing shot' in rows[0]['prompt']
    s.submit(i, consent=True, quote_hash=job['quote_hash'])
    for _ in range(6):
        if s.read(i)['state'] == 'clips_review':
            break
        s.check(i, consent=True)
    output = s.render(i, reviewed=True)
    info = s.read(i)['output']['media']
    assert output.exists() and abs(info['duration'] - 20) <= .1
