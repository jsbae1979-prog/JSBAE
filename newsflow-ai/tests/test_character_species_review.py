"""Only a bounded, optional species label may become an explicit review draft."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from newsflow.character.authoring import AnalysisResult, species_review_draft
from newsflow.character.registry import CharacterProfile
from newsflow.character.schema import CharacterError
from test_character_authoring_v3 import build, candidate, png
from test_character_registry_v3 import profile
from test_character_automation_routes import gui


LONG_SPECIES = 'An original anthropomorphic rabbit with rounded ears and soft fur'


@pytest.mark.parametrize('provider,model', [('claude_api', 'claude-sonnet-4-6'), ('openai', 'gpt-4.1-mini')])
def test_optional_species_overlength_keeps_valid_draft_and_single_paid_receipt(provider, model):
    answer = candidate()
    answer['species'] = LONG_SPECIES
    before = deepcopy(answer)
    service, adapter, budget = build(provider, answer)
    result = service.analyze(png(), provider=provider, model=model, request_id='review:one', consent=True)
    assert result['species'] == ''
    assert result['appearance'] == answer['appearance'] and result['candidates'] == answer['candidates']
    assert result['needs_review'] == [{'field': 'species', 'reason': 'string_too_long',
        'characters': len(LONG_SPECIES), 'maximum': 40, 'original': LONG_SPECIES}]
    assert answer == before and service.last_candidate == before
    assert len(adapter.bodies) == 1 and len(budget.reservations) == 1 and len(budget.finished) == 1
    assert budget.finished[0][1] == {'status':'failed', 'usage':{'prompt_tokens':10, 'completion_tokens':30}}
    assert service.last_failure['review_available'] is True
    assert service.last_failure['response_received'] is True


@pytest.mark.parametrize('fault', ['extra', 'unsafe_species', 'unsafe_other', 'rejected',
    'appearance', 'style', 'candidate_count', 'candidate_name', 'duplicate_name',
    'formula', 'wrong_type', 'huge_species', 'missing_species'])
def test_review_does_not_admit_other_invalid_or_unsafe_responses(fault):
    answer = candidate()
    answer['species'] = LONG_SPECIES
    if fault == 'extra': answer['extra'] = 'not allowed'
    if fault == 'unsafe_species': answer['species'] += '\nnot allowed'
    if fault == 'unsafe_other': answer['appearance'] += ' Bearer synthetic-secret'
    if fault == 'rejected': answer['rejected'] = True; answer['reason'] = 'synthetic rejection'
    if fault == 'appearance': answer['appearance'] = 'x' * 401
    if fault == 'style': answer['style_suggestion'] = 'x' * 151
    if fault == 'candidate_count': answer['candidates'].pop()
    if fault == 'candidate_name': answer['candidates'][0]['name_ko'] = '가' * 11
    if fault == 'duplicate_name': answer['candidates'][1]['name_ko'] = answer['candidates'][0]['name_ko']
    if fault == 'formula': answer['candidates'][0]['comedy_formula']['reaction'] = ''
    if fault == 'wrong_type': answer['species'] = ['not a label']
    if fault == 'huge_species': answer['species'] = 'x' * 401
    if fault == 'missing_species': answer.pop('species')
    assert species_review_draft(answer) is None
    service, adapter, budget = build('claude_api', answer)
    with pytest.raises(CharacterError):
        service.analyze(png(), provider='claude_api', model='claude-sonnet-4-6', request_id='invalid', consent=True)
    assert len(adapter.bodies) == 1 and len(budget.finished) == 1
    assert not service.last_failure.get('review_available')


def test_normal_analysis_and_saved_species_limit_remain_unchanged():
    service, adapter, budget = build('claude_api', candidate())
    result = service.analyze(png(), provider='claude_api', model='claude-sonnet-4-6', request_id='normal', consent=True)
    assert result['species'] == 'rabbit' and 'needs_review' not in result
    assert budget.finished[0][1]['status'] == 'success'
    assert AnalysisResult.model_fields['species'].metadata[-1].max_length == 40
    with pytest.raises(ValidationError): AnalysisResult.model_validate({**candidate(), 'species': ''})
    with pytest.raises(ValidationError): CharacterProfile.model_validate({**profile(), 'species': LONG_SPECIES})
    assert CharacterProfile.model_validate({**profile(), 'species': ''}).species == ''


def test_review_draft_http_does_not_register_a_profile_or_retry(gui):
    answer = candidate()
    answer['species'] = LONG_SPECIES
    service, adapter, budget = build('claude_api', answer)
    gui.app.state.character_authoring = service
    response = gui.post('/api/studio/characters/profiles/analyze', asset=gui.asset,
        model='claude-sonnet-4-6', request_id='review:route', consent='true')
    assert response.status_code == 200 and response.json()['needs_review'][0]['original'] == LONG_SPECIES
    assert gui.client.get('/api/studio/characters/profiles').json() == {'profiles': []}
    assert len(adapter.bodies) == 1 and len(budget.finished) == 1
