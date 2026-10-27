"""Private registration for the verification Guard copy, never the operating Guard."""
import ctypes
import os
from pathlib import Path
import sys
import threading
from verification_gate import Denied, VerificationGate, dos_path

class NativeRegistration:
    def __init__(self, gate):
        if type(gate) is not VerificationGate or not gate.installed:
            raise Denied("guard-first-required")
        self.gate = gate
        self._loader = None
        self._crt = threading.local()
        self._boundaries = set()
        self.native_dispatches = 0
        self.crt_dispatches = 0
    def attach_private_loader(self, loader):
        if self._loader is not None or self.gate.bound:
            raise Denied("registration-not-single-use")
        self._loader = loader
    def _from_reviewed_initializer(self):
        module = sys.modules.get("adapter")
        if module is None:
            return False
        frame = sys._getframe(1)
        for _ in range(12):
            if frame is None:
                break
            if frame.f_code is module._Native.__init__.__code__:
                return True
            frame = frame.f_back
        return False
    def private_binding(self, name, args, kwargs):
        if (self._loader is None or not getattr(self.gate.binding, "active", False)
            or not self._from_reviewed_initializer()):
            return None
        if args or kwargs != {"use_last_error": True}:
            raise Denied("fixed-DLL-binding-options")
        self.gate.audit("ctypes.dlopen", (name,))
        self.native_dispatches += 1
        return self._loader(name, **kwargs)
    def audit_event(self, event, args):
        if event in {"ctypes.dlopen", "ctypes.dlsym", "ctypes.dlsym/handle"}:
            if not getattr(self.gate.binding, "active", False) or not self._from_reviewed_initializer():
                return False
            self.gate.audit(event, args)
            return True
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            if getattr(self.gate.binding, "active", False) and self._from_reviewed_initializer():
                path = dos_path(os.fsdecode(os.path.abspath(args[0])))
                allowed = {dos_path(str(Path(self.gate.system32)/name)) for name in ("ntdll.dll", "kernel32.dll")}
                flags = args[2] or 0
                if path in allowed and not any(x in str(args[1] or "") for x in "wax+") and not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                    return True  # Hash read of these exact system DLLs only.
        if event.startswith("msvcrt."):
            expected = getattr(self._crt, "expected", None)
            if expected != (event, tuple(args)):
                raise Denied("unregistered-CRT-operation")
            self.crt_dispatches += 1
            return True
        return False
    def attach_boundary(self, boundary):
        module = sys.modules.get("descriptor_boundary")
        if module is None or type(boundary) is not module.DescriptorBoundary or boundary._registration is not self:
            raise Denied("unreviewed-CRT-owner")
        if boundary in self._boundaries:
            raise Denied("CRT-owner-already-registered")
        self._boundaries.add(boundary)
    def _call_crt(self, boundary, event, function, arguments):
        if event not in {"msvcrt.open_osfhandle", "msvcrt.get_osfhandle"}:
            raise Denied("unsupported-CRT-event")
        if boundary not in self._boundaries:
            raise Denied("unregistered-CRT-owner")
        if event == "msvcrt.open_osfhandle":
            pending = getattr(boundary, "_pending_transfer", None)
            if (pending is None or len(arguments) != 2 or arguments[0] != pending[0]
                or arguments[1] != (os.O_RDWR | os.O_NOINHERIT)
                or arguments[0] not in boundary._native._owned_handles):
                raise Denied("unowned-or-unregistered-CRT-transfer")
            boundary._native.verify(pending[0],pending[1],False,pending[2])
        elif len(arguments) != 1 or not any(e.fd == arguments[0] and e.state != "close_unknown" for e in boundary._descriptors.values()):
            raise Denied("unowned-CRT-descriptor")
        import msvcrt
        approved = msvcrt.open_osfhandle if event.endswith("open_osfhandle") else msvcrt.get_osfhandle
        if function is not approved or getattr(self._crt, "expected", None) is not None:
            raise Denied("foreign-or-nested-CRT-function")
        self._crt.expected = (event, tuple(arguments))
        try:
            return function(*arguments)
        finally:
            self._crt.expected = None
