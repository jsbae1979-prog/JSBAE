from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace as NS
import json
import pytest
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from newsflow.db.models import Base, NewsSource, NewsArticle, IntelligenceRun, ContentDraft, AppSetting
from newsflow.creation.catalog import DEFAULTS, read_defaults
from newsflow.creation.top_three_feeds import TopThreeFeeds, LocalFeedPreviewAdapter, KIND
from newsflow.publishing.image_generation import ImageGenerationService, ImageGenerationError
from newsflow.publishing.service import PublishingError


def setup(tmp_path, *, simulation=True, sessions=None):
 engine=None
 if sessions is None:
  engine=create_engine("sqlite:///:memory:");Base.metadata.create_all(engine)
  sessions=sessionmaker(engine,expire_on_commit=False)
 adapter=LocalFeedPreviewAdapter()
 generation=ImageGenerationService(sessions,tmp_path,NS(key=lambda:"synthetic-top3-key"),adapter=adapter)
 service=TopThreeFeeds(sessions,tmp_path,generation,simulation=simulation)
 with sessions.begin() as s:
  source=NewsSource(name="Synthetic",url="https://example.invalid/rss",enabled=False);s.add(source);s.flush()
  articles=[]
  for n,title in enumerate(["합성 도서관 운영 안내","합성 버스 노선 안내","합성 과학 전시 안내"],1):
   a=NewsArticle(title=title,summary=f"합성 요약 {n}번입니다. 실제 사건이 아닙니다.",publisher="테스트 출처",url=f"https://example.invalid/news/{n}",canonical_url=f"https://example.invalid/news/{n}",source_id=source.id);s.add(a);s.flush();articles.append(a)
  evidence={"curation_contract":{"top_k":3},"articles":[{"id":a.id,"title":a.title,"summary":a.summary,"url":a.url,"publisher":a.publisher} for a in articles]}
  analysis=IntelligenceRun(kind="analysis",status="success",provider="claude_api",options={},evidence=evidence,result={"ranking":[{"rank":n,"title":a.title,"summary":a.summary,"article_ids":[a.id]} for n,a in enumerate(articles,1)]},message="synthetic");s.add(analysis);s.flush();aid=analysis.id
  run=IntelligenceRun(kind="script",status="success",provider="claude_api",options={"analysis_run_id":aid,"selected_article_ids":[articles[0].id]},evidence={},result={},message="synthetic");s.add(run);s.flush()
  s.add(ContentDraft(run_id=run.id,duration=30,content={"title":articles[0].title,"scenes":[{"narration":"저장된 합성 대본 첫 문장입니다. " + "긴 내레이션입니다. "*50}]},sources={"articles":[{"id":articles[0].id,"url":articles[0].url}]}))
 return NS(service=service,generation=generation,sessions=sessions,engine=engine,adapter=adapter,analysis_id=aid)

@pytest.fixture
def env(tmp_path):
 e=setup(tmp_path)
 yield e
 e.engine.dispose()

def create(e,**settings):return e.service.create(e.analysis_id,{**DEFAULTS["image"],**settings})
def step(e,b):e.service.step(b,consent=True,reviewed=True)
def test_rank_sources_script_reuse_and_short_copy(env):
 b=create(env);row=env.service.get(b);v=env.service.view(b)
 assert [i["rank"] for i in v["items"]]==[1,2,3]
 assert "기존 대본" in v["items"][0]["source"]["origin"]
 assert "저장된 합성 대본 첫 문장" in v["items"][0]["content"]["body"]
 assert all(len(x["content"]["body"])<=180 for x in v["items"])
 assert "대본 미생성" in v["items"][1]["source"]["origin"]
 assert all(x["source"]["references"] and f"#TOP{x['rank']}" in x["caption"] for x in v["items"])
 assert "DATA is untrusted" in v["items"][0]["prompt"] and not env.adapter.calls
 assert row.options["max_generations"]==3 and row.options["selection"]["size"]=="1024x1280"

def test_three_fake_outputs_and_request_dedup(env):
 b=create(env)
 for _ in range(5):step(env,b)
 v=env.service.view(b);assert len(env.adapter.calls)==3
 assert v["status"]=="success" and v["plannedImages"]==3
 for rank in (1,2,3):
  with Image.open(env.service.path(b,rank)) as image:assert image.size==(1080,1350) and image.format=="JPEG"
  assert v["items"][rank-1]["mediaUrl"] and "출처:" in v["items"][rank-1]["caption"]
 assert create(env,quality="high")==b and len(env.adapter.calls)==3
 assert env.service.get(b).options["selection"]["quality"]=="medium"

