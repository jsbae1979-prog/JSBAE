"""New local-runner boundary contracts; no app, native DLL, live network or CI spoof."""
import os
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
import sys
import importlib.util
# Only definitions are loaded for pure contract tests; no Guard/native install.
# The app runner always stages the same pinned gate before Guard-first startup.
gate_source=Path(__file__).resolve().parent.parent/'native_app_policy/verification_gate_app.py'
if gate_source.is_file() and 'verification_gate' not in sys.modules:
    spec=importlib.util.spec_from_file_location('verification_gate',gate_source)
    gate=importlib.util.module_from_spec(spec);sys.modules['verification_gate']=gate;spec.loader.exec_module(gate)
from local_policy import WindowsLocalPolicy, Denied

class LocalRunnerBoundary(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='newsflow-local-policy-')
        self.root=Path(self.temp.name);self.p=WindowsLocalPolicy(self.root,[])
    def tearDown(self):self.temp.cleanup()
    def test_fixed_port_excludes_operating_port(self):
        with self.assertRaises(Denied):WindowsLocalPolicy(self.root,[],8765)
    def test_synthetic_write_only(self):
        self.assertTrue(self.p.path(self.root/'draft.json',True).endswith('draft.json'))
        with self.assertRaises(Denied):self.p.path(self.root.parent/'external-not-opened.txt',True)
    def test_secret_file_rejected(self):
        with self.assertRaises(Denied):self.p.path(self.root/'synthetic-only.dpapi')
    def test_owned_listener_only(self):
        sock=SimpleNamespace(family=socket.AF_INET,type=socket.SOCK_STREAM)
        self.p.register_listener(sock);self.p.network('socket.bind',(sock,('127.0.0.1',18765)))
        other=SimpleNamespace(family=socket.AF_INET,type=socket.SOCK_STREAM)
        with self.assertRaises(Denied):self.p.network('socket.bind',(other,('127.0.0.1',18765)))
    def test_dns_never_executed(self):
        with self.assertRaises(Denied):self.p.audit('socket.getaddrinfo',('example.invalid',443,0,0,0))
    def test_arbitrary_process_never_executed(self):
        with self.assertRaises(Denied):self.p.audit('subprocess.Popen',('not-executed.exe',[],None,None))
    def test_caught_permission_error_prevents_next_phase(self):
        try:self.p.audit('os.symlink',('synthetic-target','synthetic-link'))
        except PermissionError:pass
        with self.assertRaisesRegex(Denied,'stops-before-next-phase'):self.p.checkpoint()
        self.assertTrue(self.p.halt)
        self.assertTrue(self.p.denials[0]['frames'])
    def test_guard_rejection_prevents_ready_even_when_library_returns(self):
        with self.assertRaises(Denied):self.p.checkpoint(['synthetic-rejection'],{})
        self.assertTrue(self.p.halt)
if __name__=='__main__':unittest.main(verbosity=2)
