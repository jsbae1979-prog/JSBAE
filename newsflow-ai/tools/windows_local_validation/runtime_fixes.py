"""Remove optional startup probes from the synthetic runner, never grant new I/O.

No installed dependency is edited or pre-imported. Core WindowsFileLock is intact.
"""
import hashlib
import ntpath
import os
from pathlib import Path
import sys

STRICT_SOURCE_SHA256='41564e8e8253a0ac0ed146fdaebdbed94afa3f7d604bd6b0ce25410f8dc436df'

def bounded_import_paths(entries,roots):
    def canonical(value):return ntpath.normcase(ntpath.abspath(value))
    allowed=[canonical(str(root)) for root in roots]
    def keep(entry):
        path=canonical(entry)
        for root in allowed:
            try:
                if ntpath.commonpath((path,root))==root:return True
            except ValueError:pass
        return False
    return [entry for entry in entries if isinstance(entry,str) and keep(entry)]

class OptionalLinkProbe:
    def __init__(self,policy,source,original):
        self.policy=policy;self.source=ntpath.normcase(str(source));self.original=original;self.suppressed=0
    def invoke(self,frame,source,target,args,kwargs):
        exact=(frame.f_globals.get('__name__')=='filelock._strict'
               and frame.f_code.co_name=='_probe_link_follow_symlinks'
               and ntpath.normcase(frame.f_code.co_filename)==self.source)
        if exact and not args and kwargs=={'follow_symlinks':False}:
            # These checks add no permission. They also reject Reparse/ADS/UNC.
            first=self.policy.path(source,True);second=self.policy.path(target,True)
            temp=ntpath.join(self.policy.workspace,'temp')
            try:inside=ntpath.commonpath((first,temp))==temp and ntpath.commonpath((second,temp))==temp
            except ValueError:inside=False
            if inside and ntpath.dirname(first)==ntpath.dirname(second) and ntpath.basename(first)=='probe-source' and ntpath.basename(second)=='probe-link':
                self.suppressed+=1
                # The unchanged optional probe explicitly catches this and returns False.
                raise NotImplementedError('Optional hardlink capability probe disabled in synthetic runner')
        # Every real link attempt still reaches the unchanged Guard denial.
        return self.original(source,target,*args,**kwargs)
    def __call__(self,source,target,*args,**kwargs):
        return self.invoke(sys._getframe(1),source,target,args,kwargs)

def install_optional_probe(policy,package):
    source=Path(package)/'_strict.py'
    policy.path(source)
    if hashlib.sha256(source.read_bytes()).hexdigest()!=STRICT_SOURCE_SHA256:
        raise RuntimeError('Unreviewed optional probe source; no interception installed')
    if 'filelock' in sys.modules:raise RuntimeError('Guard-first filelock import must remain unchanged')
    hook=OptionalLinkProbe(policy,source,os.link);os.link=hook
    return hook
