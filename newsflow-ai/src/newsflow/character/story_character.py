"""Text-only character direction, projected without appearance/style or image data."""
from copy import deepcopy


def story_character(profile):
    if not isinstance(profile,dict): return {}
    formula=profile.get('comedy_formula')
    formula=formula if isinstance(formula,dict) else {}
    result={
        'name':profile.get('name',profile.get('name_ko','')),
        'personality':profile.get('personality',''),
        'recurring_situation':profile.get('recurring_situation',formula.get('setup','')),
        'signature_reaction':profile.get('signature_reaction',formula.get('reaction','')),
        'world':profile.get('world',formula.get('world','')),
    }
    cast=profile.get('supporting_cast')
    if cast:
        # Named supporting roles only; visual traits stay in the video stage.
        result['supporting_cast']=[{key:deepcopy(row[key]) for key in ('id','name','role','personality') if key in row}
                                  if isinstance(row,dict) else deepcopy(row) for row in cast]
    return deepcopy(result) if any(result.values()) else {}


ROLE_DIRECTIONS={
    'setup':'Establish the situation clearly.',
    'build':'Show the contrast between the character and the surroundings; develop the situation.',
    'contrast':'Show the contrast between the character and the surroundings.',
    'punchline':"Comedic payoff: hold the character's reaction for a beat, exaggerated expression.",
}
