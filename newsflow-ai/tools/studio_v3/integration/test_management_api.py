"""Only the new read metadata and management save/approval contracts; no broad audit."""
from test_sample_content import app_client
from test_full_app_forms import token
from sqlalchemy import select

def test_readonly_settings_metadata_does_not_disclose_secrets(app_client):
 c,app=app_client
 response=c.get('/api/studio/modules/settings');assert response.status_code==200
 d=response.json();assert d['catalog']['storage']['dataDirectory']==str(app.state.config.data_dir)
 assert d['catalog']['storage']['python']=='3.14.7'
 assert all('api_key' not in x and 'key' not in x for x in d.get('services',[]))
 assert 'unsafe-inline' not in c.get('/studio/settings').headers['content-security-policy']

def test_management_metadata_account_period_is_explicit(app_client,tmp_path):
 c,app=app_client
 import pytest
 from management_seed import seed_management
 mp=pytest.MonkeyPatch()
 try:
  meta=seed_management(c,app,tmp_path,mp)
  d=c.get('/api/studio/modules/analytics').json();metrics=d['collections']['metrics']
  assert len(metrics)==2 and {x['account_id'] for x in metrics}==set(meta['accounts'][:2])
  assert all(x['synthetic'] and x['job_id'] and x['period_start'] and x['period_end'] for x in metrics)
  assert 'synthetic-forbidden-reference' not in c.get('/api/studio/modules/publishing').text
  assert d['collections']['requests'][0]['status']=='unknown' and d['collections']['requests'][0]['estimated_usd'] is None
 finally:mp.undo()

def test_schedule_save_is_paused_and_csrf_origin_unchanged(app_client):
 c,_=app_client;csrf=token(c)
 payload={'name':'합성 관리 예약','kind':'daily','local_time':'10:00','source':'sample','duration':'30','platform':'youtube','voice':'offline-silence'}
 assert c.post('/schedules',data=payload).status_code==403
 assert c.post('/schedules',data={**payload,'csrf_token':csrf},headers={'Origin':'https://outside.invalid'}).status_code==403
 assert c.post('/schedules',data={**payload,'csrf_token':csrf}).status_code==303
 saved=c.get('/api/studio/modules/automation').json()['collections']['schedules'][0]
 assert saved['status']=='paused'
 assert saved['source']=='sample' and saved['voice']=='offline-silence'

def test_reading_management_does_not_execute_or_retry_unknown(app_client,tmp_path):
 c,app=app_client
 import pytest
 from newsflow.db.models import APIRequestReservation,PublishAttempt,PublishJob
 from management_seed import seed_management
 mp=pytest.MonkeyPatch()
 try:
  seed_management(c,app,tmp_path,mp)
  for module in ['automation','library','publishing','analytics','settings']:
   assert c.get('/api/studio/modules/'+module).status_code==200
  with app.state.sessions() as s:
   assert s.get(APIRequestReservation,'d'*32).status=='unknown'
   assert not list(s.scalars(select(PublishAttempt)))
   assert any(x.status=='unknown' for x in s.scalars(select(PublishJob)))
  assert c.get('/api/samples').json()['assets'].__len__()==12
 finally:mp.undo()
