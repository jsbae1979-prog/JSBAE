"""Bounded Windows byte-range lock capabilities for trusted verification only.

Not a filelock monkey patch, DLL proxy, process API or product entry point.
The existing host Guard is neither imported nor changed. Native execution is
performed only by the separately approved Windows verification runner.
"""
from __future__ import annotations
import ctypes as C
from dataclasses import dataclass
import math
import ntpath
import os
import re
import threading
import time
from verification_gate import Denied, VerificationGate, dos_path

class NativeFailure(OSError):
    pass

class LockTimeout(TimeoutError):
    pass

class _Unicode(C.Structure):
    _fields_ = [("Length", C.c_uint16), ("MaximumLength", C.c_uint16),
                ("Buffer", C.c_void_p)]

class _Attributes(C.Structure):
    _fields_ = [("Length", C.c_uint32), ("RootDirectory", C.c_void_p),
                ("ObjectName", C.POINTER(_Unicode)), ("Attributes", C.c_uint32),
                ("SecurityDescriptor", C.c_void_p),
                ("SecurityQualityOfService", C.c_void_p)]

class _IO(C.Structure):
    _fields_ = [("Status", C.c_void_p), ("Information", C.c_size_t)]

class _Info(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in
        ("attributes", "creation_low", "creation_high", "access_low", "access_high",
         "write_low", "write_high", "volume", "size_high", "size_low",
         "links", "index_high", "index_low")]

class _Overlapped(C.Structure):
    _fields_ = [("Internal", C.c_size_t), ("InternalHigh", C.c_size_t),
                ("Offset", C.c_uint32), ("OffsetHigh", C.c_uint32),
                ("hEvent", C.c_void_p)]

_H = C.c_void_p
_U = C.c_uint32
_P = C.c_void_p

