"""Synthetic profile/worker ownership only; no product policy bypass."""
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest
import step13_guard as guard

RESOURCES=[]
@pytest.fixture(autouse=True)
def step13_isolation(monkeypatch,tmp_path,request):
 env_root=Path(os.environ['NEWSFLOW_VALIDATION_OUTPUT'])/'fixture-env'/hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:20]
 env_root.mkdir(parents=True,exist_ok=False)
 for name in ('TEMP','TMP','LOCALAPPDATA','APPDATA','NEWSFLOW_DATA_DIR'):
  target=env_root/('env-'+name.lower());target.mkdir()
  monkeypatch.setenv(name,str(target))
 # Evidence-only test fixtures; never permit writes to product source.
 if request.node.nodeid.endswith('test_workflow_signals.py::test_signal_colors_accessible_reasons_and_no_automatic_checks'):
  monkeypatch.chdir(env_root)
 evidence=getattr(request.module,'EVIDENCE',None)
 if isinstance(evidence,Path) and evidence.is_absolute() and evidence.is_relative_to(guard.PROJECT/'validation-output'):
  monkeypatch.setattr(request.module,'EVIDENCE',env_root/'evidence')
 from newsflow import main
 from newsflow.publishing.calendar import PublishingCalendar
 from newsflow.scheduler.service import Scheduler
 from newsflow.video.ai.service import AIVideoCoordinator
 apps=[];baseline=set(threading.enumerate())
 original_factory=main.FastAPI
 def tracked_app(*args,**kwargs):
  app=original_factory(*args,**kwargs);apps.append(app);return app
 monkeypatch.setattr(main,'FastAPI',tracked_app)
 for cls in (Scheduler,PublishingCalendar,AIVideoCoordinator):
  original=cls.start
  def limited_start(self,*args,__original=original,**kwargs):
   factory_call=False
   frame=sys._getframe(1);main_name=os.path.normcase(main.__file__)
   try:
    while frame is not None:
     if frame.f_code.co_name in ('create_app','lifespan') and os.path.normcase(frame.f_code.co_filename)==main_name:
      factory_call=True;break
     frame=frame.f_back
   finally:del frame
   if factory_call and os.environ.get('STEP13_WORKER_MODE')!='idle-proof':return None
   return __original(self,*args,**kwargs)
  monkeypatch.setattr(cls,'start',limited_start)
 yield
 for app in reversed(apps):
  for name in ('youtube','tiktok','instagram','publishing_calendar','scheduler','video_ai','autopilot'):
   obj=getattr(app.state,name,None)
   if obj is not None and callable(getattr(obj,'close',None)):obj.close()
  # Lifespan normally closes these; this also covers clients not entered as contexts.
  for name in ('coordinator','video'):
   obj=getattr(app.state,name,None)
   if obj is not None and callable(getattr(obj,'close',None)):obj.close()
  engine=getattr(app.state,'engine',None)
  if engine is not None:engine.dispose()
 from browser_boundary import browser_owned_threads
 owned_browser=browser_owned_threads()
 deferred=[t for t in threading.enumerate() if t not in baseline and t in owned_browser and t.is_alive()]
 deadline=time.monotonic()+3
 while time.monotonic()<deadline:
  remaining=[t for t in threading.enumerate() if t not in baseline and t not in owned_browser and t.is_alive()]
  if not remaining:break
  for thread in remaining:thread.join(timeout=.05)
 remaining=[t.name for t in threading.enumerate() if t not in baseline and t not in owned_browser and t.is_alive()]
 RESOURCES.append({'apps':len(apps),'threads_remaining':remaining,'browser_executor_threads_deferred':len(deferred)})
 assert not remaining,'synthetic fixture left live threads'
def pytest_sessionfinish(session,exitstatus):
 output=Path(os.environ['NEWSFLOW_VALIDATION_OUTPUT'])
 (output/'fixture-cleanup-safe.json').write_text(json.dumps({'tests':len(RESOURCES),'tests_with_remaining_threads':sum(bool(r['threads_remaining']) for r in RESOURCES),'app_instances':sum(r['apps'] for r in RESOURCES),'browser_executor_threads_deferred':sum(r.get('browser_executor_threads_deferred',0) for r in RESOURCES)}),encoding='utf-8')
