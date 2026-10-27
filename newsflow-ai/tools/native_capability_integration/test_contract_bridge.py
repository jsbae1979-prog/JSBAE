import json
from pathlib import Path
import sys
import threading
import unittest
from types import SimpleNamespace

from adapter import NativeFailure, LockTimeout
from verification_gate import Denied
from contract_bridge import VerificationRegistry, CompatibilityBlocked, JournalFailure

GATE = None
NATIVE = None
PROBE = None

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.registry = VerificationRegistry(GATE, NATIVE)
        self.lock = self.registry.create("shared")
    def tearDown(self):
        self.registry.close()
        self.assertTrue(self.registry.status()["closed"])
        self.assertEqual(self.registry.status()["scope"]["open_capabilities"], 0)
    def peer(self):
        return self.registry.create("shared")
    def journal(self):
        return json.loads(self.lock._journal.read_text(encoding="utf-8"))
    def test_01_guard_first_and_no_preimport(self):
        self.assertEqual(GATE.events[0], "gate-installed-before-adapter-import-and-DLL-binding")
        self.assertNotIn("filelock", sys.modules)
        self.assertFalse(any(n == "newsflow" or n.startswith("newsflow.") for n in sys.modules))
    def test_02_actual_filelock_source_contract_matches(self):
        self.assertEqual(PROBE["version"], "3.32.7")
        self.assertTrue(PROBE["all_source_contracts_match"])
        self.assertEqual(PROBE["upstream_runtime_compatibility"], "BLOCKED")
    def test_03_existing_Guard_registration_stays_blocked(self):
        self.assertEqual(PROBE["existing_Guard_registration"], "BLOCKED")
        self.assertFalse(PROBE["full_app_allowed"])
        with self.assertRaises(CompatibilityBlocked):
            self.registry.require_upstream_binding()
    def test_04_registration_before_guard_denied(self):
        with self.assertRaises(Denied):
            VerificationRegistry(SimpleNamespace(installed=False), NATIVE)
    def test_05_unknown_capability_denied(self):
        with self.assertRaises(Denied):
            VerificationRegistry(GATE, NATIVE, capability="arbitrary-native-DLL")
    def test_06_native_reentrancy_retains_outer_lock(self):
        peer = self.peer()
        self.lock.acquire()
        self.lock.acquire()
        self.assertEqual(self.lock.snapshot()["depth"], 2)
        self.lock.release()
        with self.assertRaises(LockTimeout):
            peer.acquire()
        self.lock.release()
        peer.acquire()
        peer.release()
    def test_07_context_proxy_does_not_double_acquire(self):
        with self.lock.acquire() as active:
            self.assertIs(active, self.lock)
            self.assertEqual(active.snapshot()["depth"], 1)
        self.assertFalse(self.lock.snapshot()["held"])
    def test_08_nested_contexts_and_body_exception(self):
        with self.assertRaisesRegex(ValueError, "synthetic-body"):
            with self.lock:
                with self.lock:
                    self.assertEqual(self.lock.snapshot()["depth"], 2)
                    raise ValueError("synthetic-body")
        self.assertEqual(self.lock.snapshot()["depth"], 0)
        self.peer().acquire()
    def test_09_timeout_rolls_back_only_failed_session(self):
        peer = self.peer()
        self.lock.acquire()
        with self.assertRaises(LockTimeout):
            peer.acquire(timeout=0.04)
        self.assertEqual(peer.snapshot()["state"], "ready")
        self.assertEqual(peer.snapshot()["depth"], 0)
        self.assertTrue(self.lock.snapshot()["held"])
        self.lock.release()
        peer.acquire()
    def test_10_nonblocking_attempt(self):
        peer = self.peer()
        self.lock.acquire()
        with self.assertRaises(LockTimeout):
            peer.acquire(timeout=1.0, blocking=False)
        self.assertFalse(peer.snapshot()["pending_cleanup"])
    def test_11_unbounded_and_unsupported_options_blocked(self):
        for timeout in (-1, 3, float("nan"), float("inf")):
            with self.subTest(timeout=str(timeout)):
                with self.assertRaises(CompatibilityBlocked):
                    self.registry.create("denied", timeout=timeout)
        for options in ({"on_acquired": lambda fd: None}, {"lifetime": 1},
                        {"thread_local": False}, {"is_singleton": True},
                        {"fallback_to_soft": True}, {"preserve_lock_file": False}):
            with self.subTest(option=list(options)[0]):
                with self.assertRaises(CompatibilityBlocked):
                    self.registry.create("denied", **options)
    def test_12_unheld_release_is_noop(self):
        before = self.lock.snapshot()
        self.lock.release()
        self.assertEqual(self.lock.snapshot(), before)
    def test_13_explicit_force_releases_only_owned_lock(self):
        self.lock.acquire()
        self.lock.acquire()
        self.lock.release(force=True)
        self.assertEqual(self.lock.snapshot()["depth"], 0)
        self.peer().acquire()
    def test_14_cross_thread_denied(self):
        errors = []
        def run():
            try:
                self.lock.acquire()
            except Denied:
                errors.append("denied")
        thread = threading.Thread(target=run)
        thread.start(); thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, ["denied"])
    def test_15_descriptor_PID_DLL_exports_blocked(self):
        for method, argument in ((self.registry.descriptor, -1234),
                                 (self.registry.query_process, 2147483647),
                                 (self.registry.native_symbol, "OpenProcess")):
            with self.subTest(method=method.__name__):
                with self.assertRaises(CompatibilityBlocked):
                    method(argument)
    def test_16_paths_cannot_be_smuggled_as_registration_names(self):
        for name in (r"C:\synthetic\outside", "../outside", r"\\server\share",
                     "name:ADS", r"\\?\C:\dummy", "CON"):
            with self.subTest(name=name):
                with self.assertRaises(Denied):
                    self.registry.create(name)
    def test_17_unlock_failure_retains_lock_and_journal(self):
        peer = self.peer()
        self.lock.acquire()
        original = NATIVE.unlock
        def fail(handle):
            raise NativeFailure("synthetic-unlock-failure")
        NATIVE.unlock = fail
        try:
            with self.assertRaises(NativeFailure):
                self.lock.release()
            self.assertTrue(self.lock.snapshot()["held"])
            self.assertEqual(self.journal()["state"], "release_uncertain")
            with self.assertRaises(CompatibilityBlocked):
                self.lock.acquire()
            with self.assertRaises(LockTimeout):
                peer.acquire()
        finally:
            NATIVE.unlock = original
        self.lock.release()  # Explicit owner retry; never automatic.
        peer.acquire()
    def test_18_post_unlock_close_failure_is_not_held(self):
        peer = self.peer()
        self.lock.acquire()
        original = NATIVE.close
        def fail(handle):
            raise NativeFailure("synthetic-close-failure")
        NATIVE.close = fail
        try:
            with self.assertRaises(NativeFailure):
                self.lock.release()
            self.assertFalse(self.lock.snapshot()["held"])
            self.assertEqual(self.journal()["state"], "cleanup_required")
            with self.assertRaises(CompatibilityBlocked):
                self.lock.acquire()
            peer.acquire()
        finally:
            NATIVE.close = original
        self.lock.close()
        peer.release()
    def test_19_uncertain_acquire_is_not_replayed(self):
        original = NATIVE.lock
        calls = []
        def fail(handle):
            calls.append(handle)
            raise NativeFailure("synthetic-unknown-outcome")
        NATIVE.lock = fail
        try:
            with self.assertRaises(NativeFailure):
                self.lock.acquire()
            self.assertEqual(self.journal()["state"], "acquire_uncertain")
            with self.assertRaises(CompatibilityBlocked):
                self.lock.acquire()
            self.assertEqual(len(calls), 1)
        finally:
            NATIVE.lock = original
        self.lock.close()
    def test_20_context_body_and_release_failure_both_preserved(self):
        original = NATIVE.unlock
        def fail(handle):
            raise NativeFailure("synthetic-unlock-failure")
        NATIVE.unlock = fail
        try:
            with self.assertRaises(NativeFailure) as captured:
                with self.lock:
                    raise ValueError("synthetic-body")
            self.assertIsInstance(captured.exception.__context__, ValueError)
            self.assertTrue(self.lock.snapshot()["held"])
        finally:
            NATIVE.unlock = original
        self.lock.release()
    def test_21_journal_failure_blocks_new_execution(self):
        original = self.lock._persist
        def fail():
            raise OSError("synthetic-disk-failure")
        self.lock._persist = fail
        try:
            with self.assertRaises(JournalFailure):
                self.lock.acquire()
            self.assertEqual(self.lock.snapshot()["state"], "journal_failed")
            with self.assertRaises(CompatibilityBlocked):
                self.lock.acquire()
        finally:
            self.lock._persist = original
        self.lock.close()
    def test_22_closed_session_and_registry_deny_reuse(self):
        self.lock.acquire()
        self.registry.close()
        with self.assertRaises(Denied):
            self.lock.acquire()
        with self.assertRaises(Denied):
            self.registry.create("again")
    def test_23_sessions_do_not_change_each_others_state(self):
        other = self.registry.create("independent")
        self.lock.acquire()
        before = self.lock.snapshot()
        other.acquire()
        other.release()
        self.assertEqual(self.lock.snapshot(), before)
    def test_24_restart_record_does_not_authorize_reacquire(self):
        self.lock.acquire()
        state = self.journal()
        self.assertEqual(state["state"], "held")
        self.assertTrue(state["held"])
        # A saved record is evidence, never a capability or stale-owner proof.
        with self.assertRaises(Denied):
            self.registry._scope.open(state)
