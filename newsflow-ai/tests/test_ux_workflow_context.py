"""Production choices survive the existing manual path without adding execution permissions."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import csrf

from newsflow.db.models import AppSetting, ContentDraft, IntelligenceRun, NewsArticle, NewsSource
from newsflow.gui.production_context import context_for_draft, context_for_run, context_json, parse_context
from newsflow.intelligence.provider import FakeProvider
from newsflow.intelligence.settings import write_studio_settings
from newsflow.video.supertonic_tts import SupertonicTTS
from newsflow.video.tts import WindowsTTS


def set_values(app, **values):
    with app.state.sessions.begin() as session:
        for key, value in values.items():
            row = session.get(AppSetting, key)
            if row:
                row.value = value
            else:
                session.add(AppSetting(key=key, value=value))


def article(app):
    with app.state.sessions.begin() as session:
        source = NewsSource(name="합성 검증 RSS", url="https://example.com/workflow-feed", enabled=True)
        session.add(source)
        session.flush()
        news = NewsArticle(title="합성 지역 소식", summary="검증용이며 실제 보도가 아닙니다.",
                           url="https://example.com/workflow-news", canonical_url="https://example.com/workflow-news",
                           publisher="합성 출처", source_id=source.id)
        session.add(news)
        session.flush()
        return news.id


@pytest.mark.parametrize("provider,model,duration", [("claude_code", "sonnet", 45), ("codex", "default", 45),
                                                   ("claude_code", "sonnet", 60)])
def test_home_choices_survive_manual_analysis_script_and_video(client, app, monkeypatch, provider, model, duration):
    write_studio_settings(app.state.sessions, provider, model)
    set_values(app, video_default_voice="supertonic:F1")
    fake = FakeProvider()
    app.state.ai_provider = fake
    monkeypatch.setattr(WindowsTTS, "voice_details", lambda self: [])
    monkeypatch.setattr(SupertonicTTS, "voices", lambda self: ["supertonic:F1"])
    news_id = article(app)
    token = csrf(client)
    started = client.post("/autopilot/quick-start", data={
        "csrf_token": token, "source": "feeds", "duration": duration,
    }, follow_redirects=False)
    assert started.status_code == 303 and fake.calls == 0
    flow = parse_qs(urlsplit(started.headers["location"]).query)["flow"][0]
    context = parse_context(flow)
    assert context["initial_duration"] == duration
    assert context["initial_provider"] == provider and context["initial_voice"] == "supertonic:F1"
    guide = client.get(started.headers["location"]).text
    assert f"처음 선택한 길이 {duration}초" in guide and "/ai?flow=" in guide
    prepared = client.get("/ai", params={"flow": flow}).text
    assert f"최초 선택 · {duration}초" in prepared and "아직 AI를 실행하지 않았습니다" in prepared
    denied = client.post("/ai/analyze", data={
        "csrf_token": token, "article_ids": [news_id], "provider": provider, "model": model, "flow": flow,
    })
    assert denied.status_code == 422 and fake.calls == 0
    analyzed = client.post("/ai/analyze", data={
        "csrf_token": token, "article_ids": [news_id], "provider": provider, "model": model,
        "flow": flow, "consent": "true",
    })
    assert analyzed.status_code == 200 and fake.calls == 1
    analysis_id = int(analyzed.url.params["analysis_id"])
    # A later global-default edit must not rewrite the already-started production.
    write_studio_settings(app.state.sessions, "offline", "offline")
    set_values(app, video_default_voice="offline-silence")
    after_defaults_changed = client.get(f"/ai?analysis_id={analysis_id}").text
    assert f'value="{duration}" selected' in after_defaults_changed
    assert f'value="{provider}" selected' in after_defaults_changed
    assert f'value="{model}"' in after_defaults_changed
    tampered = context_json({**context, "initial_voice": "offline-silence", "initial_duration": 30})
    generated = client.post("/ai/generate", data={
        "csrf_token": token, "analysis_id": analysis_id, "duration": duration,
        "provider": provider, "model": model, "flow": tampered, "consent": "true",
    })
    assert generated.status_code == 200 and fake.calls == 2
    draft_id = int(generated.url.params["draft_id"])
    with app.state.sessions() as session:
        draft = session.get(ContentDraft, draft_id)
        assert draft.duration == duration and draft.review_status == "review_required"
        assert sum(scene["seconds"] for scene in draft.content["scenes"]) == duration
        saved = context_for_draft(session, draft)
        assert saved == {**context, "analysis_id": analysis_id}
        assert context_for_run(session.get(IntelligenceRun, analysis_id)) == context
        assert session.get(IntelligenceRun, draft.run_id).provider == provider
    video = client.get(f"/video?draft_id={draft_id}").text
    assert f'value="{duration}" selected' in video
    assert 'value="supertonic:F1" selected' in video
    assert 'name="reviewed" value="true" required' in video
    tasks = client.get("/autopilot/jobs").text
    assert "대본 검토 필요" in tasks and "합성 지역 소식" in tasks
    assert tasks.count(f'href="/ai?draft_id={draft_id}"') == 1
    assert f'href="/ai?analysis_id={analysis_id}"' not in tasks


def test_initial_choices_are_not_claimed_as_actual_provider(client, app):
    app.state.ai_provider = FakeProvider()
    news_id = article(app)
    initial = {"source": "feeds", "initial_duration": 45, "initial_provider": "claude_code",
               "initial_model": "sonnet", "initial_voice": "offline-silence"}
    response = client.post("/ai/analyze", data={
        "csrf_token": csrf(client), "article_ids": [news_id], "provider": "codex", "model": "default",
        "consent": "true", "flow": context_json(initial),
    })
    assert response.status_code == 200
    assert "분석·대본 예정: Claude Code" in response.text
    assert "분석 실행: Codex · 완료" in response.text
    assert 'value="codex" selected' in response.text
    assert "Codex · 사용" in client.get("/autopilot/jobs").text


@pytest.mark.parametrize("update", [
    {"initial_duration": 31}, {"initial_duration": True}, {"initial_provider": "unsupported"},
    {"initial_model": "../command"}, {"initial_voice": "voice\ncommand"}, {"source": "untrusted"},
])
def test_invalid_context_does_not_run_ai(client, app, update):
    app.state.ai_provider = fake = FakeProvider()
    context = {"source": "feeds", "initial_duration": 45, "initial_provider": "claude_code",
               "initial_model": "sonnet", "initial_voice": "offline-silence", **update}
    response = client.post("/ai/analyze", data={
        "csrf_token": csrf(client), "article_ids": [1], "provider": "claude_code", "model": "sonnet",
        "flow": json.dumps(context), "consent": "true",
    })
    assert response.status_code == 422 and fake.calls == 0


def test_different_openai_model_guides_without_starting_engine(client, app, monkeypatch):
    from newsflow.gui import autopilot_routes

    article(app)
    write_studio_settings(app.state.sessions, "openai", "gpt-4o")
    monkeypatch.setattr(autopilot_routes, "external_ready", lambda *_: {"ready": True})
    monkeypatch.setattr(app.state.autopilot, "start", lambda **kw: pytest.fail("wrong model auto-start"))
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": csrf(client), "source": "feeds", "duration": 45,
    }, follow_redirects=False)
    assert response.status_code == 303 and "guide=model" in response.headers["location"]
    context = parse_context(parse_qs(urlsplit(response.headers["location"]).query)["flow"][0])
    assert context["initial_model"] == "gpt-4o"


def test_failed_script_is_visible_once_without_automatic_retry(client, app):
    app.state.ai_provider = FakeProvider()
    news_id = article(app)
    context = {"source": "feeds", "initial_duration": 45, "initial_provider": "claude_code",
               "initial_model": "sonnet", "initial_voice": "offline-silence"}
    analyzed = client.post("/ai/analyze", data={
        "csrf_token": csrf(client), "article_ids": [news_id], "provider": "claude_code", "model": "sonnet",
        "flow": context_json(context), "consent": "true",
    })
    analysis_id = int(analyzed.url.params["analysis_id"])
    with app.state.sessions.begin() as session:
        analysis = session.get(IntelligenceRun, analysis_id)
        failed = IntelligenceRun(kind="script", status="failed", provider="claude_code",
                    options={"duration": 45, "production_context": {**context, "analysis_id": analysis_id}},
                    evidence=analysis.evidence, result={}, message="응답 결과를 확인하지 못했습니다.")
        session.add(failed)
        session.flush()
        failed_id = failed.id
    calls = app.state.ai_provider.calls
    tasks = client.get("/autopilot/jobs").text
    assert "조치 필요" in tasks and "자동 재실행 없음" in tasks
    assert tasks.count(f'href="/ai?analysis_id={analysis_id}&amp;failed_run_id={failed_id}"') == 1
    failure = client.get(f"/ai?analysis_id={analysis_id}&failed_run_id={failed_id}").text
    assert "응답 결과를 확인하지 못했습니다" in failure and "자동으로 다시 요청하지 않았습니다" in failure
    assert app.state.ai_provider.calls == calls
