"""Focused synthetic contracts for explicit per-execution limits only."""
from decimal import Decimal
from types import SimpleNamespace
import json
from pathlib import Path
import pytest
from sqlalchemy import select
from newsflow.db.models import AppSetting,APIRequestReservation
from newsflow.db.session import make_engine,migrate,session_factory
from newsflow.intelligence.api_settings import FakeAPIBudgetService,APISettingsError,save_api_settings,read_api_settings
from newsflow.intelligence.credentials import AnthropicKeyStore,FakeCipher
from newsflow.intelligence.settings import AISettings,read_settings,write_settings,check_budget
from newsflow.intelligence.provider import Options
from newsflow.video.ai import settings as video
from newsflow.video.elevenlabs_tts import ElevenLabsTTS,save_settings as save_tts,TTSError

@pytest.fixture
def env(tmp_path):
 engine=make_engine(tmp_path/'test.sqlite');migrate(engine);sessions=session_factory(engine)
 key=AnthropicKeyStore(tmp_path/'secrets',FakeCipher());key.save('sk-synthetic-per-execution-0123456789')
 yield sessions,key,tmp_path
 engine.dispose()

def configure(sessions,limit='.30',monthly='0'):
 return save_api_settings(sessions,'claude_api',model='claude-sonnet-4-6',approved=True,
  search_enabled=False,search_approved=False,request_limit_usd=limit,monthly_limit_usd=monthly,
  input_price_per_1m='3',output_price_per_1m='15',search_price_per_1k='10')

def reserve(budget,key,identifier):
 return budget.reserve(provider='claude_api',request_id=identifier,kind='script',model='claude-sonnet-4-6',
  max_output_tokens=1000,key_store=key)

def test_completed_historical_usage_does_not_block_next_request(env):
 sessions,key,_=env;configure(sessions)
 with sessions.begin() as s:s.add(AppSetting(key='api_claude_api_monthly_limit_usd',value='0.000001'))
 budget=FakeAPIBudgetService(sessions)
 first=reserve(budget,key,'synthetic:1');budget.finish(first.id,status='success',usage={'prompt_tokens':100,'completion_tokens':100,'search_calls':0})
 second=reserve(budget,key,'synthetic:2')
 assert second.reserved_usd==first.reserved_usd and Decimal(0)<second.reserved_usd<=Decimal('.30')
 with sessions() as s:
  assert s.get(AppSetting,'api_claude_api_monthly_limit_usd').value=='0.000001'
  assert s.get(APIRequestReservation,first.id).status=='success'

def test_per_request_limit_and_unknown_replay_still_block(env):
 sessions,key,_=env;configure(sessions,limit='.10')
 budget=FakeAPIBudgetService(sessions)
 with pytest.raises(APISettingsError,match='1회 실행'):reserve(budget,key,'synthetic:over')
 with sessions() as s:assert list(s.scalars(select(APIRequestReservation)))==[]
 configure(sessions)
 first=reserve(budget,key,'synthetic:unknown');budget.finish(first.id,status='unknown')
 with pytest.raises(APISettingsError,match='결과 불명'):reserve(budget,key,'synthetic:next')
 with pytest.raises(APISettingsError,match='이미 기록'):reserve(budget,key,'synthetic:unknown')

def test_missing_per_request_limit_never_uses_old_monthly_budget(env):
 sessions,key,_=env
 with sessions.begin() as s:s.add(AppSetting(key='api_claude_api_monthly_limit_usd',value='10000'))
 with pytest.raises(APISettingsError,match='1회 실행'):configure(sessions,limit='0')
 assert read_api_settings(sessions,'claude_api').monthly_limit_usd==Decimal(10000)
 assert read_api_settings(sessions,'claude_api').request_limit_usd==0