class _Native:
    """Private fixed bindings; raw functions/handles are never API results."""
    def __init__(self, gate: VerificationGate):
        if type(gate) is not VerificationGate:
            raise Denied("verification-gate-required")
        self.gate = gate
        signatures = {
            "kernel32.dll": {
                "CreateFileW": ([C.c_wchar_p, _U, _U, _P, _U, _U, _H], _H),
                "CloseHandle": ([_H], C.c_int),
                "GetFileInformationByHandle": ([_H, C.POINTER(_Info)], C.c_int),
                "GetFinalPathNameByHandleW": ([_H, C.c_wchar_p, _U, _U], _U),
                "LockFileEx": ([_H, _U, _U, _U, _U, C.POINTER(_Overlapped)], C.c_int),
                "UnlockFileEx": ([_H, _U, _U, _U, C.POINTER(_Overlapped)], C.c_int),
            },
            "ntdll.dll": {
                "NtCreateFile": ([C.POINTER(_H), _U, C.POINTER(_Attributes),
                    C.POINTER(_IO), _P, _U, _U, _U, _U, _P, _U], C.c_int32),
                "RtlNtStatusToDosError": ([_U], _U),
            },
        }
        self._functions = {}
        self._owned_handles = set()
        with gate._binding_only():
            for dll, symbols in signatures.items():
                library = C.WinDLL(gate.dll_path(dll), use_last_error=True)
                for name, (arguments, result) in symbols.items():
                    fn = getattr(library, name)
                    fn.argtypes, fn.restype = arguments, result
                    self._functions[name] = gate._register_function(name, fn)
        gate.events.append("fixed-native-bindings-complete")
    def _fn(self, name):
        return self._functions[name]
    def error(self, label):
        return NativeFailure(C.get_last_error(), label)
    def _require_owned(self, handle):
        if type(handle) is not int or handle not in self._owned_handles:
            raise Denied("unregistered-native-handle")
    def close(self, handle):
        self._require_owned(handle)
        if not self._fn("CloseHandle")(handle):
            raise self.error("owned-handle-close-failed")
        self._owned_handles.remove(handle)
    def info(self, handle):
        self._require_owned(handle)
        result = _Info()
        if not self._fn("GetFileInformationByHandle")(handle, C.byref(result)):
            raise self.error("owned-handle-info-failed")
        return result
    def final(self, handle):
        self._require_owned(handle)
        buffer = C.create_unicode_buffer(32768)
        n = self._fn("GetFinalPathNameByHandleW")(handle, buffer, len(buffer), 0)
        if not n or n >= len(buffer):
            raise self.error("final-path-unavailable")
        value = buffer.value
        if not value.startswith("\\\\?\\") or value.startswith("\\\\?\\UNC\\"):
            raise Denied("non-DOS-final-path")
        return dos_path(value[4:])
    def verify(self, handle, expected, directory, identity=None):
        info = self.info(handle)
        if info.attributes & 0x400:
            raise Denied("reparse-point")
        if bool(info.attributes & 0x10) != directory:
            raise Denied("file-kind")
        if self.final(handle) != expected:
            raise Denied("final-handle-path-mismatch")
        current = (info.volume, info.index_high, info.index_low)
        if identity is not None and current != identity:
            raise Denied("file-identity-changed")
        if not directory and (info.links != 1 or info.size_high or info.size_low):
            raise Denied("lock-must-be-empty-single-link-file")
        return current
    def drive(self, drive):
        # Only bootstrap a DOS drive root for ancestry metadata validation.
        if not re.fullmatch(r"[a-zA-Z]:\\", drive):
            raise Denied("invalid-drive-root")
        handle = self._fn("CreateFileW")(drive, 0x00100080, 3, None, 3,
                                         0x02200000, None)
        if handle in (None, C.c_void_p(-1).value):
            raise self.error("drive-root-open-failed")
        self._owned_handles.add(handle)
        return handle
    def relative(self, parent, component, directory=False, create=False):
        self._require_owned(parent)
        # One validated component, NEVER a caller-supplied NT namespace or pointer.
        if not re.fullmatch(r"[\w .()@+-]{1,120}", component, re.ASCII) or component in (".", ".."):
            raise Denied("invalid-relative-component")
        text = C.create_unicode_buffer(component)
        length = len(component.encode("utf-16-le"))
        unicode = _Unicode(length, length + 2, C.cast(text, _P))
        attributes = _Attributes(C.sizeof(_Attributes), parent,
                                 C.pointer(unicode), 0x40, None, None)
        io, result = _IO(), _H()
        access = 0x001000A0 if directory else 0xC0100000
        options = 0x200020 | (0x1 if directory else 0x40)
        status = self._fn("NtCreateFile")(C.byref(result), access,
            C.byref(attributes), C.byref(io), None, 0, 3,
            2 if create else 1, options, None, 0)
        if status < 0:
            error = self._fn("RtlNtStatusToDosError")(status & 0xFFFFFFFF)
            raise NativeFailure(error, "bounded-NtCreateFile-failed")
        if not result.value:
            raise NativeFailure("NtCreateFile-returned-no-handle")
        self._owned_handles.add(result.value)
        return result.value
    def lock(self, handle):
        self._require_owned(handle)
        overlap = _Overlapped()
        if self._fn("LockFileEx")(handle, 3, 0, 1, 0, C.byref(overlap)):
            return True
        error = C.get_last_error()
        if error == 33:  # ERROR_LOCK_VIOLATION; all other errors stay errors.
            return False
        raise NativeFailure(error, "byte-lock-acquire-failed")
    def unlock(self, handle):
        self._require_owned(handle)
        overlap = _Overlapped()
        if not self._fn("UnlockFileEx")(handle, 0, 1, 0, C.byref(overlap)):
            raise self.error("byte-lock-release-failed")

class Registration:
    __slots__ = ()

class LockCapability:
    __slots__ = ()

@dataclass
class _Entry:
    handle: int
    path: str
    identity: tuple
    owner: int | None = None

