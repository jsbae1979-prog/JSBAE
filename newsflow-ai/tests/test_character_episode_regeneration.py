"""Review-directed Fake scene regeneration never overwrites paid media or auto-retries."""
from copy import deepcopy
from datetime import timedelta

import pytest

from newsflow.character.compose import digest
from newsflow.character.episode_regeneration import affected_positions
from newsflow.character.episode_service import now, fp
from newsflow.character.episode_story import EpisodeScript
from newsflow.character.schema import CharacterError

from test_character_episode_automation import setup_episode, script
from test_character_episode_recovery import synthetic_downloads


def reviewed(tmp_path, monkeypatch, cap='5'):
    service, video, identifier, _, _ = setup_episode(tmp_path, 35)
    value = script(35)
    original = deepcopy(value['scenes'][0])
    value['scenes'] = []
    for index, seconds in enumerate((8, 9, 9, 8)):
        row = {**deepcopy(original), 'no': index + 1, 'seconds': seconds,
               'continuity': 'continue' if index % 2 else 'cut',
               'from': index if index % 2 else None,
               'freeze_end': 'medium' if index == 3 else 'none'}
        value['scenes'].append(row)
    service.authoring.generate = lambda *_, **__: EpisodeScript.model_validate(value)
    service.write(identifier, consent=True)
    if cap != '5':
        from newsflow.character.kling import check
        service.update_studio_settings(identifier, check(service.read(identifier)['studio_selection']), cap)
    synthetic_downloads(monkeypatch, video)
    monkeypatch.setattr('newsflow.character.episode_service.probe_clip',
        lambda *_: {'duration': 15, 'width': 144, 'height': 256, 'has_audio': True})
    def fetch(status, path, cancel):
        path.write_bytes(('synthetic-' + path.name).encode('ascii'))
    video.fetch = fetch
    service.prepare(identifier, consent=True, script_reviewed=True)
    service.submit(identifier, consent=True, quote_hash=service.read(identifier)['quote_hash'])
    for _ in range(3):
        if service.read(identifier)['state'] == 'clips_review': break
        service.check(identifier, consent=True)
    assert service.read(identifier)['state'] == 'clips_review' and len(video.sent) == 4
    return service, video, identifier


def test_descendants_are_transitive_and_independent_cuts_are_preserved():
    scenes = [{'position': 1, 'continuity': 'cut', 'from': None},
              {'position': 2, 'continuity': 'continue', 'from': 1},
              {'position': 3, 'continuity': 'cut', 'from': None},
              {'position': 4, 'continuity': 'continue', 'from': 2}]
    assert affected_positions(scenes, 1) == [1, 2, 4]
    assert affected_positions(scenes, 2) == [2, 4]
    assert affected_positions(scenes, 3) == [3]


def test_quote_does_not_generate_or_change_old_clips_and_can_be_canceled(tmp_path, monkeypatch):
    service, video, identifier = reviewed(tmp_path, monkeypatch)
    before = deepcopy(service.read(identifier))
    service.prepare_regeneration(identifier, 1, consent=True)
    job = service.read(identifier)
    assert job['state'] == 'regeneration_quoted' and job['regeneration']['affected'] == [1, 2]
    assert job['regeneration']['quote_total_usd'] == '0.20'
    assert job['scenes'] == before['scenes'] and len(video.sent) == 4
    service.cancel_regeneration(identifier, quote_hash=job['regeneration_hash'])
    assert service.read(identifier)['state'] == 'clips_review'
    assert service.read(identifier)['scenes'] == before['scenes'] and len(video.sent) == 4


def test_only_approved_scene_and_continued_descendant_get_new_attempts(tmp_path, monkeypatch):
    service, video, identifier = reviewed(tmp_path, monkeypatch)
    original = deepcopy(service.read(identifier)['scenes'])
    files = {row['file']: (service.folder(identifier)/row['file']).read_bytes() for row in original}
    service.prepare_regeneration(identifier, 1, consent=True)
    quote_hash = service.read(identifier)['regeneration_hash']
    with pytest.raises(CharacterError):
        service.regenerate_scenes(identifier, consent=False, quote_hash=quote_hash)
    with pytest.raises(CharacterError):
        service.regenerate_scenes(identifier, consent=True, quote_hash='stale')
    assert len(video.sent) == 4
    service.regenerate_scenes(identifier, consent=True, quote_hash=quote_hash)
    assert len(video.sent) == 5
    job = service.read(identifier)
    assert job['scenes'][1]['state'] == 'waiting_dependency'
    assert job['scenes'][2:] == original[2:]
    for _ in range(3):
        if service.read(identifier)['state'] == 'clips_review': break
        service.check(identifier, consent=True)
    job = service.read(identifier)
    assert job['state'] == 'clips_review' and len(video.sent) == 6
    assert [row['attempt'] for row in job['scenes']] == [2, 2, 1, 1]
    assert job['scenes'][0]['file'] == 'scene-1-t2.mp4'
    assert job['scenes'][1]['dependency']['clip_sha256'] == job['scenes'][0]['sha256']
    assert job['scenes'][1]['dependency']['attempt'] == 2
    for name, content in files.items():
        assert (service.folder(identifier)/name).read_bytes() == content
    assert job['scenes'][0]['history'][0]['sha256'] == original[0]['sha256']
    assert job['quote_total_usd'] == '0.60'


