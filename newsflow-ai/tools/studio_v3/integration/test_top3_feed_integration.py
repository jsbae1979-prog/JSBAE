"""New TOP3 forms through the real app; only disposable Windows Actions may run this."""
import importlib.util
from io import BytesIO
from pathlib import Path

from test_full_app_forms import client, token

__all__ = ["client"]


def seed(app):
    path=Path(__file__).resolve().parents[2]/"feed_top3/tests/test_top_three_feeds.py"
    spec=importlib.util.spec_from_file_location("top3_synthetic_fixture",path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    # Insert synthetic rows with the app DB's own IDs; preserve its initial RSS presets.
    e=mod.setup(app.state.config.data_dir, sessions=app.state.sessions)
    from types import SimpleNamespace as NS

    from newsflow.creation.top_three_feeds import LocalFeedPreviewAdapter, TopThreeFeeds
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


def test_top3_reviewed_local_post_matches_preview_and_is_idempotent(client):
 c,app=client;aid=seed(app);csrf=token(c)
 from sqlalchemy import select

 from newsflow.creation.catalog import DEFAULTS
 from newsflow.db.models import ImagePostDelivery, IntelligenceRun
 b=c.post('/api/feed-batches',data={**DEFAULTS['image'],'size':'1024x1024','analysis_id':aid,'csrf_token':csrf}).json()['id']
 assert c.post(f'/api/feed-batches/{b}/step',data={'csrf_token':csrf,'consent':'true','reviewed':'true'}).status_code==200
 # A synthetic, already-completed production-shaped record tests only local review/storage.
 # No generation becomes available and no real key/adapter is installed.
 with app.state.sessions.begin() as s:
  row=s.get(IntelligenceRun,b);row.options={**row.options,'simulation':False}
 path=f'/api/feed-batches/{b}/items/1/review'
 assert c.post(path,data={'csrf_token':csrf}).status_code==422
 assert c.post(path,data={'csrf_token':csrf,'reviewed':'true','rights':'true','sources_confirmed':'true'}).status_code==422
 body={'csrf_token':csrf,'reviewed':'true','rights':'true','sources_confirmed':'true','ai_disclosure':'disclose'}
 first=c.post(path,data=body);assert first.status_code==200,first.text
 second=c.post(path,data=body);assert second.status_code==200,second.text
 assert first.json()['postId']==second.json()['postId'] and first.json()['published'] is False
 post_id=first.json()['postId']
 assert c.get(f'/image-posts/{post_id}/file').content==c.get(f'/api/feed-batches/{b}/items/1/file').content
 assert 'AI 생성 이미지' in c.get(f'/image-posts/{post_id}/caption').text
 with app.state.sessions() as s:assert not list(s.scalars(select(ImagePostDelivery)))
 assert len(app.state.image_generation.adapter.calls)==1
