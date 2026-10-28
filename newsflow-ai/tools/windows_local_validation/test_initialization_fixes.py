"""Focused new contracts only. No native DLL/app/network/link operation executes."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
gate_source=Path(__file__).resolve().parent.parent/'native_app_policy/verification_gate_app.py'
if 'verification_gate' not in sys.modules:
    spec=importlib.util.spec_from_file_location('verification_gate',gate_source)
    gate=importlib.util.module_from_spec(spec);sys.modules['verification_gate']=gate;spec.loader.exec_module(gate)
from local_policy import WindowsLocalPolicy,Denied
from runtime_fixes import bounded_import_paths,OptionalLinkProbe,install_optional_probe

class InitializationFixes(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(prefix='newsflow-startup-fix-');self.root=Path(self.folder.name)
        self.policy=WindowsLocalPolicy(self.root,[]);self.source=str(self.root/'_strict.py')
        self.first=self.root/'Temp'/'probe-one'/'probe-source';self.first.parent.mkdir(parents=True);self.first.write_text('synthetic')
        self.second=self.first.with_name('probe-link')
        self.frame=NS(f_globals={'__name__':'filelock._strict'},f_code=NS(co_name='_probe_link_follow_symlinks',co_filename=self.source))
    def tearDown(self):self.folder.cleanup()
    def test_only_bounded_import_search_roots_remain(self):
        entries=[r'C:\test\runtime\Lib',r'C:\test\runtime\Lib\site-packages',r'C:\old\candidate\src']
        self.assertEqual(bounded_import_paths(entries,[r'C:\test\runtime']),entries[:2])
    def test_synthetic_file_read_is_unchanged(self):
        self.policy.audit('open',(str(self.first),'r',0));self.assertEqual(self.first.read_text(),'synthetic')
    def test_exact_optional_probe_creates_no_link(self):
        calls=[];hook=OptionalLinkProbe(self.policy,self.source,lambda *a,**k:calls.append(a))
        with self.assertRaises(NotImplementedError):hook.invoke(self.frame,self.first,self.second,(),{'follow_symlinks':False})
        self.assertEqual(calls,[]);self.assertEqual(hook.suppressed,1);self.assertFalse(self.second.exists());self.assertFalse(self.policy.halt)
    def test_arbitrary_link_still_reaches_guard_rejection(self):
        def guarded(source,target,*a,**k):self.policy.audit('os.link',(source,target,-1,-1))
        hook=OptionalLinkProbe(self.policy,self.source,guarded)
        other=NS(f_globals={'__name__':'other'},f_code=self.frame.f_code)
        with self.assertRaises(Denied):hook.invoke(other,self.first,self.second,(),{})
        self.assertTrue(self.policy.halt);self.assertEqual(hook.suppressed,0);self.assertFalse(self.second.exists())
    def test_probe_cannot_touch_outside_path(self):
        hook=OptionalLinkProbe(self.policy,self.source,lambda *a,**k:self.fail('Real link called'))
        with self.assertRaises(Denied):hook.invoke(self.frame,self.root.parent/'probe-source',self.root.parent/'probe-link',(),{'follow_symlinks':False})
        self.assertTrue(self.policy.halt)
    def test_operating_path_rejected_without_reading_it(self):
        path=r'C:\Codex\NewsFlowAI\not-opened.db'
        self.assertEqual(self.policy.describe_path(path),'<OPERATING_PROTECTED>')
        with self.assertRaises(Denied):self.policy.path(path)
    def test_source_mismatch_does_not_replace_link_function(self):
        package=self.root/'package';package.mkdir();(package/'_strict.py').write_text('unreviewed synthetic source')
        original=os.link
        with self.assertRaisesRegex(RuntimeError,'Unreviewed'):install_optional_probe(self.policy,package)
        self.assertIs(os.link,original)
    def test_external_read_rejection_stops_next_phase(self):
        try:self.policy.audit('open',(str(self.root.parent/'outside-not-opened.txt'),'r',0))
        except Denied:pass
        with self.assertRaisesRegex(Denied,'stops-before-next-phase'):self.policy.checkpoint()
if __name__=='__main__':unittest.main(verbosity=2)
