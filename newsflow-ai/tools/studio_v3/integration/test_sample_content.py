"""Focused offline sample behavior on disposable Windows CI only."""
import hashlib
import json
from io import BytesIO

import pytest

# Historical 12-item starter bundle tests, retired by the user's 2026-10-29 instruction.
# Existing reports remain evidence of the earlier version. Current ownership/retirement
# behavior is covered by tests/test_sample_retirement.py (20 focused PASS).
pytest.skip("RETIRED: bundled sample UX/assets removed; replacement: tests/test_sample_retirement.py", allow_module_level=True)
from PIL import Image
from sqlalchemy import func, select

from test_full_app_forms import client, token


@pytest.fixture
def app_client(tmp_path):
    # Same deny-process semantics as the accepted GUI fixture; preserve class
    # inheritance needed by CPython Windows asyncio, never pre-import filelock.
    class GUIFixturePatch(pytest.MonkeyPatch):
        def setattr(self, *args, **kwargs):
            if len(args) >= 3 and getattr(args[0], '__name__', '') == 'subprocess' and args[1] == 'Popen':
                parent = args[0].Popen
                class DeniedPopen(parent):
                    def __new__(cls, *a, **k):
                        raise AssertionError('Actual subprocess forbidden in synthetic app tests')
                args = (args[0], args[1], DeniedPopen) + args[3:]
            return super().setattr(*args, **kwargs)
    mp = GUIFixturePatch()
    fixture = client.__wrapped__(tmp_path, mp)
    try:
        yield next(fixture)
    finally:
        fixture.close()
        mp.undo()


def service(app, root=None):
    from newsflow.samples.catalog import Samples
    args = (app.state.sessions, app.state.config.data_dir, app.state.image_studio)
    return Samples(*args, root=root) if root else Samples(*args)


def counts(app):
    from newsflow.db.models import ContentDraft, IntelligenceRun
    with app.state.sessions() as s:
        return [s.scalar(select(func.count()).select_from(model)) for model in (IntelligenceRun, ContentDraft)]


def test_first_run_offline_catalog_no_generation_history(app_client):
    c, app = app_client
    before = counts(app)
    a = c.get('/api/samples').json()
    assert a['schemaVersion'] == 1 and len(a['assets']) == 12 and not a['warning']
    assert {t: sum(x['type'] == t for x in a['assets']) for t in ('standalone','news-top3','character','news-short','character-short')} == {
        'standalone': 3, 'news-top3': 3, 'character': 3, 'news-short': 1, 'character-short': 2}
    assert all(x['sample'] and not x['providerGenerated'] and not x['rightsVerified'] and not x['hidden'] for x in a['assets'])
    assert c.get('/api/samples').json() == a
    assert not (app.state.config.data_dir/'sample-copies').exists()
    assert counts(app) == before == [0, 0]
    assert c.get('/api/studio/production-context').json()['top3'] == []


def test_all_files_hash_decode_and_video_ranges(app_client):
    c, _ = app_client
    for x in c.get('/api/samples').json()['assets']:
        r = c.get(x['mediaUrl'])
        assert r.status_code == 200 and r.headers['content-type'] == x['mime']
        assert len(r.content) == x['bytes'] and hashlib.sha256(r.content).hexdigest() == x['sha256']
        if x['mime'] == 'image/png':
            with Image.open(BytesIO(r.content)) as im:
                im.load();assert im.size == (720,1080)
        else:
            part = c.get(x['mediaUrl'], headers={'range':'bytes=0-1023'})
            assert part.status_code == 206 and part.content == r.content[:1024]
            assert x['audio'] is False and x['duration'] == 12 and x['width'] == 720 and x['height'] == 1280
            assert c.get(x['posterUrl']).headers['content-type'] == 'image/jpeg'


def test_csrf_origin_copy_idempotence_and_user_file_preserved(app_client):
    c, app = app_client
    url = '/api/samples/standalone-city/copy'
    assert c.post(url, data={}).status_code == 403
    csrf = token(c)
    assert c.post(url,data={'csrf_token':csrf},headers={'Origin':'https://external.invalid'}).status_code == 403
    sentinel=app.state.config.data_dir/'my-project.txt';sentinel.write_text('keep-user-work')
    before = counts(app)
    for _ in range(3):
        r=c.post(url,data={'csrf_token':csrf});assert r.status_code == 200
    row=next(x for x in c.get('/api/samples').json()['assets'] if x['id']=='standalone-city')
    assert row['copied']
    assert hashlib.sha256(c.get(row['copyUrl']).content).hexdigest()==row['sha256']
    assert len(list((app.state.config.data_dir/'sample-copies').rglob('*.png')))==1
    assert counts(app)==before and sentinel.read_text()=='keep-user-work'
    assert 'attachment' in c.get(row['copyUrl']+'?download=true').headers['content-disposition']
    assert service(app).listing()['assets']==c.get('/api/samples').json()['assets']


