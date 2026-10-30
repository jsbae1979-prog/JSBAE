"""Focused Fake-only continuation, retry exposure and response-recovery contracts."""
from copy import deepcopy
from pathlib import Path

import pytest

from newsflow.character.episode_service import EpisodeFlow
from newsflow.character.episode_story import EpisodeScript
from newsflow.character.kling import check
from newsflow.character.schema import CharacterError
from newsflow.video.ai.contracts import ClipStatus

from test_character_episode_automation import setup_episode, script, image


def quoted(tmp_path, cap='5'):
    service, video, identifier, registry, profile = setup_episode(tmp_path)
    service.write(identifier, consent=True)
    if cap != '5':
        service.update_studio_settings(identifier, check(service.read(identifier)['studio_selection']), cap)
    service.prepare(identifier, consent=True, script_reviewed=True)
    return service, video, identifier


def synthetic_downloads(monkeypatch, video):
    def fetch(status, path, cancel):
        path.write_bytes(b'locally-owned-fake-video')
    video.fetch = fetch
    monkeypatch.setattr('newsflow.character.episode_service.probe_clip',
        lambda *_: {'duration': 7, 'width': 144, 'height': 256, 'has_audio': True})
    def frame(self, job, parent):
        path = self.owner.folder(job['id']) / 'test-last.png'
        path.write_bytes(image())
        return path
    monkeypatch.setattr(EpisodeFlow, 'last_frame', frame)


def test_single_continuous_shot_is_not_misclassified_as_singing():
    value = script()
    value['scenes'][0]['action'] = 'A single continuous shot follows the character picking up the tool.'
    assert EpisodeScript.model_validate(value).scenes[0].action.startswith('A single')


def test_known_failed_scene_requires_new_approval_and_counts_prior_exposure(tmp_path):
    service, video, identifier = quoted(tmp_path, '0.25')
    service.submit(identifier, consent=True, quote_hash=service.read(identifier)['quote_hash'])
    video.fail = True
    service.check(identifier, consent=True)
    assert len(video.sent) == 1 and service.read(identifier)['scenes'][0]['state'] == 'failed'
    service.prepare_retry(identifier, consent=True)
    with pytest.raises(CharacterError):
        service.retry_scene(identifier, consent=True, quote_hash=service.read(identifier)['retry_hash'])
    job = service.read(identifier)
    assert len(video.sent) == 1 and job['scenes'][0]['attempt'] == 1
    assert job['quote_total_usd'] == '0.20'


def test_explicit_failed_retry_keeps_first_receipt_and_dependency_waiting(tmp_path):
    service, video, identifier = quoted(tmp_path)
    service.submit(identifier, consent=True, quote_hash=service.read(identifier)['quote_hash'])
    video.fail = True
    service.check(identifier, consent=True)
    original = deepcopy(service.read(identifier)['scenes'][0])
    service.prepare_retry(identifier, consent=True)
    retry_hash = service.read(identifier)['retry_hash']
    with pytest.raises(CharacterError):
        service.retry_scene(identifier, consent=False, quote_hash=retry_hash)
    assert len(video.sent) == 1
    service.retry_scene(identifier, consent=True, quote_hash=retry_hash)
    job = service.read(identifier)
    assert len(video.sent) == 2 and job['scenes'][0]['attempt'] == 2
    assert job['scenes'][0]['history'][0]['handle'] == original['handle']
    assert job['scenes'][0]['idempotency_key'] == f'{identifier}-s1-t2'
    assert job['scenes'][1]['state'] == 'waiting_dependency'
    assert job['quote_total_usd'] == '0.30'


def test_timeout_submission_cannot_enter_failed_retry_path(tmp_path):
    service, video, identifier = quoted(tmp_path)
    video.unknown = True
    with pytest.raises(CharacterError):
        service.submit(identifier, consent=True, quote_hash=service.read(identifier)['quote_hash'])
    with pytest.raises(CharacterError):
        service.prepare_retry(identifier, consent=True)
    for _ in range(2):
        service.check(identifier, consent=True)
    assert len(video.sent) == 1
    assert service.read(identifier)['scenes'][1]['state'] == 'waiting_dependency'


def test_transient_status_failure_can_recover_without_resubmission(tmp_path):
    service, video, identifier = quoted(tmp_path)
    service.submit(identifier, consent=True, quote_hash=service.read(identifier)['quote_hash'])
    def fail(_): raise OSError('synthetic status transport failure')
    video.check = fail
    with pytest.raises(CharacterError):
        service.check(identifier, consent=True)
    original = deepcopy(service.read(identifier)['scenes'][0]['handle'])
    video.check = lambda _: ClipStatus('in_progress')
    service.check(identifier, consent=True)
    assert len(video.sent) == 1
    assert service.read(identifier)['scenes'][0]['handle'] == original


def test_failed_download_recovers_accepted_request_without_post_retry(tmp_path, monkeypatch):
    service, video, identifier = quoted(tmp_path)
    synthetic_downloads(monkeypatch, video)
    good_fetch = video.fetch
    def fail(*_): raise OSError('synthetic download interruption')
    video.fetch = fail
    service.submit(identifier, consent=True, quote_hash=service.read(identifier)['quote_hash'])
    with pytest.raises(CharacterError):
        service.check(identifier, consent=True)
    original_key = video.sent[0][1]
    video.fetch = good_fetch
    service.check(identifier, consent=True)
    assert sum(key == original_key for _, key in video.sent) == 1
    assert service.read(identifier)['scenes'][0]['state'] == 'downloaded'
    assert len(video.sent) == 2  # The previously approved dependent scene starts once.


