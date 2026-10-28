"""Windows11 local synthetic runner policy; independent of the CI-only AppPolicy.

Trusted verification harness, not OS isolation against a hostile Python program.
No product, installed dependency, CI guard or global native table is changed.
"""
import contextlib
import ntpath
import os
from pathlib import Path
import socket
import sqlite3
import sys
import threading
import re
import time
from verification_gate import Denied, dos_path, within

FILES={'open','os.listdir','os.scandir','os.remove','os.rmdir','os.mkdir','os.rename','os.chmod','os.utime','os.link','os.symlink'}
NETWORK={'socket.bind','socket.connect','socket.sendto','socket.sendmsg','socket.getaddrinfo','socket.gethostbyname','socket.gethostbyaddr','socket.getnameinfo'}
PROCESS={'subprocess.Popen','_winapi.CreateProcess','os.system','os.startfile','os.startfile/2','os.exec','os.posix_spawn','os.spawn'}
LOCK_NAMES=('autopilot','collection','render','ai-video','claude-feed-card','feed-image-generation','top3-feeds','scheduler','smoke')
class WindowsLocalPolicy:
    def __init__(self,workspace,read_roots,port=18765):
        if os.name!='nt' or sys.version_info[:3]!=(3,14,7) or sys.getwindowsversion().build<22000 or sys.getwindowsversion().product_type!=1:
            raise Denied('Windows11-Python3147-only')
        if os.environ.get('GITHUB_ACTIONS') is not None:
            raise Denied('local-runner-does-not-use-CI-environment')
        if port!=18765:raise Denied('fixed-test-port-required')
        self.workspace=dos_path(str(workspace));self.read_roots=tuple(dos_path(str(p)) for p in read_roots)
        self.port=port;self.phase='bootstrap';self.denials=[];self.allowed={};self.halt=False
        self.database_paths=set();self.sqlite_connections=set();self.closed_connections=0;self._connection_type=None
        self.listener=None;self._socketpair_code=socket.socketpair.__code__
        self.owner=threading.get_ident();self.io_depth=0;self.threads=[];self._thread_grant=threading.local()
    def deny(self,reason):
        frames=[];frame=sys._getframe(1);event=None;targets=[]
        for _ in range(20):
            if frame is None:break
            frames.append({'module':frame.f_globals.get('__name__',''),'file':self.describe_path(frame.f_code.co_filename),'line':frame.f_lineno,'function':frame.f_code.co_name})
            if frame.f_code is WindowsLocalPolicy.audit.__code__:
                event=frame.f_locals.get('event');values=frame.f_locals.get('args',())
                count=2 if event in {'os.link','os.symlink','os.rename'} else 1
                targets=[self.describe_path(v) for v in values[:count]]
            frame=frame.f_back
        self.halt=True;self.denials.append({'phase':self.phase,'reason':reason,'event':event,'targets':targets,'monotonic_seconds':time.monotonic(),'frames':frames});raise Denied(reason)
    def describe_path(self,value):
        # No file reads/resolution, argument repr, contents, query strings or credentials.
        if not isinstance(value,(str,bytes,os.PathLike)):return '<NON_PATH>'
        raw=os.fsdecode(value)
        if raw.startswith('<'):return raw[:80]
        path=ntpath.normcase(ntpath.abspath(raw))
        operating=ntpath.normcase(r'C:\Codex\NewsFlowAI')
        if within(path,operating):return '<OPERATING_PROTECTED>'
        if within(path,self.workspace):return '<SYNTHETIC>/'+ntpath.relpath(path,self.workspace).replace('\\','/')
        if Path(path).suffix.lower() in {'.dpapi','.token','.credentials','.key'}:return '<SECRET_PATH_REDACTED>'
        return re.sub(r'(?i)([a-z]:\\users\\)[^\\]+',r'\1<USER>',path).replace('\\','/')
    def checkpoint(self,guard_denials=(),gate_denials=()):
        # Libraries can catch PermissionError for optional feature detection.
        # A returned create_app() is not permission to serve after such a denial.
        if self.halt or self.denials or guard_denials or gate_denials:
            self.halt=True
            raise Denied('recorded-boundary-rejection-stops-before-next-phase')
    def path(self,value,write=False):
        if isinstance(value,int):self.deny('raw-file-descriptor')
        raw=os.fsdecode(value)
        if raw.startswith(('\\\\','\\','/')) or '\x00' in raw:self.deny('UNC-device-path')
        drive,tail=ntpath.splitdrive(raw)
        if ':' in tail or any(p in {'.','..'} for p in tail.replace('/','\\').split('\\')):self.deny('ADS-or-traversal')
        p=dos_path(os.path.abspath(raw));roots=(self.workspace,) if write else (self.workspace,)+self.read_roots
        if not any(within(p,r) for r in roots):self.deny('outside-synthetic-write' if write else 'outside-fixed-read-roots')
        if Path(p).suffix.lower() in {'.dpapi','.token','.credentials'}:self.deny('credential-material')
        q=Path(p)
        while True:
            try:
                if getattr(q.lstat(),'st_file_attributes',0)&0x400:self.deny('reparse-path')
            except FileNotFoundError:pass
            if q.parent==q:break
            q=q.parent
        return p
    def database(self,value):
        raw=os.fsdecode(value)
        if raw==':memory:' or raw.lower().startswith('file:'):self.deny('unregistered-SQLite-location')
        p=self.path(raw,True)
        if p not in self.database_paths:self.deny('unregistered-SQLite-database')
        return p
    def register_listener(self,sock):
        if self.listener is not None or threading.get_ident()!=self.owner:self.deny('listener-registration')
        if sock.family!=socket.AF_INET or sock.type&15!=socket.SOCK_STREAM:self.deny('listener-type')
        self.listener=sock
    def network(self,event,args):
        if event not in {'socket.bind','socket.connect'}:self.deny('DNS-datagram-external-network')
        sock,address=args
        if sock.family!=socket.AF_INET or sock.type&15!=socket.SOCK_STREAM or not isinstance(address,tuple) or len(address)!=2 or address[0]!='127.0.0.1' or type(address[1]) is not int or address[1]==8765:self.deny('non-owned-IPv4-loopback')
        if event=='socket.bind' and sock is self.listener and address==('127.0.0.1',self.port):return
        f=sys._getframe(1)
        for _ in range(14):
            if f is None:break
            if f.f_code is self._socketpair_code:
                if event=='socket.bind' and sock is f.f_locals.get('lsock') and address==('127.0.0.1',0):return
                listener=f.f_locals.get('lsock')
                if event=='socket.connect' and sock is f.f_locals.get('csock') and listener is not None and address==listener.getsockname():return
                self.deny('invalid-eventloop-selfpipe')
            f=f.f_back
        self.deny('unowned-loopback-client-or-listener')
    def audit(self,event,args):
        if event in NETWORK:self.network(event,args);self.allowed[event]=self.allowed.get(event,0)+1;return True
        if event in PROCESS:self.deny('arbitrary-process-worker-shell')
        if event in {'sqlite3.enable_load_extension','sqlite3.load_extension'}:self.deny('SQLite-extension')
        if event=='sqlite3.connect':self.database(args[0]);return True
        if event=='sqlite3.connect/handle':
            if self._connection_type is None or type(args[0]) is not self._connection_type:self.deny('foreign-SQLite-connection')
            return True
        if event not in FILES:return False
        if event in {'os.link','os.symlink'}:self.deny('link-creation')
        if event=='open':
            mode,flags=args[1] or '',args[2] or 0
            self.path(args[0],any(c in str(mode) for c in 'wax+') or bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)))
        elif event in {'os.listdir','os.scandir'}:self.path(args[0] if args and args[0] is not None else os.getcwd())
        elif event=='os.rename':self.path(args[0],True);self.path(args[1],True)
        else:self.path(args[0],True)
        self.allowed[event]=self.allowed.get(event,0)+1;return True
    def install_sqlite(self,paths):
        self.database_paths={self.path(p,True) for p in paths};original=sqlite3.connect;parent=sqlite3.Connection;policy=self
        class SyntheticConnection(parent):
            def __init__(self,*a,**k):
                super().__init__(*a,**k);parent.execute(self,'PRAGMA temp_store=MEMORY')
                def authorize(action,a,b,db,trigger):
                    if action in {sqlite3.SQLITE_ATTACH,sqlite3.SQLITE_DETACH}:return sqlite3.SQLITE_DENY
                    if action==sqlite3.SQLITE_FUNCTION and str(b).lower() in {'load_extension','readfile','writefile'}:return sqlite3.SQLITE_DENY
                    if action==sqlite3.SQLITE_PRAGMA:
                        if str(a).lower() in {'writable_schema','temp_store_directory','data_store_directory'}:return sqlite3.SQLITE_DENY
                        if str(a).lower()=='temp_store' and b not in (None,'2','MEMORY','memory'):return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK
                parent.set_authorizer(self,authorize);policy.sqlite_connections.add(self)
            def set_authorizer(self,*a,**k):policy.deny('SQLite-authorizer-replacement')
            def enable_load_extension(self,*a,**k):policy.deny('SQLite-extension')
            def load_extension(self,*a,**k):policy.deny('SQLite-extension')
            def close(self):
                parent.close(self)
                if self in policy.sqlite_connections:policy.sqlite_connections.remove(self);policy.closed_connections+=1
        self._connection_type=SyntheticConnection
        def connect(database,*a,**k):
            policy.database(database)
            if len(a)>4 or 'factory' in k or k.get('uri',False):policy.deny('SQLite-connect-options')
            k['factory']=SyntheticConnection;return original(database,*a,**k)
        sqlite3.connect=connect;sqlite3.dbapi2.connect=connect
    def install_threads(self):
        policy=self;original=threading.Thread.start
        def start(thread,*a,**k):
            module=sys.modules.get('anyio._backends._asyncio');expected=getattr(module,'WorkerThread',None) if module else None
            if policy.io_depth<1 or threading.get_ident()!=policy.owner or type(thread) is not expected or thread.name!='AnyIO worker thread' or sum(t.is_alive() for t in policy.threads)>=2:policy.deny('unapproved-thread')
            policy.threads.append(thread);policy._thread_grant.target=thread
            try:return original(thread,*a,**k)
            finally:policy._thread_grant.target=None
        threading.Thread.start=start
        import _thread
        def wrap(fn):
            def bounded(function,*a,**k):
                owner=getattr(policy._thread_grant,'target',None)
                if owner is None or getattr(function,'__self__',None) is not owner:policy.deny('raw-thread')
                return fn(function,*a,**k)
            return bounded
        for name in ['start_new_thread','start_joinable_thread']:
            if hasattr(_thread,name):setattr(_thread,name,wrap(getattr(_thread,name)))
        if hasattr(threading,'_start_joinable_thread'):threading._start_joinable_thread=wrap(threading._start_joinable_thread)
    @contextlib.contextmanager
    def request_io(self):
        if threading.get_ident()!=self.owner:self.deny('request-owner')
        self.io_depth+=1
        try:yield
        finally:self.io_depth-=1
    def status(self):return {'phase':self.phase,'denials':self.denials,'remaining_SQLite_connections':len(self.sqlite_connections),'SQLite_closed':self.closed_connections,'threads_alive':sum(t.is_alive() for t in self.threads),'processes_started':0,'halt':self.halt,'allowed':self.allowed}
