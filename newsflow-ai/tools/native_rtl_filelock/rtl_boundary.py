"""Real Rtl ownership and unchanged-filelock native boundary; verification only."""
from dataclasses import dataclass
import ctypes as C
import math
import msvcrt
import os
from pathlib import Path
import threading
from adapter import _Unicode, _Attributes, _IO, LockScope, NativeFailure
from verification_gate import Denied, dos_path

class OutcomeUnknown(OSError):
    pass

class NativeBuffer:
    __slots__=()

@dataclass
class BufferRecord:
    user: object
    native: object
    pointer: int
    length: int
    path: str
    state: str="ready"

@dataclass
class HandleRecord:
    handle: int
    path: str
    identity: tuple
    state: str="native_owned"
    fd: int|None=None

class RtlBoundary:
    def __init__(self,native,registration):
        if registration.bridge is not None:raise Denied("one-Rtl-boundary")
        self.native,self.registration,self.gate=native,registration,native.gate
        self.scope=LockScope(native,self.gate.new_scope())
        self.paths={};self.buffers={};self.by_user={}
        self.handles={};self.fds={};self.blocked=set()
        self.events=[];self.allocations=0;self.frees=0;self.nt_opens=0
        self.lock_calls=0;self.unlock_calls=0;self.unlink_attempts=0
        self._owner=threading.get_ident();self.closed=False;self._cleanup=False
        self._fault=None;self._unresolved_calls=[]
        self._original_open=msvcrt.open_osfhandle
        self._original_get=msvcrt.get_osfhandle
        self._original_close=os.close
        registration.bridge=self
        self.gate.register_rtl_owner(self)
        self._bind_rtl()
    def _live(self):
        if self.closed or threading.get_ident()!=self._owner:raise Denied("closed-or-other-thread")
    def _bind_rtl(self):
        self.rtl={}
        with self.gate._rtl_binding(self):
            lib=C.WinDLL(self.gate.dll_path("ntdll.dll"),use_last_error=True)
            types={
             "RtlDosPathNameToNtPathName_U_WithStatus":([C.c_wchar_p,C.POINTER(_Unicode),C.c_void_p,C.c_void_p],C.c_int32),
             "RtlFreeUnicodeString":([C.POINTER(_Unicode)],None)}
            for name,(arguments,result) in types.items():
                fn=getattr(lib,name);fn.argtypes=arguments;fn.restype=result
                self.rtl[name]=self.gate._register_function(name,fn)
            self.gate._bind_owned_reader(self)
    def register_path(self,name):
        self._live()
        path,_=self.scope._path(str(Path(self.scope.root)/(name+".lock")))
        if path not in self.paths:
            token=self.scope.register(path)
            anchor=self.scope._registrations[token]
            self.paths[path]=(token,anchor.identity)
        return path
    def _path(self,path):
        self._live();canonical,_=self.scope._path(path)
        if canonical not in self.paths:raise Denied("unregistered-lock-path")
        if canonical in self.blocked:raise OutcomeUnknown("path-quarantined-no-replay")
        return canonical
    def prepare_buffer(self,path,user=None):
        path=self._path(path)
        if user is None:user=_Unicode()
        if id(user) in self.by_user:raise Denied("Unicode-container-already-used")
        output=_Unicode()
        try:
            status=self.rtl["RtlDosPathNameToNtPathName_U_WithStatus"](path,C.byref(output),None,None)
        except BaseException:
            self._unresolved_calls.append("Rtl-conversion-interrupted")
            self.blocked.add(path)
            raise OutcomeUnknown("unobserved-Rtl-call-no-retry")
        if status!=0:
            if output.Buffer:
                token=NativeBuffer()
                self.buffers[token]=BufferRecord(user,output,output.Buffer,int(output.Length),path,"conversion_unknown")
                self.by_user[id(user)]=token;self.allocations+=1
                self.blocked.add(path)
                raise OutcomeUnknown("Rtl-failure-with-unknown-buffer-ownership")
            raise NativeFailure(status,"Rtl-conversion-failed")
        if not output.Buffer:raise NativeFailure("Rtl-returned-no-allocation")
        token=NativeBuffer()
        record=BufferRecord(user,output,output.Buffer,int(output.Length),path)
        self.buffers[token]=record;self.by_user[id(user)]=token;self.allocations+=1
        try:
            if not 0<record.length<=2048 or record.length%2 or output.MaximumLength<record.length:
                raise Denied("invalid-Rtl-buffer-shape")
            data=self.gate._read_rtl_owned(self,record.pointer,record.length)
            if data.decode("utf-16-le").casefold()!=("\\??\\"+path).casefold():
                raise Denied("Rtl-converted-path-mismatch")
            view=_Unicode.from_buffer(user)
            view.Length=output.Length;view.MaximumLength=output.MaximumLength;view.Buffer=output.Buffer
        except BaseException:
            self.release_buffer(token)
            raise
        return token
    def owns_memory_read(self,pointer,size):
        return any(r.pointer==pointer and r.native.Buffer==pointer and r.length==size and r.state=="ready" for r in self.buffers.values())
    def buffer_metadata(self,token):
        r=self._buffer(token)
        return {"allocator":"native-Rtl","length":r.length,"state":r.state,"pointer_exported":False}
    def _buffer(self,token):
        self._live()
        if type(token) is not NativeBuffer or token not in self.buffers:raise Denied("foreign-buffer")
        return self.buffers[token]
    def release_buffer(self,token,*,_fault=None):
        r=self._buffer(token)
        if r.state!="ready" or r.native.Buffer!=r.pointer:raise Denied("double-in-use-or-unknown-free")
        view=_Unicode.from_buffer(r.user)
        if view.Buffer not in (None,r.pointer) or (view.Buffer is not None and (view.Length!=r.native.Length or view.MaximumLength!=r.native.MaximumLength)):
            raise Denied("Unicode-buffer-ownership-mismatch")
        if _fault=="before":raise NativeFailure("synthetic-before-Rtl-free")
        if _fault not in (None,"after"):raise Denied("unsupported-free-fault")
        r.state="freeing"
        try:self.rtl["RtlFreeUnicodeString"](C.byref(r.native))
        except BaseException:
            r.state="free_unknown";self.blocked.add(r.path);raise
        r.state="freed";self.frees+=1
        view.Buffer=None;view.Length=0;view.MaximumLength=0
        self.events.append("native-Rtl-buffer-freed-once")
        if _fault=="after":raise OutcomeUnknown("post-free-notification-failed")
    def _frame(self,names):
        frame=self.registration.package_frame("filelock._windows",set(names))
        if frame is None:raise Denied("unreviewed-filelock-native-caller")
        return frame
    def _object(self,arg,frame,name,kind):
        obj=getattr(arg,"_obj",None)
        if obj is not frame.f_locals.get(name) or type(obj) is not kind:
            raise Denied("unowned-output-container")
        return obj
    def _validate_acquire(self):
        frame=self.registration.package_frame("filelock._api",{"acquire"})
        if frame is None:raise Denied("native-path-outside-reviewed-acquire")
        wait=frame.f_locals.get("timeout")
        lock=frame.f_locals.get("self")
        if (type(wait) not in (int,float) or not math.isfinite(wait) or not 0<=wait<=2
            or getattr(lock,"on_acquired",None) is not None
            or not getattr(lock,"is_thread_local",False)
            or getattr(lock,"lifetime",None) is not None
            or frame.f_locals.get("cancel_check") is not None):
            raise Denied("unsupported-FileLock-contract")
    def dispatch(self,module,symbol,args):
        if module!="filelock._windows":raise Denied("identity-native-invocation-denied")
        import sys
        up=sys.modules["filelock._windows"]
        if symbol=="RtlDosPathNameToNtPathName_U_WithStatus":
            frame=self._frame({"_nt_open"});self._validate_acquire()
            if len(args)!=4 or args[2:]!=(None,None) or args[0]!=frame.f_locals.get("path"):
                raise Denied("Rtl-input-contract")
            user=self._object(args[1],frame,"nt_name",up._UNICODE_STRING)
            self.prepare_buffer(args[0],user);return 0
        if symbol=="RtlFreeUnicodeString":
            frame=self._frame({"_nt_open"})
            if len(args)!=1:raise Denied("Rtl-free-arity")
            user=self._object(args[0],frame,"nt_name",up._UNICODE_STRING)
            token=self.by_user.get(id(user))
            self.release_buffer(token);return None
        if symbol=="NtCreateFile":return self._nt_open(up,args)
        if symbol=="RtlNtStatusToDosError":
            self._frame({"_open_non_reparse_fd"})
            if len(args)!=1 or type(args[0]) is not int:raise Denied("status-scalar-only")
            return self.native._fn(symbol)(args[0]&0xffffffff)
        if symbol=="GetFileInformationByHandle":
            frame=self._frame({"_open_non_reparse_fd"})
            if len(args)!=2:raise Denied("info-arity")
            target=self._object(args[1],frame,"info",up._BY_HANDLE_FILE_INFORMATION)
            entry=self.handles.get(args[0])
            if entry is None:raise Denied("foreign-info-handle")
            self.native.verify(entry.handle,entry.path,False,entry.identity)
            value=self.native.info(entry.handle)
            if C.sizeof(target)!=C.sizeof(value):raise Denied("info-layout")
            memoryview(target).cast("B")[:]=memoryview(value).cast("B")
            return 1
        if symbol=="CloseHandle":
            self._frame({"_open_non_reparse_fd"})
            if len(args)!=1 or args[0] not in self.handles:raise Denied("foreign-native-close")
            self.native.close(args[0]);del self.handles[args[0]];return 1
        if symbol in {"LockFileEx","UnlockFileEx"}:return self._lock_api(up,symbol,args)
        raise Denied("unregistered-native-symbol")
    def _nt_open(self,up,args):
        frame=self._frame({"_nt_open"})
        if len(args)!=11:raise Denied("NT-arity")
        user=frame.f_locals.get("nt_name");token=self.by_user.get(id(user));record=self._buffer(token)
        if record.state!="ready":raise Denied("NT-buffer-not-live")
        attrs=self._object(args[2],frame,"attributes",up._OBJECT_ATTRIBUTES)
        output=self._object(args[0],frame,"handle",C.c_void_p)
        target_io=self._object(args[3],frame,"io_status",up._IO_STATUS_BLOCK)
        objname=C.c_void_p.from_buffer(attrs,up._OBJECT_ATTRIBUTES.ObjectName.offset).value
        view=_Unicode.from_buffer(user)
        if (args[1]!=0xC0100000 or args[4] is not None or args[5]!=0x80 or args[6:]!=(3,3,0x200060,None,0)
            or attrs.Length!=C.sizeof(attrs) or attrs.RootDirectory is not None or attrs.Attributes!=0x40
            or attrs.SecurityDescriptor is not None or attrs.SecurityQualityOfService is not None
            or objname!=C.addressof(user) or view.Buffer!=record.pointer
            or view.Length!=record.native.Length or view.MaximumLength!=record.native.MaximumLength):
            raise Denied("NT-fixed-input-or-buffer-ownership")
        own_attrs=_Attributes(C.sizeof(_Attributes),None,C.pointer(record.native),0x40,None,None)
        result,io=C.c_void_p(),_IO();record.state="in_use";output_handled=False
        try:
            try:
                status=self.native._fn("NtCreateFile")(C.byref(result),0xC0100000,C.byref(own_attrs),C.byref(io),
                    None,0x80,3,3,0x200060,None,0)
            except BaseException:
                record.state="nt_unknown";self.blocked.add(record.path)
                self._unresolved_calls.append("NT-call-interrupted")
                raise
            self.nt_opens+=1
            if status==0:
                h=result.value
                if not h:raise NativeFailure("NT-success-without-handle")
                self.native._owned_handles.add(h)
                identity=self.paths[record.path][1]
                try:self.native.verify(h,record.path,False,identity)
                except BaseException:
                    self.native.close(h);output_handled=True;raise
                self.handles[h]=HandleRecord(h,record.path,identity);output_handled=True
                output.value=h
                memoryview(target_io).cast("B")[:]=memoryview(io).cast("B")
            elif status>0:
                self.blocked.add(record.path);record.state="unknown"
                raise OutcomeUnknown("asynchronous-NT-result-not-permitted")
            return status
        except BaseException:
            if result.value and not output_handled and result.value not in self.native._owned_handles:
                self._unresolved_calls.append("NT-output-handle-unobserved")
                record.state="nt_unknown";self.blocked.add(record.path)
            raise
        finally:
            if record.state=="in_use":record.state="ready"
    def install_crt_wrappers(self):
        if msvcrt.open_osfhandle is not self._original_open:raise Denied("foreign-CRT-wrapper")
        msvcrt.open_osfhandle=self._open_crt
        msvcrt.get_osfhandle=self._get_crt
        os.close=self._close_crt
    def owns_crt_request(self,event,args):
        if event=="msvcrt.open_osfhandle":
            return len(args)==2 and args[0] in self.handles and args[1]==(os.O_RDWR|os.O_NOINHERIT)
        if event=="msvcrt.get_osfhandle":return len(args)==1 and args[0] in self.fds
        return False
    def _open_crt(self,handle,flags):
        self._frame({"_open_non_reparse_fd"})
        if handle not in self.handles or flags!=(os.O_RDWR|os.O_NOINHERIT):raise Denied("foreign-CRT-transfer")
        entry=self.handles[handle]
        self.native.verify(handle,entry.path,False,entry.identity)
        try:fd=self.registration._crt_call("msvcrt.open_osfhandle",self._original_open,(handle,flags))
        except BaseException:
            entry.state="transfer_unknown";self.blocked.add(entry.path);raise
        self.native._owned_handles.remove(handle);del self.handles[handle]
        entry.fd,entry.state=fd,"crt_owned";self.fds[fd]=entry
        self.events.append("owned-native-to-CRT-transfer")
        return fd
    def _get_crt(self,fd):
        self._frame({"_lock_fd_nonblocking","_unlock_fd"})
        return self._raw_get(fd)
    def _raw_get(self,fd):
        if fd not in self.fds:raise Denied("foreign-CRT-descriptor")
        h=self.registration._crt_call("msvcrt.get_osfhandle",self._original_get,(fd,))
        if h!=self.fds[fd].handle:raise Denied("CRT-handle-mismatch")
        return h
    def _verify_crt(self,fd):
        h=self._raw_get(fd);entry=self.fds[fd]
        if h in self.native._owned_handles:raise Denied("double-handle-owner")
        self.native._owned_handles.add(h)
        try:self.native.verify(h,entry.path,False,entry.identity)
        finally:self.native._owned_handles.remove(h)
        return h,entry
    def _lock_api(self,up,symbol,args):
        frame=self._frame({"_lock_fd_nonblocking" if symbol=="LockFileEx" else "_unlock_fd"})
        fd=frame.f_locals.get("fd")
        if fd not in self.fds:raise Denied("foreign-descriptor-lock")
        expected=(3,0,1,0) if symbol=="LockFileEx" else (0,1,0)
        if len(args)!=len(expected)+2 or tuple(args[1:-1])!=expected:raise Denied("lock-range")
        overlap=self._object(args[-1],frame,"overlapped",up._OVERLAPPED)
        if overlap.Offset or overlap.OffsetHigh or overlap.hEvent or overlap.Internal or overlap.InternalHigh:
            raise Denied("overlapped-not-zero")
        h,entry=self._verify_crt(fd)
        if args[0]!=h:raise Denied("lock-handle-mismatch")
        if entry.path in self.blocked:raise OutcomeUnknown("native-outcome-quarantined-no-replay")
        self.native._owned_handles.add(h)
        try:
            if symbol=="LockFileEx":
                self.lock_calls+=1
                held=self.native.lock(h)
                if held:entry.state="held";return 1
                C.set_last_error(33);return 0
            self.unlock_calls+=1
            self.native.unlock(h);entry.state="crt_owned";return 1
        except BaseException:
            entry.state="lock_unknown" if symbol=="LockFileEx" else "unlock_unknown"
            self.blocked.add(entry.path);raise
        finally:self.native._owned_handles.remove(h)
    def _close_crt(self,fd):
        if fd not in self.fds:
            if (self.registration.package_frame("filelock._windows",{"_acquire"}) is not None
                or self.registration.package_frame("filelock._api",{"_close_released_fd"}) is not None):
                raise Denied("foreign-filelock-close")
            return self._original_close(fd)
        if not self._cleanup and self.registration.package_frame("filelock._windows",{"_acquire"}) is None and self.registration.package_frame("filelock._api",{"_close_released_fd"}) is None:
            raise Denied("unreviewed-CRT-close")
        _,entry=self._verify_crt(fd)
        if entry.state=="close_unknown":raise OutcomeUnknown("close-must-not-be-replayed")
        if self._fault=="close-before":
            entry.state="close_not_started";raise OSError("synthetic-before-close")
        try:self._original_close(fd)
        except BaseException:
            entry.state="close_unknown";self.blocked.add(entry.path);raise
        del self.fds[fd];entry.state="closed"
        self.events.append("CRT-close-not-CloseHandle")
        if self._fault=="close-after":raise OSError("synthetic-after-close-notification")
    def note_unlink(self,path):
        try:canonical=dos_path(os.fsdecode(path))
        except Denied:return
        if canonical in self.paths:self.unlink_attempts+=1
    def cleanup_owned(self):
        self._live()
        if self._unresolved_calls:raise OutcomeUnknown("unresolved-native-call-prevents-cleanup-success")
        self._cleanup=True
        try:
            for fd in list(self.fds):self._close_crt(fd)
            for h,entry in list(self.handles.items()):
                if entry.state=="transfer_unknown":raise OutcomeUnknown("unknown-transfer-no-blind-close")
                self.native.close(h);del self.handles[h]
            for token,record in self.buffers.items():
                if record.state=="ready":self.release_buffer(token)
                elif record.state!="freed":raise OutcomeUnknown("unknown-buffer-no-free-replay")
        finally:self._cleanup=False
    def status(self):
        return {"native_handles":len(self.handles),"CRT_descriptors":len(self.fds),
                "native_buffers":sum(r.state!="freed" for r in self.buffers.values()),
                "unresolved_calls":len(self._unresolved_calls),
                "allocations":self.allocations,"frees":self.frees,"NtCreateFile_calls":self.nt_opens,
                "lock_calls":self.lock_calls,"unlock_calls":self.unlock_calls,
                "default_unlink_attempts":self.unlink_attempts,"quarantined_paths":len(self.blocked),
                "events":list(self.events),"closed":self.closed}
    def close(self):
        if self.closed:return
        self.cleanup_owned()
        self.scope.close()
        self.buffers.clear();self.by_user.clear()
        self.closed=True
