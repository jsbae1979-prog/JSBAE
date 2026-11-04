"""Isolated same-user paths, opaque fake keys, no providers or product launch."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import hashlib,json,socket,sqlite3
import pytest
from bat_distribution import data_location as move
from bat_distribution.operation import load_operating,OperatingRequests
from bat_distribution.windows_live import ValidationConfig
from newsflow.distribution.windows_profile import private_directory,current_sid
from newsflow.distribution.local_access import LaunchSession,LocalAccess
from starlette.testclient import TestClient
import win32security

@pytest.fixture
def setup_move(tmp_path,monkeypatch):
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:tmp_path))
    base=tmp_path/'AppData/Local/NewsFlowAI-BAT';base.mkdir(parents=True)
    source=private_directory(base/'v1');program=tmp_path/'Program';(program/'app').mkdir(parents=True)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    config=ValidationConfig(program,source,port,'a'*32,False,'restored-local-operation')
    sid=win32security.ConvertSidToStringSid(current_sid())
    marker={'installationId':config.installation_id,'ownerSid':sid,'opaqueCredentialsOnly':True,'sourceDbSha256':'b'*64}
    (source/'restored-install.private.json').write_text(json.dumps(marker))
    with closing(sqlite3.connect(source/'newsflow.db')) as db:
        db.execute('create table data (id integer primary key,value text)');db.execute("insert into data values(1,'synthetic')");db.commit()
    (source/'fake-key.dpapi').write_bytes(b'OPAQUE_SYNTHETIC_NOT_A_REAL_KEY')
    (source/'media').mkdir();(source/'media/test.mp4').write_bytes(b'FAKE_NOT_VIDEO')
    (source/'backups').mkdir();(source/'backups/keep.txt').write_bytes(b'preserve backup')
    launch={'schemaVersion':2,'profileKind':'restored-local-operation','readOnly':False,'decryptCredentials':False,
        'automaticJobsEnabled':False,'externalExecutionEnabled':False,'openBrowser':False,'installationId':config.installation_id,
        'port':port,'programRoot':str(program)}
    move.atomic(base/'launch.json',launch)
    layout={'localOperationConnected':True,'validationOnly':False,'operatingProfile':'restored-local-operation',
        'updatesEnabled':False,'validationConfigSha256':move.digest(base/'launch.json')}
    move.atomic(program/'app/layout.json',layout)
    return config,base,sid,tmp_path/'NewData'

@pytest.mark.parametrize('case',['source','inside-source','ancestor','program','inside-program','drive-root','occupied','network','relative','missing-parent'])
def test_unsafe_destination_refused_without_changes(setup_move,case):
    c,b,s,target=setup_move
    occupied=target.parent/'Occupied';occupied.mkdir();(occupied/'keep').write_text('keep')
    values={'source':c.profile,'inside-source':c.profile/'child','ancestor':c.profile.parent,
        'program':c.program,'inside-program':c.program/'data','drive-root':Path(c.profile.anchor),
        'occupied':occupied,'network':Path('\\\\example.invalid\\share\\data'),'relative':Path('relative'),
        'missing-parent':target/'missing/data'}
    before=move.profile_files(c.profile)
    with pytest.raises(ValueError):move.request_move(c,str(values[case]))
    assert move.profile_files(c.profile)==before and not (c.profile/move.PENDING).exists()

def test_mapped_network_drive_rejected_before_stat(setup_move):
    c,b,s,target=setup_move
    with pytest.raises(ValueError,match='fixed-local-drive'):move.request_move(c,str(target),drive_kind=lambda anchor:4)
    assert not target.exists()

@pytest.mark.parametrize('precreate',[False,True])
def test_copy_switch_keeps_all_originals_and_second_start_is_noop(setup_move,precreate):
    c,b,s,target=setup_move
    if precreate:target.mkdir()
    before=move.profile_files(c.profile);tables=move.table_state(c.profile/'newsflow.db')
    request=move.request_move(c,str(target));assert request['state']=='pending'
    assert move.request_move(c,str(target))==request
    assert move.apply_pending(c,s) is True
    layout=json.loads((c.program/'app/layout.json').read_bytes())
    loaded=load_operating(c.program,layout);assert loaded.profile==target
    assert move.profile_files(c.profile)==before
    assert move.table_state(target/'newsflow.db')==tables
    assert (target/'fake-key.dpapi').read_bytes()==b'OPAQUE_SYNTHETIC_NOT_A_REAL_KEY'
    assert (target/'media/test.mp4').read_bytes()==b'FAKE_NOT_VIDEO'
    assert (target/'backups/keep.txt').is_file()
    private_directory(target)
    assert move.apply_pending(loaded,s) is False
    with pytest.raises(ValueError,match='unresolved'):move.apply_pending(c,s)
    raw=json.loads((b/'launch.json').read_bytes())
    assert raw['readOnly'] is False and all(raw[k] is False for k in ('decryptCredentials','automaticJobsEnabled','externalExecutionEnabled'))
    assert layout['updatesEnabled'] is False

@pytest.mark.parametrize('case',['active','foreign','absolute-json','absolute-db','space','locked'])
def test_migration_blocks_before_switch(setup_move,case,monkeypatch):
    c,b,s,target=setup_move;move.request_move(c,str(target));old=(b/'launch.json').read_bytes()
    if case=='active':(c.profile/'bat-session.private.json').write_text('{}')
    if case=='foreign':s='S-1-5-21-1-2-3-999'
    if case=='absolute-json':(c.profile/'project.json').write_text(json.dumps({'path':str(c.profile/'media/test.mp4')}))
    if case=='absolute-db':
        with sqlite3.connect(c.profile/'newsflow.db') as db:db.execute('update data set value=?',(str(c.profile/'media/test.mp4'),))
    if case=='space':monkeypatch.setattr(move.shutil,'disk_usage',lambda _:type('U',(),{'free':0})())
    if case=='locked':
        from filelock import FileLock
        with FileLock(str(c.profile/'desktop.lock')):
            with pytest.raises(Exception):move.apply_pending(c,s)
    else:
        with pytest.raises(ValueError):move.apply_pending(c,s)
    assert (b/'launch.json').read_bytes()==old and not target.exists()

def test_copy_failure_retains_source_backup_and_blocks_automatic_replay(setup_move,monkeypatch):
    c,b,s,target=setup_move;move.request_move(c,str(target));before=move.profile_files(c.profile)
    real=move.copy_verified;calls=[]
    def fail(source,dest,rows):
        calls.append(dest)
        if dest==target:raise OSError('Synthetic disk interruption')
        return real(source,dest,rows)
    monkeypatch.setattr(move,'copy_verified',fail)
    with pytest.raises(OSError):move.apply_pending(c,s)
    assert move.profile_files(c.profile)==before
    layout=json.loads((c.program/'app/layout.json').read_bytes());assert load_operating(c.program,layout).profile==c.profile
    assert len(list((b/'data-move-backups').glob('*/index.private.json')))==1
    with pytest.raises(ValueError):move.apply_pending(c,s)