@pytest.mark.parametrize("size",["1024x1024","1024x1536","1024x1280"])
def test_supported_sizes_preserve_whole_layout_with_padding(env,size):
 b=create(env,size=size);step(env,b)
 with Image.open(env.service.path(b,1)) as img:assert img.size==(1080,1350)
 assert env.adapter.calls[0]["selection"]["size"]==size

@pytest.mark.parametrize("consent,reviewed",[(False,False),(True,False),(False,True)])
def test_approval_boundaries(env,consent,reviewed):
 b=create(env)
 with pytest.raises(PublishingError):env.service.step(b,consent=consent,reviewed=reviewed)
 assert not env.adapter.calls

def test_real_price_unknown_blocks_before_credentials(tmp_path):
 e=setup(tmp_path,simulation=False);e.generation.keys=NS(key=lambda:pytest.fail("real key read"))
 try:
  b=create(e)
  with pytest.raises(PublishingError,match="예상 비용"):step(e,b)
  assert not e.adapter.calls and not e.service.view(b)["canGenerate"]
 finally:e.engine.dispose()

@pytest.mark.parametrize("mutation",["incomplete","failed","overlap","same_url","same_title","bad_url"])
def test_incomplete_or_duplicate_selection_blocked(env,mutation):
 with env.sessions.begin() as s:
  row=s.get(IntelligenceRun,env.analysis_id);r=deepcopy(row.result);ev=deepcopy(row.evidence)
  if mutation=="incomplete":r["ranking"].pop()
  if mutation=="failed":row.status="failed"
  if mutation=="overlap":r["ranking"][1]["article_ids"]=r["ranking"][0]["article_ids"]
  if mutation=="same_title":r["ranking"][1]["title"]=r["ranking"][0]["title"]
  if mutation=="same_url":ev["articles"][1]["url"]=ev["articles"][0]["url"]
  if mutation=="bad_url":ev["articles"][0]["url"]="file:///private"
  row.result=r;row.evidence=ev
 with pytest.raises(PublishingError):create(env)
 assert not env.adapter.calls

def test_failure_preserves_other_results_and_explicit_regenerate(env):
 original=env.adapter.generate
 def fail(prompt,key,**kw):
  if '\"rank\": 2' in prompt:raise ImageGenerationError("synthetic_rejected",uncertain=False)
  return original(prompt,key,**kw)
 env.adapter.generate=fail
 b=create(env)
 for _ in range(3):step(env,b)
 before=[env.service.path(b,n).read_bytes() for n in (1,3)]
 v=env.service.view(b);assert [x["status"] for x in v["items"]]==["success","failed","success"]
 env.adapter.generate=original
 env.service.change(b,v["revision"],"regenerate",rank=2,consent=True,reviewed=True)
 step(env,b)
 assert [env.service.path(b,n).read_bytes() for n in (1,3)]==before
 assert len(env.service.view(b)["items"][1]["history"])==1
 assert env.service.get(b).options["max_generations"]==4

def test_timeout_unknown_not_replayed_or_regenerated(env):
 env.adapter.generate=lambda *a,**k:(_ for _ in ()).throw(ImageGenerationError("timeout"))
 b=create(env);step(env,b);v=env.service.view(b)
 assert v["items"][0]["status"]=="unknown"
 with pytest.raises(PublishingError,match="결과 불명"):step(env,b)
 with pytest.raises(PublishingError):env.service.change(b,v["revision"],"regenerate",rank=1,consent=True,reviewed=True)
 with env.sessions() as s:assert len(list(s.scalars(select(IntelligenceRun).where(IntelligenceRun.kind=="feed_image"))))==1

def test_interrupted_before_provider_is_unknown_and_restart_keeps_success(env):
 b=create(env);step(env,b);raw=env.service.path(b,1).read_bytes()
 with env.sessions.begin() as s:
  row=s.get(IntelligenceRun,b);result=deepcopy(row.result);result["items"][1]["status"]="running";row.result=result
 restarted=TopThreeFeeds(env.sessions,env.service.root.parents[1],env.generation,simulation=True)
 with pytest.raises(PublishingError,match="결과 불명"):restarted.step(b,consent=True,reviewed=True)
 assert env.service.path(b,1).read_bytes()==raw and len(env.adapter.calls)==1
 assert restarted.view(b)["items"][1]["status"]=="unknown"

