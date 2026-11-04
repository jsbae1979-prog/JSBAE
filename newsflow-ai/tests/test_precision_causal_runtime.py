from types import SimpleNamespace as NS
import pytest
from test_precision_causal import causal,submitted,accept
from test_character_precision import precision
from newsflow.character.schema import CharacterError
from newsflow.video.ai.keys import VideoAIKeyStore
from bat_distribution import character_manual_execution as runtime
from test_precision_operating_access import connected

def test_causal_story_passes_exact_runtime_authoring_boundary(connected):
    c=connected;causal(c.p)
    response=c.request('story',revision=1,consent='true')
    assert response.status_code==200 and response.json()['state']=='images'
    assert len(c.state.calls)==1
    assert 'prop_states' in str(c.state.calls[0])

@pytest.mark.parametrize('cut',[False,True])
def test_runtime_scope_preserves_review_and_single_dispatch(precision,monkeypatch,cut):
    p=causal(precision)
    if cut:p.story['scenes'][1].update(connection='cut',transition_reason='Establish table from new angle')
    jid=submitted(p);root=p.s.root.parent
    (root/VideoAIKeyStore.FILE).write_bytes(b'synthetic-cipher')
    class Native:
        def unprotect(self,*args):return bytearray(b'synthetic-only')
    monkeypatch.setattr(runtime,'KlingClient',lambda *a,**kw:p.video)
    scope=runtime.ManualExecution(p.owner,root,Native)
    def check():
        token=runtime._REQUEST.set((scope,jid,'check'))
        try:scope.execute('check',jid,consent=True)
        finally:runtime._REQUEST.reset(token)
    check();check();assert len(p.video.sent)==1
    accept(p,jid);check();assert len(p.video.sent)==2
    check();assert len(p.video.sent)==2
    assert p.owner.read(jid)['state']=='scene_review'

def test_failed_clip_quote_still_available_with_review_waiting_cut(precision,monkeypatch):
    p=causal(precision)
    p.story['scenes'][1].update(connection='cut',transition_reason='Establish same table')
    jid=submitted(p);p.video.fail=True;p.owner.check(jid,consent=True)
    root=p.s.root.parent;(root/VideoAIKeyStore.FILE).write_bytes(b'synthetic-cipher')
    class Native:
        def unprotect(self,*args):return bytearray(b'synthetic-only')
    monkeypatch.setattr(runtime,'KlingClient',lambda *a,**kw:p.video)
    scope=runtime.ManualExecution(p.owner,root,Native)
    token=runtime._REQUEST.set((scope,jid,'retry-quote'))
    try:scope.execute('retry-quote',jid,consent=True)
    finally:runtime._REQUEST.reset(token)
    assert p.owner.read(jid)['state']=='retry_quoted' and len(p.video.sent)==1
