"""CI-only minimum app-initialization policy; no operating entry point."""
import contextlib
import ntpath
import os
from pathlib import Path
import socket
import sqlite3
import sys
import threading
from verification_gate import Denied, dos_path, within

FILE_EVENTS={"open","os.listdir","os.scandir","os.remove","os.rmdir","os.mkdir",
             "os.rename","os.chmod","os.utime","os.link","os.symlink"}
NETWORK={"socket.bind","socket.connect","socket.sendto","socket.sendmsg","socket.getaddrinfo",
         "socket.gethostbyname","socket.gethostbyaddr","socket.getnameinfo"}
PROCESS={"subprocess.Popen","_winapi.CreateProcess","os.system","os.startfile",
         "os.startfile/2","os.exec","os.posix_spawn","os.spawn"}
FORBIDDEN_SUFFIXES={".dpapi",".token",".credentials"}
LOCK_NAMES=("autopilot","collection","render","ai-video","claude-feed-card",
            "feed-image-generation","top3-feeds","scheduler","smoke")

class AppPolicy:
    def __init__(self,workspace,read_roots):
        if os.name!="nt" or os.environ.get("GITHUB_ACTIONS")!="true":
            raise Denied("Windows-CI-only")
        self.workspace=dos_path(str(workspace))
        self.read_roots=tuple(dos_path(str(p)) for p in read_roots)
        self.phase="bootstrap";self.denials=[];self.allowed={}
        self.sqlite_connections=set();self.database_paths=set()
        self._connection_type=None;self.closed_connections=0
        self._socketpair_code=socket.socketpair.__code__
        self._probe_sockets=set();self._probe_listener=None
        self._io_depth=0;self.threads=[];self._thread_grant=threading.local()
        self._owner=threading.get_ident();self.bridge=None
    def deny(self,reason):
        self.denials.append({"phase":self.phase,"reason":reason})
        raise Denied(reason)
    def note(self,event):self.allowed[event]=self.allowed.get(event,0)+1
    def path(self,value,*,write=False):
        if isinstance(value,int):self.deny("unowned-file-descriptor")
        raw=os.fsdecode(value)
        if raw.startswith(("\\\\","\\","/")) or "\x00" in raw:
            self.deny("UNC-device-path")
        drive,tail=ntpath.splitdrive(raw)
        if ":" in tail:self.deny("ADS-path")
        if any(part in {".",".."} for part in tail.replace("/","\\").split("\\")):
            self.deny("relative-traversal")
        canonical=dos_path(os.path.abspath(raw))
        roots=(self.workspace,) if write else (self.workspace,)+self.read_roots
        if not any(within(canonical,r) for r in roots):self.deny("outside-synthetic-write" if write else "outside-read-roots")
        if Path(canonical).suffix.lower() in FORBIDDEN_SUFFIXES:self.deny("credential-file")
        chain=Path(canonical)
        while True:
            try:
                metadata=chain.lstat()
                if getattr(metadata,"st_file_attributes",0)&0x400:self.deny("reparse-path-component")
            except FileNotFoundError:pass
            if chain.parent==chain:break
            chain=chain.parent
        return canonical
    def database(self,value):
        raw=os.fsdecode(value)
        if raw==":memory:" or raw.lower().startswith("file:"):self.deny("unregistered-SQLite-URI-memory")
        p=self.path(raw,write=True)
        if p not in self.database_paths:self.deny("unregistered-SQLite-database")
        return p
    def socketpair_frame(self):
        f=sys._getframe(1)
        for _ in range(12):
            if f is None:break
            if f.f_code is self._socketpair_code:return f
            f=f.f_back
        return None
    def network(self,event,args):
        if event not in {"socket.bind","socket.connect"}:self.deny("DNS-datagram-or-external-network")
        sock,address=args
        if (sock.family!=socket.AF_INET or sock.type&0xf!=socket.SOCK_STREAM or
            not isinstance(address,tuple) or len(address)!=2 or
            address[0]!="127.0.0.1" or type(address[1]) is not int or address[1]==8765):
            self.deny("only-owned-IPv4-loopback")
        pair=self.socketpair_frame()
        if pair is not None:
            if event=="socket.bind" and sock is pair.f_locals.get("lsock") and address==("127.0.0.1",0):
                return
            listener=pair.f_locals.get("lsock")
            if event=="socket.connect" and sock is pair.f_locals.get("csock") and listener is not None and address==listener.getsockname():
                return
            self.deny("invalid-eventloop-selfpipe")
        if sock in self._probe_sockets:
            if event=="socket.bind" and sock is self._probe_listener and address==("127.0.0.1",0):return
            if event=="socket.connect" and sock is not self._probe_listener and self._probe_listener is not None and address==self._probe_listener.getsockname():return
        self.deny("unowned-loopback-or-server-port")
    def audit(self,event,args):
        if event in NETWORK:
            self.network(event,args);self.note(event);return True
        if event in PROCESS:self.deny("process-shell-worker-not-required")
        if event in {"sqlite3.enable_load_extension","sqlite3.load_extension"}:self.deny("SQLite-native-extension")
        if event=="sqlite3.connect":
            self.database(args[0]);self.note(event);return True
        if event=="sqlite3.connect/handle":
            if self._connection_type is None or type(args[0]) is not self._connection_type:
                self.deny("foreign-SQLite-connection-type")
            return True
        if event not in FILE_EVENTS:return False
        if event in {"os.link","os.symlink"}:self.deny("link-creation-not-required")
        if event=="open":
            if isinstance(args[0],int):self.deny("raw-open-fd")
            mode,flags=args[1] or "",args[2] or 0
            write=any(c in str(mode) for c in "wax+") or bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
            self.path(args[0],write=write)
        elif event in {"os.listdir","os.scandir"}:
            self.path(args[0] if args and args[0] is not None else os.getcwd())
        elif event=="os.rename":
            self.path(args[0],write=True);self.path(args[1],write=True)
            if Path(args[0]).is_dir():self.deny("directory-move-not-required")
        else:self.path(args[0],write=True)
        self.note(event);return True
    def install_sqlite(self,paths):
        self.database_paths={self.path(p,write=True) for p in paths}
        original=sqlite3.connect;parent=sqlite3.Connection;policy=self
        class SyntheticConnection(parent):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs)
                parent.execute(self,"PRAGMA temp_store=MEMORY")
                def authorize(action,a,b,db,trigger):
                    if action in {sqlite3.SQLITE_ATTACH,sqlite3.SQLITE_DETACH}:return sqlite3.SQLITE_DENY
                    if action==sqlite3.SQLITE_FUNCTION and str(b).lower() in {"load_extension","readfile","writefile"}:return sqlite3.SQLITE_DENY
                    if action==sqlite3.SQLITE_PRAGMA:
                        if str(a).lower() in {"writable_schema","temp_store_directory","data_store_directory"}:return sqlite3.SQLITE_DENY
                        if str(a).lower()=="temp_store" and b not in (None,"2","MEMORY","memory"):return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK
                parent.set_authorizer(self,authorize)
                policy.sqlite_connections.add(self)
            def set_authorizer(self,*a,**k):policy.deny("SQLite-authorizer-replacement")
            def enable_load_extension(self,*a,**k):policy.deny("SQLite-native-extension")
            def load_extension(self,*a,**k):policy.deny("SQLite-native-extension")
            def close(self):
                parent.close(self)
                if self in policy.sqlite_connections:
                    policy.sqlite_connections.remove(self);policy.closed_connections+=1
        self._connection_type=SyntheticConnection
        def connect(database,*args,**kwargs):
            policy.database(database)
            # No custom factory or URI can bypass the mandatory authorizer.
            if len(args)>4 or "factory" in kwargs or kwargs.get("uri",False):policy.deny("SQLite-connect-options")
            kwargs["factory"]=SyntheticConnection
            return original(database,*args,**kwargs)
        sqlite3.connect=connect;sqlite3.dbapi2.connect=connect
    def install_threads(self):
        policy=self;original=threading.Thread.start
        def start(thread,*args,**kwargs):
            cls=type(thread);module=sys.modules.get("anyio._backends._asyncio")
            expected=getattr(module,"WorkerThread",None) if module else None
            if (policy._io_depth<1 or threading.get_ident()!=policy._owner or cls is not expected
                or thread.name!="AnyIO worker thread" or len(policy.threads)>=2):
                policy.deny("unapproved-thread-start")
            policy.threads.append(thread);policy._thread_grant.target=thread
            try:return original(thread,*args,**kwargs)
            finally:policy._thread_grant.target=None
        threading.Thread.start=start
        import _thread
        def wrap(fn):
            def bounded(function,*args,**kwargs):
                owner=getattr(policy._thread_grant,"target",None)
                if owner is None or getattr(function,"__self__",None) is not owner:
                    policy.deny("raw-thread-start")
                return fn(function,*args,**kwargs)
            return bounded
        for name in ("start_new_thread","start_joinable_thread"):
            if hasattr(_thread,name):setattr(_thread,name,wrap(getattr(_thread,name)))
        if hasattr(threading,"_start_joinable_thread"):
            threading._start_joinable_thread=wrap(threading._start_joinable_thread)
    @contextlib.contextmanager
    def read_only_asgi(self):
        self._io_depth+=1
        try:yield
        finally:self._io_depth-=1
    @contextlib.contextmanager
    def loopback_probe(self,listener,client):
        if self._probe_sockets:self.deny("probe-reentry")
        self._probe_sockets={listener,client};self._probe_listener=listener
        try:yield
        finally:self._probe_sockets.clear();self._probe_listener=None
    def status(self):
        return {"phase":self.phase,"remaining_SQLite_connections":len(self.sqlite_connections),
                "SQLite_closed":self.closed_connections,"threads_started":len(self.threads),
                "threads_alive":sum(t.is_alive() for t in self.threads),"allowed_events":self.allowed,
                "denials":self.denials,"processes_started":0}
