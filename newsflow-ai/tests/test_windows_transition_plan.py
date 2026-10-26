"""Executable rehearsal of the proposed procedure, NOT a production updater.

Every input is constructed under pytest tmp_path. No operating paths/CLI accepted.
No raw backup, DB, media or credential file is exported as CI evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import wave
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_ai_video_service import make_draft

from newsflow.config import Settings
from newsflow.db.models import (
    AppSetting,
    NewsArticle,
    NewsSource,
    PlatformAccount,
    ProductionSchedule,
    PublishDraft,
    PublishJob,
    RenderJob,
    VideoProject,
)
from newsflow.db.session import make_engine, migrate, session_factory
from newsflow.main import create_app
from newsflow.migrate_data import migrate_data
from newsflow.news.rss_adapter import FakeRSSAdapter

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = '0a59bfb41eec6b243e4470f67cd53c1e7cd07e52'


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or path.is_junction():
            raise ValueError('link requires separate review')
        if path.is_file():
            raw = path.read_bytes()
            result[str(path.relative_to(root))] = (len(raw), hashlib.sha256(raw).hexdigest())
    return result


def logical(path):
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {name: db.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall() for name in names}


def initialize(root, revision='0018'):
    root.mkdir(parents=True)
    engine = make_engine(root/'newsflow.db')
    config = Config()
    config.set_main_option('script_location', str(ROOT/'src/newsflow/db/migrations').replace('%', '%%'))
    with engine.begin() as c:
        config.attributes['connection'] = c
        command.upgrade(config, revision)
    sessions = session_factory(engine)
    with sessions.begin() as s:
        source = NewsSource(name='Synthetic disabled RSS', url='https://example.com/rss', enabled=False)
        s.add(source)
        s.flush()
        article = NewsArticle(source_id=source.id, title='합성 보존 기사', summary='보존 검사',
                              url='https://example.com/a', canonical_url='https://example.com/a', publisher='Synthetic')
        s.add(article)
        s.flush()
        article_id = article.id
        s.add(AppSetting(key='transition_synthetic_marker', value='unchanged-setting'))
        s.add(ProductionSchedule(id='a'*32, name='합성 일시 중지 예약', kind='daily', local_time='09:00',
                                 weekdays=[], options={'synthetic': True}, status='paused'))
    draft = make_draft(SimpleNamespace(state=SimpleNamespace(sessions=sessions)), article_id)
    with sessions.begin() as s:
        project = VideoProject(draft_id=draft, title='합성 영상', duration=30, snapshot={}, sources={})
        s.add(project)
        s.flush()
        job = RenderJob(project_id=project.id, status='completed', progress=100, output_name='synthetic.mp4')
        account = PlatformAccount(platform='youtube', label='Synthetic disconnected', account_type='channel',
                                  status='not_connected', credential_ref=None)
        s.add_all([job, account])
        s.flush()
        post = PublishDraft(render_job_id=job.id, platform='youtube', title='합성 대기', description='합성',
                            hashtags=[], sources={}, media_sha256='a'*64, account_id=account.id,
                            content_reviewed=False, copyright_confirmed=False)
        s.add(post)
        s.flush()
        for index, status in enumerate(['success', 'unknown', 'failed']):
            s.add(PublishJob(draft_id=post.id, platform='youtube', status=status, message='synthetic only',
                             idempotency_key=str(index)*64))
    engine.dispose()
    for folder in ['outputs/videos', 'assets', 'tts-elevenlabs', 'content']:
        (root/folder).mkdir(parents=True, exist_ok=True)
    ffmpeg = Path(os.environ.get('NEWSFLOW_FFMPEG') or shutil.which('ffmpeg') or '')
    assert ffmpeg.is_absolute() and ffmpeg.is_file(), 'Use the verified absolute FFmpeg fixture path'
    subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','color=c=blue:s=128x224:r=10',
                    '-t','0.3','-c:v','libx264','-pix_fmt','yuv420p',str(root/'outputs/videos/synthetic.mp4')], check=True)
    from PIL import Image
    Image.new('RGB', (32, 32), '#123456').save(root/'assets/synthetic.png')
    with wave.open(str(root/'tts-elevenlabs/synthetic.wav'), 'wb') as audio:
        audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\0\0'*800)
    (root/'session.key').write_text('a'*64, encoding='ascii')
    # Opaque synthetic preservation fixture, never loaded as a credential.
    (root/'content/synthetic-envelope.bin').write_bytes(b'opaque-synthetic-backup-envelope')
    return root


class Rehearsal:
    """Restricted test fixture; deliberately has no installation or deployment API."""
    def __init__(self, root):
        self.root = root.resolve()

    def inside(self, path):
        assert path.resolve().is_relative_to(self.root)
        return path

    def backup(self, source, target, *, stopped=True, space=True, copy=shutil.copy2):
        self.inside(source)
        self.inside(target)
        if not stopped or not space:
            raise ValueError('backup precondition failed; update blocked')
        before = inventory(source)
        target.mkdir(exist_ok=False)
        try:
            for name in before:
                dest = target/'raw'/name
                dest.parent.mkdir(parents=True, exist_ok=True)
                copy(source/name, dest)
            if before != inventory(source) or before != inventory(target/'raw'):
                raise ValueError('incomplete or changed snapshot')
            # Inspect a disposable copy: never checkpoint/delete WAL on source/sealed raw.
            work = self.root/('verify-'+target.name)
            shutil.copytree(target/'raw', work)
            logical(work/'newsflow.db')
            with closing(sqlite3.connect(work/'newsflow.db')) as db, closing(sqlite3.connect(target/'canonical.db')) as out:
                db.backup(out)
            assert logical(work/'newsflow.db') == logical(target/'canonical.db')
            metadata = {'files': before, 'canonical_sha256': hashlib.sha256((target/'canonical.db').read_bytes()).hexdigest()}
            (target/'manifest.json').write_text(json.dumps(metadata), encoding='utf8')
            (target/'VERIFIED').write_text('synthetic test only', encoding='ascii')
        except Exception:
            # No VERIFIED marker means this partial backup must never authorize update.
            assert not (target/'VERIFIED').exists()
            raise
        return target

    def restore(self, backup, destination):
        self.inside(backup)
        self.inside(destination)
        if not (backup/'VERIFIED').is_file():
            raise ValueError('unverified backup; restore blocked')
        saved = json.loads((backup/'manifest.json').read_text())
        if saved['files'] != {k: list(v) for k, v in inventory(backup/'raw').items()}:
            raise ValueError('backup changed; restore blocked')
        if saved['canonical_sha256'] != hashlib.sha256((backup/'canonical.db').read_bytes()).hexdigest():
            raise ValueError('canonical DB changed; restore blocked')
        shutil.copytree(backup/'raw', destination)  # refuses an existing destination
        # Only this NEW restore staging tree is normalized; sealed raw and original stay intact.
        for suffix in ['', '-wal', '-shm']:
            (destination/('newsflow.db'+suffix)).unlink(missing_ok=True)
        shutil.copy2(backup/'canonical.db', destination/'newsflow.db')
        assert logical(destination/'newsflow.db') == logical(backup/'canonical.db')
        return destination


def test_restore_point_update_failure_and_restart(tmp_path, record_property):
    current_main = ROOT/'src/newsflow/main.py'
    current_main_hash = hashlib.sha256(current_main.read_bytes()).hexdigest()
    data = initialize(tmp_path/'한글 사용자 data')
    original = logical(data/'newsflow.db')
    file_hashes = inventory(data)
    record_property('snapshot_files', len(file_hashes))
    record_property('snapshot_bytes', sum(value[0] for value in file_hashes.values()))
    plan = Rehearsal(tmp_path)
    backup = plan.backup(data, tmp_path/'backup-unique')
    archive = tmp_path/'release.tar'
    # Read-only GitHub blob fixtures are fetched by the approved parent beforehand.
    # This tests restoration of exactly five entry/dependency files, not all src.
    # No Git subprocess or repository mutation is permitted in the test child.
    validation_root = Path(os.environ['STEP13_ROOT']).resolve()
    baseline = validation_root / 'baseline-code'
    manifest_file = baseline / 'manifest-safe.json'
    pins = json.loads((validation_root / 'native-config-private.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(manifest_file.read_bytes()).hexdigest() == pins['baseline_manifest_SHA256']
    manifest = json.loads(manifest_file.read_text(encoding='utf-8-sig'))
    assert manifest['commit'] == BASE_SHA
    expected_paths = {
        'newsflow-ai/src/newsflow/main.py', 'newsflow-ai/run.bat',
        'newsflow-ai/tools/windows_launcher.py', 'newsflow-ai/pyproject.toml',
        'newsflow-ai/requirements-dev.lock',
    }
    assert set(manifest['files']) == expected_paths
    import io
    import tarfile
    with tarfile.open(archive, 'w') as packaged:
        for relative in sorted(expected_paths):
            source_file = baseline / 'files' / relative
            assert source_file.resolve().is_relative_to((baseline / 'files').resolve())
            assert not source_file.is_symlink() and not source_file.is_junction()
            raw = source_file.read_bytes()
            assert hashlib.sha256(raw).hexdigest() == manifest['files'][relative]
            member = tarfile.TarInfo(relative)
            member.size = len(raw)
            member.mode = 0o644
            packaged.addfile(member, io.BytesIO(raw))
    record_property('code_baseline_commit', BASE_SHA)
    record_property('code_baseline_files', len(expected_paths))
    archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    # Simulate a failed isolated migration transaction; never mutate the source/backup.
    candidate = plan.restore(backup, tmp_path/'candidate')
    with (closing(sqlite3.connect(candidate/'newsflow.db')) as db,
          pytest.raises(sqlite3.OperationalError), db):
        db.execute("UPDATE app_settings SET value='bad' WHERE key='transition_synthetic_marker'")
        db.execute('INSERT INTO nonexistent_table VALUES (1)')
    assert logical(candidate/'newsflow.db') == original
    rolled = plan.restore(backup, tmp_path/'rollback')
    assert logical(rolled/'newsflow.db') == original
    assert inventory(data) == file_hashes
    for name, value in file_hashes.items():
        if not name.startswith('newsflow.db'):
            assert inventory(rolled)[name] == value
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == archive_hash
    # Verify code archive extraction; no checkout/reset or installation switch.
    import tarfile
    with tarfile.open(archive) as tar:
        tar.extractall(tmp_path/'rollback-code', filter='data')
    restored_code = tmp_path/'rollback-code/newsflow-ai'
    for relative in expected_paths:
        restored_file = tmp_path/'rollback-code'/relative
        assert hashlib.sha256(restored_file.read_bytes()).hexdigest() == manifest['files'][relative]
    # Git blob bytes use LF; the Windows .gitattributes checkout uses CRLF.
    # Preserve all archive hashes, then compare launcher content without EOL conversion noise.
    restored_launcher = (restored_code/'run.bat').read_bytes()
    checkout_launcher = (ROOT/'run.bat').read_bytes()
    assert b'\r\n' in checkout_launcher
    assert b'\n' not in checkout_launcher.replace(b'\r\n', b'')
    assert restored_launcher.replace(b'\r\n', b'\n') == checkout_launcher.replace(b'\r\n', b'\n')
    # An old release is restored exactly, not expected to equal a newer working tree.
    assert (restored_code/'src/newsflow/main.py').read_bytes() == (baseline/'files/newsflow-ai/src/newsflow/main.py').read_bytes()
    assert hashlib.sha256(current_main.read_bytes()).hexdigest() == current_main_hash
    for _ in range(2):
        app = create_app(Settings(data_dir=rolled), FakeRSSAdapter({}))
        with TestClient(app, base_url='http://127.0.0.1') as client:
            for route in ['/', '/news', '/ai', '/video', '/videos', '/queue', '/simple-settings', '/health']:
                assert client.get(route).status_code == 200
            with app.state.sessions() as s:
                assert s.get(AppSetting,'transition_synthetic_marker').value == 'unchanged-setting'
                assert set(s.scalars(select(PublishJob.status))) == {'success','unknown','failed'}
                assert s.get(ProductionSchedule,'a'*32).status == 'paused'
    assert inventory(data) == file_hashes
    assert hashlib.sha256(current_main.read_bytes()).hexdigest() == current_main_hash
    for name, value in file_hashes.items():
        if not name.startswith('newsflow.db'):
            assert inventory(rolled)[name] == value


@pytest.mark.parametrize('old_revision', ['0016', '0017'])
def test_additive_upgrade_preserves_every_old_table_and_restore_revision(tmp_path, old_revision, record_property):
    data = initialize(tmp_path/'old', old_revision)
    old = logical(data/'newsflow.db')
    with closing(sqlite3.connect(data/'newsflow.db')) as db:
        schemas = dict(db.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"))
    record_property('old_tables', len(old)-1)
    record_property('old_rows', sum(len(rows) for name, rows in old.items() if name != 'alembic_version'))
    backup = Rehearsal(tmp_path).backup(data, tmp_path/'backup')
    stage = Rehearsal(tmp_path).restore(backup, tmp_path/'candidate')
    engine = make_engine(stage/'newsflow.db')
    migrate(engine)
    engine.dispose()
    after = logical(stage/'newsflow.db')
    assert after['alembic_version'] == [('0018',)]
    with closing(sqlite3.connect(stage/'newsflow.db')) as db:
        for table, schema in schemas.items():
            assert db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0] == schema
    for table, rows in old.items():
        if table != 'alembic_version':
            assert after[table] == rows
    restored = Rehearsal(tmp_path).restore(backup, tmp_path/'restore')
    assert logical(restored/'newsflow.db') == old
    # Do not start newer code on restored older DB: it would migrate again.


def test_wal_committed_rows_are_in_snapshot(tmp_path):
    data = tmp_path/'wal-source'
    data.mkdir()
    with closing(sqlite3.connect(data/'newsflow.db')) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA wal_autocheckpoint=0')
        db.execute('CREATE TABLE marker (value TEXT)')
        db.execute("INSERT INTO marker VALUES ('committed-wal')")
        db.commit()
        assert (data/'newsflow.db-wal').stat().st_size > 0
        # Open but idle writer is a test fixture for residual WAL, not permission for live backup.
        snapshot = Rehearsal(tmp_path).backup(data,tmp_path/'backup')
        restored = Rehearsal(tmp_path).restore(snapshot,tmp_path/'restore')
        assert logical(restored/'newsflow.db')['marker'] == [('committed-wal',)]


@pytest.mark.parametrize('failure', ['running','space','permission','partial','mutating'])
def test_partial_backups_never_authorize_update(tmp_path, failure):
    source = tmp_path/'source'
    source.mkdir()
    with closing(sqlite3.connect(source/'newsflow.db')) as db:
        db.execute('CREATE TABLE marker (value TEXT)')
    (source/'media.bin').write_bytes(b'synthetic')
    def failing_copy(src, dst):
        if failure == 'permission':
            raise PermissionError('synthetic permission denial')
        if failure == 'partial':
            Path(dst).write_bytes(b'partial')
            raise OSError('synthetic no space during copy')
        result = shutil.copy2(src,dst)
        if failure == 'mutating':
            (source/'media.bin').write_bytes(b'changed fixture')
        return result
    with pytest.raises((ValueError,OSError)):
        Rehearsal(tmp_path).backup(source,tmp_path/'partial',stopped=failure!='running',
                                  space=failure!='space',copy=failing_copy)
    assert not (tmp_path/'partial/VERIFIED').exists()
    with pytest.raises(ValueError):
        Rehearsal(tmp_path).restore(tmp_path/'partial',tmp_path/'must-not-exist')
    assert not (tmp_path/'must-not-exist').exists()


def test_tamper_and_overwrite_refused(tmp_path):
    data = initialize(tmp_path/'source')
    plan = Rehearsal(tmp_path)
    backup = plan.backup(data,tmp_path/'backup')
    with pytest.raises(FileExistsError):
        plan.backup(data,backup)
    existing = tmp_path/'existing'
    existing.mkdir()
    with pytest.raises(FileExistsError):
        plan.restore(backup,existing)
    (backup/'raw/session.key').write_bytes(b'corrupt synthetic backup')
    with pytest.raises(ValueError):
        plan.restore(backup,tmp_path/'blocked')
    assert not (tmp_path/'blocked').exists()


def test_legacy_migrate_data_is_not_current_backup_tool(tmp_path):
    data = initialize(tmp_path/'source')
    before = logical(data/'newsflow.db')
    with pytest.raises(ValueError, match='지원하지 않는 DB 버전'):
        migrate_data(data,tmp_path/'unsupported-target')
    assert logical(data/'newsflow.db') == before
    assert not (tmp_path/'unsupported-target/newsflow.db').exists()


@pytest.mark.skipif(sys.platform != 'win32', reason='Native current-user DPAPI requires Windows')
def test_native_synthetic_credential_copy_restores_only_same_user_context(tmp_path):
    from test_production_dpapi import IDENTITY, KEY, bundle

    from newsflow.oauth.production_dpapi import ProductionVaultError, SyntheticProductionCredentialVault
    root = tmp_path/'source'
    vault = SyntheticProductionCredentialVault(root)
    ref = vault.store(KEY,IDENTITY,bundle())
    original = inventory(root)
    restored = tmp_path/'restored'
    shutil.copytree(root,restored)
    reopened = SyntheticProductionCredentialVault(restored)
    assert reopened.load(KEY,IDENTITY,ref) == vault.load(KEY,IDENTITY,ref)
    assert inventory(root) == original
    with pytest.raises(ProductionVaultError):
        reopened.load('youtube:other-account',IDENTITY,ref)
    # No assertion that another Windows user/PC can decrypt; not tested here.