def test_dependency_quote_increase_never_spends_above_approved_amount(tmp_path, monkeypatch):
    service, video, identifier = quoted(tmp_path)
    synthetic_downloads(monkeypatch, video)
    service.submit(identifier, consent=True, quote_hash=service.read(identifier)['quote_hash'])
    video.estimate = lambda _: '0.11'
    with pytest.raises(CharacterError):
        service.check(identifier, consent=True)
    job = service.read(identifier)
    assert len(video.sent) == 1
    assert job['scenes'][0]['state'] == 'downloaded'
    assert job['scenes'][1]['state'] == 'dependency_quote_changed'
    assert job['state'] == 'scene_review'


def test_tampered_dependency_payload_is_not_uploaded_or_submitted(tmp_path, monkeypatch):
    service, video, identifier = quoted(tmp_path)
    synthetic_downloads(monkeypatch, video)
    service.submit(identifier, consent=True, quote_hash=service.read(identifier)['quote_hash'])
    job = service.read(identifier)
    job['scenes'][1]['payload']['prompt'] = 'Unapproved replacement.'
    service.save(job)
    uploads = len(video.uploads)
    with pytest.raises(CharacterError):
        service.check(identifier, consent=True)
    assert len(video.sent) == 1 and len(video.uploads) == uploads


def test_valid_script_and_cost_survive_local_prompt_failure(tmp_path, monkeypatch):
    service, video, identifier, _, _ = setup_episode(tmp_path)
    service.authoring.last_estimated_usd = '0.13'
    import newsflow.character.episode_service as module
    original = module.prompts
    def too_long(*_): raise CharacterError('prompt_length')
    monkeypatch.setattr(module, 'prompts', too_long)
    service.write(identifier, consent=True)
    job = service.read(identifier)
    assert job['state'] == 'script_review' and job['prompt_validation_error'] is True
    assert job['script'] and job['prompts'] == []
    assert job['text_reservations'][0]['usd'] == '0.13'
    assert (service.folder(identifier)/'script.json').is_file()
    with pytest.raises(CharacterError):
        service.prepare(identifier, consent=True, script_reviewed=True)
    assert not video.uploads and not video.sent and len(service.authoring.calls) == 1
    monkeypatch.setattr(module, 'prompts', original)
    service.edit_episode(identifier, job['script'], job['script_hash'])
    assert 'prompt_validation_error' not in service.read(identifier)
    assert len(service.authoring.calls) == 1


def test_owned_partial_download_is_preserved_then_same_request_downloaded(tmp_path, monkeypatch):
    service, video, identifier = quoted(tmp_path)
    synthetic_downloads(monkeypatch, video)
    good_fetch = video.fetch
    def fail(status, path, cancel):
        path.write_bytes(b'owned-partial-transfer')
        raise OSError('synthetic mid-transfer failure')
    video.fetch = fail
    service.submit(identifier, consent=True, quote_hash=service.read(identifier)['quote_hash'])
    with pytest.raises(CharacterError):
        service.check(identifier, consent=True)
    original_key = video.sent[0][1]
    job = service.read(identifier)
    assert job['scenes'][0]['partial_download_receipt']['bytes'] == len(b'owned-partial-transfer')
    video.fetch = good_fetch
    service.check(identifier, consent=True)
    row = service.read(identifier)['scenes'][0]
    assert row['state'] == 'downloaded'
    preserved = service.folder(identifier)/row['partial_downloads'][0]['file']
    assert preserved.read_bytes() == b'owned-partial-transfer'
    assert sum(key == original_key for _, key in video.sent) == 1
    assert len(video.sent) == 2


def test_foreign_file_cannot_be_adopted_as_failed_download(tmp_path, monkeypatch):
    service, video, identifier = quoted(tmp_path)
    synthetic_downloads(monkeypatch, video)
    service.submit(identifier, consent=True, quote_hash=service.read(identifier)['quote_hash'])
    path = service.folder(identifier)/'scene-1.mp4'
    path.write_bytes(b'foreign-unowned-data')
    with pytest.raises(CharacterError):
        service.check(identifier, consent=True)
    assert path.read_bytes() == b'foreign-unowned-data'
    assert not list(service.folder(identifier).glob('partial-*.mp4'))
    assert len(video.sent) == 1


def test_local_budget_refusal_restores_requestable_state_without_automatic_call(tmp_path):
    service, video, identifier, _, _ = setup_episode(tmp_path)
    job = service.read(identifier)
    job['text_reservations'] = [{'attempt': 0, 'usd': '0.25'}]
    service.save(job)
    original = service.authoring.generate
    observed = []
    def denied(*args, **kwargs):
        observed.append(kwargs)
        service.authoring.last_reserved_usd = '0'
        service.authoring.last_failure = {'stage': 'budget', 'dispatched': False}
        service.authoring.response_received = False
        raise CharacterError('budget')
    service.authoring.generate = denied
    with pytest.raises(CharacterError):
        service.write(identifier, consent=True)
    job = service.read(identifier)
    assert job['state'] == 'needs_script' and job['script_attempts'] == 0
    assert len(observed) == 1 and observed[0]['max_reserved_usd'] == '4.75'
    assert len(job['text_reservations']) == 1 and not service.authoring.calls
    request_id = observed[0]['request_id']
    def allowed(*args, **kwargs):
        observed.append(kwargs)
        service.authoring.last_failure = None
        return original(*args, **kwargs)
    service.authoring.generate = allowed
    service.write(identifier, consent=True)
    assert service.read(identifier)['state'] == 'script_review'
    assert observed[1]['request_id'] != request_id
    assert len(service.authoring.calls) == 1
