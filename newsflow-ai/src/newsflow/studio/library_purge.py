"""Explicit purge of trashed, owned local media. Audit rows remain tombstoned.

No recursive removal, provider calls, DB row deletion, retry loop or credential
access. A durable manifest precedes unlink; failures remain visible and blocked
from restore until the user explicitly continues the same manifest.
"""
from contextlib import ExitStack
from pathlib import Path
import hashlib,re
from filelock import FileLock,Timeout
from sqlalchemy import select
from newsflow.db.models import WorkspaceRemoval,RenderJob,PublishDraft,ImagePost,ImagePostDelivery,IntelligenceRun,AppSetting
from newsflow.distribution.windows_profile import unlinked
from .library_visibility import LibraryVisibility,LibraryVisibilityError,parse_items,ACTIVE

MEDIA={'.mp4','.mov','.webm','.png','.jpg','.jpeg','.webp','.wav','.mp3','.m4a','.ass','.srt','.vtt','.txt'}
PERMANENT={'purging','purge_failed','purged'}
class PurgeError(ValueError):pass

def identifiers(raw):
    import json
    try:items=json.loads(raw) if isinstance(raw,str) else raw
    except (TypeError,ValueError):raise PurgeError('invalid') from None
    if not isinstance(items,list) or not 1<=len(items)<=100 or any(not isinstance(i,str) for i in items) or len(set(items))!=len(items):
        raise PurgeError('invalid')
    for i in items:
        if i.startswith('archive:'):
            if not re.fullmatch(r'archive:(?:video:[1-9][0-9]{0,18}|activity:[A-Za-z0-9:_-]{1,70})',i):raise PurgeError('invalid')
            if i.startswith('archive:video:') and int(i.split(':')[-1])>9223372036854775807:raise PurgeError('invalid')
        else:
            try:parse_items([i])
            except LibraryVisibilityError:raise PurgeError('invalid') from None
    return items

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()

