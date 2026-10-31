"""Synthetic module projection and original form coverage. No application startup."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select
from test_read_model import setup

from newsflow.db.models import AppSetting, IntelligenceRun, NewsArticle, NewsListState, NewsSource
from newsflow.gui.studio_v3 import workspace
from newsflow.studio.read_models import SPECS, module_view, rows


@pytest.mark.parametrize("module", list(SPECS))
def test_all_module_views_are_readonly_and_secret_free(tmp_path, module):
    request, engine, sessions = setup(tmp_path)
    request.state = NS(csrf="SYNTHETIC-CSRF")
    with sessions.begin() as s:
        s.add(AppSetting(key="secret-unrelated", value="NEVER-RETURN-THIS-SECRET"))
    with engine.connect() as c:
        before = c.exec_driver_sql("select * from app_settings").fetchall()
    result = module_view(request, module)
    with engine.connect() as c:
        assert c.exec_driver_sql("select * from app_settings").fetchall() == before
    assert result["module"] == module and result["schemaVersion"] == 1
    assert result["csrfToken"] == "SYNTHETIC-CSRF"
    assert "NEVER-RETURN" not in json.dumps(result)
    assert not result["catalog"]["accountVerified"]
    assert not result["policy"]["automaticRetry"] and not result["policy"]["providerFallback"]
    engine.dispose()

@pytest.mark.parametrize("latest", ["success", "failed", "unknown", "running"])
def test_image_draft_latest_output_link_and_filename_validation(tmp_path, latest):
    request, engine, sessions = setup(tmp_path)
    request.state=NS(csrf="SYNTHETIC")
    with sessions.begin() as s:
        draft=IntelligenceRun(kind="image_draft",status="saved",provider="openai",options={},evidence={},result={"prompt":"초안 제목"},message="")
        s.add(draft);s.flush(); identifier=draft.id
        s.add(IntelligenceRun(kind="feed_image",status="success",provider="openai",options={"style":"studio","draft_id":identifier},evidence={},result={},message=""));s.flush()
        output=IntelligenceRun(kind="feed_image",status=latest,provider="openai",options={"style":"studio","draft_id":identifier},evidence={},result={},message="")
        s.add(output);s.flush(); output_id=output.id
    calls=[]
    request.app.state.image_generation.path=lambda identifier:calls.append(identifier) or tmp_path/'generated-test.jpg'
    project=workspace(request)["projects"][0]
    item=module_view(request,"images")["collections"]["drafts"][0]
    assert project["title"]=="초안 제목" and item["outputId"]==output_id
    expected=f"/image-studio/{identifier}/file" if latest=="success" else None
    assert project["mediaUrl"]==expected and item["mediaUrl"]==expected
    assert calls==([output_id,output_id] if latest=="success" else [])
    # File verification failure must remove preview, never fall back to an older success.
    def missing(_):raise OSError("synthetic file missing")
    request.app.state.image_generation.path=missing
    assert workspace(request)["projects"][0]["mediaUrl"] is None
    engine.dispose()

def test_news_hidden_records_remain_archived(tmp_path):
    _request,engine,sessions=setup(tmp_path)
    with sessions.begin() as s:
        source=NewsSource(name="synthetic",url="https://example.invalid/rss",enabled=False);s.add(source);s.flush()
        for i in range(2):
            article=NewsArticle(title=f"synthetic-{i}",url=f"https://example.invalid/{i}",canonical_url=f"https://example.invalid/{i}",source_id=source.id,publisher="synthetic");s.add(article);s.flush()
            if i:s.add(NewsListState(article_id=article.id,hidden=True,used=True))
    with sessions() as s:
        assert len(rows(s,"NewsArticle","id title"))==1
        assert len(list(s.scalars(select(NewsArticle))))==2
    engine.dispose()

def test_projection_column_contracts_exist():
    from newsflow.db import models
    for group in SPECS.values():
        for _,name,fields in group:
            assert all(hasattr(getattr(models,name),field) for field in fields.split()), (name,fields)

def test_registry_preserves_every_original_post_route_and_no_write_proxy():
    root=Path(__file__).resolve().parents[3]
    registry=json.loads((root/'src/newsflow/studio/actions.json').read_text(encoding='utf-8'))
    assert registry==json.loads((root/'frontend/src/legacy-actions.json').read_text(encoding='utf-8'))
    found=[]
    for file in (root/'src/newsflow/gui').glob('*.py'):
        for node in ast.walk(ast.parse(file.read_text(encoding='utf-8'))):
            if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
            for decorator in node.decorator_list:
                if isinstance(decorator,ast.Call) and isinstance(decorator.func,ast.Attribute) and decorator.func.attr=='post' and decorator.args and isinstance(decorator.args[0],ast.Constant):
                    found.append((file.name,decorator.args[0].value))
    for file,path in found:
        assert any(action['source']=='gui/'+file and (action['path']==path or '{action}' in path and action['path'].startswith(path.split('{action}')[0])) for action in registry),(file,path)
    assert all('/api/studio/' not in action['path'] for action in registry)
    studio=(root/'src/newsflow/studio/read_models.py').read_text(encoding='utf-8')
    assert '@router.post' not in studio
    assert '/schedules' in {x['path'] for x in registry} and '/schedule' not in {x['path'] for x in registry}

def test_news_image_post_is_independent_from_image_generation_draft(tmp_path):
    from newsflow.db.models import ImagePost
    request,engine,sessions=setup(tmp_path)
    called=[]
    request.app.state.image_posts=NS(path=lambda identifier:called.append(identifier) or tmp_path/"synthetic.jpg")
    with sessions.begin() as session:
        source=NewsSource(name="synthetic",url="https://example.invalid/rss",enabled=False);session.add(source);session.flush()
        article=NewsArticle(title="synthetic",url="https://example.invalid/news",canonical_url="https://example.invalid/news",source_id=source.id,publisher="synthetic");session.add(article);session.flush()
        post=ImagePost(article_id=article.id,title="합성 뉴스 피드",caption="합성 본문",sources={},filename="synthetic.jpg",sha256="0"*64,ai_disclosure="disclose");session.add(post);session.flush();identifier=post.id
    item=workspace(request)["projects"][0]
    assert item["id"]==f"post:{identifier}" and item["href"]==f"/image-posts?post_id={identifier}"
    assert item["mediaUrl"]==f"/image-posts/{identifier}/file" and called==[identifier]
    engine.dispose()

def test_current_tts_and_video_limits_are_read_without_reset(tmp_path):
    request,engine,sessions=setup(tmp_path)
    request.state=NS(csrf="SYNTHETIC")
    values={"studio_provider":"claude_api","studio_model_claude_api":"claude-sonnet-4-6","tts_el_enabled":"true","tts_el_voice_id":'"synthetic-voice"',"tts_el_model":'"eleven_multilingual_v2"',"tts_el_job_limit":"4321","tts_el_commercial":"true"}
    with sessions.begin() as session:
        for key,value in values.items():session.add(AppSetting(key=key,value=value))
    result=module_view(request,"settings")
    config=result['formDefaults']['video_save_tts']
    assert result['formDefaults']['intelligence_analyze']=={'provider':'claude_api','model':'claude-sonnet-4-6'}
    assert config['enabled'] is True and config['commercial'] is True
    assert config['voice_id']=='synthetic-voice' and config['job_limit']==4321
    # Monthly TTS limits were replaced by per-execution limits (1e3d5a9).
    assert 'monthly_limit' not in config
    with sessions() as session:
        assert {key:session.get(AppSetting,key).value for key in values}==values
    engine.dispose()
