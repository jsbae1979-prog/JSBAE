"""Windows synthetic filesystem model, NOT execution of Inno Setup or frozen app."""
import hashlib,json,os,sqlite3,sys,tempfile,unittest
from pathlib import Path

from package_contract import LifecycleModel,inventory,verify,canonical,relative_name
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from newsflow.paths import default_data_dir

WORK=Path(os.environ['NEWSFLOW_INSTALL_CONTRACT_WORKSPACE']).resolve()
if not WORK.is_dir() or os.name!='nt' or sys.version_info[:3]!=(3,14,7):raise RuntimeError('Owned Windows Python3.14.7 test workspace required')

class InstallContract(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='case-',dir=WORK);self.root=Path(self.temp.name)
        self.model=LifecycleModel(self.root/'profile')
        db=sqlite3.connect(self.model.data/'newsflow.db');db.execute('create table synthetic_state(name text primary key,value text)');db.execute('insert into synthetic_state values (?,?)',('sample_content:v1:hidden:character-robot','true'));db.commit();db.close()
        (self.model.data/'settings.json').write_text('{"synthetic":true,"voice":"saved"}')
        (self.model.data/'opaque-key.dpapi').write_bytes(b'NOT-A-REAL-DPAPI-CIPHERTEXT; preservation sentinel only')
        (self.model.data/'user-media.bin').write_bytes(b'SYNTHETIC-USER-CONTENT')
        (self.model.data/'sample-copies').mkdir();(self.model.data/'sample-copies/example.bin').write_bytes(b'USER-COPY')
        self.original=self.data_hashes()
    def tearDown(self):
        if self.root.resolve().parent!=WORK:raise RuntimeError('Cleanup outside owned test workspace')
        self.temp.cleanup()
    def data_hashes(self):return {str(p.relative_to(self.model.data)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.model.data.rglob('*') if p.is_file()}
    def payload(self,version):
        root=self.root/('payload-'+version);root.mkdir()
        (root/'application.bin').write_bytes(('synthetic-payload-'+version).encode())
        (root/'assets').mkdir();(root/'assets/sample.txt').write_text('same read-only sample')
        m={'version':version,'files':inventory(root)};return root,m,hashlib.sha256(canonical(m)).hexdigest()
    def test_new_stage(self):
        p,m,h=self.payload('v1');self.model.install(p,m,h)
        self.assertEqual(self.model.current()['version'],'v1');verify(self.model.program/'v1',m);self.assertEqual(self.data_hashes(),self.original)
    def test_update_preserves_database_key_settings_media_hidden_state(self):
        a,m1,h1=self.payload('v1');b,m2,h2=self.payload('v2')
        self.model.install(a,m1,h1);self.model.install(b,m2,h2)
        self.assertEqual(self.model.current()['version'],'v2');self.assertEqual(self.data_hashes(),self.original)
    def test_interrupted_stage_keeps_previous_pointer_and_cleans_owned_stage(self):
        a,m1,h1=self.payload('v1');b,m2,h2=self.payload('v2');self.model.install(a,m1,h1)
        previous=self.model.current()
        with self.assertRaises(OSError):self.model.install(b,m2,h2,fail_after=1)
        self.assertEqual(self.model.current(),previous);self.assertFalse(list(self.model.program.glob('.staging-*')));self.assertEqual(self.data_hashes(),self.original)
    def test_uninstall_preserves_all_user_data(self):
        p,m,h=self.payload('v1');self.model.install(p,m,h);self.model.uninstall({'v1':m})
        self.assertIsNone(self.model.current());self.assertEqual(self.data_hashes(),self.original)
    def test_reinstall_and_repeated_stage_do_not_duplicate_user_samples(self):
        p,m,h=self.payload('v1');self.model.install(p,m,h);self.model.uninstall({'v1':m});self.model.install(p,m,h);self.model.install(p,m,h)
        self.assertEqual(self.data_hashes(),self.original);self.assertEqual(len(list((self.model.data/'sample-copies').iterdir())),1)
    def test_tampered_manifest_rejected(self):
        p,m,h=self.payload('v1')
        with self.assertRaises(ValueError):self.model.install(p,m,'0'*64)
        self.assertIsNone(self.model.current())
    def test_corrupt_payload_rejected_before_activation(self):
        p,m,h=self.payload('v1');(p/'application.bin').write_text('tampered')
        with self.assertRaises(ValueError):self.model.install(p,m,h)
        self.assertIsNone(self.model.current());self.assertEqual(self.data_hashes(),self.original)
    def test_unknown_program_file_is_not_deleted(self):
        p,m,h=self.payload('v1');self.model.install(p,m,h);extra=self.model.program/'v1/unknown-user-file.txt';extra.write_text('preserve')
        with self.assertRaises(ValueError):self.model.uninstall({'v1':m})
        self.assertTrue(extra.is_file());self.assertEqual(self.data_hashes(),self.original)
    def test_profile_paths_are_separate_not_distinct_windows_principals(self):
        a=default_data_dir('win32',{'LOCALAPPDATA':str(self.root/'A/Local')});b=default_data_dir('win32',{'LOCALAPPDATA':str(self.root/'B/Local')})
        self.assertNotEqual(a,b);self.assertFalse(a.is_relative_to(b));self.assertFalse(b.is_relative_to(a))
    def test_unowned_existing_root_rejected(self):
        p=self.root/'not-owned';p.mkdir()
        with self.assertRaises(ValueError):LifecycleModel(p)
    def test_data_cannot_be_recursive_cleanup_target(self):
        with self.assertRaises(ValueError):self.model._delete_stage(self.model.data)
        self.assertEqual(self.data_hashes(),self.original)
    def test_traversal_unc_ads_and_reserved_paths_rejected(self):
        for value in ('../data/x','/absolute','C:/data','a:b','a\\b','a/../b','a/NUL.txt','a/trailing.','a/trailing '):
            with self.subTest(value=value),self.assertRaises(ValueError):relative_name(value)
    def test_test_guard_database_keys_and_logs_not_payload(self):
        for value in ('tools/x.py','tests/x.py','step13_guard.py','verification_gate.py','native_guard_copy/x.py','user.db','api-key.dpapi','session.key','.env.local','runtime.log'):
            with self.subTest(value=value),self.assertRaises(ValueError):relative_name(value)
if __name__=='__main__':
    class Result(unittest.TextTestResult):
        def __init__(self,*a,**k):super().__init__(*a,**k);self.passed=[]
        def addSuccess(self,test):self.passed.append(test.id());super().addSuccess(test)
    result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(unittest.defaultTestLoader.loadTestsFromTestCase(InstallContract))
    (WORK/'contract-result.json').write_text(json.dumps({'scope':'Synthetic filesystem model, not compiled installer/app/OS multi-user proof','Python':sys.version.split()[0],'pass':len(result.passed),'fail':len(result.failures),'error':len(result.errors),'skip':len(result.skipped),'passed_ids':result.passed,'failures':[{'id':t.id(),'traceback':s} for t,s in result.failures+result.errors]},indent=2),encoding='utf8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
