"""Private story response evidence and finite UI projections; only fake providers."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from test_api_settings import sessions, store
from test_character_kling_studio import studio, create, story
from newsflow.character.claude import StudioResponseError
from newsflow.character.schema import CharacterError
from newsflow.character.story_response import persist_candidate, public_failure
from newsflow.character.studio_story import StudioStoryboard
from newsflow.studio.read_models import character_rows

SECRET = 'synthetic-private-marker-do-not-project'


def test_private_candidate_is_immutable_idempotent_and_filters_usage(tmp_path):
    candidate = story(30, 'off')
    candidate['untrusted_extra'] = SECRET
    usage = {'prompt_tokens': 100, 'completion_tokens': 20, 'search_calls': 0,
             'authorization': SECRET, 'negative': -1, 'bool': True}
    original = deepcopy(candidate)
    saved = persist_candidate(tmp_path, 1, candidate, usage)
    path = tmp_path / saved['file']
    raw = path.read_bytes()
    record = json.loads(raw)
    assert candidate == original and record['candidate'] == original
    assert record['usage'] == {'prompt_tokens': 100, 'completion_tokens': 20, 'search_calls': 0}
    assert saved['sha256'] == hashlib.sha256(raw).hexdigest() and saved['bytes'] == len(raw)
    assert persist_candidate(tmp_path, 1, candidate, usage) == saved
    with pytest.raises(ValueError, match='candidate-exists'):
        persist_candidate(tmp_path, 1, {**candidate, 'title': 'different response'}, usage)
    assert path.read_bytes() == raw and list(tmp_path.iterdir()) == [path]


def test_candidate_larger_than_512_kib_is_rejected_before_any_write(tmp_path):
    with pytest.raises(ValueError, match='candidate-size'):
        persist_candidate(tmp_path, 1, {'text': 'x' * (512 * 1024)})
    assert list(tmp_path.iterdir()) == []


def test_public_failure_never_projects_response_values_or_unknown_fields():
    value = {'failure_stage': 'schema', 'stop_reason': SECRET, 'api_key': SECRET,
             'validation_errors': [{'loc': ['scenes', 0, 'action'], 'type': 'string_too_long',
                                    'input': SECRET, 'msg': SECRET, 'ctx': {'secret': SECRET}},
                                   {'loc': [SECRET, 1000], 'type': SECRET}]}
    safe = public_failure(value)
    assert safe['stage'] == 'schema' and safe['stop_reason'] == 'other'
    assert safe['validation_errors'] == [
        {'loc': ['scenes', 0, 'action'], 'type': 'string_too_long'},
        {'loc': ['unknown_field', 'unknown_field'], 'type': 'other'}]
    assert SECRET not in json.dumps(safe)
    assert public_failure({'http_status': 400, 'headers': SECRET}) == {
        'stage': 'request', 'message': '스토리 API 요청이 완료되지 않았습니다.'}
    assert public_failure({'unknown': SECRET}) is None


def test_failed_response_is_private_and_public_view_is_finite_without_replay(studio):
    service = studio.service
    identifier = create(studio, duration=30, clip_seconds=6, sound='off')
    before = service.read(identifier)
    before['events'].append({'stage': 'older-local-record', 'at': 'synthetic'})
    before['script_attempt_history'] = [{'marker': 'keep-existing-history'}]
    service.save(before)
    reference = (service.folder(identifier) / 'reference.png').read_bytes()
    candidate = story(30, 'off')
    candidate['untrusted_extra'] = SECRET
    calls = []
    def fail(*args):
        calls.append(args)
        raise StudioResponseError('schema', stop_reason='end_turn', errors=[{
            'loc': ['scenes', 0, 'action'], 'type': 'string_too_long', 'input': SECRET, 'msg': SECRET}])
    service.writer = SimpleNamespace(last_candidate=candidate,
        last_usage={'prompt_tokens': 100, 'completion_tokens': 20}, write_studio=fail)
    with pytest.raises(CharacterError):
        service.write(identifier, consent=True)
    job = service.read(identifier)
    assert job['state'] == 'script_failed' and job['response_received'] is True
    assert len(calls) == 1 and not studio.clients
    assert job['events'][:len(before['events'])] == before['events']
    assert job['script_attempt_history'] == before['script_attempt_history']
    assert job['script_failure'] == {'failure_stage': 'schema', 'stop_reason': 'end_turn',
        'validation_errors': [{'loc': ['scenes', 0, 'action'], 'type': 'string_too_long'}]}
    metadata = job['script_responses'][0]
    raw = (service.folder(identifier) / metadata['file']).read_bytes()
    assert json.loads(raw)['candidate'] == candidate
    assert metadata['sha256'] == hashlib.sha256(raw).hexdigest()
    assert SECRET not in json.dumps(metadata) and 'candidate' not in metadata
    projected = character_rows(SimpleNamespace(character=service))[0]
    assert projected['scriptResponseSaved'] is True and projected['scriptRetryAllowed'] is True
    assert projected['scriptFailure']['stage'] == 'schema'
    assert SECRET not in json.dumps(projected)
    assert metadata['file'] not in json.dumps(projected)
    assert (service.folder(identifier) / 'reference.png').read_bytes() == reference
    assert len(calls) == 1


def test_explicit_second_attempt_preserves_first_candidate_and_prior_history(studio):
    service = studio.service
    identifier = create(studio, duration=30, clip_seconds=6, sound='off')
    candidate = story(30, 'off')
    calls = []
    def fail(*args):
        calls.append('failed')
        raise StudioResponseError('timing', errors=[{'loc': ['scenes'], 'type': 'scene_count'}])
    service.writer = SimpleNamespace(last_candidate=deepcopy(candidate),
        last_usage={'prompt_tokens': 100, 'completion_tokens': 20}, write_studio=fail)
    with pytest.raises(CharacterError):
        service.write(identifier, consent=True)
    first = service.read(identifier)
    first_metadata = deepcopy(first['script_responses'][0])
    first_path = service.folder(identifier) / first_metadata['file']
    first_raw = first_path.read_bytes()
    def succeed(*args):
        calls.append('success')
        return StudioStoryboard.model_validate(candidate)
    service.writer.write_studio = succeed
    service.writer.last_candidate = deepcopy(candidate)
    service.write(identifier, consent=True)
    job = service.read(identifier)
    assert calls == ['failed', 'success'] and job['state'] == 'script_review'
    assert [row['attempt'] for row in job['script_responses']] == [1, 2]
    assert job['script_responses'][0] == first_metadata and first_path.read_bytes() == first_raw
    assert job['script_attempt_history'] == [{'attempt': 1, 'state': 'script_failed',
        'response_received': True, 'failure': public_failure(first['script_failure'])}]
    assert job['script'] == candidate and (service.folder(identifier) / 'script.json').is_file()
    assert json.loads((service.folder(identifier) / job['script_responses'][1]['file']).read_bytes())['candidate'] == candidate
    projected = character_rows(SimpleNamespace(character=service))[0]
    assert projected['scriptResponseSaved'] is True and projected['scriptRetryAllowed'] is False
    assert projected['scriptFailure'] is None and not studio.clients
