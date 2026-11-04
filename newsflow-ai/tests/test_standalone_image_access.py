from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
import pytest
from PIL import Image
from starlette.testclient import TestClient
from newsflow.creation.catalog import DEFAULTS
from newsflow.distribution.local_access import LaunchSession,LocalAccess
from newsflow.intelligence.credentials import FakeCipher, CredentialError
from newsflow.publishing.service import PublishingError
from bat_distribution.operation import OperatingRequests
from bat_distribution.studio_image_access import StudioImageAccess
from test_feed_budget import budget_setup
from test_top_three_selection import feeds
from test_complete_feed import settings

@pytest.fixture
def standalone(app,budget_setup):
    b=budget_setup;settings(b,limit='1');calls=[];response={'error':None}
    class Fake:
        def generate(self,prompt,key,*,selection):
            assert key=='synthetic-feed-image-key-123456789'
            calls.append(deepcopy(selection))
            if response['error']:raise response['error']
            output=BytesIO();Image.new('RGB',tuple(map(int,selection['size'].split('x')))).save(output,'JPEG')
            return output.getvalue(),{'input_tokens':100,'output_tokens':500,'total_tokens':600}
    owner=StudioImageAccess(app,app.state.config.data_dir,lambda:FakeCipher(),adapter=Fake())
    session=LaunchSession(18779);auth=LocalAccess(app,session)
    draft=app.state.image_studio.create('합성 테스트용 파란 배경 그림',DEFAULTS['image'])
    with TestClient(owner.wrap(OperatingRequests(auth),auth),base_url=session.origin,client=('127.0.0.1',43210),follow_redirects=False) as c:
        c.cookies.set(session.cookie_name,session.claim(session.launch_url().split('#')[1]));c.get('/studio/images')
        def post(**changes):
            data={'csrf_token':c.cookies.get('newsflow_csrf'),'consent':'true','reviewed':'true',**changes}
            return c.post(f'/image-studio/{draft}/generate',data=data,headers={'Origin':session.origin})
        yield SimpleNamespace(b=b,owner=owner,client=c,post=post,draft=draft,calls=calls,response=response,studio=app.state.image_studio)

def test_standalone_exact_request_once_and_budget(standalone):
    x=standalone
    assert x.post().status_code==303
    row=x.studio.output(x.draft);assert row.status=='success'
    assert x.owner.generation.path(row.id).is_file()
    state=x.studio.get(x.draft).options['image_budget']
    assert state['limitUsd']=='1' and state['billingStatus']=='usage_calculated' and not state['billingVerified']
    assert x.post().status_code==303 and len(x.calls)==1
    with pytest.raises(CredentialError):x.owner.keys.key()

@pytest.mark.parametrize('case',['no_consent','no_review','bad_csrf','no_session','bad_origin','unverified','unapproved','small_budget','reference','reservation'])
def test_standalone_blocks_without_dispatch(standalone,case):
    x=standalone;changes={}
    if case=='no_consent':changes['consent']='false'
    if case=='no_review':changes['reviewed']='false'
    if case=='bad_csrf':changes['csrf_token']='wrong'
    if case=='no_session':x.client.cookies.clear()
    if case=='unverified':x.b.store.save('changed-synthetic-key-123456789')
    if case=='unapproved':settings(x.b,approved=False)
    if case=='small_budget':settings(x.b,limit='0.001')
    if case=='reference':
        out=BytesIO();Image.new('RGB',(256,256)).save(out,'PNG')
        asset=x.studio.asset_bytes(out.getvalue())
        from newsflow.db.models import IntelligenceRun
        with x.owner.app.state.sessions.begin() as s:
            r=s.get(IntelligenceRun,x.draft);r.options={**r.options,'reference':asset}
    if case=='reservation':x.owner.save(x.draft,{'dispatchState':'sent_or_unknown'})
    if case=='bad_origin':
        r=x.client.post(f'/image-studio/{x.draft}/generate',data={'csrf_token':x.client.cookies.get('newsflow_csrf'),'consent':'true','reviewed':'true'},headers={'Origin':'https://outside.invalid'})
    else:r=x.post(**changes)
    assert r.status_code in {403,422},r.text
    assert not x.calls and x.studio.output(x.draft) is None

@pytest.mark.parametrize('failure',['timeout','failure'])
def test_standalone_failure_never_replays(standalone,failure):
    from newsflow.publishing.image_generation import ImageGenerationError
    x=standalone;x.response['error']=TimeoutError('fake') if failure=='timeout' else ImageGenerationError('fake',uncertain=False,http_status=400)
    assert x.post().status_code==303
    assert x.studio.output(x.draft).status in {'unknown','failed'}
    assert x.post().status_code==303 and len(x.calls)==1
    assert not x.studio.get(x.draft).options['image_budget']['billingVerified']

def test_standalone_other_paths_closed(standalone):
    x=standalone
    for path in [f'/image-studio/{x.draft}/generate/','/api/image-studio/generate','/image-studio/01/generate']:
        assert x.client.post(path).status_code==403
    with pytest.raises(PublishingError):x.owner.generation._generate(None,None,None,'studio',{},'fake')
    assert not x.calls
