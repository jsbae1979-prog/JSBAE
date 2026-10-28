"""Disposable Windows CI records only; never a first-run or production seeder."""
from pathlib import Path
from datetime import datetime, UTC, timedelta
from hashlib import sha256
from io import BytesIO
import uuid

def seed_management(c, app, root, monkeypatch):
 from test_top3_feed_integration import seed
 from test_core_windows_roundtrip import script_sources
 from test_full_app_forms import token
 from newsflow.db import models as m
 from PIL import Image
 from newsflow.samples.catalog import ROOT
 from newsflow.video import thumbnails
 analysis=seed(app);draft_id,_,_=script_sources(app,analysis)
 raw=c.get('/api/samples/news-short/file').content
 assert raw[4:8]==b'ftyp'
 name='video-'+uuid.uuid4().hex+'.mp4';target=app.state.video.outputs/name;target.write_bytes(raw)
 poster=c.get('/api/samples/news-short/poster').content
 output=BytesIO()
 with Image.open(BytesIO(poster)) as image:image.convert('RGB').save(output,'PNG')
 def synthetic_thumbnail(source,*a):
  assert Path(source).resolve().parent==target.resolve().parent and Path(source).read_bytes()==raw
  return output.getvalue()
 monkeypatch.setattr(thumbnails,'thumbnail',synthetic_thumbnail)
 now=datetime.now(UTC)
 with app.state.sessions.begin() as s:
  project=m.VideoProject(draft_id=draft_id,title='합성 뉴스 미리보기 · 샘플 MP4 참조',duration=12,snapshot={},sources={});s.add(project);s.flush()
  render=m.RenderJob(project_id=project.id,status='success',progress=100,output_name=name,message='Synthetic reference media; no generation API',metadata_json={'playable':True,'duration':12,'synthetic':True});s.add(render);s.flush()
  accounts=[]
  for platform,label in [('instagram','합성 IG 계정 A'),('instagram','합성 IG 계정 B'),('youtube','합성 YouTube 계정')]:
   a=m.PlatformAccount(platform=platform,label=label,account_type='professional_business' if platform=='instagram' else 'youtube_channel',status='not_connected',api_ready=False,credential_ref='synthetic-forbidden-reference');s.add(a);s.flush();accounts.append(a.id)
  draft=m.PublishDraft(render_job_id=render.id,platform='youtube',title='합성 게시 초안',description='실제 게시하지 않는 검증 자료',hashtags=['#합성'],account_id=None,sources={},media_sha256=sha256(raw).hexdigest(),content_reviewed=False,copyright_confirmed=False,sources_confirmed=False,ai_disclosure='unreviewed',revision=1,state='unvalidated');s.add(draft);s.flush()
  s.add(m.PublishJob(draft_id=draft.id,platform='youtube',status='unknown',message='합성 결과 불명 · 재전송 금지',idempotency_key='2'*64))
  for index,account in enumerate(accounts[:2]):
   instagram_draft=m.PublishDraft(render_job_id=render.id,platform='instagram',title='합성 게시 초안',description='실제 게시하지 않는 검증 자료',hashtags=['#합성'],account_id=account,sources={},media_sha256=sha256(raw).hexdigest(),content_reviewed=False,copyright_confirmed=False,sources_confirmed=False,ai_disclosure='unreviewed',revision=1,state='unvalidated')
   s.add(instagram_draft);s.flush()
   job=m.PublishJob(draft_id=instagram_draft.id,platform='instagram',status='success',message='합성 과거 기록 · 실제 SNS 호출 없음',idempotency_key=str(index+3)*64);s.add(job);s.flush()
   s.add(m.SocialMetric(job_id=job.id,account_id=account,platform='instagram',remote_id='synthetic-'+str(index),metric='views',value=str(12+index*23),unit='views',period_start=(now-timedelta(days=2)).date().isoformat(),period_end=now.date().isoformat(),period_basis='synthetic',synthetic=True))
  draft=instagram_draft
  for index in range(3):s.add(m.AIUsage(provider='openai',model='synthetic-model',kind='analysis',status='success',prompt_tokens=100,completion_tokens=20,total_tokens=120,created_at=now-timedelta(days=index)))
  s.add(m.APIRequestReservation(id='d'*32,request_id='synthetic-unknown',provider='openai_api',kind='analysis',model='synthetic-model',status='unknown',reserved_usd='0.5',estimated_usd=None,bounds={},prices={},test_only=True))
  result={'analysis':analysis,'draft':draft.id,'render':render.id,'accounts':accounts,'synthetic':True}
 csrf=token(c)
 for title,hour in [('합성 아침 뉴스','09:00'),('합성 저녁 뉴스','20:00')]:
  response=c.post('/schedules',data={'csrf_token':csrf,'name':title,'kind':'daily','local_time':hour,'source':'sample','duration':'30','platform':'youtube','voice':'offline-silence'})
  assert response.status_code==303,response.text
 schedules=c.get('/api/studio/modules/automation').json()['collections']['schedules']
 result['schedule']=schedules[0]['id']
 from newsflow.gui import operations_routes
 monkeypatch.setattr(operations_routes,'status',lambda request:{'status':'synthetic-unregistered','revision':1,'prepared':False,'message':'합성 상태 조회 · OS 등록/프로세스 호출 없음'})
 return result

def seed_trash_fixture(c,app,session):
 from newsflow.db import models as m
 raw=c.get('/api/samples/news-short/file').content
 name='video-'+uuid.uuid4().hex+'.mp4';(app.state.video.outputs/name).write_bytes(raw)
 from sqlalchemy import select
 existing=session.scalar(select(m.VideoProject).order_by(m.VideoProject.id))
 project=m.VideoProject(draft_id=existing.draft_id,title='휴지 보관 전용 합성 영상',duration=12,snapshot={},sources={});session.add(project);session.flush()
 render=m.RenderJob(project_id=project.id,status='success',progress=100,output_name=name,message='Synthetic unlinked reference',metadata_json={'playable':True,'duration':12,'synthetic':True});session.add(render);session.flush()
 return {'render':render.id}