class LibraryPurge:
    def __init__(self,state):
        self.state=state;self.root=unlinked(Path(state.config.data_dir));self.visibility=LibraryVisibility(state.sessions,state.character)

    def _safe(self,relative):
        p=Path(relative)
        if p.is_absolute() or not p.parts or any(x in {'.','..'} or ':' in x for x in p.parts):raise PurgeError('path')
        full=unlinked(self.root/p)
        if not full.resolve().is_relative_to(self.root.resolve()):raise PurgeError('path')
        # Saved manifests may only name product-owned media roots, never keys/backups.
        if p.parts[0] not in {'character','outputs','sample-copies','trash'} or full.suffix.lower() not in MEDIA:raise PurgeError('path')
        return full

    def _file(self,path,expected=None):
        try:rel=Path(path).relative_to(self.root).as_posix();p=self._safe(rel)
        except (OSError,ValueError):raise PurgeError('path') from None
        if not p.exists():return None
        if not p.is_file() or p.stat().st_nlink!=1:raise PurgeError('shared')
        value=digest(p)
        if expected is not None and value!=expected:raise PurgeError('integrity')
        return {'path':rel,'sha256':value,'bytes':p.stat().st_size}

    def _news(self,session,identifier):
        row=session.get(RenderJob,identifier)
        if row is None:raise PurgeError('missing')
        if row.status in ACTIVE:raise PurgeError('busy')
        if session.scalar(select(PublishDraft.id).where(PublishDraft.render_job_id==identifier)) is not None:raise PurgeError('linked')
        if not re.fullmatch(r'video-[a-f0-9]{32}\.mp4',row.output_name):raise PurgeError('path')
        old=session.get(WorkspaceRemoval,f'video:{identifier}')
        if old:
            detail=old.detail
            if detail.get('state') not in {'trashed',*PERMANENT}:raise PurgeError('busy')
            if detail.get('output_name')!=row.output_name:raise PurgeError('path')
            return [self._file(self.state.video.root/'trash/videos'/row.output_name,detail.get('sha256'))]
        return [self._file(self.state.video.outputs/row.output_name)]

    def _plan(self,session,item,row):
        detail=row.detail if isinstance(row.detail,dict) else {}
        if not item.startswith('archive:'):
            try:self.visibility._item(session,item,removing=True)
            except LibraryVisibilityError as e:raise PurgeError(str(e)) from None
        if detail.get('state') in {'purging','purge_failed'}:
            files=detail.get('purgeFiles')
            if not isinstance(files,list) or len(files)>10000:raise PurgeError('integrity')
            for f in files:
                if not isinstance(f,dict) or set(f)!={'path','sha256','bytes'} or not re.fullmatch('[a-f0-9]{64}',str(f['sha256'])):raise PurgeError('integrity')
                p=self._safe(f['path'])
                if not self._owned(session,item,p):raise PurgeError('path')
                if p.exists() and (not p.is_file() or p.stat().st_nlink!=1 or digest(p)!=f['sha256']):raise PurgeError('integrity')
            return files
        if detail.get('state')=='purged':return []
        if item.startswith('archive:'):
            key=item.removeprefix('archive:')
            return self._news(session,int(key.split(':')[1])) if key.startswith('video:') else []
        try:self.visibility._item(session,item,removing=True)
        except LibraryVisibilityError as e:raise PurgeError(str(e)) from None
        kind,value=item.split(':',1)
        if kind=='news':return self._news(session,int(value))
        if kind=='character':
            job=self.state.character.read(value)
            if 'unknown' in job['state'] or any('unknown' in str(s.get('state','')) for s in job.get('scenes',[])):raise PurgeError('unknown')
            folder=unlinked(self.state.character.folder(value));files=[]
            for path in folder.rglob('*'):
                unlinked(path)
                if path.is_file() and path.suffix.lower() in MEDIA:files.append(self._file(path))
            return files
        if kind=='reference':
            import json
            record=json.loads(session.get(AppSetting,'sample_content:v1:copy:'+value).value)
            return [self._file(self.root/'sample-copies/v1'/value/(record['sha256']+ext),record['sha256'])
                    for ext in ('.png','.jpg','.mp4')]
        if kind=='post':
            row=session.get(ImagePost,int(value))
            if session.scalar(select(ImagePostDelivery.id).where(ImagePostDelivery.post_id==row.id)) is not None:raise PurgeError('linked')
            if not re.fullmatch(r'image-[a-f0-9]{32}\.jpg',row.filename):raise PurgeError('path')
            return [self._file(self.state.image_posts.outputs/row.filename,row.sha256)]
        rows=list(session.scalars(select(IntelligenceRun).where(IntelligenceRun.kind=='feed_image',
            IntelligenceRun.options['style'].as_string()=='studio',IntelligenceRun.options['draft_id'].as_integer()==int(value))))
        files=[]
        for output in rows:
            if output.status in ACTIVE:raise PurgeError('busy')
            if output.status!='success':continue
            name=output.result.get('filename','')
            if not re.fullmatch(r'generated-[0-9]+\.jpg',name):raise PurgeError('path')
            files.append(self._file(self.state.image_generation.outputs/name,output.result.get('sha256')))
        return files

    def _owned(self,session,item,path):
        if item.startswith('archive:activity:'):return False
        if item.startswith('archive:video:'):item='news:'+item.split(':')[-1]
        kind,value=item.split(':',1)
        if kind=='character':
            job=self.state.character.read(value)
            if 'unknown' in job['state'] or any('unknown' in str(s.get('state','')) for s in job.get('scenes',[])):raise PurgeError('unknown')
            return path.is_relative_to(self.state.character.folder(value))
        if kind=='news':
            row=session.get(RenderJob,int(value))
            if not row or row.status in ACTIVE:raise PurgeError('busy')
            if session.scalar(select(PublishDraft.id).where(PublishDraft.render_job_id==row.id)) is not None:raise PurgeError('linked')
            return path in {self.state.video.outputs/row.output_name,self.state.video.root/'trash/videos'/row.output_name}
        if kind=='post':
            row=session.get(ImagePost,int(value))
            if not row:return False
            if session.scalar(select(ImagePostDelivery.id).where(ImagePostDelivery.post_id==row.id)) is not None:raise PurgeError('linked')
            return path==self.state.image_posts.outputs/row.filename
        if kind=='reference':
            import json
            row=session.get(AppSetting,'sample_content:v1:copy:'+value)
            if not row:return False
            h=json.loads(row.value).get('sha256','')
            return path in {self.root/'sample-copies/v1'/value/(h+ext) for ext in ('.png','.jpg','.mp4')}
        rows=session.scalars(select(IntelligenceRun).where(IntelligenceRun.kind=='feed_image',
            IntelligenceRun.options['style'].as_string()=='studio',IntelligenceRun.options['draft_id'].as_integer()==int(value)))
        valid=set()
        for output in rows:
            if output.status in ACTIVE:raise PurgeError('busy')
            if output.status=='success':valid.add(self.state.image_generation.outputs/output.result.get('filename',''))
        return path in valid

    def purge(self,raw,*,confirmed=False):
        if confirmed is not True:raise PurgeError('confirmation')
        items=identifiers(raw);keys={i:(i.removeprefix('archive:') if i.startswith('archive:') else 'library:'+i) for i in items}
        try:
            with ExitStack() as stack:
                stack.enter_context(FileLock(str(self.root/'library-purge.lock')).acquire(timeout=0))
                stack.enter_context(FileLock(str(self.state.video.root/'workspace-cleanup.lock')).acquire(timeout=0))
                if any(i.startswith('character:') for i in items):stack.enter_context(self.state.character.lock())
                plans={}
                with self.state.sessions.begin() as session:
                    session.connection().exec_driver_sql('BEGIN IMMEDIATE')
                    for item,key in keys.items():
                        row=session.get(WorkspaceRemoval,key)
                        if row is None:raise PurgeError('not_trashed')
                        plans[item]=[f for f in self._plan(session,item,row) if f is not None]
                    # All items validate before any tombstone or file is changed.
                    for item,key in keys.items():
                        row=session.get(WorkspaceRemoval,key)
                        if row.detail.get('state')!='purged':row.detail={**row.detail,'state':'purging','purgeFiles':plans[item]}
                try:
                    files={f['path']:f for rows in plans.values() for f in rows}
                    for rel,f in files.items():
                        p=self._safe(rel)
                        if not p.exists():continue
                        if not p.is_file() or p.stat().st_nlink!=1 or digest(p)!=f['sha256']:raise PurgeError('integrity')
                        p.unlink()
                except (OSError,ValueError):
                    with self.state.sessions.begin() as session:
                        for key in keys.values():
                            row=session.get(WorkspaceRemoval,key)
                            if row.detail.get('state')!='purged':row.detail={**row.detail,'state':'purge_failed'}
                    raise PurgeError('failed') from None
                with self.state.sessions.begin() as session:
                    for item,key in keys.items():
                        row=session.get(WorkspaceRemoval,key);row.detail={**row.detail,'state':'purged','purgeFiles':plans[item]}
                        aliases=[]
                        if item.startswith('news:'):aliases=['video:'+item.split(':')[1]]
                        if item.startswith('archive:video:'):aliases=['library:news:'+item.split(':')[-1]]
                        for alias in aliases:
                            other=session.get(WorkspaceRemoval,alias)
                            if other:other.detail={**other.detail,'state':'purged'}
        except Timeout:raise PurgeError('busy') from None
        return {'purged':items,'recoverable':False,'historicalRecordsPreserved':True}
