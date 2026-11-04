"""Provider-neutral scene-image plan. No credentials, networking or vendor payloads."""
from copy import deepcopy
from typing import Literal
from pydantic import Field, model_validator
from .schema import Strict
from .registry import safe_text
from .episode_story import ComedySfx

PROMPT_VERSION = 'scene-still-v2'
CONTINUITY_POLICY = 'precision-continuity-v2'
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
    connection: Literal['cut', 'continue'] = 'cut'
    set_id: str = Field(default='', max_length=60)
    environment: str = Field(default='', max_length=120)
    start_state: str = Field(default='', max_length=160)
    end_state: str = Field(default='', max_length=160)
    transition_reason: str = Field(default='', max_length=160)
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
Treat each still as the START of its clip, not its ending. Plan one achievable action per clip.
Use one stable set_id, location and environment (weather, lighting, time) for continuous action.
First scene connection=cut. For following scenes default to connection=continue in the same set.
For continue, copy the preceding end_state exactly into start_state; keep the same character IDs,
location and environment. Describe where bodies and props end up in end_state, and the causal link in continuity.
A deliberate cut needs transition_reason explaining the visible transition or narrative ellipsis;
never use a cut to conceal missing travel or change weather without explanation.
Prefer one location and one incident. Do not reset the action or pose at every boundary.
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


def validate_scenario(work, cast, value, video_model, policy=None):
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
    if policy == CONTINUITY_POLICY:
        validate_connections(result.model_dump()['scenes'], video_model)
    return result.model_dump()

def validate_connections(scenes, model):
    for i, scene in enumerate(scenes):
        no = scene['no']
        if any(not scene.get(k, '').strip() for k in ('set_id','environment','start_state','end_state')):
            raise ValueError(f'장면 {no}: 장소·환경·시작·끝 상태를 입력하세요.')
        if i == 0:
            if scene['connection'] != 'cut': raise ValueError('첫 장면은 시작 장면이어야 합니다.')
            continue
        previous = scenes[i-1]
        if not scene['continuity'].strip(): raise ValueError(f'장면 {no}: 앞 장면과 이어질 내용을 입력하세요.')
        if scene['connection'] == 'continue':
            if not model.get('continuation_param'): raise ValueError('이 모델은 마지막 프레임 연결을 지원하지 않습니다.')
            if any(scene[k] != previous[k] for k in ('set_id','location','environment')) or set(scene['characters']) != set(previous['characters']):
                raise ValueError(f'장면 {no}: 이어지는 장소·환경·등장인물을 일치시키세요.')
            if scene['start_state'] != previous['end_state']:
                raise ValueError(f'장면 {no}: 시작 상태를 앞 장면의 끝 상태와 연결하세요.')
        elif not scene['transition_reason'].strip():
            raise ValueError(f'장면 {no}: 장소 전환이나 시간 경과의 이유를 입력하세요.')


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
    moment.update({k:scene[k] for k in ('set_id','environment','start_state') if scene.get(k)})
    text = ('Depict the exact start_state before the action begins. One full-frame scene, never a contact sheet. Each attached reference corresponds in order to characters. '
            'Preserve each face, body, fur color, clothing and accessories. Preserve shared location and props. '
            + NO_TEXT + '\n' + json.dumps({'shared':shared,'characters':characters,'moment':moment},ensure_ascii=False))
    if len(text)>12000: raise ValueError('공통 설정과 장면 설명을 줄여 주세요.')
    return text

def motion_rows(work, cast, scenes, settings, policy=None):
    from .kling import validate_video_prompt
    rows=[]
    connected = policy == CONTINUITY_POLICY
    if connected:
        from newsflow.video_models.catalog import CATALOG
        validate_connections(scenes, CATALOG.model(settings['video_model']))
    for i, scene in enumerate(scenes):
        people='; '.join(cast[x]['name_ko']+': '+cast[x]['appearance'] for x in scene['characters'])
        connection = scene['connection'] if connected else 'cut'
        context = ''
        if connected:
            start = ('Continue from the actual final frame of the preceding clip; do not reset the pose. '
                     if connection == 'continue' else 'Begin an intentional establishing shot from the approved image. ')
            context = (f"{start}Set: {scene['location']}. Environment: {scene['environment']}. "
                       f"Start state: {scene['start_state']}. End state: {scene['end_state']}. ")
            if i:
                context += f"Previous action: {scenes[i-1]['motion']}. "
                if connection == 'cut': context += f"Transition: {scene['transition_reason']}. "
            if i+1 < len(scenes) and scenes[i+1]['connection']=='continue': context += f"Next scene starts: {scenes[i+1]['start_state']}. "
        image_start = "Animate the supplied final frame; approved still references guide identity, not a pose reset." if connected and connection == "continue" else "Animate the approved starting image."
        prompt=(f"{work['style']}. {people}. {image_start} "
                f"{context}{scene['motion']} Camera: {scene['motion_camera']}. Continuity: {scene['continuity']}. "
                'Preserve identity, clothes, prop locations and geography; no teleporting. No text on screen. ')
        prompt += (f"Ambient sound effects only: {scene['sound'] or 'environmental ambience'}. "
                   if settings['sound']=='on' else 'Silent video. ')
        prompt += 'No dialogue, no voices, no music.'
        validate_video_prompt(prompt)
        rows.append({'position':scene['no'],'seconds':scene['seconds'],'continuity':connection,'from':scene['no']-1 if connection=='continue' else None,'prompt':prompt})
    return rows
