"""Versioned causal plan and hash-bound human clip review. No external IO."""
from pydantic import Field
from .schema import Strict, CharacterError
from .precision_contract import SceneImagePlan

POLICY = 'precision-causal-v3'

class PropState(Strict):
    id: str = Field(min_length=1, max_length=40)
    before: str = Field(min_length=1, max_length=100)
    after: str = Field(min_length=1, max_length=100)
    change: str = Field(default='', max_length=150)

class CausalScene(SceneImagePlan):
    cause: str = Field(min_length=1, max_length=160)
    result: str = Field(min_length=1, max_length=160)
    prop_states: list[PropState] = Field(default_factory=list, max_length=8)

class CausalScenario(Strict):
    scenes: list[CausalScene] = Field(min_length=2, max_length=12)

INSTRUCTION = """
For each scene include cause and result. After scene one, copy the previous result exactly
into cause. The motion must visibly turn that cause into this result with one achievable action.
Resolve the same incident; the final payoff must use evidence established in earlier actions.
Never materialize evidence, food, crumbs or new characters just to explain the ending.
Track every story-relevant prop in prop_states with a stable id and before/after strings
describing quantity, physical form and location. Keep the same set of prop ids in every scene.
Copy each previous after exactly to the next before, even for an intentional cut.
For changed states, change must name the visible action that causes the change.
Objects not yet visible must be tracked as offscreen; reveal them through a visible action.
Whole objects and fragments are different states; do not turn crumbs into whole objects.
The still pose, start_state and camera must describe the same starting moment.
For continuation, preserve the inherited framing and positions; camera movement is gradual,
never a contradictory new starting angle. Do not compress several separate actions into one clip.
"""

def validate_causal(scenes):
    previous = None
    for scene in scenes:
        if not scene['cause'].strip() or not scene['result'].strip():
            raise ValueError(f"장면 {scene['no']}: 원인과 결과를 입력하세요.")
        props = scene['prop_states']
        current = {p['id']: p for p in props}
        if len(current) != len(props):
            raise ValueError(f"장면 {scene['no']}: 소품 이름이 중복됩니다.")
        for prop in props:
            if prop['before'] != prop['after'] and not prop['change'].strip():
                raise ValueError(f"장면 {scene['no']}: 소품이 바뀌는 행동을 입력하세요.")
        if previous:
            if scene['cause'] != previous['result']:
                raise ValueError(f"장면 {scene['no']}: 앞 장면 결과를 원인으로 연결하세요.")
            old = {p['id']: p for p in previous['prop_states']}
            if set(current) != set(old) or any(p['before'] != old[k]['after'] for k,p in current.items()):
                raise ValueError(f"장면 {scene['no']}: 소품의 수량·형태·위치를 앞 장면 끝과 연결하세요.")
        previous = scene

def context(scene):
    import json
    return (f"Cause: {scene['cause']}. Visible result: {scene['result']}. "
        'Prop states (do not invent or multiply objects): '
        + json.dumps(scene['prop_states'],ensure_ascii=False) + '. '
        'Preserve the starting framing and body positions; move the camera gradually, never reset it. ')

def waiting_cut(job, row):
    return (job.get('continuity_policy') == POLICY and row.get('state') == 'waiting_review'
        and row.get('continuity') == 'cut' and type(row.get('position')) is int
        and row['position'] > 1 and not row.get('handle'))

def reviewed(row):
    receipt = row.get('continuity_review', {})
    return row.get('state') == 'downloaded' and receipt.get('sha256') == row.get('sha256') and receipt.get('attempt') == row.get('attempt')

def pending_review(job):
    if job.get('continuity_policy') != POLICY or job.get('state') != 'scene_review': return None
    rows = job.get('scenes', [])
    for i,row in enumerate(rows[:-1]):
        if row['state'] == 'downloaded' and not reviewed(row) and rows[i+1]['state'] in {'waiting_dependency','waiting_review'}:
            return {'position':row['position'], 'clip_sha256':row['sha256'], 'next':rows[i+1]['position']}
    return None

def review_clip(service, identifier, position, clip_sha256, consent=False):
    service.consent(consent)
    from .compose import digest
    from .service import now
    with service.lock():
        job=service.read(identifier)
        expected=pending_review(job)
        if not expected or (position,clip_sha256)!=(expected['position'],expected['clip_sha256']):
            raise CharacterError('blocked')
        row=job['scenes'][position-1]
        path=service.folder(identifier)/row['file']
        if path.is_symlink() or path.is_junction() or digest(path)!=clip_sha256:
            raise CharacterError('media')
        row['continuity_review']={'sha256':clip_sha256,'attempt':row['attempt'],'at':now().isoformat()}
        job['events'].append({'kind':'continuity_review','position':position,**row['continuity_review']})
        service.save(job)
    # This function never dispatches or fetches. The existing approved check route does that.
