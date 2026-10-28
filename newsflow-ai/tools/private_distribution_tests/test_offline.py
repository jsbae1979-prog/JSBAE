"""Synthetic Windows transaction tests; no operating files/keys or signed claim."""
import json
from pathlib import Path
import sqlite3
from contextlib import closing, contextmanager

import pytest

from newsflow.distribution.offline import (
    OfflineBlocked, OfflineInstall, atomic, digest, payload_check, relative, tree, version,
)
from newsflow.distribution.updates import UpdateBlocked, publisher_matches


@contextmanager
def database(path):
    with closing(sqlite3.connect(path)) as db:
        with db:
            yield db


@pytest.fixture
def installed(tmp_path):
    program = tmp_path / 'Programs'
    profile = tmp_path / 'Data'
    install = OfflineInstall(program, profile)
    source = tmp_path / 'payload-1'
    source.mkdir()
    (source / 'NewsFlowAI-Candidate.exe').write_bytes(b'SYNTHETIC-PAYLOAD-OLD-NOT-EXECUTABLE')
    old = manifest(source, '1.0.0', 1)
    install.initialize(source, old)
    with database(profile / 'newsflow.db') as db:
        db.execute('CREATE TABLE marker(value TEXT)')
        db.execute("INSERT INTO marker VALUES ('original')")
    for name in ('key.dpapi', 'settings.json', 'media.mp4', 'samples-hidden.json'):
        (profile / name).write_bytes(b'SYNTHETIC-OPAQUE-RETAIN-' + name.encode())
    source2 = tmp_path / 'payload-2'
    source2.mkdir()
    (source2 / 'NewsFlowAI-Candidate.exe').write_bytes(b'SYNTHETIC-NEW-DIFFERENT-NOT-EXECUTABLE')
    new = manifest(source2, '1.1.0', 2)
    return install, source2, new


def manifest(source, number, sequence):
    return dict(appId='NewsFlowAI', channel='private-offline', version=number,
                sequence=sequence, supportedFrom=['1.0.0'], files=tree(source))


def marker(profile):
    with database(profile / 'newsflow.db') as db:
        return db.execute('SELECT value FROM marker').fetchone()[0]


def mutate_then_fail(install):
    def fail(slot):
        with database(install.profile / 'newsflow.db') as db:
            db.execute("UPDATE marker SET value='MIGRATED-BUT-FAILED'")
        raise RuntimeError('synthetic health/migration failure')
    return fail


def test_real_sqlite_migration_rollback_and_opaque_files(installed):
    i, source, new = installed
    old = {n: digest(i.profile / n) for n in ('key.dpapi', 'media.mp4', 'settings.json', 'samples-hidden.json')}
    with pytest.raises(RuntimeError):
        i.update_verified(source, new, mutate_then_fail(i))
    assert marker(i.profile) == 'original'
    assert i.current() == {'version': '1.0.0', 'sequence': 1}
    assert json.loads(i.journal.read_bytes())['phase'] == 'ROLLED_BACK'
    assert old == {n: digest(i.profile / n) for n in old}
    assert i.active_executable().read_bytes().startswith(b'SYNTHETIC-PAYLOAD-OLD')


def test_success_commits_after_migration_and_preserves_old_slot(installed):
    i, source, new = installed
    def migrate(slot):
        with database(i.profile / 'newsflow.db') as db:
            db.execute("UPDATE marker SET value='migrated'")
    i.update_verified(source, new, migrate)
    assert marker(i.profile) == 'migrated'
    assert i.current()['version'] == '1.1.0'
    assert (i.slots / '1.0.0/NewsFlowAI-Candidate.exe').exists()
    assert i.pending() is None


def test_power_cut_blocks_launch_and_retry_until_explicit_recovery(installed):
    i, source, new = installed
    def crash(slot):
        with database(i.profile / 'newsflow.db') as db:
            db.execute("UPDATE marker SET value='unknown'")
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        i.update_verified(source, new, crash)
    assert i.pending()['phase'] == 'MIGRATING'
    with pytest.raises(OfflineBlocked):
        i.active_executable()
    with pytest.raises(OfflineBlocked):
        i.update_verified(source, new, lambda slot: None)
    i.recover()
    assert marker(i.profile) == 'original'
    assert i.current()['version'] == '1.0.0'


def test_tamper_refused_before_backup_or_database_changes(installed):
    i, source, new = installed
    (source / 'NewsFlowAI-Candidate.exe').write_bytes(b'TAMPERED')
    with pytest.raises(OfflineBlocked):
        i.update_verified(source, new, lambda slot: None)
    assert marker(i.profile) == 'original'
    assert not i.journal.exists()


