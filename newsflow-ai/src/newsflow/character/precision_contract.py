"""Provider-neutral scene-image plan. No credentials, networking or vendor payloads."""
from copy import deepcopy
from typing import Literal
from pydantic import Field, model_validator
from .schema import Strict
from .registry import safe_text
from .episode_story import ComedySfx

PROMPT_VERSION = 'scene-still-v1'
NO_TEXT = 'No subtitles, speech bubbles, letters, logos or watermark in the image.'

class WorkSettings(Strict):
    title: str = Field(min_length=1, max_length=100)
    topic: str = Field(min_length=1, max_length=150)
    relationships: str = Field(default='', max_length=300)
    genre: str = Field(default='대사 없는 코미디', max_length=80)
    world: str = Field(default='', max_length=300)
    background: str = Field(default='', max_length=300)
    props: str = Field(default='', max_length=300)
    style: str = Field(min_length=1, max_length=600)
    ratio: Literal['9:16'] = '9:16'
    scene_count: int = Field(ge=2, le=12)
    duration: int = Field(ge=15, le=60)
    prohibitions: str = Field(default='', max_length=300)

class SceneImagePlan(Strict):
    no: int = Field(ge=1, le=12)
    characters: list[str] = Field(min_length=1, max_length=4)
    description: str = Field(min_length=1, max_length=300)
    location: str = Field(min_length=1, max_length=200)
    pose: str = Field(min_length=1, max_length=300)
    emotion: str = Field(min_length=1, max_length=150)
    camera: str = Field(min_length=1, max_length=120)
    props: str = Field(default='', max_length=200)
    continuity: str = Field(default='', max_length=300)
    caption: str = Field(default='', max_length=20)
    seconds: int = Field(ge=3, le=15)
    motion: str = Field(min_length=1, max_length=300, pattern=r'^[^가-힣]*[A-Za-z][^가-힣]*$')
    motion_camera: str = Field(min_length=1, max_length=120, pattern=r'^[^가-힣]*[A-Za-z][^가-힣]*$')
    sound: str = Field(default='', max_length=100)
    sfx: list[ComedySfx] = Field(default_factory=list, max_length=2)

    @model_validator(mode='after')
    def unique(self):
        if len(set(self.characters)) != len(self.characters): raise ValueError('duplicate character')
        # Reuse the established no-dialogue motion contract.
        from .episode_story import EpisodeScene
        EpisodeScene(no=self.no,seconds=self.seconds,continuity='cut',action=self.motion,
                     camera=self.motion_camera,sound=self.sound,caption=self.caption,sfx=self.sfx)
        from .editing import load_sfx_map
        if any(effect.key not in load_sfx_map() for effect in self.sfx): raise ValueError('unknown local effect')
        return self

class PrecisionScenario(Strict):
    scenes: list[SceneImagePlan] = Field(min_length=2, max_length=12)

INSTRUCTION = '''Write one coherent dialogue-free visual story from input.work and input.characters.
Use only the supplied character IDs; keep appearance, clothes, location, prop positions and causal action continuous.
Return exactly input.work.scene_count scenes, totaling exactly input.work.duration seconds.
Every seconds value must be in input.allowed_seconds. Describe a single still moment in pose/emotion/camera;
describe temporal action separately in English motion and motion_camera. No dialogue, no voices, no music.
Use Korean description and short caption. Optional local sfx keys must come from input.sfx_keys. Never put captions in the still scene. End with a visual payoff.
Do not invent brands, copyrighted characters or real people. Return only the requested JSON object.'''

def validate_work_timing(work, video_model):
    """Reject impossible scene partitions before any paid authoring request."""
    from newsflow.video_models.catalog import duration_values
    value = WorkSettings.model_validate(work)
    allowed = [n for n in duration_values(video_model) if 3 <= n <= 15]
    reachable = {0}
    for _ in range(value.scene_count):
        reachable = {total + n for total in reachable for n in allowed if total + n <= value.duration}
    if value.duration not in reachable:
        raise ValueError('영상 길이와 장면 수가 선택 모델에서 가능한지 확인하세요.')


def validate_scenario(work, cast, value, video_model):
    from newsflow.video_models.catalog import duration_values
    safe_text(value)
    result = PrecisionScenario.model_validate(value)
    if len(result.scenes) != work['scene_count'] or sum(x.seconds for x in result.scenes) != work['duration']:
        raise ValueError('장면 수와 전체 길이를 확인하세요. 길이를 임의로 늘리지 않습니다.')
    if [x.no for x in result.scenes] != list(range(1,len(result.scenes)+1)):
        raise ValueError('장면 순서를 확인하세요.')
    allowed = duration_values(video_model)
    for scene in result.scenes:
        if not set(scene.characters) <= set(cast) or scene.seconds not in allowed:
            raise ValueError('등장 캐릭터와 영상 모델의 장면 길이를 확인하세요.')
    return result.model_dump()

def story_input(work, cast, video_model):
    from newsflow.video_models.catalog import duration_values
    from .editing import load_sfx_map
    return {'work':deepcopy(work), 'sfx_keys':list(load_sfx_map()), 'characters':[
        {k:deepcopy(c[k]) for k in ('id','name_ko','species','personality','comedy_formula')}
        for c in cast.values()], 'allowed_seconds':duration_values(video_model)}

def image_prompt(work, cast, scene):
    # Subtitle/caption is intentionally excluded, even when it is filled in.
    import json
    shared = {k:work[k] for k in ('relationships','genre','world','background','props','style','ratio','prohibitions')}
    characters = [{k:cast[c][k] for k in ('id','name_ko','species','appearance','personality','outfit','style_lock')}
                  for c in scene['characters']]
    moment = {k:scene[k] for k in ('location','pose','emotion','camera','props','continuity')}
    text = ('One full-frame scene, never a contact sheet. Each attached reference corresponds in order to characters. '
            'Preserve each face, body, fur color, clothing and accessories. Preserve shared location and props. '
            + NO_TEXT + '\n' + json.dumps({'shared':shared,'characters':characters,'moment':moment},ensure_ascii=False))
    if len(text)>12000: raise ValueError('공통 설정과 장면 설명을 줄여 주세요.')
    return text

def motion_rows(work, cast, scenes, settings):
    from .kling import validate_video_prompt
    rows=[]
    for scene in scenes:
        people='; '.join(cast[x]['name_ko']+': '+cast[x]['appearance'] for x in scene['characters'])
        prompt=(f"{work['style']}. {people}. Animate the approved starting image. "
                f"{scene['motion']} Camera: {scene['motion_camera']}. Continuity: {scene['continuity']}. "
                'Preserve identity, clothes, prop locations and geography; no teleporting. No text on screen. ')
        prompt += (f"Ambient sound effects only: {scene['sound'] or 'environmental ambience'}. "
                   if settings['sound']=='on' else 'Silent video. ')
        prompt += 'No dialogue, no voices, no music.'
        validate_video_prompt(prompt)
        rows.append({'position':scene['no'],'seconds':scene['seconds'],'continuity':'cut','from':None,'prompt':prompt})
    return rows
