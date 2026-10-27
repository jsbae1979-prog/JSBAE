import ast
import ctypes
import importlib
import json
import msvcrt
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest

from adapter import NativeFailure, LockTimeout
from verification_gate import Denied
from descriptor_boundary import DescriptorBoundary, BufferToken, DescriptorToken, BoundaryBlocked, OutcomeUnknown

NATIVE = None
REGISTRATION = None
GUARD = None
FACTS = None
ALL_BOUNDARIES = []

class CopyBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.boundary = DescriptorBoundary(NATIVE, REGISTRATION)
        ALL_BOUNDARIES.append(self.boundary)
        self.path = self.boundary.register_file("dummy")
        self.buffer = self.boundary.prepare_path(self.path)
        self.descriptor = self.boundary.transfer(self.buffer)
    def tearDown(self):
        self.boundary.close()
        self.assertEqual(self.boundary.status()["descriptors"], 0)
        self.assertEqual(self.boundary.status()["buffers"], 0)
        self.assertEqual(self.boundary.status()["unresolved_transfers"], 0)
        self.assertEqual(len(NATIVE._owned_handles), 0)
    def peer(self):
        return self.boundary.transfer(self.buffer)
    def test_01_real_Guard_copy_first(self):
        self.assertTrue(GUARD.INSTALLED)
        self.assertTrue(FACTS["registration_before_install_denied"])
        self.assertEqual(FACTS["initialization_order"], [
            "verification-Guard-copy-installed", "capability-gate-installed",
            "registered-source-pinned-capability", "native-binding-after-registration"])
        self.assertNotIn("filelock", sys.modules)
        self.assertEqual(set(GUARD._SYSTEM_DLLS), {"kernel32","crypt32","advapi32"})
    def test_02_guard_AST_delta_is_only_registration(self):
        self.assertTrue(FACTS["provenance"]["all_other_existing_function_AST_identical"])
        self.assertFalse(FACTS["provenance"]["global_DLL_and_symbol_allowlists_changed"])
    def test_03_registration_is_once_only(self):
        with self.assertRaises(PermissionError):
            GUARD.register_verification_capability(REGISTRATION)
    def test_04_CRT_transfer_removes_native_close_ownership(self):
        entry = self.boundary._descriptors[self.descriptor]
        self.assertNotIn(entry.handle, NATIVE._owned_handles)
        with self.assertRaises(Denied):
            NATIVE.close(entry.handle)
        self.assertTrue(self.boundary._borrow(self.descriptor,"verify"))
    def test_05_real_lock_contention_and_release(self):
        peer = self.peer()
        self.boundary.acquire(self.descriptor)
        with self.assertRaises(LockTimeout):
            self.boundary.acquire(peer,0.04)
        self.boundary.release(self.descriptor)
        self.boundary.acquire(peer)
        self.boundary.release(peer)
    def test_06_reentrancy_keeps_outer_OS_lock(self):
        peer = self.peer()
        self.boundary.acquire(self.descriptor)
        self.boundary.acquire(self.descriptor)
        self.boundary.release(self.descriptor)
        with self.assertRaises(LockTimeout):
            self.boundary.acquire(peer)
        self.boundary.release(self.descriptor)
        self.boundary.acquire(peer)
    def test_07_CRT_close_never_calls_native_CloseHandle(self):
        target = self.boundary._descriptors[self.descriptor].handle
        original = NATIVE.close
        def checked(handle):
            self.assertNotEqual(handle, target)
            return original(handle)
        NATIVE.close = checked
        try:
            self.boundary.close_descriptor(self.descriptor)
        finally:
            NATIVE.close = original
        with self.assertRaises(Denied):
            self.boundary.acquire(self.descriptor)
    def test_08_foreign_closed_and_integer_descriptors_denied(self):
        for token in (-1, 0, object(), DescriptorToken(), BufferToken()):
            with self.subTest(kind=type(token).__name__):
                with self.assertRaises(Denied):
                    self.boundary.acquire(token)
        self.boundary.close_descriptor(self.descriptor)
        with self.assertRaises(Denied):
            self.boundary.close_descriptor(self.descriptor)
    def test_09_raw_CRT_transfer_is_not_a_capability(self):
        entry = self.boundary._descriptors[self.descriptor]
        with self.assertRaises(Denied):
            msvcrt.open_osfhandle(entry.handle, os.O_RDWR|os.O_NOINHERIT)
        with self.assertRaises(Denied):
            msvcrt.get_osfhandle(entry.fd)
    def test_10_external_path_and_handle_denied(self):
        dummy = Path(GUARD.ROOT)/"foreign-dummy.lock"
        dummy.write_bytes(b"synthetic-unchanged")
        with self.assertRaises(Denied):
            self.boundary.prepare_path(str(dummy))
        self.assertEqual(dummy.read_bytes(),b"synthetic-unchanged")
        with self.assertRaises(Denied):
            NATIVE.info(-123456789)
    def test_11_UNC_ADS_device_relative_denied(self):
        for path in (r"\\server\share\dummy.lock", self.path+":stream",
                     r"\\?\C:\dummy.lock", r"\Device\dummy", "relative.lock"):
            with self.subTest(path=path):
                with self.assertRaises(Denied):
                    self.boundary.prepare_path(path)
    def test_12_buffer_lifetime_and_double_free(self):
        token = self.boundary.prepare_path(self.path)
        meta = self.boundary.buffer_metadata(token)
        self.assertEqual(meta["allocator"],"Python-owned-relative-name")
        self.assertFalse(meta["native_Rtl_allocation"])
        self.boundary.free_path(token)
        with self.assertRaises(Denied):
            self.boundary.free_path(token)
        with self.assertRaises(Denied):
            self.boundary.transfer(token)
    def test_13_in_use_buffer_cannot_be_freed(self):
        token = self.boundary.prepare_path(self.path)
        def probe():
            self.assertEqual(self.boundary.buffer_metadata(token)["state"],"in_use")
            with self.assertRaises(Denied):
                self.boundary.free_path(token)
        handle, _, _ = self.boundary._relative_open(token,during_call=probe)
        NATIVE.close(handle)
        self.assertEqual(self.boundary.buffer_metadata(token)["state"],"ready")
        self.boundary.free_path(token)
    def test_14_native_Rtl_conversion_and_free_remain_blocked(self):
        with self.assertRaises(BoundaryBlocked):
            self.boundary.upstream_path_conversion(self.path)
        with self.assertRaises(BoundaryBlocked):
            self.boundary.native_free(object())
    def test_15_pre_transfer_failure_has_native_owner_cleanup(self):
        token = self.boundary.prepare_path(self.path)
        before = len(NATIVE._owned_handles)
        with self.assertRaises(NativeFailure):
            self.boundary.transfer(token,_fault="before")
        self.assertEqual(len(NATIVE._owned_handles),before)
        self.assertEqual(self.boundary.status()["descriptors"],1)
    def test_16_post_transfer_notification_retains_descriptor_and_blocks_replay(self):
        token = self.boundary.prepare_path(self.path)
        with self.assertRaises(OutcomeUnknown):
            self.boundary.transfer(token,_fault="after")
        self.assertIn("notification_unknown",self.boundary.status()["states"])
        with self.assertRaises(Denied):
            self.boundary.transfer(token)
        self.assertEqual(self.boundary.status()["descriptors"],2)
    def test_17_pre_close_failure_preserves_owned_descriptor(self):
        with self.assertRaises(NativeFailure):
            self.boundary.close_descriptor(self.descriptor,_fault="before")
        self.assertEqual(self.boundary.status()["descriptors"],1)
        with self.assertRaises(BoundaryBlocked):
            self.boundary.acquire(self.descriptor)
        self.boundary.close_descriptor(self.descriptor)
    def test_18_post_close_notification_is_not_a_live_descriptor(self):
        with self.assertRaises(OutcomeUnknown):
            self.boundary.close_descriptor(self.descriptor,_fault="after")
        self.assertEqual(self.boundary.status()["descriptors"],0)
        with self.assertRaises(Denied):
            self.boundary.close_descriptor(self.descriptor)
    def test_19_unlock_failure_does_not_drop_ownership(self):
        self.boundary.acquire(self.descriptor)
        original = NATIVE.unlock
        def fail(handle):
            raise NativeFailure("synthetic-unlock-failure")
        NATIVE.unlock=fail
        try:
            with self.assertRaises(NativeFailure):
                self.boundary.release(self.descriptor)
            self.assertEqual(self.boundary.status()["depths"],[1])
            self.assertEqual(self.boundary.status()["states"],["unlock_unknown"])
            with self.assertRaises(BoundaryBlocked):
                self.boundary.acquire(self.descriptor)
        finally:
            NATIVE.unlock=original
        self.boundary.release(self.descriptor)
    def test_20_raw_DLL_and_unregistered_symbol_still_denied(self):
        with self.assertRaises(PermissionError):
            ctypes.WinDLL("ntdll")
        with self.assertRaises(PermissionError):
            getattr(ctypes.WinDLL("kernel32"),"OpenProcess")
        self.assertNotIn(("ntdll","NtCreateFile"),GUARD._NATIVE)
    def test_21_external_PID_and_descriptor_export_denied(self):
        with self.assertRaises(BoundaryBlocked):
            self.boundary.query_process(2147483647)
        with self.assertRaises(BoundaryBlocked):
            self.boundary.raw_descriptor(self.descriptor)
    def test_22_network_process_and_DB_boundaries_preserved(self):
        with socket.socket() as sock:
            with self.assertRaises(PermissionError):
                sock.connect(("203.0.113.1",443))
        with socket.socket() as sock:
            with self.assertRaises(PermissionError):
                sock.connect(("127.0.0.1",8765))
        with self.assertRaises(PermissionError):
            socket.getaddrinfo("synthetic.invalid",443)
        with self.assertRaises(PermissionError):
            subprocess.Popen([str(Path(GUARD.ROOT)/"not-approved.exe")])
        import sqlite3
        with self.assertRaises(PermissionError):
            sqlite3.connect(str(Path(GUARD.ROOT)/"dummy.sqlite"))
    def test_23_write_to_configured_project_remains_denied(self):
        with self.assertRaises(PermissionError):
            (GUARD.PROJECT/"must-not-exist.txt").write_text("synthetic")
        self.assertFalse(GUARD.PROJECT.exists())
    def test_24_invalid_timeout_and_foreign_buffer_denied(self):
        for timeout in (-1,3,float("inf"),float("nan")):
            with self.assertRaises(Denied):
                self.boundary.acquire(self.descriptor,timeout)
        with self.assertRaises(Denied):
            self.boundary.free_path(BufferToken())
    def test_25_native_lock_success_then_error_is_not_replayed(self):
        peer=self.peer()
        target=self.boundary._descriptors[self.descriptor].handle
        original=NATIVE.lock
        attempts=[]
        def interrupted(handle):
            if handle!=target:
                return original(handle)
            attempts.append(handle)
            self.assertTrue(original(handle))
            raise OutcomeUnknown("synthetic-after-actual-lock")
        NATIVE.lock=interrupted
        try:
            with self.assertRaises(OutcomeUnknown):
                self.boundary.acquire(self.descriptor)
            with self.assertRaises(BoundaryBlocked):
                self.boundary.acquire(self.descriptor)
            self.assertEqual(len(attempts),1)
        finally:
            NATIVE.lock=original
        with self.assertRaises(LockTimeout):
            self.boundary.acquire(peer)
        self.boundary.close_descriptor(self.descriptor)
        self.boundary.acquire(peer)
    def test_26_private_CRT_dispatch_requires_pending_owned_transfer(self):
        anchor=self.boundary._scope._registrations[next(iter(self.boundary._paths.values()))].handle
        with self.assertRaises(Denied):
            REGISTRATION._call_crt(self.boundary,"msvcrt.open_osfhandle",msvcrt.open_osfhandle,
                                   (anchor,os.O_RDWR|os.O_NOINHERIT))
        with self.assertRaises(Denied):
            REGISTRATION._call_crt(self.boundary,"msvcrt.get_osfhandle",msvcrt.get_osfhandle,(-12345,))
    def test_99_unmodified_filelock_import_still_fails_closed(self):
        # Post-Guard negative integration probe only. Never preload or retry.
        with self.assertRaises(PermissionError):
            importlib.import_module("filelock")
        self.assertNotIn("filelock",sys.modules)
        FACTS["upstream_filelock_full_import"]="BLOCKED at guarded native binding"