def test_continuation_selected_alone_uses_unchanged_parent_frame(tmp_path, monkeypatch):
    service, video, identifier = reviewed(tmp_path, monkeypatch)
    parent = deepcopy(service.read(identifier)['scenes'][0])
    service.prepare_regeneration(identifier, 2, consent=True)
    job = service.read(identifier)
    assert job['regeneration']['affected'] == [2]
    item = job['regeneration']['items'][0]
    assert not item['waiting_dependency']
    assert item['dependency']['clip_sha256'] == parent['sha256']
    service.regenerate_scenes(identifier, consent=True, quote_hash=job['regeneration_hash'])
    assert len(video.sent) == 5 and service.read(identifier)['scenes'][0] == parent


def test_regeneration_exposure_cap_blocks_before_any_new_generation(tmp_path, monkeypatch):
    service, video, identifier = reviewed(tmp_path, monkeypatch, cap='0.50')
    with pytest.raises(CharacterError):
        service.prepare_regeneration(identifier, 1, consent=True)
    assert len(video.sent) == 4 and service.read(identifier)['state'] == 'clips_review'


def test_expired_regeneration_quote_does_not_submit(tmp_path, monkeypatch):
    service, video, identifier = reviewed(tmp_path, monkeypatch)
    service.prepare_regeneration(identifier, 1, consent=True)
    job = service.read(identifier)
    job['regeneration']['at'] = (now() - timedelta(minutes=16)).isoformat()
    job['regeneration_hash'] = fp(job['regeneration'])
    service.save(job)
    with pytest.raises(CharacterError):
        service.regenerate_scenes(identifier, consent=True, quote_hash=job['regeneration_hash'])
    assert len(video.sent) == 4


def test_foreign_clip_path_is_blocked_before_quote_upload(tmp_path, monkeypatch):
    service, video, identifier = reviewed(tmp_path, monkeypatch)
    foreign = tmp_path / 'foreign.mp4'
    foreign.write_bytes(b'foreign-synthetic')
    job = service.read(identifier)
    job['scenes'][0].update(file=str(foreign), sha256=digest(foreign))
    service.save(job)
    video.upload_reference = lambda *_: pytest.fail('foreign file must be rejected before upload')
    with pytest.raises(CharacterError):
        service.prepare_regeneration(identifier, 1, consent=True)
    assert foreign.read_bytes() == b'foreign-synthetic' and len(video.sent) == 4


def test_completed_final_and_composition_are_preserved_as_revision(tmp_path, monkeypatch):
    service, video, identifier = reviewed(tmp_path, monkeypatch)
    folder = service.folder(identifier)
    final = folder/'final.mp4'
    final.write_bytes(b'original-final-synthetic')
    compose = folder/'compose'; compose.mkdir()
    (compose/'edit-evidence.json').write_text('{}', encoding='utf8')
    (folder/'review.json').write_text('{}', encoding='utf8')
    job = service.read(identifier)
    job.update(state='completed', output={'file': 'final.mp4', 'sha256': digest(final)})
    service.save(job)
    service.prepare_regeneration(identifier, 1, consent=True)
    assert final.read_bytes() == b'original-final-synthetic'
    service.regenerate_scenes(identifier, consent=True, quote_hash=service.read(identifier)['regeneration_hash'])
    job = service.read(identifier)
    old = job['generation_history'][-1]['output']
    assert (folder/old['file']).read_bytes() == b'original-final-synthetic'
    assert (folder/old['file']).parent.joinpath('compose/edit-evidence.json').is_file()
    assert all(item['moved'] for item in job['regeneration_intent']['preserved'])
    assert not final.exists() and not compose.exists()
    assert len(video.sent) == 5
