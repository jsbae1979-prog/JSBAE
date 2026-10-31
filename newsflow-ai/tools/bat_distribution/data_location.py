"""Same-user data relocation: explicit local request, stopped copy, verified switch.

Never decrypts keys, merges profiles, deletes the old profile, or starts a process.
The launch configuration and program manifest remain the authority after a switch.
"""
from __future__ import annotations
from contextlib import closing, ExitStack
from pathlib import Path
from uuid import uuid4
import hashlib,json,os,shutil,socket,sqlite3
from filelock import FileLock
from .lifecycle import Blocked, ordinary_absolute, separated

PENDING='data-location-request.private.json'
EPHEMERAL={'desktop.lock','bat-session.private.json','browser-launch.private.json','browser-open-result.json',PENDING}

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def atomic(path,value):
    path=ordinary_absolute(path); temp=path.with_name(path.name+'.move-'+uuid4().hex)
    with temp.open('xb') as f:
        f.write(json.dumps(value,ensure_ascii=False,indent=2).encode('utf8'));f.flush();os.fsync(f.fileno())
    try:
        if path.exists():
            import win32security as s
            flag=s.DACL_SECURITY_INFORMATION
            s.SetFileSecurity(str(temp),flag,s.GetFileSecurity(str(path),flag))
        os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)

def destination_for(config,value,*,drive_kind=None):
    if not isinstance(value,str) or not value.strip():raise Blocked('destination-required')
    # Reject a mapped network drive before querying anything on that drive.
    p=Path(value.strip())
    if not p.is_absolute() or not p.drive or str(p).startswith(('\\\\','//')):
        raise Blocked('absolute-local-data-path-required')
    if drive_kind is None:
        import win32file
        drive_kind=win32file.GetDriveType
    if drive_kind(p.anchor)!=3:raise Blocked('fixed-local-drive-required')
    p=ordinary_absolute(p); source=ordinary_absolute(config.profile)
    separated(config.program,p)
    if p==source or p.is_relative_to(source) or source.is_relative_to(p) or p==Path(p.anchor):
        raise Blocked('data-path-overlap')
    control=ordinary_absolute(Path.home()/'AppData/Local/NewsFlowAI-BAT')
    if p==control or control.is_relative_to(p):raise Blocked('launch-control-overlap')
    if not p.parent.is_dir():raise Blocked('destination-parent-required')
    if p.exists() and (not p.is_dir() or any(p.iterdir())):raise Blocked('destination-must-be-empty')
    return p

def request_move(config,value,*,drive_kind=None):
    target=destination_for(config,value,drive_kind=drive_kind)
    pending=ordinary_absolute(config.profile/PENDING)
    request={'schemaVersion':1,'installationId':config.installation_id,'source':str(config.profile),
             'destination':str(target),'state':'pending'}
    if pending.exists() and json.loads(pending.read_bytes())!=request:
        raise Blocked('another-data-move-pending')
    if not pending.exists():atomic(pending,request)
    return {'state':'pending','dataDirectory':str(config.profile),'destination':str(target),
            'message':'이동 예약 완료. 정상 종료 후 다음 Start에서 복사·검증하고 전환합니다. 기존 폴더는 보존합니다.'}

def table_state(path):
    out={}
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('pragma integrity_check').fetchone()!=('ok',):raise Blocked('database-integrity')
        for (name,) in db.execute("select name from sqlite_master where type='table' order by name"):
            rows=db.execute('select * from "'+name.replace('"','""')+'"').fetchall()
            out[name]={'count':len(rows),'sha256':hashlib.sha256(repr(sorted(rows,key=repr)).encode()).hexdigest()}
    return out

def profile_files(source):
    rows=[]
    for f in sorted(source.rglob('*')):
        ordinary_absolute(f)
        if not f.is_file():continue
        rel=f.relative_to(source).as_posix()
        if rel in EPHEMERAL or rel.endswith(('.lock','-wal','-shm')):continue
        rows.append({'path':rel,'bytes':f.stat().st_size,'sha256':digest(f)})
    return rows

def check_relative_references(source,rows):
    """Do not silently invalidate absolute path contracts or rewrite user history."""
    needles=(str(source).casefold(),source.as_posix().casefold())
    for row in rows:
        f=source/row['path']
        if f.suffix=='.json' and not set(f.relative_to(source).parts)&{'logs','diagnostics','backups','credential-backups','update-backups','archives'}:
            def strings(v):
                if isinstance(v,str):yield v
                elif isinstance(v,dict):
                    for x in v.values():yield from strings(x)
                elif isinstance(v,list):
                    for x in v:yield from strings(x)
            if any(any(n in s.casefold() for n in needles) for s in strings(json.loads(f.read_bytes()))):
                raise Blocked('absolute-profile-reference-requires-review')
        if f.suffix.lower() in {'.db','.sqlite','.sqlite3'}:
            with closing(sqlite3.connect(f.as_uri()+'?mode=ro',uri=True)) as db:
                for (t,) in db.execute("select name from sqlite_master where type='table'"):
                    q=lambda x:'"'+x.replace('"','""')+'"'
                    for col in db.execute('pragma table_info('+q(t)+')').fetchall():
                        values=db.execute('select '+q(col[1])+' from '+q(t)+' where typeof('+q(col[1])+')=\'text\'')
                        if any(any(n in v[0].casefold() for n in needles) for v in values):
                            raise Blocked('absolute-profile-reference-requires-review')