class LockScope:
    """Single-use synthetic scope; only newly registered direct-child .lock files."""
    def __init__(self, native: _Native, grant):
        self._native = native
        self.root = native.gate.claim(grant)
        self._directories = []
        self._registrations = {}
        self._handles = {}
        self._mutex = threading.RLock()
        self._closed = False
        drive, tail = ntpath.splitdrive(self.root)
        components = tail[1:].split("\\")
        if not components or not components[-1].startswith("scope-"):
            raise Denied("fresh-synthetic-scope-required")
        try:
            expected = drive + "\\"
            handle = native.drive(expected)
            self._directories.append(handle)
            native.verify(handle, expected, True)
            for component in components:
                handle = native.relative(self._directories[-1], component, directory=True)
                self._directories.append(handle)
                expected = ntpath.join(expected, component)
                native.verify(handle, expected, True)
        except BaseException:
            self.close()
            raise
    def _live(self):
        if self._closed:
            raise Denied("closed-scope")
    def _path(self, value):
        path = dos_path(value)
        if ntpath.dirname(path) != self.root:
            raise Denied("outside-registered-direct-child-scope")
        name = ntpath.basename(path)
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}\.lock", name):
            raise Denied("synthetic-lock-filename-required")
        return path, name
    def register(self, path):
        with self._mutex:
            self._live()
            canonical, name = self._path(path)
            handle = self._native.relative(self._directories[-1], name, create=True)
            try:
                identity = self._native.verify(handle, canonical, False)
            except BaseException:
                self._native.close(handle)
                raise
            token = Registration()
            self._registrations[token] = _Entry(handle, canonical, identity)
            return token
    def open(self, registration):
        with self._mutex:
            self._live()
            if type(registration) is not Registration or registration not in self._registrations:
                raise Denied("foreign-registration")
            anchor = self._registrations[registration]
            self._native.verify(anchor.handle, anchor.path, False, anchor.identity)
            handle = self._native.relative(self._directories[-1], ntpath.basename(anchor.path))
            try:
                self._native.verify(handle, anchor.path, False, anchor.identity)
            except BaseException:
                self._native.close(handle)
                raise
            token = LockCapability()
            self._handles[token] = _Entry(handle, anchor.path, anchor.identity)
            return token
    def _entry(self, token, verify=True):
        self._live()
        if type(token) is not LockCapability or token not in self._handles:
            raise Denied("foreign-forged-or-closed-handle")
        entry = self._handles[token]
        if verify:
            self._native.verify(entry.handle, entry.path, False, entry.identity)
        return entry
    def acquire(self, token, timeout=0.0):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 <= timeout <= 2:
            raise Denied("timeout-must-be-finite-zero-to-two-seconds")
        deadline = time.monotonic() + timeout
        while True:
            with self._mutex:
                entry = self._entry(token)
                if entry.owner is not None:
                    raise Denied("already-locked-no-implicit-reentrancy")
                if self._native.lock(entry.handle):
                    entry.owner = threading.get_ident()
                    return
            if time.monotonic() >= deadline:
                raise LockTimeout("exclusive-byte-zero-lock-contended")
            time.sleep(min(0.01, max(0, deadline - time.monotonic())))
    def release(self, token):
        with self._mutex:
            entry = self._entry(token, verify=False)
            if entry.owner != threading.get_ident():
                raise Denied("unheld-or-other-thread-lock")
            self._native.unlock(entry.handle)
            entry.owner = None  # Only after successful OS unlock.
    def close_handle(self, token):
        with self._mutex:
            entry = self._entry(token, verify=False)
            if entry.owner is not None:
                self.release(token)
            self._native.close(entry.handle)
            del self._handles[token]  # Only after successful OS close.
    def status(self):
        with self._mutex:
            return {"open_capabilities": len(self._handles),
                    "registrations": len(self._registrations),
                    "directory_handles": len(self._directories),
                    "held_locks": sum(x.owner is not None for x in self._handles.values()),
                    "closed": self._closed}
    def native_symbol(self, *_args, **_kwargs):
        raise Denied("raw-native-symbols-not-exposed")
    def query_process(self, *_args, **_kwargs):
        raise Denied("process-lookup-not-necessary-and-not-implemented")
    def close(self):
        with self._mutex:
            if self._closed:
                return
            for token in list(self._handles):
                self.close_handle(token)
            for token, entry in list(self._registrations.items()):
                self._native.close(entry.handle)
                del self._registrations[token]
            while self._directories:
                self._native.close(self._directories[-1])
                self._directories.pop()
            self._closed = True
