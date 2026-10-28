"""Focused argument/default tests; never starts a server or loads real media."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ENTRY=Path(sys.argv.pop(1)).resolve()
ROOT=Path(sys.argv.pop(1)).resolve()

class PackagedEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.bundle=Path(self.temp.name)
        (self.bundle/'media').mkdir()
        pins={}
        for n in ('ffmpeg.exe','ffprobe.exe'):
            (self.bundle/'media'/n).write_bytes(b'SYNTHETIC-NOT-EXECUTABLE')
            pins[n]=hashlib.sha256(b'SYNTHETIC-NOT-EXECUTABLE').hexdigest()
        (self.bundle/'media-integrity.json').write_text(json.dumps(pins),encoding='utf8')
        spec=importlib.util.spec_from_file_location('private_packaged_entry',ENTRY)
        self.entry=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.entry)
        self.run=Mock()
        fake=types.ModuleType('newsflow.distribution.launch')
        fake.run=self.run
        for ctx in (patch.object(sys,'frozen',True,create=True),
                    patch.object(sys,'_MEIPASS',str(self.bundle),create=True),
                    patch.dict(sys.modules,{'newsflow.distribution.launch':fake}),
                    patch.dict(self.entry.os.environ,{},clear=True)):
            ctx.start();self.addCleanup(ctx.stop)

    def invoke(self,args):
        with patch.object(sys,'argv',['candidate.exe',*args]):
            self.entry.main()

    def test_default_keeps_browser_and_authenticated_launcher(self):
        self.invoke([])
        self.run.assert_called_once_with(open_browser=True)

    def test_no_browser_only_changes_browser_opening(self):
        self.invoke(['--no-browser'])
        self.run.assert_called_once_with(open_browser=False)

    def test_console_interrupt_closes_without_bootloader_failure(self):
        self.run.side_effect=KeyboardInterrupt
        self.invoke(['--no-browser'])
        self.run.assert_called_once_with(open_browser=False)

    def test_other_runtime_failure_is_not_hidden(self):
        self.run.side_effect=RuntimeError('SYNTHETIC-STARTUP-FAILURE')
        with self.assertRaisesRegex(RuntimeError,'SYNTHETIC'):
            self.invoke(['--no-browser'])

    def test_unknown_operation_rejected(self):
        with self.assertRaisesRegex(SystemExit,'Unsupported'):
            self.invoke(['--disable-auth'])
        self.run.assert_not_called()

    def test_unfrozen_entry_rejected(self):
        with patch.object(sys,'frozen',False),self.assertRaisesRegex(SystemExit,'Frozen'):
            self.invoke([])
        self.run.assert_not_called()

    def test_no_browser_retains_media_integrity_check(self):
        (self.bundle/'media/ffmpeg.exe').write_bytes(b'TAMPERED')
        with self.assertRaisesRegex(SystemExit,'integrity'):
            self.invoke(['--no-browser'])
        self.run.assert_not_called()

if __name__=='__main__':
    unittest.main()
