"""Verification-only contract subset over the approved native capability.

Never imported by the app; never substituted for filelock.FileLock.
Unsupported upstream binding/descriptor/process contracts fail closed.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import re
import threading
import uuid
from adapter import LockScope, LockTimeout, _Native
from verification_gate import Denied, VerificationGate

class CompatibilityBlocked(Denied):
    pass

class JournalFailure(OSError):
    pass

class _AcquireContext:
    def __init__(self, session):
        self._session = session
        self._consumed = False
    def __enter__(self):
        if self._consumed:
            raise CompatibilityBlocked("context-proxy-already-consumed")
        self._consumed = True
        return self._session
    def __exit__(self, kind, error, traceback):
        self._session.release()
        return False

def _timeout(value):
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 2:
        raise CompatibilityBlocked("only-explicit-finite-timeout-zero-to-two-seconds")
    return float(value)

class VerificationRegistry:
    CAPABILITY = "synthetic-filelock-contract-subset-v1"
    def __init__(self, gate, native, capability=CAPABILITY):
        if type(gate) is not VerificationGate or not gate.installed:
            raise Denied("guard-first-registration-required")
        if type(native) is not _Native or native.gate is not gate:
            raise Denied("foreign-native-provider")
        if capability != self.CAPABILITY:
            raise Denied("unknown-capability")
        self._scope = LockScope(native, gate.new_scope())
        self._registrations = {}
        self._sessions = []
        self._owner = threading.get_ident()
        self._closed = False
    def _live(self):
        if self._closed or threading.get_ident() != self._owner:
            raise Denied("closed-or-other-thread-registry")
    def create(self, name, *, timeout=0.0, **unsupported_options):
        self._live()
        if unsupported_options:
            raise CompatibilityBlocked("unsupported-filelock-options:" + ",".join(sorted(unsupported_options)))
        _timeout(timeout)
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", name):
            raise Denied("registered-synthetic-name-required")
        if name not in self._registrations:
            self._registrations[name] = self._scope.register(str(Path(self._scope.root) / (name + ".lock")))
        session = ContractSession(self, self._registrations[name], timeout)
        self._sessions.append(session)
        session._event("created")
        return session
    def require_upstream_binding(self):
        raise CompatibilityBlocked("upstream-import-descriptor-and-existing-Guard-registration-not-approved")
    def descriptor(self, *_args):
        raise CompatibilityBlocked("caller-owned-CRT-descriptor-contract-not-supported")
    def query_process(self, *_args):
        raise CompatibilityBlocked("PID-query-owner-recovery-not-supported")
    def native_symbol(self, *_args):
        raise CompatibilityBlocked("DLL-pointer-handle-export-not-supported")
    def close(self):
        if self._closed:
            return
        self._live()
        for session in self._sessions:
            session.close()
        self._scope.close()
        self._closed = True
    def status(self):
        return {"closed": self._closed, "sessions": [x.snapshot() for x in self._sessions],
                "scope": self._scope.status()}

class ContractSession:
    """Same-thread reentrant/context subset, explicit bounded wait only.

    Stable synthetic file identity is preserved. This is NOT the upstream
    default unlink contract, an arbitrary-path API or a BaseFileLock subclass.
    """
    def __init__(self, registry, registration, timeout):
        self._registry, self._registration = registry, registration
        self._timeout = _timeout(timeout)
        self._token = None
        self._depth = 0
        self._state = "ready"
        self._closed = False
        self._owner = threading.get_ident()
        self._events = []
        self._journal = Path(registry._scope.root) / ("state-" + uuid.uuid4().hex + ".json")
    def _check_owner(self):
        if threading.get_ident() != self._owner:
            raise Denied("cross-thread-session-not-supported")
    def _live(self):
        self._check_owner()
        self._registry._live()
        if self._closed:
            raise Denied("closed-session")
    def snapshot(self):
        return {"state": self._state, "depth": self._depth, "held": self._depth > 0,
                "pending_cleanup": self._token is not None and self._depth == 0,
                "closed": self._closed, "events": list(self._events)}
    def _persist(self):
        temp = self._journal.with_name("journal-" + uuid.uuid4().hex + ".tmp")
        try:
            with temp.open("x", encoding="utf-8") as stream:
                json.dump(self.snapshot(), stream)
            temp.replace(self._journal)
        finally:
            if temp.exists():
                temp.unlink()
    def _event(self, action):
        self._events.append(action)
        self._events = self._events[-64:]
        try:
            self._persist()
        except OSError as error:
            self._state = "journal_failed"
            raise JournalFailure("no-success-claim-after-journal-failure") from error
    def acquire(self, timeout=None, *, blocking=True):
        self._live()
        wait = self._timeout if timeout is None else _timeout(timeout)
        if type(blocking) is not bool:
            raise CompatibilityBlocked("blocking-must-be-bool")
        if self._state not in {"ready", "held"}:
            raise CompatibilityBlocked("explicit-recovery-required-no-automatic-retry")
        if self._depth:
            self._depth += 1
            self._event("reentered")
            return _AcquireContext(self)
        if self._token is not None:
            raise CompatibilityBlocked("pending-cleanup")
        self._token = self._registry._scope.open(self._registration)
        self._state = "acquiring"
        self._event("acquire-started")
        try:
            self._registry._scope.acquire(self._token, wait if blocking else 0.0)
        except LockTimeout:
            self._registry._scope.close_handle(self._token)
            self._token = None
            self._state = "ready"
            self._event("contended-timeout")
            raise
        except BaseException:
            self._state = "acquire_uncertain"
            self._event("acquire-failed-no-replay")
            raise
        self._depth, self._state = 1, "held"
        self._event("acquired")
        return _AcquireContext(self)
    def release(self, force=False):
        self._live()
        if type(force) is not bool:
            raise CompatibilityBlocked("force-must-be-bool")
        if self._depth == 0:
            return  # Matches upstream release of an unlocked lock; no OS call.
        if self._depth > 1 and not force:
            self._depth -= 1
            self._event("nested-release")
            return
        try:
            self._registry._scope.release(self._token)
        except BaseException:
            self._state = "release_uncertain"
            self._event("unlock-failed-no-replay")
            raise
        self._depth, self._state = 0, "unlocked"
        self._event("unlocked")
        try:
            self._registry._scope.close_handle(self._token)
        except BaseException:
            self._state = "cleanup_required"
            self._event("post-unlock-close-failed")
            raise
        self._token = None
        self._state = "ready"
        self._event("released")
    def close(self):
        if self._closed:
            return
        self._live()
        if self._depth:
            self.release(force=True)
        if self._token is not None:
            self._registry._scope.close_handle(self._token)
            self._token = None
        self._state, self._closed = "closed", True
        self._event("explicit-close")
    def __enter__(self):
        self.acquire()
        return self
    def __exit__(self, kind, error, traceback):
        self.release()
        return False
