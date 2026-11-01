"""Isolated DB/files, no real key, HTTP or image generation."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from PIL import Image
import pytest
from starlette.testclient import TestClient
from newsflow.db.models import IntelligenceRun
from newsflow.publishing.image_generation import ImageGenerationService
from newsflow.publishing.service import PublishingError
from bat_distribution.operation import OperatingRequests
from test_top_three_selection import feeds
from test_feed_costs import ready, approve

def terminal_image(service, identifier, *, status='success', attempt=1, bad_hash=False):
    row=service.get(identifier);source=row.evidence['sources'][0]
    with service.sessions.begin() as s:
        generated=IntelligenceRun(kind='feed_image',provider='openai',status=status,
            options={'article_id':source['article_id'],'analysis_id':row.evidence['analysis_id'],'rank':1},
            evidence={'source':{'batch_id':identifier,'rank':1,'attempt':attempt}},result={},message='Synthetic result')
        s.add(generated);s.flush();gid=generated.id
        raw=BytesIO();Image.new('RGB',(32,40),'blue').save(raw,'JPEG');raw=raw.getvalue()
        service.generation.outputs.mkdir(parents=True,exist_ok=True)
        name=f'generated-{gid}.jpg';(service.generation.outputs/name).write_bytes(raw)
        generated.result={'filename':name,'sha256':'0'*64 if bad_hash else sha256(raw).hexdigest()}
    return gid

@pytest.mark.parametrize('initial',['unknown','running'])
def test_recover_saved_success_without_provider_or_new_reservation(feeds,app,initial):
    from newsflow.creation.catalog import DEFAULTS
    i=feeds.create(42,DEFAULTS['image']);feeds.generation=ImageGenerationService(feeds.sessions,app.state.config.data_dir,None)
    feeds.generation._generate=lambda *a,**k:pytest.fail('No paid generation')
    gid=terminal_image(feeds,i)
    row=feeds.get(i);result=deepcopy(row.result);result['items'][0].update(status=initial,message='preserve failure')
    feeds._save(i,result);original=deepcopy(feeds.get(i).options)
    feeds.change(i,result['revision'],'recover')
    row=feeds.get(i);item=row.result['items'][0]
    assert item['status']=='success' and item['generation_id']==gid
    assert item['recovery_history'][0]['message']=='preserve failure'
    assert feeds.path(i,1).is_file() and row.options==original
    unchanged=deepcopy(row.result);feeds.change(i,row.result['revision'],'recover')
    assert feeds.get(i).result==unchanged

@pytest.mark.parametrize('case',['missing','wrong_attempt','bad_hash','ambiguous','provider_unknown'])
def test_uncertain_or_mismatched_evidence_never_becomes_success(feeds,app,case):
    from newsflow.creation.catalog import DEFAULTS
    i=feeds.create(42,DEFAULTS['image']);feeds.generation=ImageGenerationService(feeds.sessions,app.state.config.data_dir,None)
    feeds.generation._generate=lambda *a,**k:pytest.fail('No paid generation')
    if case!='missing':terminal_image(feeds,i,attempt=2 if case=='wrong_attempt' else 1,bad_hash=case=='bad_hash',status='unknown' if case=='provider_unknown' else 'success')
    if case=='ambiguous':terminal_image(feeds,i)
    row=feeds.get(i);r=deepcopy(row.result);r['items'][0].update(status='unknown',message='original failure')
    feeds._save(i,r);feeds.change(i,r['revision'],'recover')
    assert feeds.get(i).result==r
    with pytest.raises(PublishingError):feeds.change(i,r['revision'],'regenerate',rank=1,consent=True,reviewed=True)

def test_status_get_and_repeated_preparation_preserve_approval(app,ready):
    s,i,calls=ready;approve(s,i);before=deepcopy(s.get(i).options)
    with TestClient(OperatingRequests(app),base_url='http://127.0.0.1:18779') as c:
        c.get('/studio/images');rev=s.get(i).result['revision']
        response=c.get(f'/api/feed-batches/{i}/cost-review')
        assert response.status_code==200 and response.json()['costReview']['approved']
        assert s.get(i).result['revision']==rev and s.get(i).options==before
        assert c.post(f'/api/feed-batches/{i}/cost-review',data={'revision':rev,'csrf_token':c.cookies.get('newsflow_csrf')}).status_code==200
        assert s.get(i).options==before
    assert not calls

def test_expired_quote_does_not_prevent_local_regeneration(app,ready):
    s,i,calls=ready;approve(s,i);s.step(i,consent=True,reviewed=True)
    s.costs.clock=lambda:201
    assert not s.view(i)['canGenerate'] and s.view(i)['canPrepareRegeneration']
    before=deepcopy(s.get(i).result['items'][0])
    with TestClient(OperatingRequests(app),base_url='http://127.0.0.1:18779') as c:
        c.get('/studio/images');row=s.get(i)
        r=c.post(f'/api/feed-batches/{i}/change',data={'revision':row.result['revision'],'action':'regenerate','rank':1,'consent':'true','reviewed':'true','csrf_token':c.cookies.get('newsflow_csrf')})
        assert r.status_code==200,r.text
        assert r.json()['items'][0]['status']=='pending' and not r.json()['canGenerate']
    assert len(calls)==1 and s.get(i).result['items'][0]['history'][0]=={k:v for k,v in before.items() if k!='history'}
    assert s.costs.view(s.get(i))['reservedUsd']=='0.10'

def test_model_edit_requotes_but_does_not_release_exposure(ready):
    s,i,calls=ready;approve(s,i);s.step(i,consent=True,reviewed=True)
    s.change(i,s.get(i).result['revision'],'edit',rank=2,title='New title',body='Reviewed copy')
    assert not s.view(i)['canGenerate']
    s.cost_review(i,s.get(i).result['revision'])
    assert s.costs.view(s.get(i))['reservedUsd']=='0.10' and not s.view(i)['canGenerate']

@pytest.mark.parametrize('configured,verified,match',[(False,False,True),(True,False,True),(True,True,False),(True,True,True)])
def test_production_readiness_is_wired_and_never_claims_a_quote(app,monkeypatch,configured,verified,match):
    from newsflow.creation.catalog import DEFAULTS
    readiness=app.state.top_three_feeds.costs.readiness
    assert readiness is not None
    monkeypatch.setattr(readiness.connections,'status',lambda *args:{'configured':configured,'verified':verified,'modelVerified':verified,'model':DEFAULTS['image']['model'] if match else 'other-model'})
    r=readiness(DEFAULTS['image'])
    assert r['modelVerified']==(configured and verified and match)
    assert not r['costBoundVerified'] and not r['generationEnabled']
    assert not r['rateReference']['guaranteedMaximum']
