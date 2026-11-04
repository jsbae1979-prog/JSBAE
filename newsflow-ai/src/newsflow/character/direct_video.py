"""Image/topic-to-video, without a text provider or generated storyboard.

The deterministic execution segments only respect native model duration limits.
Every later segment continues the preceding verified last frame. Quotes, caps,
receipts, explicit submit and unknown-result protections remain in EpisodeFlow.
"""
from typing import Literal
from pydantic import Field
from .schema import Strict,CharacterError,clean_topic
from .episode_story import EpisodeScene
from .kling import validate_video_prompt
from newsflow.video_models.catalog import duration_values

class DirectVideoPlan(Strict):
    schema_version:Literal[4]=4
    title:str=Field(min_length=1,max_length=60)
    topic:str=Field(min_length=1,max_length=60)
    scenes:list[EpisodeScene]=Field(min_length=1,max_length=60)
    hook_caption:str=''
    end_caption:str=''
    upload:dict=Field(default_factory=dict)

def segment_lengths(total,model):
    allowed=duration_values(model)
    if type(total) is not int or total not in range(15,61,5) or not allowed:raise CharacterError('media')
    for count in range(1,61):
        short,extra=divmod(total,count)
        values=[short+1]*extra+[short]*(count-extra)
        if all(value in allowed for value in values):return values
    raise CharacterError('media')

def make_plan(topic,total,model,*,allow_continuation=False):
    topic=clean_topic(topic,60);lengths=segment_lengths(total,model)
    if type(allow_continuation) is not bool or (len(lengths)>1 and not allow_continuation):
        raise CharacterError('media')
    return DirectVideoPlan(title=topic,topic=topic,upload={'title':topic,'description':'','hashtags':[]},scenes=[
      EpisodeScene(no=i+1,seconds=seconds,continuity='cut' if i==0 else 'continue',
        **{'from':i if i else None},action="Develop the next natural part of the user's topic as one continuous visible incident.",
        camera='Natural continuous camera movement.',sound='Environmental ambience and action sounds only.',
        speed='normal',fast_intensity=None,freeze_end='none',sfx=[],caption='')
      for i,seconds in enumerate(lengths)])

def validate_plan(value,total,model,topic,*,allow_continuation=False):
    plan=DirectVideoPlan.model_validate(value)
    expected=make_plan(topic,total,model,allow_continuation=allow_continuation)
    if plan.model_dump(by_alias=True)!=expected.model_dump(by_alias=True):raise CharacterError('media')
    return plan

def continuity_context(plan, index):
    """Known instructions, not an AI-authored story or claimed video analysis."""
    scene = plan.scenes[index]
    elapsed = sum(s.seconds for s in plan.scenes[:index])
    if len(plan.scenes) == 1:
        task = 'Act out the topic as one complete incident, with a visible setup, development and ending.'
    elif index == 0:
        task = 'Begin the topic and develop its situation. Leave the action in progress for the next segment; do not end or reset the incident.'
    elif index == len(plan.scenes) - 1:
        task = 'Continue the unfinished action and its consequences, then bring this same incident to a clear visual ending within this segment.'
    else:
        task = 'Continue and develop the same unfinished action and its consequences. Leave it in progress for the next segment.'
    return {
        'topic': plan.topic, 'elapsed_seconds': elapsed,
        'segment_seconds': scene.seconds, 'total_seconds': sum(s.seconds for s in plan.scenes),
        'previous_segment': scene.from_scene,
        'previous_direction': continuity_context(plan, index - 1)['direction'] if index else '',
        'direction': task,
        'evidence': 'preceding_verified_last_frame' if index else 'original_character_reference',
    }


def prompts(plan,settings,character):
    rows=[];count=len(plan.scenes)
    for i,scene in enumerate(plan.scenes):
        context = continuity_context(plan, i)
        continuity=('Establish the situation using the character reference. ' if i==0 else
          'Continue from the supplied start image, the verified preceding clip last frame. '
          'Use its visible pose, props, location and unfinished action as the current situation. '
          'Do not restart, recap or repeat the opening. ')
        previous=('Previous segment direction (instruction, not observed result): '+context['previous_direction']+' ') if i else ''
        sound='Environmental ambience and action sounds only.' if settings['sound']=='on' else 'Silent video. No sound.'
        text=(character['style_lock']+' '+character['appearance']+' '+
          f'One coherent {context["total_seconds"]}-second short; segment {i+1}/{count}, '
          f'timeline {context["elapsed_seconds"]}-{context["elapsed_seconds"]+scene.seconds}s. '+
          'User topic (not narration): '+plan.topic+' '+continuity+previous+context['direction']+' '+
          'Keep the same character, setting and props. No unrelated incidents, recasting or time jumps. '
          'No dialogue, no voices, no music, no text on screen. '+sound)
        validate_video_prompt(text)
        rows.append({'position':scene.no,'seconds':scene.seconds,'continuity':scene.continuity,
          'from':scene.from_scene,'prompt':text,'continuation_context':context})
    return rows


def verify_continuation(job, row, parent):
    """The quoted context must belong to this topic and the immediate parent."""
    from .service import generation_rows, fingerprint
    expected = generation_rows(job)
    current = expected[row['position'] - 1]
    previous = expected[parent['position'] - 1]
    if (row['from'] != row['position'] - 1 or parent['position'] != row['from']
            or row.get('continuation_context') != current['continuation_context']
            or row.get('prompt') != current['prompt'] or row['payload'].get('prompt') != current['prompt']
            or parent.get('prompt') != previous['prompt']
            or parent['payload'].get('prompt') != previous['prompt']):
        raise CharacterError('blocked')
    return fingerprint({'current': current['continuation_context'], 'previous_prompt': previous['prompt']})


def timeline(plan):
    rows=[];cursor=0
    for scene in plan.scenes:
        rows.append({'no':scene.no,'start':cursor,'seconds':scene.seconds,'source_seconds':scene.seconds,
          'speed':1,'content_seconds':scene.seconds,'freeze_seconds':0})
        cursor+=scene.seconds
    return rows
