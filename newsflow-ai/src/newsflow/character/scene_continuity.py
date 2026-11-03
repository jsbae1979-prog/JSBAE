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