def test_saving_request_limit_preserves_old_monthly_setting(env):
 sessions,_,_=env
 with sessions.begin() as s:s.add(AppSetting(key='api_claude_api_monthly_limit_usd',value='123'))
 configure(sessions,monthly='999')
 assert read_api_settings(sessions,'claude_api').monthly_limit_usd==Decimal(123)

def test_legacy_token_path_has_only_explicit_per_run_limit(env):
 sessions,_,_=env
 with sessions.begin() as s:s.add(AppSetting(key='ai_monthly_token_limit',value='50000000'))
 assert read_settings(sessions).request_token_limit==0
 with pytest.raises(Exception,match='1회 토큰'):check_budget(sessions,read_settings(sessions),Options(max_tokens=200),100)
 write_settings(sessions,'openai','gpt-4.1-mini',True,timeout=20,request_token_limit=1000)
 settings=read_settings(sessions)
 assert settings.monthly_token_limit==50000000 and settings.request_token_limit==1000
 check_budget(sessions,settings,Options(max_tokens=200),800)
 with pytest.raises(Exception,match='1회 한도'):check_budget(sessions,settings,Options(max_tokens=201),800)

def test_video_batch_not_old_plan_or_month_total(env,monkeypatch):
 sessions,_,_=env
 monkeypatch.setattr(video,'plan_spent',lambda *a:pytest.fail('historical spending is not a new execution'))
 settings=video.VideoAISettings(job_limit=Decimal(1),monthly_limit=Decimal('.01'))
 with sessions() as s:
  video.check_budget(s,settings,987,Decimal('.5'))
  with pytest.raises(video.VideoSettingsError,match='1회 실행'):video.check_budget(s,settings,987,Decimal('1.01'))
  with pytest.raises(video.VideoSettingsError,match='견적'):video.check_budget(s,settings,987,Decimal(0))

def test_voice_limit_is_per_request_characters_and_monthly_preserved(env):
 sessions,_,tmp=env
 with sessions.begin() as s:s.add(AppSetting(key='tts_el_monthly_limit',value='1'))
 save_tts(sessions,enabled=True,voice_id='synthetic',model='eleven_multilingual_v2',job_limit=3,monthly_limit=999,commercial=True)
 with sessions() as s:assert s.get(AppSetting,'tts_el_monthly_limit').value=='1'
 config={'enabled':True,'voice_id':'synthetic','model':'eleven_multilingual_v2','job_limit':3,'monthly_limit':1,'commercial':True}
 tts=ElevenLabsTTS(tmp,config,consent=True,transport=lambda *a:pytest.fail('no external request over limit'))
 with pytest.raises(TTSError,match='1회 실행'):tts.synthesize_timed('한글네자',tmp/'unused.wav','elevenlabs',3)

def test_no_cumulative_editable_fields_in_action_registry():
 root=Path(__file__).resolve().parents[1]
 rows=json.loads((root/'src/newsflow/studio/actions.json').read_text(encoding='utf8'))
 assert rows==json.loads((root/'frontend/src/legacy-actions.json').read_text(encoding='utf8'))
 chosen=[a for a in rows if a['id'] in {'ai_settings_save_ai_settings','api_settings_save_configuration','video_ai_save_settings','video_save_tts'}]
 assert len(chosen)==4
 assert not any(f['name'] in {'monthly_limit','monthly_limit_usd','monthly_token_limit'} for a in chosen for f in a['fields'])
 assert {'request_limit_usd','request_token_limit'} <= {f['name'] for a in chosen for f in a['fields']}

def test_unknown_price_cannot_be_zero_cost_video():
 from newsflow.video.ai.service import AIVideoCoordinator
 model=video.ModelEntry(id=1,provider='higgsfield',path='synthetic/model',label='synthetic',price_per_second=None,
  durations=(5,),resolution='720p',confirmed=True)
 scene=SimpleNamespace(model_path=model.path,start_ms=0,end_ms=5000)
 assert AIVideoCoordinator._quote(scene,{model.path:model},reported=True) is None
