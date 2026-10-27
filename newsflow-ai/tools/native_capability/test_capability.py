"""Synthetic security tests; no operating path/PID/key is used, even negatively."""
import ctypes
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import unittest
import _winapi

from verification_gate import Denied, Grant
from adapter import LockScope, LockCapability, NativeFailure, LockTimeout

GATE = None
NATIVE = None

class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.scopes = []
        self.scope = self.new_scope()
        self.path = str(Path(self.scope.root) / "dummy.lock")
    def tearDown(self):
        for scope in reversed(self.scopes):
            scope.close()
            self.assertEqual(scope.status(), {"open_capabilities": 0, "registrations": 0,
                "directory_handles": 0, "held_locks": 0, "closed": True})
    def new_scope(self):
        scope = LockScope(NATIVE, GATE.new_scope())
        self.scopes.append(scope)
        return scope
    def pair(self):
        registration = self.scope.register(self.path)
        return self.scope.open(registration), self.scope.open(registration)
    def test_01_guard_first(self):
        self.assertEqual(GATE.events[:2], [
            "gate-installed-before-adapter-import-and-DLL-binding", "fixed-native-bindings-complete"])
        self.assertTrue(GATE.installed)
    def test_02_real_exclusive_lock_and_release(self):
        a, b = self.pair()
        self.scope.acquire(a)
        with self.assertRaises(LockTimeout):
            self.scope.acquire(b)
        self.scope.release(a)
        self.scope.acquire(b)
        self.scope.release(b)
    def test_03_contention_timeout(self):
        a, b = self.pair()
        self.scope.acquire(a)
        start = time.monotonic()
        with self.assertRaises(LockTimeout):
            self.scope.acquire(b, 0.06)
        elapsed = time.monotonic() - start
        self.assertGreaterEqual(elapsed, 0.05)
        self.assertLess(elapsed, 1.0)
        self.scope.release(a)
    def test_04_closed_and_recycled_capability(self):
        a, b = self.pair()
        self.scope.close_handle(a)
        self.scope.acquire(b)
        with self.assertRaises(Denied):
            self.scope.acquire(a)
        self.scope.release(b)
    def test_05_raw_and_forged_handles(self):
        for token in (0, 1, -1, object(), LockCapability(), None):
            with self.subTest(type=type(token).__name__):
                with self.assertRaises(Denied):
                    self.scope.acquire(token)
    def test_06_foreign_scope_capability(self):
        a, _ = self.pair()
        other = self.new_scope()
        with self.assertRaises(Denied):
            other.acquire(a)
    def test_07_foreign_registration(self):
        reg = self.scope.register(self.path)
        with self.assertRaises(Denied):
            self.new_scope().open(reg)
    def test_08_unheld_unlock(self):
        a, _ = self.pair()
        with self.assertRaises(Denied):
            self.scope.release(a)
    def test_09_wrong_thread_unlock(self):
        a, _ = self.pair()
        self.scope.acquire(a)
        errors = []
        def release():
            try:
                self.scope.release(a)
            except Denied:
                errors.append("denied")
        worker = threading.Thread(target=release)
        worker.start()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ["denied"])
        self.scope.release(a)
    def test_10_invalid_timeout(self):
        a, _ = self.pair()
        for timeout in (-1, 3, math.inf, math.nan, "1", True):
            with self.subTest(timeout=str(timeout)):
                with self.assertRaises(Denied):
                    self.scope.acquire(a, timeout)
    def test_11_external_synthetic_path(self):
        dummy = Path(GATE.workspace) / "outside-scope.lock"
        dummy.write_bytes(b"synthetic-unchanged")
        with self.assertRaises(Denied):
            self.scope.register(str(dummy))
        self.assertEqual(dummy.read_bytes(), b"synthetic-unchanged")
    def test_12_UNC_and_device(self):
        for value in (r"\\server\share\dummy.lock", r"\\?\C:\dummy.lock",
                      r"\\.\C:\dummy.lock", r"\Device\HarddiskVolume1\dummy.lock"):
            with self.subTest(path=value):
                with self.assertRaises(Denied):
                    self.scope.register(value)
    def test_13_ADS(self):
        with self.assertRaises(Denied):
            self.scope.register(self.path + ":hidden")
    def test_14_relative_parent_and_drive_relative(self):
        for value in ("dummy.lock", r"C:dummy.lock",
                      str(Path(self.scope.root) / ".." / "dummy.lock")):
            with self.subTest(path=value):
                with self.assertRaises(Denied):
                    self.scope.register(value)
    def test_15_ambiguous_names(self):
        for name in ("CON.lock", "NUL.lock", "COM1.lock", "dummy.lock.",
                     "dummy.lock ", "bad?.lock", "bad\x00.lock"):
            with self.subTest(name=name):
                with self.assertRaises(Denied):
                    self.scope.register(str(Path(self.scope.root) / name))
    def test_16_preexisting_file_not_truncated(self):
        file = Path(self.path)
        file.write_bytes(b"do-not-truncate")
        with self.assertRaises(NativeFailure):
            self.scope.register(self.path)
        self.assertEqual(file.read_bytes(), b"do-not-truncate")
    def test_17_double_registration(self):
        self.scope.register(self.path)
        with self.assertRaises(NativeFailure):
            self.scope.register(self.path)
    def test_18_closed_scope(self):
        self.scope.close()
        with self.assertRaises(Denied):
            self.scope.register(self.path)
    def test_19_native_symbol_not_exposed(self):
        for symbol in ("NtCreateFile", "OpenProcess", "GetProcessTimes",
                       "RtlDosPathNameToNtPathName_U_WithStatus",
                       "RtlFreeUnicodeString", "VirtualAlloc", "system"):
            with self.subTest(symbol=symbol):
                with self.assertRaises(Denied):
                    self.scope.native_symbol(symbol)
    def test_20_external_PID_blocked_before_OS(self):
        for pid in (-1, 0, 2147483647, "dummy"):
            with self.subTest(pid=pid):
                with self.assertRaises(Denied):
                    self.scope.query_process(pid)
    def test_21_raw_DLL_blocked(self):
        with self.assertRaises(Denied):
            ctypes.WinDLL(str(Path(GATE.system32) / "ntdll.dll"))
    def test_22_arbitrary_symbol_blocked(self):
        # Existing DLL object is private; deliberately exercise audit gate without
        # loading/resolving a real forbidden symbol.
        with self.assertRaises(Denied):
            sys.audit("ctypes.dlsym", object(), "OpenProcess")
    def test_23_network_and_DNS_blocked(self):
        with socket.socket() as sock:
            with self.assertRaises(Denied):
                sock.connect(("203.0.113.1", 443))
        with self.assertRaises(Denied):
            socket.getaddrinfo("synthetic.invalid", 443)
    def test_24_child_process_blocked(self):
        with self.assertRaises(Denied):
            subprocess.Popen([sys.executable, "-V"])
    def test_25_no_implicit_reentrancy(self):
        a, _ = self.pair()
        self.scope.acquire(a)
        with self.assertRaises(Denied):
            self.scope.acquire(a)
        self.scope.release(a)
    def test_26_active_scope_cannot_be_renamed(self):
        with self.assertRaises(OSError):
            os.rename(self.scope.root, self.scope.root + "-renamed")
        self.assertTrue(Path(self.scope.root).is_dir())
    def test_27_parent_junction_is_denied(self):
        # All targets are empty synthetic folders. No operating path is probed.
        grant = GATE.new_scope()
        target = Path(GATE.workspace) / ("target-" + Path(grant.root).name)
        target.mkdir()
        os.rmdir(grant.root)
        _winapi.CreateJunction(str(target), grant.root)
        with self.assertRaises((Denied, NativeFailure)):
            LockScope(NATIVE, grant)
        self.assertEqual(list(target.iterdir()), [])
    def test_28_nested_junction_is_denied(self):
        target = Path(GATE.workspace) / ("nested-target-" + Path(self.scope.root).name)
        target.mkdir()
        link = Path(self.scope.root) / "junction"
        _winapi.CreateJunction(str(target), str(link))
        with self.assertRaises(Denied):
            self.scope.register(str(link / "dummy.lock"))
        self.assertEqual(list(target.iterdir()), [])
    def test_29_leaf_reparse_is_denied(self):
        target = Path(GATE.workspace) / ("leaf-target-" + Path(self.scope.root).name)
        target.mkdir()
        _winapi.CreateJunction(str(target), self.path)
        with self.assertRaises((Denied, NativeFailure)):
            self.scope.register(self.path)
        self.assertEqual(list(target.iterdir()), [])
    def test_30_existing_hardlink_is_denied(self):
        dummy = Path(GATE.workspace) / ("hardlink-" + Path(self.scope.root).name)
        dummy.write_bytes(b"synthetic")
        os.link(dummy, self.path)
        with self.assertRaises(NativeFailure):
            self.scope.register(self.path)
        self.assertEqual(dummy.read_bytes(), b"synthetic")
    def test_31_handle_path_mismatch_is_denied(self):
        a, _ = self.pair()
        # Trusted fault injection changes expected metadata, not OS handle/input.
        entry = self.scope._handles[a]
        original = entry.path
        entry.path = str(Path(self.scope.root) / "different.lock")
        try:
            with self.assertRaises(Denied):
                self.scope.acquire(a)
        finally:
            entry.path = original
    def test_32_file_identity_mismatch_is_denied(self):
        a, _ = self.pair()
        entry = self.scope._handles[a]
        original = entry.identity
        entry.identity = (-1, -1, -1)
        try:
            with self.assertRaises(Denied):
                self.scope.acquire(a)
        finally:
            entry.identity = original
    def test_33_failed_unlock_preserves_state(self):
        a, b = self.pair()
        self.scope.acquire(a)
        original = NATIVE.unlock
        def fail(_handle):
            raise NativeFailure("synthetic-unlock-failure")
        NATIVE.unlock = fail
        try:
            with self.assertRaises(NativeFailure):
                self.scope.release(a)
            self.assertEqual(self.scope.status()["held_locks"], 1)
            with self.assertRaises(LockTimeout):
                self.scope.acquire(b)
        finally:
            NATIVE.unlock = original
        self.scope.release(a)
    def test_34_failed_close_preserves_ownership(self):
        a, _ = self.pair()
        original = NATIVE.close
        def fail(_handle):
            raise NativeFailure("synthetic-close-failure")
        NATIVE.close = fail
        try:
            with self.assertRaises(NativeFailure):
                self.scope.close_handle(a)
            self.assertEqual(self.scope.status()["open_capabilities"], 2)
        finally:
            NATIVE.close = original
        self.scope.close_handle(a)
    def test_35_grant_cannot_be_forged_or_reused(self):
        with self.assertRaises(Denied):
            LockScope(NATIVE, Grant(self.scope.root))
        grant = GATE.new_scope()
        other = LockScope(NATIVE, grant)
        self.scopes.append(other)
        with self.assertRaises(Denied):
            LockScope(NATIVE, grant)
    def test_36_binding_window_cannot_be_reopened(self):
        with self.assertRaises(Denied):
            with GATE._binding_only():
                pass

    def test_37_grant_path_tampering(self):
        grant = GATE.new_scope()
        grant.root = str(Path(GATE.workspace) / "foreign-synthetic")
        with self.assertRaises(Denied):
            LockScope(NATIVE, grant)