def copy_verified(source,dest,rows):
    tables={}
    for row in rows:
        f=ordinary_absolute(source/row['path']);out=ordinary_absolute(dest/row['path'])
        if digest(f)!=row['sha256']:raise Blocked('source-changed')
        out.parent.mkdir(parents=True,exist_ok=True)
        if f.suffix.lower() in {'.db','.sqlite','.sqlite3'}:
            with closing(sqlite3.connect(f.as_uri()+'?mode=ro',uri=True)) as src:
                with closing(sqlite3.connect(out)) as dst:src.backup(dst)
            expected=table_state(f)
            if table_state(out)!=expected:raise Blocked('database-copy-mismatch')
            tables[row['path']]=expected
        else:
            with f.open('rb') as src,out.open('xb') as dst:
                shutil.copyfileobj(src,dst,1024*1024);dst.flush();os.fsync(dst.fileno())
            if digest(out)!=row['sha256']:raise Blocked('copy-mismatch')
    return tables

def apply_pending(config,owner_sid):
    pending=ordinary_absolute(config.profile/PENDING)
    if not pending.exists():return False
    if config.profile_kind!='restored-local-operation':raise Blocked('operating-profile-required')
    if pending.stat().st_size>4096:raise Blocked('move-request-size')
    req=json.loads(pending.read_bytes())
    if (set(req)!={'schemaVersion','installationId','source','destination','state'} or req['schemaVersion']!=1
        or req['installationId']!=config.installation_id or req['source']!=str(config.profile) or req['state']!='pending'):
        raise Blocked('unresolved-data-move-no-retry')
    from newsflow.distribution.windows_profile import private_directory,current_sid
    import win32security as security
    if security.ConvertSidToStringSid(current_sid())!=owner_sid:raise Blocked('same-user-data-move-required')
    from .restored_install import check_restored_profile,restored_paths
    check_restored_profile(config,owner_sid)
    target=destination_for(config,req['destination'])
    if (config.profile/'bat-session.private.json').exists():raise Blocked('stop-required-before-data-move')
    base,_=restored_paths(); launch=base/'launch.json'; layout=config.program/'app/layout.json'
    old_launch=launch.read_bytes();old_layout=layout.read_bytes()
    raw=json.loads(old_launch);manifest=json.loads(old_layout)
    if manifest['validationConfigSha256']!=hashlib.sha256(old_launch).hexdigest():raise Blocked('launch-integrity')
    with ExitStack() as stack:
        stack.enter_context(FileLock(str(config.profile/'desktop.lock')).acquire(timeout=0))
        lease=stack.enter_context(socket.socket());lease.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        lease.bind(('127.0.0.1',config.port))
        rows=profile_files(config.profile);check_relative_references(config.profile,rows)
        if shutil.disk_usage(target.parent).free<sum(r['bytes'] for r in rows)*2+64*1024*1024:
            raise Blocked('insufficient-data-drive-space')
        backups=base/'data-move-backups';private_directory(backups)
        backup=backups/uuid4().hex;private_directory(backup)
        (backup/'launch.before.json').write_bytes(old_launch);(backup/'layout.before.json').write_bytes(old_layout)
        private_directory(backup/'files')
        tables=copy_verified(config.profile,backup/'files',rows)
        atomic(backup/'index.private.json',{'source':str(config.profile),'destination':str(target),'files':rows,'tables':tables,'state':'backed-up'})
        # Empty pre-created target only; no existing content or foreign owner is adopted.
        if target.exists():
            sd=security.GetFileSecurity(str(target),security.OWNER_SECURITY_INFORMATION)
            if security.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner())!=owner_sid:raise Blocked('destination-owner')
            target.rmdir()
        private_directory(target)
        atomic(pending,{**req,'state':'copying'})
        try:
            if copy_verified(config.profile,target,rows)!=tables:raise Blocked('copy-table-mismatch')
            if profile_files(config.profile)!=rows:raise Blocked('source-changed')
            raw['dataDirectory']=str(target)
            new_launch=json.dumps(raw,ensure_ascii=False,indent=2).encode('utf8')
            atomic(launch,raw);manifest['validationConfigSha256']=digest(launch)
            atomic(layout,manifest)
            # A completed receipt stays outside the active data tree and never authorizes deletion.
            atomic(backup/'result.private.json',{'state':'switched','source':str(config.profile),
                'destination':str(target),'fileCount':len(rows),'bytes':sum(r['bytes'] for r in rows),
                'launchSha256':digest(launch),'layoutSha256':digest(layout)})
            atomic(pending,{**req,'state':'completed'})
        except BaseException:
            # Restore configuration, retain copied data and failure evidence; no automatic retry.
            atomic(launch,json.loads(old_launch));atomic(layout,json.loads(old_layout))
            restored=json.loads(old_layout);restored['validationConfigSha256']=digest(launch);atomic(layout,restored)
            atomic(pending,{**req,'state':'failed-no-retry'})
            raise
    return True

def install(app,config):
    if config.profile_kind=='restored-local-operation':app.state.data_location_request=lambda value:request_move(config,value)
