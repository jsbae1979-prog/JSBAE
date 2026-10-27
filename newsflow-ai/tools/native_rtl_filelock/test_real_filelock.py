import ctypes as C
import gc
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
import filelock
from verification_gate import Denied
from rtl_boundary import OutcomeUnknown, NativeBuffer

B=None
FACTS=None

class RealFileLockTests(unittest.TestCase):
    serial=0
    def setUp(self):
        type(self).serial+=1
        self.path=B.register_path("case"+str(type(self).serial))
        self.locks=[]
    def lock(self,**options):
        item=filelock.FileLock(self.path,**options);self.locks.append(item);return item
    def tearDown(self):
        B._fault=None
        for item in self.locks:
            if item.is_locked and str(item.lock_file).lower() not in B.blocked:
                item.release(force=True)
        B.cleanup_owned()
        self.assertEqual(len(B.fds),0)
        self.assertEqual(len(B.handles),0)
        self.assertEqual(B.status()["native_buffers"],0)
    def test_01_real_guard_first_package_import(self):
        self.assertTrue(FACTS["Guards_installed_before_filelock"])
        self.assertEqual(filelock.__version__,"3.32.7")
        self.assertEqual(filelock.FileLock.__module__,"filelock._windows")
        self.assertTrue(FACTS["source_contract_match"])
        self.assertNotIn("newsflow",sys.modules)
    def test_02_actual_acquire_zero_release(self):
        item=self.lock()
        item.acquire(timeout=0)
        self.assertTrue(item.is_locked);self.assertEqual(item.lock_counter,1)
        self.assertEqual(len(B.fds),1)
        item.release()
        self.assertFalse(item.is_locked);self.assertEqual(item.lock_counter,0)
        self.assertEqual(len(B.fds),0)
    def test_03_real_contention_timeout(self):
        first,second=self.lock(),self.lock()
        first.acquire(timeout=0)
        with self.assertRaises(filelock.Timeout):second.acquire(timeout=0)
        self.assertFalse(second.is_locked)
        first.release()
        second.acquire(timeout=0);second.release()
    def test_04_positive_timeout_and_recovery(self):
        first,second=self.lock(),self.lock()
        first.acquire(timeout=0);start=time.monotonic()
        with self.assertRaises(filelock.Timeout):second.acquire(timeout=0.03)
        self.assertGreaterEqual(time.monotonic()-start,0.02)
        self.assertEqual(second.lock_counter,0)
        first.release();second.acquire(timeout=0);second.release()
    def test_05_actual_context_proxy_and_nested_reentrancy(self):
        item=self.lock()
        with item.acquire(timeout=0) as active:
            self.assertIs(active,item);self.assertEqual(item.lock_counter,1)
            with item.acquire(timeout=0):
                self.assertEqual(item.lock_counter,2)
            self.assertEqual(item.lock_counter,1)
            with self.assertRaises(filelock.Timeout):self.lock().acquire(timeout=0)
        self.assertFalse(item.is_locked)
    def test_06_default_cleanup_attempt_and_file_reuse(self):
        inode=Path(self.path).stat().st_ino
        before=B.unlink_attempts
        for _ in range(2):
            item=self.lock()
            with item.acquire(timeout=0):self.assertTrue(item.is_locked)
        self.assertGreaterEqual(B.unlink_attempts-before,2)
        # Registered safety anchor omits delete sharing; Windows permits persistence.
        self.assertTrue(Path(self.path).is_file())
        self.assertEqual(Path(self.path).stat().st_ino,inode)
        self.assertEqual(len(B.fds),0)
    def test_07_preserve_file_option_does_not_unlink(self):
        before=B.unlink_attempts
        item=self.lock(preserve_lock_file=True)
        with item.acquire(timeout=0):pass
        self.assertEqual(B.unlink_attempts,before)
        self.assertTrue(Path(self.path).exists())
    def test_08_CRT_owner_not_native_CloseHandle_owner(self):
        item=self.lock();item.acquire(timeout=0)
        fd=item._context.lock_file_fd
        self.assertIn(fd,B.fds)
        handle=B.fds[fd].handle
        self.assertNotIn(handle,B.native._owned_handles)
        with self.assertRaises(Denied):B.native.close(handle)
        item.release()
        self.assertNotIn(fd,B.fds)
    def test_09_upstream_external_descriptor_is_rejected(self):
        with self.assertRaises(Denied):
            filelock.lock_descriptor(-12345,blocking=False)
    def test_10_external_synthetic_path_denied_before_Rtl(self):
        dummy=Path(B.gate.workspace)/"outside-registered-scope.lock"
        dummy.write_bytes(b"synthetic-unchanged")
        count=B.allocations
        with self.assertRaises(Denied):
            filelock.FileLock(str(dummy)).acquire(timeout=0)
        self.assertEqual(B.allocations,count)
        self.assertEqual(dummy.read_bytes(),b"synthetic-unchanged")
    def test_11_UNC_ADS_device_and_relative_denied_without_OS_probe(self):
        for path in (r"\\server\share\dummy.lock",self.path+":stream",
                     r"\\?\C:\dummy.lock",r"\Device\dummy","relative.lock"):
            with self.subTest(path=path):
                with self.assertRaises(Denied):B.prepare_buffer(path)
    def test_12_real_Rtl_allocate_and_free_once(self):
        alloc,free=B.allocations,B.frees
        token=B.prepare_buffer(self.path)
        meta=B.buffer_metadata(token)
        self.assertEqual(meta["allocator"],"native-Rtl")
        self.assertFalse(meta["pointer_exported"])
        self.assertGreater(meta["length"],0)
        B.release_buffer(token)
        with self.assertRaises(Denied):B.release_buffer(token)
        self.assertEqual(B.allocations-alloc,1);self.assertEqual(B.frees-free,1)
    def test_13_Python_and_arbitrary_pointer_cannot_be_freed(self):
        count=B.frees
        with self.assertRaises(Denied):B.release_buffer(C.create_unicode_buffer("dummy"))
        with self.assertRaises(Denied):B.release_buffer(NativeBuffer())
        with self.assertRaises(Denied):
            filelock._windows._ntdll.RtlFreeUnicodeString(C.c_void_p(1))
        self.assertEqual(B.frees,count)
    def test_14_in_use_buffer_cannot_be_freed_during_real_NT_call(self):
        original=B.native._functions["NtCreateFile"];observed=[]
        def probe(*args):
            tokens=[t for t,r in B.buffers.items() if r.state=="in_use"]
            if tokens:
                observed.append(True)
                with self.assertRaises(Denied):B.release_buffer(tokens[0])
            return original(*args)
        B.native._functions["NtCreateFile"]=probe
        try:
            item=self.lock()
            item.acquire(timeout=0);item.release()
        finally:B.native._functions["NtCreateFile"]=original
        self.assertTrue(observed)
    def test_15_changed_user_pointer_denied_before_free(self):
        token=B.prepare_buffer(self.path);record=B.buffers[token]
        view=type(record.native).from_buffer(record.user)
        original=view.Buffer
        python=C.create_unicode_buffer("not-native")
        view.Buffer=C.addressof(python)
        try:
            with self.assertRaises(Denied):B.release_buffer(token)
        finally:view.Buffer=original
        B.release_buffer(token)
    def test_16_unknown_buffer_owner_is_not_freed(self):
        token=B.prepare_buffer(self.path);record=B.buffers[token]
        count=B.frees;record.state="free_unknown"
        try:
            with self.assertRaises(Denied):B.release_buffer(token)
            self.assertEqual(B.frees,count)
        finally:record.state="ready"  # Trusted state injection; no native free occurred.
        B.release_buffer(token)
    def test_17_Rtl_output_is_validated_and_rejected_allocation_is_freed(self):
        original=B.gate._read_rtl_owned
        def changed(owner,pointer,size):
            original(owner,pointer,size)
            return "wrong-native-path".encode("utf-16-le")
        B.gate._read_rtl_owned=changed
        before=B.frees
        try:
            with self.assertRaises(Denied):B.prepare_buffer(self.path)
        finally:B.gate._read_rtl_owned=original
        self.assertEqual(B.frees,before+1)
    def test_18_post_free_notification_does_not_double_free(self):
        token=B.prepare_buffer(self.path);before=B.frees
        with self.assertRaises(OutcomeUnknown):B.release_buffer(token,_fault="after")
        with self.assertRaises(Denied):B.release_buffer(token)
        self.assertEqual(B.frees,before+1)
    def test_19_native_lock_unknown_outcome_not_replayed(self):
        original=B.native.lock;calls=[]
        def fail_after(handle):
            calls.append(handle);self.assertTrue(original(handle))
            raise OutcomeUnknown("synthetic-after-native-lock")
        B.native.lock=fail_after
        try:
            with self.assertRaises(OutcomeUnknown):self.lock().acquire(timeout=0)
        finally:B.native.lock=original
        before=B.allocations
        with self.assertRaises(OutcomeUnknown):self.lock().acquire(timeout=0)
        self.assertEqual(len(calls),1);self.assertEqual(B.allocations,before)
        self.assertEqual(len(B.fds),0)  # Actual package closed its descriptor on error.
    def test_20_unlock_unknown_preserves_logical_lock_no_native_replay(self):
        item=self.lock();item.acquire(timeout=0)
        original=B.native.unlock;calls=[]
        def fail(handle):
            calls.append(handle);raise OutcomeUnknown("synthetic-unlock-unknown")
        B.native.unlock=fail
        try:
            with self.assertRaises(OutcomeUnknown):item.release()
        finally:B.native.unlock=original
        self.assertTrue(item.is_locked)
        with self.assertRaises(OutcomeUnknown):item.release()
        self.assertEqual(len(calls),1)
        B.cleanup_owned()  # Explicit known-owned CRT close; no normal-unlock claim.
    def test_21_close_failure_before_and_after_commit(self):
        item=self.lock();item.acquire(timeout=0)
        B._fault="close-before"
        try:
            with self.assertRaises(OSError):item.release()
        finally:B._fault=None
        self.assertFalse(item.is_locked);self.assertEqual(len(B.fds),1)
        B.cleanup_owned()
        item=self.lock();item.acquire(timeout=0);B._fault="close-after"
        try:
            with self.assertRaises(OSError):item.release()
        finally:B._fault=None
        self.assertFalse(item.is_locked);self.assertEqual(len(B.fds),0)
    def test_22_process_and_unknown_DLL_symbol_blocked(self):
        import filelock._identity
        with self.assertRaises(Denied):filelock._identity.process_alive(2147483647)
        with self.assertRaises(PermissionError):C.WinDLL("ntdll")
        with self.assertRaises(Denied):getattr(filelock._windows._ntdll,"VirtualAlloc")
        with self.assertRaises(PermissionError):C.string_at(1,2)
    def test_23_callbacks_and_unbounded_wait_not_enabled(self):
        calls=[]
        item=self.lock(on_acquired=lambda fd:calls.append(fd))
        with self.assertRaises(Denied):item.acquire(timeout=0)
        self.assertEqual(calls,[])
        item=self.lock()
        with self.assertRaises(Denied):item.acquire()
    def test_24_Guard_network_process_and_operating_port_unchanged(self):
        with socket.socket() as sock:
            with self.assertRaises(PermissionError):sock.connect(("203.0.113.1",443))
        with socket.socket() as sock:
            with self.assertRaises(PermissionError):sock.connect(("127.0.0.1",8765))
        with self.assertRaises(PermissionError):socket.getaddrinfo("synthetic.invalid",443)
        with self.assertRaises(PermissionError):
            subprocess.Popen([str(Path(B.gate.workspace)/"not-approved.exe")])
    def test_25_final_handle_metadata_is_rechecked(self):
        original=B.native.verify
        anchors=set(B.native._owned_handles)
        def reject(handle,path,directory,identity=None):
            if not directory and handle not in anchors:
                raise Denied("synthetic-final-identity-mismatch")
            return original(handle,path,directory,identity)
        B.native.verify=reject
        try:
            with self.assertRaises(Denied):self.lock().acquire(timeout=0)
        finally:B.native.verify=original
        self.assertEqual(len(B.handles),0);self.assertEqual(len(B.fds),0)

    def test_26_actual_default_unlink_success_under_owned_generation(self):
        item=self.lock()
        with self.assertRaises(Denied):B.retire_anchor_for_default_cleanup(self.path)
        item.acquire(timeout=0)
        B.retire_anchor_for_default_cleanup(self.path)
        with self.assertRaises(Denied):B.retire_anchor_for_default_cleanup(self.path)
        before=B.unlink_attempts
        item.release()
        self.assertFalse(item.is_locked)
        self.assertFalse(Path(self.path).exists())
        self.assertGreater(B.unlink_attempts,before)
        alloc=B.allocations
        with self.assertRaises(Denied):self.lock().acquire(timeout=0)
        self.assertEqual(B.allocations,alloc)
