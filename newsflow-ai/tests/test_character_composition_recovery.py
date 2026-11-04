"""Fake providers and synthetic bytes only; no supplier/account calls."""
from copy import deepcopy
import json

import pytest
from filelock import Timeout
from test_character_shorts import prepared, setup, sessions, store

from newsflow.character.compose import digest
from newsflow.character.schema import CharacterError


def ready(setup):
    service = setup.service
    identifier = prepared(setup)
    folder = service.folder(identifier)
    job = service.read(identifier)
    for scene in job['scenes']:
        path = folder / f"scene-{scene['position']}.mp4"
        path.write_bytes(b'SYNTHETIC_CLIP' + bytes([scene['position']]))
        scene.update(state='downloaded', file=path.name, sha256=digest(path))
    job['state'] = 'clips_review'
    service.save(job)
    return service, identifier, folder


def compositor(folder, story, clips, **kwargs):
    (folder/'compose').mkdir(exist_ok=False)
    (folder/'compose'/'local-evidence.txt').write_text('synthetic')
    path = folder/'final.mp4'
    path.write_bytes(b'SYNTHETIC_FINAL')
    return {'file':'final.mp4', 'sha256':digest(path), 'media':{}}


def preserved(service, identifier):
    job = service.read(identifier)
    return deepcopy({key:job.get(key) for key in ('scenes','script','plan_hash','quote_approvals','quote_hash')})


def test_failed_partial_output_retries_without_supplier_or_clip_changes(setup):
    service, identifier, folder = ready(setup)
    before = preserved(service, identifier)
    calls = (setup.video.calls, setup.writer.calls)
    def failed(folder, *args, **kwargs):
        compositor(folder, *args, **kwargs)
        raise OSError('synthetic failure')
    service.composer = failed
    with pytest.raises(CharacterError): service.render(identifier, reviewed=True)
    assert service.read(identifier)['state'] == 'compose_failed'
    failed_attempt = next((folder/'compose-runs').iterdir())
    assert (failed_attempt/'final.mp4').read_bytes() == b'SYNTHETIC_FINAL'
    # Legacy failed artifacts must also be preserved, never deleted to retry.
    (folder/'compose').mkdir(); (folder/'compose'/'old.txt').write_text('old')
    (folder/'final.mp4').write_bytes(b'OLD_INCOMPLETE')
    assert service.composition_retry_available(identifier)
    service.composer = compositor
    output = service.render(identifier, reviewed=True)
    job = service.read(identifier)
    assert output == folder/'final.mp4' and job['state'] == 'completed'
    assert [r['state'] for r in job['composition_attempts']] == ['failed','completed']
    archive = folder/'compose-runs'/job['composition_attempts'][-1]['id']/'previous'
    assert (archive/'compose'/'old.txt').read_text() == 'old'
    assert (archive/'final.mp4').read_bytes() == b'OLD_INCOMPLETE'
    assert (folder/'compose'/'local-evidence.txt').is_file()
    assert json.loads((folder/'review.json').read_text(encoding='utf-8'))['output'] == job['output']
    assert preserved(service, identifier) == before
    assert (setup.video.calls, setup.writer.calls) == calls
    assert service.render(identifier, reviewed=True) == output
    assert len(service.read(identifier)['composition_attempts']) == 2


def test_interrupted_render_is_manually_recoverable_after_lock_released(setup):
    service, identifier, folder = ready(setup)
    class Interrupted(BaseException): pass
    def interrupted(folder, *args, **kwargs):
        (folder/'compose').mkdir()
        raise Interrupted()
    service.composer = interrupted
    with pytest.raises(Interrupted): service.render(identifier, reviewed=True)
    assert service.read(identifier)['state'] == 'composing'
    restarted = type(service)(service.root.parent,service.sessions,service.keys,
        writer=setup.writer,video=setup.video,budget=service.budget,composer=compositor)
    assert restarted.composition_retry_available(identifier)
    assert restarted.read(identifier)['state'] == 'composing'  # GET never runs composition.
    restarted.render(identifier, reviewed=True)
    job = restarted.read(identifier)
    assert [r['state'] for r in job['composition_attempts']] == ['interrupted','completed']


def test_active_compositor_keeps_other_retry_blocked(setup):
    service, identifier, folder = ready(setup)
    def active(folder, *args, **kwargs):
        assert not service.composition_retry_available(identifier)
        with pytest.raises(Timeout): service.render(identifier, reviewed=True)
        return compositor(folder, *args, **kwargs)
    service.composer = active
    service.render(identifier, reviewed=True)


@pytest.mark.parametrize('defect',['missing','corrupt','not_downloaded','escape','duplicate'])
def test_invalid_clips_never_start_recovery(setup, defect):
    service, identifier, folder = ready(setup)
    job = service.read(identifier); scene = job['scenes'][0]
    if defect == 'missing': (folder/scene['file']).unlink()
    elif defect == 'corrupt': (folder/scene['file']).write_bytes(b'changed')
    elif defect == 'not_downloaded': scene['state'] = 'unknown'
    elif defect == 'escape': scene['file'] = '../outside.mp4'
    else: job['scenes'].append(deepcopy(scene))
    job['state'] = 'compose_failed'; service.save(job)
    assert not service.composition_retry_available(identifier)
    with pytest.raises((CharacterError,OSError)): service.render(identifier,reviewed=True)
    assert not (folder/'compose-runs').exists()


def test_bad_output_receipt_preserves_attempt_and_can_retry(setup):
    service, identifier, folder = ready(setup)
    def bad(*args, **kwargs):
        return {**compositor(*args, **kwargs), 'sha256':'a'*64}
    service.composer = bad
    with pytest.raises(CharacterError): service.render(identifier,reviewed=True)
    assert not (folder/'final.mp4').exists()
    service.composer = compositor
    service.render(identifier,reviewed=True)


def test_legacy_stale_composing_and_consent_are_preserved(setup):
    service, identifier, folder = ready(setup)
    job=service.read(identifier);job['state']='composing';service.save(job)
    with pytest.raises(CharacterError): service.render(identifier)
    assert service.composition_retry_available(identifier)
    service.composer=compositor
    service.render(identifier,reviewed=True)
    assert service.read(identifier)['state']=='completed'


@pytest.mark.parametrize('phase',['review','publication','completion_save'])
def test_local_commit_failure_is_not_success_and_remains_retryable(setup,monkeypatch,phase):
    service, identifier, folder = ready(setup)
    service.composer=compositor
    from newsflow.character import composition_recovery
    original_move=composition_recovery.move_owned
    original_save=service.save
    from pathlib import Path
    original_write=Path.write_text
    once=[True]
    def move(root, source, destination):
        if once[0] and destination == folder/'final.mp4':
            once[0]=False;raise OSError('synthetic publication interruption')
        return original_move(root,source,destination)
    def save(job):
        if once[0] and job['state']=='completed':
            once[0]=False;raise OSError('synthetic completion journal interruption')
        return original_save(job)
    def write(path,*args,**kwargs):
        if once[0] and path.name=='review.json':
            once[0]=False;raise OSError('synthetic review interruption')
        return original_write(path,*args,**kwargs)
    if phase=='review':monkeypatch.setattr(Path,'write_text',write)
    elif phase=='publication':monkeypatch.setattr(composition_recovery,'move_owned',move)
    else:monkeypatch.setattr(service,'save',save)
    with pytest.raises(CharacterError):service.render(identifier,reviewed=True)
    assert service.read(identifier)['state']=='compose_failed'
    assert service.composition_retry_available(identifier)
    service.render(identifier,reviewed=True)
    assert service.read(identifier)['state']=='completed'
