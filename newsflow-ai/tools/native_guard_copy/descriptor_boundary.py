"""Opaque CRT descriptor ownership and Python-owned path buffer lifetimes.

No upstream filelock monkey patch, raw descriptor export or general native free.
"""
from dataclasses import dataclass
import ctypes as C
import json
import math
import msvcrt
import os
from pathlib import Path
import threading
import time

from adapter import _Unicode, _Attributes, _IO, LockScope, LockTimeout, NativeFailure
from verification_gate import Denied

class BoundaryBlocked(Denied):
    pass

class OutcomeUnknown(OSError):
    pass

class BufferToken:
    __slots__ = ()

class DescriptorToken:
    __slots__ = ()

@dataclass
class _Buffer:
    memory: object
    path: str
    registration: object
    state: str = "ready"

@dataclass
class _Descriptor:
    fd: int
    handle: int
    path: str
    identity: tuple
    depth: int = 0
    state: str = "crt_owned"

class DescriptorBoundary:
    def __init__(self, native, registration):
        if registration.gate is not native.gate or registration._loader is None:
            raise Denied("registered-provider-required")
        self._native, self._registration = native, registration
        self._scope = LockScope(native, native.gate.new_scope())
        self._paths, self._buffers, self._descriptors = {}, {}, {}
        self._owner = threading.get_ident()
        self._closed = False
        self._unresolved_transfers = set()
        self.history = []
        self._pending_transfer = None
        registration.attach_boundary(self)
    def _live(self):
        if self._closed or threading.get_ident() != self._owner:
            raise Denied("closed-or-other-thread-boundary")
    def register_file(self, name):
        self._live()
        path, _ = self._scope._path(str(Path(self._scope.root)/(name+".lock")))
        if path not in self._paths:
            self._paths[path] = self._scope.register(path)
        return path  # A path is not a handle/capability and authorizes no external file.
    def prepare_path(self, path):
        self._live()
        canonical, name = self._scope._path(path)
        if canonical not in self._paths:
            raise Denied("path-not-registered")
        token = BufferToken()
        self._buffers[token] = _Buffer(C.create_unicode_buffer(name), canonical, self._paths[canonical])
        return token
    def _buffer(self, token):
        self._live()
        if type(token) is not BufferToken or token not in self._buffers:
            raise Denied("foreign-or-freed-buffer")
        return self._buffers[token]
    def buffer_metadata(self, token):
        entry = self._buffer(token)
        return {"state": entry.state, "length_bytes": len(entry.memory.value.encode("utf-16-le")),
                "allocator": "Python-owned-relative-name", "native_Rtl_allocation": False}
    def free_path(self, token):
        entry = self._buffer(token)
        if entry.state == "in_use":
            raise Denied("buffer-in-use")
        del self._buffers[token]
        self.history.append("Python-buffer-released-once")
    def native_free(self, *_args):
        raise BoundaryBlocked("Rtl-allocation-and-arbitrary-native-free-not-supported")
    def _relative_open(self, token, during_call=None):
        entry = self._buffer(token)
        if entry.state != "ready":
            raise Denied("buffer-not-ready")
        anchor = self._scope._registrations[entry.registration]
        self._native.verify(anchor.handle, entry.path, False, anchor.identity)
        entry.state = "in_use"
        try:
            if during_call is not None:
                during_call()  # Trusted test fault/probe only; never a product callback.
            length = len(entry.memory.value.encode("utf-16-le"))
            text = _Unicode(length, length+2, C.addressof(entry.memory))
            attrs = _Attributes(C.sizeof(_Attributes), self._scope._directories[-1],
                                C.pointer(text), 0x40, None, None)
            result, io = C.c_void_p(), _IO()
            status = self._native._fn("NtCreateFile")(C.byref(result), 0xC0100000,
                C.byref(attrs), C.byref(io), None, 0, 3, 1, 0x200060, None, 0)
            if status < 0:
                error = self._native._fn("RtlNtStatusToDosError")(status & 0xFFFFFFFF)
                raise NativeFailure(error, "registered-relative-open")
            if not result.value:
                raise NativeFailure("missing-owned-handle")
            handle = result.value
            self._native._owned_handles.add(handle)
            try:
                self._native.verify(handle, entry.path, False, anchor.identity)
            except BaseException:
                self._native.close(handle)
                raise
            return handle, entry.path, anchor.identity
        finally:
            entry.state = "ready"
    def transfer(self, buffer, *, _fault=None):
        self._live()
        if _fault not in (None, "before", "after"):
            raise Denied("unapproved-test-fault")
        handle, path, identity = self._relative_open(buffer)
        if _fault == "before":
            self._native.close(handle)
            self.history.append("transfer-not-started-native-close")
            raise NativeFailure("synthetic-pre-transfer-failure")
        self._pending_transfer = (handle,path,identity)
        try:
            fd = self._registration._call_crt(self,"msvcrt.open_osfhandle", msvcrt.open_osfhandle,
                                              (handle, os.O_RDWR | os.O_NOINHERIT))
        except BaseException:
            # Do not guess whether an unexpected runtime interruption transferred it.
            self._unresolved_transfers.add(handle)
            self._buffers[buffer].state = "transfer_unknown"
            self.history.append("TRANSFER_UNKNOWN-no-automatic-close-or-retry")
            raise OutcomeUnknown("CRT-transfer-needs-explicit-ownership-evidence")
        finally:
            self._pending_transfer = None
        self._native._owned_handles.remove(handle)  # Ownership now belongs to CRT.
        token = DescriptorToken()
        self._descriptors[token] = _Descriptor(fd, handle, path, identity)
        self.history.append("native-to-CRT-ownership-committed")
        if _fault == "after":
            self._descriptors[token].state = "notification_unknown"
            self._buffers[buffer].state = "transfer_notification_unknown"
            self.history.append("post-transfer-notification-unknown-descriptor-retained")
            raise OutcomeUnknown("post-transfer-notification-failed")
        return token
    def _entry(self, token):
        self._live()
        if type(token) is not DescriptorToken or token not in self._descriptors:
            raise Denied("foreign-or-closed-descriptor")
        return self._descriptors[token]
    def _borrow(self, token, action):
        entry = self._entry(token)
        actual = self._registration._call_crt(self, "msvcrt.get_osfhandle", msvcrt.get_osfhandle, (entry.fd,))
        if actual != entry.handle or entry.handle in self._native._owned_handles:
            raise Denied("CRT-ownership-or-handle-identity-mismatch")
        self._native._owned_handles.add(actual)  # Temporary verified borrow; never CloseHandle.
        try:
            self._native.verify(actual, entry.path, False, entry.identity)
            if action == "verify":
                return True
            if action == "lock":
                return self._native.lock(actual)
            if action == "unlock":
                return self._native.unlock(actual)
            raise Denied("unapproved-borrow-action")
        finally:
            self._native._owned_handles.remove(actual)
    def acquire(self, token, timeout=0.0):
        entry = self._entry(token)
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0 <= timeout <= 2:
            raise Denied("bounded-timeout-required")
        if entry.state not in {"crt_owned", "held"}:
            raise BoundaryBlocked("unknown-outcome-no-automatic-retry")
        if entry.depth:
            entry.depth += 1
            return
        deadline = time.monotonic()+timeout
        try:
            while True:
                if self._borrow(token,"lock"):
                    entry.depth, entry.state = 1, "held"
                    return
                if time.monotonic() >= deadline:
                    raise LockTimeout("descriptor-byte-lock-contended")
                time.sleep(0.01)
        except LockTimeout:
            raise
        except BaseException:
            entry.state = "lock_unknown"
            raise
    def release(self, token):
        entry = self._entry(token)
        if not entry.depth:
            return
        if entry.depth > 1:
            entry.depth -= 1
            return
        try:
            self._borrow(token,"unlock")
        except BaseException:
            entry.state = "unlock_unknown"
            raise
        entry.depth, entry.state = 0, "crt_owned"
    def close_descriptor(self, token, *, _fault=None):
        entry = self._entry(token)
        if entry.state == "close_unknown":
            raise BoundaryBlocked("unresolved-close-cannot-be-replayed")
        if _fault not in (None,"before","after"):
            raise Denied("unapproved-test-fault")
        if entry.depth:
            self.release(token)
            if entry.depth:
                raise Denied("nested-lock-must-be-released")
        self._borrow(token,"verify")
        if _fault == "before":
            entry.state = "close_not_started"
            raise NativeFailure("synthetic-pre-close-failure")
        try:
            os.close(entry.fd)  # CRT owns it: NEVER native CloseHandle.
        except BaseException:
            entry.state = "close_unknown"
            raise OutcomeUnknown("close-outcome-needs-explicit-evidence")
        del self._descriptors[token]
        self.history.append("CRT-close-committed-no-CloseHandle")
        if _fault == "after":
            self.history.append("post-close-notification-failed-but-ownership-retired")
            raise OutcomeUnknown("post-close-notification-failed")
    def raw_descriptor(self, *_args):
        raise BoundaryBlocked("raw-descriptor-export-denied")
    def query_process(self, *_args):
        raise BoundaryBlocked("external-PID-denied")
    def upstream_path_conversion(self, *_args):
        raise BoundaryBlocked("upstream-Rtl-conversion-buffer-contract-BLOCKED")
    def status(self):
        return {"descriptors":len(self._descriptors),"buffers":len(self._buffers),
                "unresolved_transfers":len(self._unresolved_transfers),
                "states":[e.state for e in self._descriptors.values()],
                "depths":[e.depth for e in self._descriptors.values()],
                "closed":self._closed,"history":list(self.history)}
    def close(self):
        if self._closed:
            return
        self._live()
        if self._unresolved_transfers:
            raise BoundaryBlocked("unresolved-transfer-prevents-cleanup-success")
        for token in list(self._descriptors):
            entry = self._descriptors[token]
            # Explicit owned cleanup; unknown transfer/close is never guessed.
            if entry.state == "close_unknown":
                raise BoundaryBlocked("unresolved-close-prevents-successful-cleanup")
            while entry.depth:
                self.release(token)
            self.close_descriptor(token)
        for token in list(self._buffers):
            self.free_path(token)
        self._scope.close()
        self._closed = True