@pytest.mark.parametrize('ver,seq,base', [('0.9.0', 3, ['1.0.0']), ('1.0.0', 2, ['1.0.0']), ('1.1.0', 1, ['1.0.0']), ('1.1.0', 2, ['0.9.0'])])
def test_rollback_replay_unsupported_paths(installed, ver, seq, base):
    i, source, new = installed
    new.update(version=ver, sequence=seq, supportedFrom=base)
    with pytest.raises(OfflineBlocked):
        i.update_verified(source, new, lambda slot: None)
    assert not i.journal.exists()


@pytest.mark.parametrize('name', ['../outside', '/root', 'C:/outside', 'a\\b', 'a:stream', 'CON', 'LPT1.txt', 'a/../b', 'a//b', 'x.', 'a/ ', 'a?b'])
def test_unsafe_payload_names(name):
    with pytest.raises(OfflineBlocked):
        relative(name)


def test_extra_file_and_case_collision(installed):
    i, source, new = installed
    (source / 'unexpected.txt').write_text('not inventoried')
    with pytest.raises(OfflineBlocked):
        payload_check(source, new)
    new['files'].append(dict(new['files'][0], path='NEWSFLOWAI-CANDIDATE.EXE'))
    with pytest.raises(OfflineBlocked):
        payload_check(source, new)


def test_two_process_lock_blocks_update_without_force_stop(installed):
    from filelock import FileLock
    i, source, new = installed
    with FileLock(str(i.profile / 'desktop.lock')).acquire(timeout=0):
        with pytest.raises(OfflineBlocked):
            i.update_verified(source, new, lambda slot: None)
    assert not i.journal.exists()


def test_backup_tamper_fails_closed_and_preserves_pending(installed):
    i, source, new = installed
    def crash(slot):
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        i.update_verified(source, new, crash)
    (i.backups / i.pending()['backup'] / 'files/key.dpapi').write_bytes(b'TAMPERED')
    with pytest.raises(OfflineBlocked):
        i.recover()
    assert i.pending() is not None


def test_failed_stage_preserves_pointer_and_data(installed, monkeypatch):
    i, source, new = installed
    import newsflow.distribution.offline as module
    real_copy = module._copy
    def fail(source, dest):
        if '.staging-' in str(dest):
            raise OSError('synthetic copy lock')
        real_copy(source, dest)
    monkeypatch.setattr(module, '_copy', fail)
    with pytest.raises(OSError):
        i.update_verified(source, new, lambda slot: None)
    assert i.current()['version'] == '1.0.0'
    assert marker(i.profile) == 'original'


@pytest.mark.parametrize('value', ['1.0', '01.0.0', '../1.0.0', '1.0.0-beta', None])
def test_invalid_versions(value):
    with pytest.raises(OfflineBlocked):
        version(value)


@pytest.mark.parametrize('observed', [dict(status='NotSigned'), dict(status='Valid', certificateSha256='f'*64, timestamped=True, codeSigning=True), dict(status='Valid', certificateSha256='a'*64, timestamped=False, codeSigning=True)])
def test_no_signature_wrong_publisher_missing_timestamp(observed, tmp_path):
    with pytest.raises(UpdateBlocked):
        publisher_matches(tmp_path / 'synthetic.exe', 'a'*64, lambda p: observed)


def test_unprovisioned_trust_cannot_call_verifier(tmp_path):
    with pytest.raises(UpdateBlocked):
        publisher_matches(tmp_path / 'synthetic.exe', '', lambda p: pytest.fail('must not execute'))


def test_uninstall_retains_data_backups_and_reinstall_not_duplicate(installed):
    i, source, new = installed
    i.update_verified(source, new, lambda slot: None)
    data_before = marker(i.profile)
    backup_ids = [p.name for p in i.backups.iterdir()]
    i.remove_installed_programs()
    assert marker(i.profile) == data_before
    assert [p.name for p in i.backups.iterdir()] == backup_ids
    assert not i.pointer.exists()
    assert not list(i.slots.iterdir())
    i.initialize(source, new)
    assert i.current()['version'] == '1.1.0'
    assert marker(i.profile) == data_before


def test_db_created_during_failed_first_run_is_rolled_back(installed):
    i, source, new = installed
    (i.profile / 'newsflow.db').unlink()
    with pytest.raises(RuntimeError):
        def bad_migration(slot):
            with database(i.profile / 'newsflow.db') as db:
                db.execute('CREATE TABLE partial(value TEXT)')
            raise RuntimeError('migration incomplete')
        i.update_verified(source, new, bad_migration)
    assert not (i.profile / 'newsflow.db').exists()
    assert i.current()['version'] == '1.0.0'


