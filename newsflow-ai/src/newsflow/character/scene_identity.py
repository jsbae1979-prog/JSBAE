"""Resolve only the exact selected Korean proper name; never translate scene prose."""
from copy import deepcopy
import re


def resolve_scene_identity(value, character):
    name = character.get('name_ko') or character.get('name')
    if not isinstance(value, dict) or not isinstance(name, str) or not re.search('[가-힣]', name):
        return value
    result = deepcopy(value)
    # Do not match part of a different name or remove Korean action instructions.
    pattern = re.compile(r'(?<![\w])' + re.escape(name) + r'(?![\w])')
    scenes = result.get('scenes')
    if isinstance(scenes, list):
        for scene in scenes:
            if isinstance(scene, dict):
                for field in ('action', 'camera'):
                    if isinstance(scene.get(field), str):
                        scene[field] = pattern.sub('the character', scene[field])
    return result
