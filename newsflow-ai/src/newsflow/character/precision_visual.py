"""Versioned, human-approved set references; no provider calls or journal mutation."""
from .service import fingerprint

POLICY = 'approved-set-reference-v1'

def anchor_scene(work, scene):
    if work.get('visual_reference_policy') != POLICY:
        return None
    plan = scene['plan']
    key = tuple(plan.get(k, '') for k in ('set_id', 'environment', 'location'))
    if not all(key):
        raise ValueError('장소와 고정 배경을 먼저 저장하세요.')
    return next((s for s in work['scenes'] if s['plan']['no'] < plan['no'] and
        tuple(s['plan'].get(k, '') for k in ('set_id', 'environment', 'location')) == key), None)

def binding(work, scene):
    anchor = anchor_scene(work, scene)
    if anchor is None:
        return None
    receipt = anchor.get('confirmed') or {}
    version = next((v for v in anchor['versions'] if v['version'] == receipt.get('version')), None)
    if (not version or version['state'] != 'success' or anchor.get('selected') != version['version'] or
            version['plan_hash'] != fingerprint(anchor['plan']) or receipt.get('sha256') != version['sha256']):
        raise ValueError('같은 장소의 첫 장면을 먼저 검토하고 확정하세요.')
    return {'scene': anchor['plan']['no'], 'version': version['version'],
            'asset': version['asset'], 'sha256': version['sha256'], 'plan_hash': version['plan_hash']}

def matches(work, scene, version):
    if version.get('plan_hash') != fingerprint(scene['plan']):
        return False
    if work.get('visual_reference_policy') != POLICY:
        return True
    try:
        return version.get('visual_anchor') == binding(work, scene)
    except ValueError:
        return False

def request_prompt(work, scene):
    anchor = binding(work, scene)
    if not anchor:
        return scene['prompt']
    n = len(scene['plan']['characters'])
    # Image ordering is exactly the service refs() ordering. No extra characters.
    prompt = scene['prompt'].replace('Each attached reference corresponds in order to characters. ', '') + (
        f'\nReference roles: images 1 through {n} are character identity references in the listed order. '
        f'Image {n+1} is the user-approved set reference from scene {anchor["scene"]}. '
        'Use the last image for the SAME room geometry, window and door placement, furniture, '
        'lighting, palette and the design of recurring props. Do not mirror the room or swap screen sides. '
        'It is NOT an extra character reference or a target pose: show ONLY this scene cast and '
        'the current moment/start state. Follow current before-state for prop quantity and position, '
        'not obsolete action or prop states in the set reference. Render one frame, not a collage.')

    if len(prompt)>12000:
        raise ValueError('공통 설정과 장면 설명을 줄여 주세요.')
    return prompt

def annotate(work):
    """Derived response fields only; caller passes a detached copy."""
    for scene in work['scenes']:
        try:
            anchor = anchor_scene(work, scene)
            scene['visual_anchor_scene'] = anchor['plan']['no'] if anchor else None
            binding(work, scene)
            scene['image_ready'] = True
        except ValueError:
            scene['image_ready'] = False
        for version in scene['versions']:
            version['matches_current_plan'] = matches(work, scene, version)
        receipt = scene.get('confirmed') or {}
        scene['confirmed_valid'] = any(v['version'] == receipt.get('version') and
            v.get('sha256') == receipt.get('sha256') and matches(work, scene, v) for v in scene['versions'])
    return work
