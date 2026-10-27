"""Source-attested native facades for unchanged filelock; CI only."""
import ctypes as C
import os
from pathlib import Path
import sys
import threading
from verification_gate import VerificationGate, Denied, dos_path

class DeniedSymbol:
    def __init__(self, owner, module, symbol):
        object.__setattr__(self,"owner",owner);object.__setattr__(self,"module",module)
        object.__setattr__(self,"symbol",symbol);object.__setattr__(self,"metadata",{})
    def __setattr__(self,name,value):
        if name not in ("argtypes","restype") or self.owner.package_frame(self.module,{"<module>"}) is None:
            raise Denied("unreviewed-native-signature-write")
        self.metadata[name]=value
    def __getattr__(self,name):
        if name in self.metadata:return self.metadata[name]
        raise AttributeError(name)
    def __call__(self,*args):
        if self.symbol in {"OpenProcess","GetProcessTimes"}:
            raise Denied("process-symbol-declaration-only-no-execution")
        return self.owner.bridge.dispatch(self.module,self.symbol,args)

class SafeLibrary:
    _symbols={
        "ntdll":{"NtCreateFile","RtlDosPathNameToNtPathName_U_WithStatus","RtlFreeUnicodeString","RtlNtStatusToDosError"},
        "kernel32":{"CloseHandle","GetFileInformationByHandle","LockFileEx","UnlockFileEx","OpenProcess","GetProcessTimes"}}
    def __init__(self,owner,module,name):
        self._owner,self._module,self._name=owner,module,name;self._calls={}
    def __getattr__(self,symbol):
        if symbol not in self._symbols[self._name]:
            raise Denied("unregistered-filelock-native-symbol")
        if symbol not in self._calls:self._calls[symbol]=DeniedSymbol(self._owner,self._module,symbol)
        return self._calls[symbol]

class NativeRegistration:
    def __init__(self,gate,package_sources):
        if type(gate) is not VerificationGate or not gate.installed:
            raise Denied("guard-first")
        self.gate,self.sources=gate,package_sources
        self.bridge=None;self._loader=None;self._crt=threading.local()
        self.native_bindings=0;self.facade_bindings=0;self.crt_calls=0
        self.app_policy=None
    def attach_private_loader(self,loader):
        if self._loader is not None or self.gate.bound:raise Denied("registration-once")
        self._loader=loader
    def _private_frame(self):
        expected=[]
        module=sys.modules.get("adapter")
        if module is not None:expected.append(module._Native.__init__.__code__)
        module=sys.modules.get("rtl_boundary")
        if module is not None:expected.append(module.RtlBoundary._bind_rtl.__code__)
        frame=sys._getframe(1)
        for _ in range(16):
            if frame is None:break
            if frame.f_code in expected:return True
            frame=frame.f_back
        return False
    def package_frame(self,module,names):
        loaded=sys.modules.get(module);path=self.sources.get(module)
        if loaded is None or path is None:return None
        frame=sys._getframe(1)
        for _ in range(20):
            if frame is None:break
            if (frame.f_globals is loaded.__dict__ and frame.f_code.co_name in names
                and os.path.normcase(frame.f_code.co_filename)==os.path.normcase(path)):
                return frame
            frame=frame.f_back
        return None
    def private_binding(self,name,args,kwargs):
        if self._loader is not None and getattr(self.gate.binding,"active",False) and self._private_frame():
            if args or kwargs!={"use_last_error":True}:raise Denied("fixed-private-DLL-options")
            self.gate.audit("ctypes.dlopen",(name,))
            self.native_bindings+=1
            return self._loader(name,**kwargs)
        for module in ("filelock._windows","filelock._identity"):
            if self.package_frame(module,{"<module>"}) is not None:
                if args or name not in ("ntdll","kernel32"):raise Denied("filelock-DLL-name")
                if kwargs not in ({},{"use_last_error":True}):raise Denied("filelock-DLL-options")
                if module=="filelock._identity" and name!="kernel32":raise Denied("identity-DLL")
                self.facade_bindings+=1
                return SafeLibrary(self,module,name)
        raise Denied('unapproved-app-native-DLL')
    def attach_app_policy(self,policy,expected_sha256):
        import hashlib
        from app_policy import AppPolicy
        module=sys.modules.get('app_policy')
        if (self.app_policy is not None or self.gate.app_policy is not None or type(policy) is not AppPolicy
            or module is None or hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()!=expected_sha256):
            raise Denied('unreviewed-app-policy-registration')
        self.app_policy=policy;self.gate.app_policy=policy
    def audit_event(self,event,args):
        if self.app_policy is not None and self.app_policy.audit(event,args):return True
        if event in {"ctypes.dlopen","ctypes.dlsym","ctypes.dlsym/handle"}:
            if not getattr(self.gate.binding,"active",False) or not self._private_frame():return False
            self.gate.audit(event,args);return True
        if event=="open" and isinstance(args[0],(str,bytes,os.PathLike)):
            if getattr(self.gate.binding,"active",False) and self._private_frame():
                p=dos_path(os.fsdecode(os.path.abspath(args[0])))
                allowed={dos_path(str(Path(self.gate.system32)/n)) for n in ("ntdll.dll","kernel32.dll")}
                if p in allowed and not any(c in str(args[1] or "") for c in "wax+") and not (args[2] or 0)&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC):
                    return True
        if event.startswith("msvcrt."):
            if getattr(self._crt,"expected",None)!=(event,tuple(args)):
                raise Denied("unregistered-CRT-event")
            self.crt_calls+=1;return True
        if event=="os.remove" and self.bridge is not None:
            self.bridge.note_unlink(args[0])
        return False
    def _crt_call(self,event,function,args):
        if self.bridge is None or not self.bridge.owns_crt_request(event,args):
            raise Denied("unowned-CRT-request")
        if getattr(self._crt,"expected",None) is not None:raise Denied("nested-CRT-call")
        self._crt.expected=(event,tuple(args))
        try:return function(*args)
        finally:self._crt.expected=None
