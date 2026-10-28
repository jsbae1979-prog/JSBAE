"""Private package inventory/retention contracts, not a general-user installer."""
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import shutil
from uuid import uuid4

FORBIDDEN_MODULES={'step13_guard','guard_verification','native_boundary','native_boundary_original','verification_gate','verification_gate_app','guard_capability','app_policy','run_app_policy','technical_boundary','technical_probe','technical_entry','technical_media','native_capability','native_capability_integration','native_guard_copy','native_rtl_filelock','native_app_policy','windows_local_validation'}
FORBIDDEN_SUFFIXES={'.db','.sqlite','.sqlite3','.dpapi','.key','.token','.credentials','.log'}

def relative_name(value):
    if not isinstance(value,str) or not value or '\\' in value or ':' in value or '\x00' in value:raise ValueError('unsafe-package-path')
    p=PurePosixPath(value)
    if p.is_absolute() or any(x in {'.','..',''} for x in value.split('/')):raise ValueError('unsafe-package-path')
    for part in p.parts:
        stem=part.split('.')[0].upper()
        if part.endswith((' ','.')) or any(c in part for c in '<>"|?*') or stem in {'CON','PRN','AUX','NUL','CONIN$','CONOUT$'} or re.fullmatch(r'(COM|LPT)[0-9]',stem):raise ValueError('reserved-package-path')
    if any(x.lower() in {'tools','tests','validation','__pycache__'} for x in p.parts):raise ValueError('test-source-not-payload')
    if any(x.lower() in FORBIDDEN_MODULES for x in p.parts):raise ValueError('verification-module-not-payload')
    if p.suffix.lower() in FORBIDDEN_SUFFIXES or p.name.lower().startswith('.env') or p.stem.lower() in FORBIDDEN_MODULES:raise ValueError('private-or-test-file')
    return p

def ordinary_tree(root,*,source=False):
    root=Path(root).resolve()
    for p in sorted(root.rglob('*')):
        if source and '__pycache__' in p.parts:continue
        if p.is_symlink() or p.is_junction() or getattr(p.lstat(),'st_file_attributes',0)&0x400:raise ValueError('linked-payload')
        if p.is_file():yield p,relative_name(p.relative_to(root).as_posix())

def inventory(root):
    return [{'path':str(rel),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p,rel in ordinary_tree(root)]

def verify(root,manifest):
    expected=manifest['files'];names=[str(relative_name(r['path'])) for r in expected]
    if len({x.casefold() for x in names})!=len(names):raise ValueError('duplicate-payload')
    actual=inventory(root)
    if actual!=expected:raise ValueError('payload-integrity-failed')

def canonical(value):return json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':')).encode()

class LifecycleModel:
    """Synthetic filesystem contract only. Does not install/register/run Windows apps.

    Explicit ownership marker confines the model to a newly created test tree.
    User Data is a sibling of Programs and is never deleted or migrated here.
    """
    def __init__(self,root):
        self.root=Path(root).absolute();self.marker=self.root/'owned-deployment-model.json'
        self.program=self.root/'Programs';self.data=self.root/'Data'
        if self.root.exists():
            if not self.marker.is_file():raise ValueError('unowned-test-root')
        else:
            self.root.mkdir();self.marker.write_bytes(canonical({'kind':'NewsFlow-private-lifecycle-model','version':1}))
        if json.loads(self.marker.read_bytes())!={'kind':'NewsFlow-private-lifecycle-model','version':1}:raise ValueError('marker')
        for p in [self.root,*self.root.parents]:
            if p.is_symlink() or p.is_junction():raise ValueError('reparse-root')
        self.program.mkdir(exist_ok=True);self.data.mkdir(exist_ok=True)
    def current(self):
        p=self.program/'current.json'
        return json.loads(p.read_bytes()) if p.exists() else None
    def _inside_program(self,path):
        path=Path(os.path.abspath(path))
        if not path.is_relative_to(self.program.absolute()) or path==self.program:raise ValueError('outside-owned-programs')
        for p in [path,*path.parents]:
            if p.is_symlink() or p.is_junction():raise ValueError('linked-owned-path')
            if p==self.root:break
        if not path.resolve().is_relative_to(self.program.resolve()):raise ValueError('resolved-program-path')
        return path
    def _delete_stage(self,path):
        # Resolve/bound check precedes every recursive cleanup. Never accepts Data.
        p=self._inside_program(path)
        if not p.name.startswith('.staging-'):raise ValueError('not-owned-staging')
        if p.exists():shutil.rmtree(p)
    def install(self,payload,manifest,expected_digest,*,fail_after=None):
        if hashlib.sha256(canonical(manifest)).hexdigest()!=expected_digest:raise ValueError('untrusted-manifest-digest')
        version=manifest['version']
        if not re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z._-]{0,40}',version):raise ValueError('version')
        verify(payload,manifest)
        destination=self._inside_program(self.program/version)
        if destination.exists():
            verify(destination,manifest)
        else:
            stage=self._inside_program(self.program/('.staging-'+uuid4().hex));stage.mkdir()
            try:
                for n,row in enumerate(manifest['files'],1):
                    rel=relative_name(row['path']);target=stage.joinpath(*rel.parts)
                    target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(Path(payload).joinpath(*rel.parts),target)
                    if fail_after==n:raise OSError('synthetic-interrupted-install')
                verify(stage,manifest);stage.rename(destination)
            except BaseException:
                self._delete_stage(stage);raise
        pointer=self.program/'current.new';pointer.write_bytes(canonical({'version':version,'manifest_digest':expected_digest}))
        os.replace(pointer,self.program/'current.json')
    def uninstall(self,manifests):
        # Remove only known immutable program bytes; preserve unknown files, all Data.
        for version,m in manifests.items():
            if not re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z._-]{0,40}',version):raise ValueError('version')
            root=self._inside_program(self.program/version)
            if root.exists():
                verify(root,m)
                for row in m['files']:self._inside_program(root/row['path']).unlink()
                for p in sorted(root.rglob('*'),key=lambda p:len(p.parts),reverse=True):
                    if p.is_dir():p.rmdir()
                root.rmdir()
        for name in ('current.json','current.new'):
            p=self.program/name
            if p.exists():p.unlink()
