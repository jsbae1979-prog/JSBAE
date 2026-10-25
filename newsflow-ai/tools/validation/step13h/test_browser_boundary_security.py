from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import threading
import pytest
import browser_boundary as b

@pytest.mark.parametrize('url',["http://127.0.0.1/","http://127.0.0.1:8765/","http://localhost:18765/","https://127.0.0.1:18765/","http://127.0.0.1:18765@other.invalid/","file:///C:/private","https://example.invalid/"])
def test_real_network_policy_remains_exact_localhost18765(url):
 assert not b.safe_url(url)
def test_localhost_network_is_distinct_from_virtual_fulfillment():
 assert b.safe_url('http://127.0.0.1:18765/fake')
 assert not b.safe_url('http://127.0.0.1/fake')

def node_env():return {'NODE_OPTIONS':'--require="'+b.Path(b.B['preload']).as_posix()+'"'}
def test_exact_node_contract_validated_without_spawning():
 assert b.validate_node(None,[b.B['node'],b.B['cli'],'run-driver'],b.R,node_env())[-1]=='run-driver'
@pytest.mark.parametrize('tail',[['-e','process.exit()'],['other.js'],['run-driver','--shell']])
def test_arbitrary_node_entry_denied(tail):
 with pytest.raises(b.BoundaryViolation):b.validate_node(None,[b.B['node'],*tail],b.R,node_env())
def test_node_credentials_are_rejected_without_use():
 with pytest.raises(b.BoundaryViolation):b.validate_node(None,[b.B['node'],b.B['cli'],'run-driver'],b.R,dict(node_env(),TEST_API_KEY='synthetic'))
def test_modified_preload_hash_is_denied(monkeypatch):
 monkeypatch.setitem(b.B,'preload_SHA256','0'*64)
 with pytest.raises(b.BoundaryViolation):b.validate_node(None,[b.B['node'],b.B['cli'],'run-driver'],b.R,node_env())
def test_virtual_mock_origin_cannot_continue_to_a_socket():
 from playwright.sync_api import Route
 fake=SimpleNamespace(request=SimpleNamespace(url='http://127.0.0.1/create'))
 with pytest.raises(b.BoundaryViolation):Route.continue_(fake)
 with pytest.raises(b.BoundaryViolation):Route.fallback(fake)
def test_owned_thread_identity_does_not_exempt_a_same_named_app_thread(monkeypatch):
 event=threading.Event();ex=ThreadPoolExecutor(max_workers=1,thread_name_prefix='asyncio');future=ex.submit(event.wait)
 unknown=threading.Thread(target=event.wait,name='asyncio_0');unknown.start()
 loop=SimpleNamespace(_default_executor=ex);monkeypatch.setattr(b,'PLAYWRIGHT_LOOPS',[loop])
 try:
  owned=b.browser_owned_threads()
  assert owned and unknown not in owned
  assert all(t in ex._threads for t in owned)
 finally:
  event.set();unknown.join(3);ex.shutdown(wait=True,cancel_futures=True)
 assert not unknown.is_alive() and all(not t.is_alive() for t in ex._threads)
