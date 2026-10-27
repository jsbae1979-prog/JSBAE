"""New TOP3 forms through the real app; only disposable Windows Actions may run this."""
from copy import deepcopy
from io import BytesIO
import importlib.util
from pathlib import Path
import pytest
from test_full_app_forms import client as client, token


def seed(app):
    path=Path(__file__).resolve().parents[2]/"feed_top3/tests/test_top_three_feeds.py"
    spec=importlib.util.spec_from_file_location("top3_synthetic_fixture",path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    # Insert synthetic rows with the app DB's own IDs; preserve its initial RSS presets.
    e=mod.setup(app.state.config.data_dir, sessions=app.state.sessions)
    from newsflow.creation.top_three_feeds import TopThreeFeeds,LocalFeedPreviewAdapter
    from types import SimpleNamespace as NS
    app.state.image_generation.adapter=LocalFeedPreviewAdapter()
    app.state.image_generation.keys=NS(key=lambda:"synthetic-top3-key",status=lambda:{"configured":True})
    app.state.top_three_feeds=TopThreeFeeds(app.state.sessions,app.state.config.data_dir,app.state.image_generation,simulation=True)
    return e.analysis_id


def test_top3_json_forms_fake_output_review_and_csrf_boundaries(client):
 c,app=client;aid=seed(app);csrf=token(c)
 from newsflow.creation.catalog import DEFAULTS
 payload={"analysis_id":aid,**DEFAULTS["image"]}
 assert c.post("/api/feed-batches",data=payload).status_code==403
 assert c.post("/api/feed-batches",data={**payload,"csrf_token":csrf},headers={"Origin":"https://outside.invalid"}).status_code==403
 r=c.post("/api/feed-batches",data={**payload,"csrf_token":csrf});assert r.status_code==200,r.text
 batch=r.json();b=batch["id"]
 assert batch["plannedImages"]==3 and batch["items"][0]["source"]["draft_id"]
 assert c.post(f"/api/feed-batches/{b}/step",data={"csrf_token":csrf}).status_code==422
 for _ in range(3):
  r=c.post(f"/api/feed-batches/{b}/step",data={"csrf_token":csrf,"consent":"true","reviewed":"true"});assert r.status_code==200,r.text
 assert len(app.state.image_generation.adapter.calls)==3
 for item in r.json()["items"]:
  media=c.get(item["mediaUrl"]);assert media.status_code==200
  from PIL import Image
  with Image.open(BytesIO(media.content)) as img:assert img.size==(1080,1350)
  assert c.post(f"/api/feed-batches/{b}/items/{item['rank']}/review",data={"csrf_token":csrf,"reviewed":"true","rights":"true","sources_confirmed":"true","ai_disclosure":"disclose"}).status_code==422
 assert c.get('/api/feed-batches/999999/items/1/file').status_code==404
 assert c.post(f"/api/feed-batches/{b}/step",data={"csrf_token":csrf,"consent":"true","reviewed":"true"}).status_code==200
 assert len(app.state.image_generation.adapter.calls)==3
 assert "unsafe-inline" not in c.get('/studio/images').headers['Content-Security-Policy']


def test_top3_defaults_independent_and_real_unquoted_execution_blocked(client):
 c,app=client;aid=seed(app);csrf=token(c)
 from newsflow.creation.catalog import DEFAULTS
 initial=c.get('/api/studio/modules/images').json()['catalog']['imageDefaults']
 choice={**DEFAULTS['image'],'quality':'high'}
 assert c.post('/api/feed-batches/defaults',data={**choice,'csrf_token':csrf}).status_code==200
 assert c.get('/api/feed-batches').json()['defaults']==choice
 assert c.get('/api/studio/modules/images').json()['catalog']['imageDefaults']==initial
 # Constructor-only test mode cannot be enabled by submitting a form field.
 from newsflow.creation.top_three_feeds import TopThreeFeeds
 app.state.top_three_feeds=TopThreeFeeds(app.state.sessions,app.state.config.data_dir,app.state.image_generation)
 b=c.post('/api/feed-batches',data={**choice,'analysis_id':aid,'csrf_token':csrf,'simulation':'true'}).json()
 assert b['simulation'] is False and b['canGenerate'] is False
 assert c.post(f"/api/feed-batches/{b['id']}/step",data={'csrf_token':csrf,'consent':'true','reviewed':'true','simulation':'true','estimated_cost':'0.01'}).status_code==422
 assert not app.state.image_generation.adapter.calls
