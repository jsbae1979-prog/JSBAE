"""Synthetic ASGI/update contracts only, no app factory, native state or real keys."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from newsflow.distribution.local_access import LaunchSession,LocalAccess
from newsflow.distribution.updates import validate_update,UpdateBlocked

WORK=Path(os.environ['NEWSFLOW_DISTRIBUTION_TEST_ROOT']).resolve()
if os.name!='nt' or sys.version_info[:3]!=(3,14,7) or not WORK.is_dir():
    raise RuntimeError('Owned Windows Python3.14.7 workspace required')


class AccessContract(unittest.TestCase):
    def setUp(self):
        self.now=0
        self.session=LaunchSession(49152,clock=lambda:self.now)
        self.calls=[]
        async def inner(scope,receive,send):
            self.calls.append(scope)
            # Contract sentinel: outer gate must not replace inner CSRF/Origin.
            status=403 if scope['method']=='POST' else 200
            await send({'type':'http.response.start','status':status,'headers':[(b'x-inner-csrf',b'unchanged')]})
            await send({'type':'http.response.body','body':b'inner'})
        self.gate=LocalAccess(inner,self.session)
    def request(self,path='/api/samples',method='GET',headers=None,peer='127.0.0.1',query=b''):
        fields=[(b'host',b'127.0.0.1:49152')]+[(k.encode(),v.encode('latin1')) for k,v in (headers or {}).items()]
        scope={'type':'http','path':path,'method':method,'query_string':query,'headers':fields,'client':(peer,12345)}
        out=[]
        async def receive():return {'type':'http.request','body':b'','more_body':False}
        async def send(value):out.append(value)
        asyncio.run(self.gate(scope,receive,send))
        return out
    def login(self):
        token=self.session.launch_url().split('#')[1]
        out=self.request('/__local/claim','POST',{'origin':self.session.origin,'x-newsflow-bootstrap':token})
        self.assertEqual(out[0]['status'],204)
        cookie=dict(out[0]['headers'])[b'set-cookie'].decode()
        return cookie.split(';')[0]
    def test_unauthenticated_data_static_and_media_denied(self):
        for path in ['/api/samples','/static/x.js','/api/samples/news-short/file','/studio/dashboard']:
            self.assertEqual(self.request(path)[0]['status'],403)
        self.assertEqual(self.calls,[])
    def test_wrong_other_user_cookie_denied(self):
        foreign=LaunchSession(49152)
        self.assertEqual(self.request(headers={'cookie':f'{self.session.cookie_name}={foreign._session}'})[0]['status'],403)
    def test_claim_cookie_flags_and_data_access(self):
        cookie=self.login()
        out=self.request(headers={'cookie':cookie})
        self.assertEqual(out[0]['status'],200);self.assertEqual(len(self.calls),1)
    def test_bootstrap_one_time(self):
        token=self.session.launch_url().split('#')[1];self.login()
        self.assertEqual(self.request('/__local/claim','POST',{'origin':self.session.origin,'x-newsflow-bootstrap':token})[0]['status'],403)
    def test_expired_bootstrap_denied(self):
        token=self.session.launch_url().split('#')[1];self.now=121
        self.assertEqual(self.request('/__local/claim','POST',{'origin':self.session.origin,'x-newsflow-bootstrap':token})[0]['status'],403)
    def test_session_expires_and_restart_invalidates(self):
        cookie=self.login();self.now=43201
        self.assertEqual(self.request(headers={'cookie':cookie})[0]['status'],403)
        self.assertFalse(LaunchSession(49152).valid_cookie(cookie))
    def test_cookie_is_httponly_same_site_and_port_named(self):
        token=self.session.launch_url().split('#')[1]
        out=self.request('/__local/claim','POST',{'origin':self.session.origin,'x-newsflow-bootstrap':token})
        value=dict(out[0]['headers'])[b'set-cookie'].decode()
        for bit in ['nf_local_49152=','HttpOnly','SameSite=Strict','Path=/']:
            self.assertIn(bit,value)
        self.assertNotIn('Domain=',value)
    def test_cross_origin_claim_and_write_denied(self):
        token=self.session.launch_url().split('#')[1]
        self.assertEqual(self.request('/__local/claim','POST',{'origin':'https://outside.invalid','x-newsflow-bootstrap':token})[0]['status'],403)
        cookie=self.login()
        self.assertEqual(self.request(method='POST',headers={'cookie':cookie})[0]['status'],403)
        self.assertEqual(self.calls,[])
    def test_inner_csrf_remains_required(self):
        out=self.request(method='POST',headers={'cookie':self.login(),'origin':self.session.origin})
        self.assertEqual(out[0]['status'],403);self.assertEqual(dict(out[0]['headers'])[b'x-inner-csrf'],b'unchanged')
    def test_foreign_peer_and_cross_site_denied(self):
        self.assertEqual(self.request(peer='192.0.2.1')[0]['status'],403)
        self.assertEqual(self.request(headers={'sec-fetch-site':'cross-site'})[0]['status'],403)
    def test_wrong_host_duplicate_host_denied(self):
        self.assertEqual(self.request(headers={'host':'localhost:49152'})[0]['status'],403)
    def test_token_in_query_not_accepted_or_echoed(self):
        secret=self.session.launch_url().split('#')[1]
        out=self.request(query=('token='+secret).encode())
        self.assertEqual(out[0]['status'],403);self.assertNotIn(secret.encode(),out[1]['body'])
    def test_claim_body_and_non_ascii_token_rejected(self):
        self.assertEqual(self.request('/__local/claim','POST',{'origin':self.session.origin,'content-length':'1'})[0]['status'],413)
        self.assertIsNone(self.session.claim('é'*43))
    def test_competing_bootstrap_has_single_winner(self):
        token=self.session.launch_url().split('#')[1]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(self.session.claim,[token]*8))
        self.assertEqual(sum(x is not None for x in results),1)
    def test_bootstrap_page_contains_no_secret(self):
        out=self.request('/__local/connect');body=out[1]['body']
        self.assertNotIn(self.session._bootstrap.encode(),body)
        self.assertNotIn(self.session._session.encode(),body)
    def test_operating_port_not_allowed(self):
        with self.assertRaises(ValueError):LaunchSession(8765)


class UpdateContract(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=WORK,prefix='update-case-')
        self.root=Path(self.temp.name)
        self.artifact=self.root/'NewsFlowAI-Setup.exe';self.artifact.write_bytes(b'SYNTHETIC-NOT-AN-EXE')
        self.file=self.root/'manifest.ps1'
        self.manifest={'appId':'NewsFlowAI','channel':'stable','sequence':2,'version':'1.0.1','file':self.artifact.name,'sha256':hashlib.sha256(self.artifact.read_bytes()).hexdigest(),'bytes':self.artifact.stat().st_size}
        self.trust={'updatesEnabled':True,'channel':'stable','publisherCertificateSha256':'a'*64}
        self.fake=lambda p:{'status':'Valid','certificateSha256':'a'*64,'timestamped':True,'codeSigning':True}
        self.write()
    def tearDown(self):
        if self.root.resolve().parent!=WORK:raise RuntimeError('Wrong cleanup root')
        self.temp.cleanup()
    def write(self):
        blob=base64.b64encode(json.dumps(self.manifest).encode()).decode()
        self.file.write_text('# NewsFlow-Update-Manifest-v1\n# '+blob+'\n# SIG # Begin signature block\n# TEST-STUB-NOT-A-SIGNATURE\n',encoding='ascii')
    def check(self,**kwargs):return validate_update(self.file,self.artifact,self.trust,1,verifier=kwargs.get('verifier',self.fake))
    def test_synthetic_valid_shape_only(self):self.assertEqual(self.check()['sequence'],2)
    def test_missing_publisher_blocks_before_verifier(self):
        self.trust['publisherCertificateSha256']=''
        with self.assertRaises(UpdateBlocked):self.check(verifier=lambda p:self.fail('must not verify without pin'))
    def test_updates_disabled(self):
        self.trust['updatesEnabled']=False
        with self.assertRaises(UpdateBlocked):self.check()
    def test_wrong_publisher_rejected(self):
        with self.assertRaises(UpdateBlocked):self.check(verifier=lambda p:{**self.fake(p),'certificateSha256':'b'*64})
    def test_unsigned_rejected(self):
        with self.assertRaises(UpdateBlocked):self.check(verifier=lambda p:{'status':'NotSigned'})
    def test_missing_timestamp_rejected(self):
        with self.assertRaises(UpdateBlocked):self.check(verifier=lambda p:{**self.fake(p),'timestamped':False})
    def test_wrong_eku_rejected(self):
        with self.assertRaises(UpdateBlocked):self.check(verifier=lambda p:{**self.fake(p),'codeSigning':False})
    def test_tampered_payload_rejected(self):
        self.artifact.write_bytes(b'CHANGED')
        with self.assertRaises(UpdateBlocked):self.check()
    def test_rollback_and_replay_rejected(self):
        for seq in [0,1]:
            self.manifest['sequence']=seq;self.write()
            with self.assertRaises(UpdateBlocked):self.check()
    def test_wrong_channel_rejected(self):
        self.manifest['channel']='beta';self.write()
        with self.assertRaises(UpdateBlocked):self.check()
    def test_script_never_executed(self):
        self.file.write_text('Write-Output dangerous\n'+self.file.read_text())
        with self.assertRaises(UpdateBlocked):self.check()
        self.assertFalse((self.root/'highest-sequence.json').exists())
    def test_validation_does_not_advance_install_state(self):
        before={p.name:p.read_bytes() for p in self.root.iterdir()};self.check()
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})

if __name__=='__main__':
    class Result(unittest.TextTestResult):
        def __init__(self,*a,**k):super().__init__(*a,**k);self.passed=[]
        def addSuccess(self,t):self.passed.append(t.id());super().addSuccess(t)
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (AccessContract,UpdateContract)])
    r=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
    (WORK/'boundary-results.json').write_text(json.dumps({'scope':'Synthetic ASGI and stub-signature update validator; not real app/OS-user/signature proof','Python':sys.version.split()[0],'pass':len(r.passed),'fail':len(r.failures),'error':len(r.errors),'skip':len(r.skipped),'passed_ids':r.passed,'failures':[{'id':t.id(),'traceback':s} for t,s in r.failures+r.errors]},indent=2),encoding='utf8')
    raise SystemExit(0 if r.wasSuccessful() else 1)
