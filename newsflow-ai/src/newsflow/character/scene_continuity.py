"""Frozen new-job continuity; retain the quote/receipt path for legacy jobs."""
from copy import deepcopy
from .kling import validate_video_prompt


def connect(rows, story, character):
    result = deepcopy(rows)
    shared = ('Single continuous incident. Same room layout, weather, lighting, clothes and props throughout. '
              'Do not reset the scene or teleport the character. No unregistered extra characters. ')
    for index, row in enumerate(result):
        if index:
            previous = story.scenes[index-1]
            row.update(continuity='continue', **{'from': previous.no})
            context = ('The supplied first frame is the previous shot ending. Begin exactly there: preserve body '
                       'position, held objects and background. Show any movement before changing position. '
                       'Previous action (context, do not replay): ' + previous.action + ' Next beat: ')
        else:
            context = 'Establish the room and props that every following shot will retain. '
        row['prompt'] = shared + context + row['prompt']
        validate_video_prompt(row['prompt'])
    return result


POLICY = 'single_incident_v2'

STORY_DIRECTION = (
    'Continuity takes priority over quick cuts and camera spectacle. Plan one continuous incident with ONLY the selected character. '
    'Do not invent coworkers, crowds, a second protagonist or new locations. Show pressure through existing objects and ambient effects. '
    'Before writing, track the location, body position and each movable prop at every beat boundary; '
    'a prop must be introduced once, then visibly picked up, carried or put down before its state changes. '
    'Each scene has one achievable main action and at most one gradual camera move. '
    'Scene 1 is already an interesting action, but clearly establishes the place and usable props. '
    'After scene 1, use continue from the immediately preceding scene; begin with its resulting pose and held objects. '
    'No offscreen reset, flashback, reverse chronology, sudden standing/sitting or duplicate objects. '
    'Keep screen direction, light and weather consistent. Keep the character and key props visible at every scene end. '
    'The loop ending returns toward the opening through visible motion; never jump back or undo the story. '
    'Check the sequence as one film before returning the SAME response, without adding fields or changing the output schema. '
)


def connected_prompts(story, settings, character, story_format=None):
    """Keep full user fields within the existing API limit; frame state wins over plans."""
    from .kling import VIDEO_PROMPT_LIMIT
    result = []
    count = len(story.scenes)
    for index, scene in enumerate(story.scenes):
        parts = [
            'Continuous incident; one character/place/time. No cuts, extra people, teleportation or duplicate props.',
            'Identity/style only: ' + character['style_lock'] + '. ' + character['appearance'],
            ('Start at supplied final frame; its pose, props, light and direction override conflicting text.' if index else
             ('Hook now; no calm establishing shot. Show usable props.' if story_format and story_format['hook_first'] else
              'Establish the situation and usable props.')),
            'Next action: ' + scene.action,
            'One gradual camera move: ' + scene.camera,
            ('Payoff reaction; return toward opening only by visible motion.' if index == count-1 else
             'End with character and props visible, ready for next action.'),
            ('Ambient effects only: ' + (scene.sound or 'environment ambience') + '.' if settings['sound']=='on' else 'Silent video.'),
            'No dialogue, no voices, no music, no on-screen text.',
        ]
        # Planned prior action is optional context, never a substitute for the observed frame.
        # Omit only this duplicate context if it would overflow; do not truncate user fields.
        if index:
            prior = 'Prior plan, not observed fact; do not replay: ' + story.scenes[index-1].action
            if len(' '.join(parts + [prior])) <= VIDEO_PROMPT_LIMIT:
                parts.insert(3, prior)
        prompt = ' '.join(parts)
        validate_video_prompt(prompt)
        result.append({'position': scene.no, 'seconds': scene.seconds,
                       'continuity': 'continue' if index else 'cut',
                       'from': story.scenes[index-1].no if index else None, 'prompt': prompt})
    return result