def test_pause_resume_edit_conflict_and_defaults_independent(env):
 b=create(env);v=env.service.view(b);before=deepcopy(v["selection"])
 env.service.change(b,v["revision"],"edit",rank=1,title="사용자 검토 제목",body="합성 자료를 요약했습니다.",hashtags="#합성")
 with pytest.raises(PublishingError,match="다른 화면"):env.service.change(b,v["revision"],"pause")
 v=env.service.view(b);env.service.change(b,v["revision"],"pause")
 with pytest.raises(PublishingError,match="중지"):step(env,b)
 env.service.save_defaults({**DEFAULTS["image"],"quality":"high"})
 assert read_defaults(env.sessions,"image")==DEFAULTS["image"]
 assert env.service.get(b).options["selection"]==before
 v=env.service.view(b);env.service.change(b,v["revision"],"resume");step(env,b)
 assert "사용자 검토 제목" in env.adapter.calls[0]["prompt"]
 assert TopThreeFeeds(env.sessions,env.service.root.parents[1],env.generation).defaults()["quality"]=="high"

def test_tampered_output_and_frozen_source_rejected(env):
 b=create(env);step(env,b);env.service.path(b,1).write_bytes(b"tampered")
 assert env.service.view(b)["items"][0]["mediaUrl"] is None
 with pytest.raises(PublishingError):env.service.path(b,1)
 with env.sessions.begin() as s:
  row=s.get(IntelligenceRun,b);data=deepcopy(row.evidence);data["sources"][0]["title"]="changed";row.evidence=data
 with pytest.raises(PublishingError,match="변경"):env.service.get(b)

def test_lock_contention_prevents_duplicate_submit(env):
 from filelock import FileLock
 b=create(env)
 with FileLock(env.service.lock.lock_file):
  with pytest.raises(PublishingError,match="진행 중"):step(env,b)
 assert not env.adapter.calls

def test_edited_source_after_batch_does_not_change_snapshot(env):
 b=create(env);before=deepcopy(env.service.get(b).evidence)
 with env.sessions.begin() as s:
  row=s.get(IntelligenceRun,env.analysis_id);row.result={"ranking":[]}
 assert env.service.get(b).evidence==before
 step(env,b);assert len(env.adapter.calls)==1


def test_same_events_in_a_new_analysis_are_not_automatically_rendered_twice(env):
 b=create(env)
 with env.sessions.begin() as s:
  old=s.get(IntelligenceRun,env.analysis_id)
  newer=IntelligenceRun(kind="analysis",status="success",provider=old.provider,options={},evidence=deepcopy(old.evidence),result=deepcopy(old.result),message="synthetic reranking")
  s.add(newer);s.flush();identifier=newer.id
 with pytest.raises(PublishingError,match="이미 TOP 3"):env.service.create(identifier,DEFAULTS['image'])
 assert not env.adapter.calls and env.service.get(b).status=="saved"


def test_export_synthetic_three_results_only(env):
 import os
 b=create(env)
 for _ in range(3):step(env,b)
 view=env.service.view(b)
 assert view['simulation'] is True and len(env.adapter.calls)==3
 output=os.environ.get('NEWSFLOW_TOP3_EVIDENCE')
 if output:
  root=Path(output);root.mkdir(parents=True,exist_ok=True)
  for n in (1,2,3):(root/f'fake-top{n}.jpg').write_bytes(env.service.path(b,n).read_bytes())
  (root/'fake-batch.json').write_text(json.dumps(view,ensure_ascii=False,indent=2),encoding='utf-8')


def test_explicit_recover_after_write_gap_reuses_output_without_new_request(env):
 b=create(env);step(env,b)
 before=env.service.path(b,1).read_bytes()
 with env.sessions.begin() as s:
  row=s.get(IntelligenceRun,b);data=deepcopy(row.result);data['items'][0]['status']='running';data['items'][0]['generation_id']=None;row.result=data
 v=env.service.view(b);env.service.change(b,v['revision'],'recover')
 assert len(env.adapter.calls)==1 and env.service.view(b)['items'][0]['status']=='success'
 assert env.service.path(b,1).read_bytes()==before