def test_hide_restart_restore_and_user_isolation(app_client,tmp_path):
    c, app = app_client
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from newsflow.db.models import AppSetting
    from newsflow.samples.catalog import Samples
    csrf=token(c)
    assert c.post('/api/samples/character-cat/visibility',data={'csrf_token':csrf,'hidden':'true'}).status_code==200
    assert next(x for x in service(app).listing()['assets'] if x['id']=='character-cat')['hidden']
    engine=create_engine('sqlite:///'+str(tmp_path/'other-user.db'))
    AppSetting.__table__.create(engine)
    other=Samples(sessionmaker(engine),tmp_path/'other-user',app.state.image_studio)
    assert not any(x['hidden'] or x['copied'] for x in other.listing()['assets'])
    other.copy('standalone-cat')
    assert other.copy_path(other.get('standalone-cat')).is_file()
    assert not service(app).copy_path(service(app).get('standalone-cat')).exists()
    assert not any(x['copied'] for x in service(app).listing()['assets'])
    engine.dispose()
    assert c.post('/api/samples/character-cat/visibility',data={'csrf_token':csrf,'hidden':'false'}).status_code==200
    assert not any(x['hidden'] for x in service(app).listing()['assets'])


def test_character_use_creates_only_local_reference_until_explicit_save(app_client):
    c,app=app_client;csrf=token(c)
    assert app.state.character.listing()==[]
    result=c.post('/api/samples/character-robot/copy',data={'csrf_token':csrf,'use':'true'}).json()
    assert result['editableProject'] is False and result['referenceAsset']
    assert app.state.character.listing()==[] and counts(app)==[0,0]
    defaults=c.get('/api/studio/modules/characters').json()['catalog']['characterDefaults']
    r=c.post('/character',data={'csrf_token':csrf,'topic':'합성 로봇 샘플 참조 작업','episode_limit':'5','day_limit':'20',
        'script_model':defaults['script_model'],'video_model':defaults['video_model'],'reference_asset':result['referenceAsset']})
    assert r.status_code==303
    job=app.state.character.listing()[0]
    assert job['state']=='needs_script' and not job.get('output')
    assert len(app.state.character.listing())==1 and counts(app)==[0,0]


def test_video_copy_is_reference_only_not_fake_completed_project(app_client):
    c,app=app_client;csrf=token(c)
    before=counts(app)
    r=c.post('/api/samples/character-short-cat/copy',data={'csrf_token':csrf,'use':'true'}).json()
    assert r['editableProject'] is False and r['referenceAsset']
    assert c.get(r['mediaUrl']).status_code==200
    assert counts(app)==before and app.state.character.listing()==[]


def test_missing_corrupt_and_outside_manifest_do_not_block_user_work(app_client,tmp_path):
    _,app=app_client
    s=service(app,tmp_path/'missing');assert s.listing()['assets']==[] and s.listing()['warning']
    root=tmp_path/'broken';root.mkdir()
    (root/'manifest.json').write_text('{bad-json')
    assert service(app,root).listing()['warning']
    good=service(app).get('standalone-city')
    (root/'manifest.json').write_text(json.dumps({'version':1,'assets':[{**good,'path':'../external.png'}]}))
    assert service(app,root).listing()['assets']==[]
    (root/'manifest.json').write_text(json.dumps({'version':1,'assets':[{**good,'path':'broken.png'}]}))
    (root/'broken.png').write_bytes(b'not-a-png')
    assert service(app,root).listing()['assets']==[]
    assert counts(app)==[0,0]


def test_existing_copy_not_overwritten_when_modified(app_client):
    _,app=app_client
    from newsflow.samples.catalog import SampleError
    s=service(app);s.copy('standalone-earth')
    row=s.get('standalone-earth');path=s.copy_path(row)
    path.write_bytes(b'user-edited-file')
    with pytest.raises(SampleError):s.copy('standalone-earth')
    assert path.read_bytes()==b'user-edited-file'
    assert hashlib.sha256(s.checked(row).read_bytes()).hexdigest()==row['sha256']


def test_full_app_reinitialization_keeps_private_copy_and_visibility(tmp_path):
    # Recreate the actual app/services/SQLite engine against the same synthetic
    # user directory. This is not an EXE or Windows 11 process restart claim.
    root=tmp_path/'repeated-start'
    first=app_client.__wrapped__(root)
    try:
        c,app=next(first);csrf=token(c)
        assert c.post('/api/samples/standalone-city/copy',data={'csrf_token':csrf}).status_code==200
        assert c.post('/api/samples/character-cat/visibility',data={'csrf_token':csrf,'hidden':'true'}).status_code==200
        folder=app.state.config.data_dir
        sentinel=folder/'existing-project.txt';sentinel.write_text('preserve-on-update')
        before=sorted(str(x.relative_to(folder)) for x in folder.rglob('*.png'))
    finally:
        first.close()
    second=app_client.__wrapped__(root)
    try:
        c,app=next(second)
        listing=c.get('/api/samples').json()['assets']
        assert len(listing)==12
        assert next(x for x in listing if x['id']=='character-cat')['hidden']
        copied=next(x for x in listing if x['id']=='standalone-city')
        assert copied['copied'] and c.get(copied['copyUrl']).status_code==200
        assert sorted(str(x.relative_to(folder)) for x in folder.rglob('*.png'))==before
        assert sentinel.read_text()=='preserve-on-update' and counts(app)==[0,0]
    finally:
        second.close()