def test_no_backup_recursion_or_secret_content_in_journal(installed):
    i, source, new = installed
    private = i.backups / 'previous-retained'
    private.mkdir()
    (private / 'opaque.dpapi').write_bytes(b'SYNTHETIC-EXCLUDED-BACKUP')
    i.update_verified(source, new, lambda slot: None)
    new_backup = next(p for p in i.backups.iterdir() if p.name != 'previous-retained')
    assert not (new_backup / 'files/update-backups').exists()
    assert b'SYNTHETIC' not in i.journal.read_bytes()


@pytest.mark.parametrize('enabled,observed', [
    (False, None),
    (True, {'status': 'NotSigned'}),
    (True, {'status': 'Valid', 'certificateSha256': 'f'*64, 'timestamped': True, 'codeSigning': True}),
    (True, {'status': 'Valid', 'certificateSha256': 'a'*64, 'timestamped': False, 'codeSigning': True}),
])
def test_shipped_entry_rejects_before_profile_or_payload_access(tmp_path, monkeypatch, enabled, observed):
    import importlib.util
    import sys
    import newsflow.distribution.updates as updates
    local = tmp_path / 'SyntheticLocal'
    local.mkdir()
    bundle = tmp_path / 'Bundle'
    bundle.mkdir()
    (bundle / 'private-mode.json').write_text(json.dumps({'mode': 'update'}))
    (bundle / 'publisher-trust.json').write_text(json.dumps({'updatesEnabled': enabled, 'publisherCertificateSha256': 'a'*64}))
    entry_path = Path(__file__).parents[1] / 'private_distribution/private_entry.py'
    spec = importlib.util.spec_from_file_location('offline_frozen_entry_test', entry_path)
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle), raising=False)
    monkeypatch.setattr(sys, 'argv', ['synthetic-update.exe'])
    monkeypatch.setenv('LOCALAPPDATA', str(local))
    monkeypatch.setattr(updates, 'authenticode', lambda path: observed)
    with pytest.raises((OfflineBlocked, UpdateBlocked)):
        entry.main()
    assert list(local.iterdir()) == []


def test_installer_entry_creates_protected_slots_before_inno_copy(tmp_path, monkeypatch):
    import importlib.util
    import sys
    from newsflow.distribution.windows_profile import private_directory
    local = tmp_path / 'Local'
    local.mkdir()
    bundle = tmp_path / 'Bundle'
    bundle.mkdir()
    (bundle / 'private-mode.json').write_text(json.dumps({'mode': 'launcher'}))
    spec = importlib.util.spec_from_file_location('offline_setup_entry_test', Path(__file__).parents[1] / 'private_distribution/private_entry.py')
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle), raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(local))
    root = local / 'Programs/NewsFlowAI-Private'
    monkeypatch.setattr(sys, 'argv', ['helper.exe', '--prepare-install', str(root)])
    entry.main()
    assert private_directory(root / 'slots') == root / 'slots'
    assert private_directory(local / 'NewsFlowAI-Desktop/v1/update-backups').exists()
    with pytest.raises(OfflineBlocked):
        entry.main()  # no adoption/overwrite of an existing installation
    slot = root / 'slots/1.0.0'
    slot.mkdir()
    (slot / 'NewsFlowAI-Candidate.exe').write_bytes(b'SYNTHETIC-INNO-COPY')
    initial = manifest(slot, '1.0.0', 1)
    (root / 'initial-release.json').write_text(json.dumps(initial))
    monkeypatch.setattr(sys, 'argv', ['helper.exe', '--finalize-install', str(root)])
    entry.main()
    assert json.loads((root / 'current.json').read_bytes())['version'] == '1.0.0'


@pytest.mark.parametrize('extension,mime', [('.png', 'image/png'), ('.jpg', 'image/jpeg')])
def test_sample_poster_mime_preserves_existing_jpeg_and_supports_new_png(tmp_path, monkeypatch, extension, mime):
    from types import SimpleNamespace
    from newsflow.samples import routes
    path = tmp_path / ('synthetic-poster' + extension)
    path.write_bytes(b'SYNTHETIC-HEADER-SELECTION-ONLY')
    service = SimpleNamespace(get=lambda identifier: {}, checked=lambda row, poster: path)
    monkeypatch.setattr(routes, 'service', lambda request: service)
    response = routes.poster(None, 'synthetic')
    assert response.headers['content-type'] == mime


@pytest.mark.parametrize('error', [ValueError('sk-proj-synthetic-secret-never-print'), PermissionError(13, 'SYNTHETIC-TOKEN-NEVER-PRINT')])
def test_failure_message_excludes_arbitrary_secret_error_text(error):
    import importlib.util
    entry_path = Path(__file__).parents[1] / 'private_distribution/private_entry.py'
    spec = importlib.util.spec_from_file_location('private_error_display_test', entry_path)
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    text = entry.failure_message(error)
    assert str(error) not in text
    assert 'sk-proj' not in text and 'SYNTHETIC-TOKEN' not in text
    assert type(error).__name__ in text
