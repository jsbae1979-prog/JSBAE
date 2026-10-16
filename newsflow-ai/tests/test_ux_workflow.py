"""Simplified entry points preserve provider choices, review gates and explicit consent."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from conftest import csrf
from sqlalchemy import func, select

from newsflow.db.models import AppSetting, AutopilotJob, ContentDraft, NewsSource


def save(app, **values):
    with app.state.sessions.begin() as session:
        for key, value in values.items():
            row = session.get(AppSetting, key)
            if row:
                row.value = value
            else:
                session.add(AppSetting(key=key, value=value))


def job_count(app):
    with app.state.sessions() as session:
        return session.scalar(select(func.count()).select_from(AutopilotJob))


def enabled_source(app):
    with app.state.sessions.begin() as session:
        source = session.scalar(select(NewsSource).where(NewsSource.url == "https://example.com/rss"))
        if source:
            source.enabled = True
        else:
            session.add(NewsSource(name="Fixture RSS", url="https://example.com/rss", enabled=True))


@pytest.mark.parametrize("provider,model", [("claude_code", "sonnet"), ("codex", "default")])
def test_saved_account_provider_guides_to_studio_without_job_or_replacement(client, app, provider, model):
    save(app, studio_provider=provider, **{"studio_model_" + provider: model})
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": csrf(client), "source": "feeds", "duration": 30,
    }, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/autopilot/start?guide=provider&flow=")
    page = client.get(response.headers["location"]).text
    assert "저장한 AI를 유지했습니다" in page and 'href="/ai?flow=' in page
    assert job_count(app) == 0
    with app.state.sessions() as session:
        assert session.get(AppSetting, "studio_provider").value == provider
        assert session.get(AppSetting, "studio_model_" + provider).value == model


def test_trial_uses_offline_and_stops_for_news_and_script_review(client, app):
    save(app, studio_provider="codex", autopilot_ai="openai", video_default_voice="offline-silence")
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": csrf(client), "source": "sample", "duration": 30,
    }, follow_redirects=False)
    assert response.status_code == 303
    identifier = response.headers["location"].rsplit("/", 1)[1]
    app.state.autopilot.future.result(timeout=15)
    selected = app.state.autopilot.snapshot(identifier)
    assert (selected["source"], selected["ai_mode"], selected["content_mode"]) == ("sample", "offline", "trial")
    assert selected["status"] == "waiting_review" and selected["current_stage"] == "select"
    page = client.get(response.headers["location"]).text
    assert "영상으로 만들 뉴스를 직접 고르기 위해" in page
    assert f'value="{selected["progress"]}"' in page
    resumed = client.post(f"/autopilot/jobs/{identifier}/resume", data={
        "csrf_token": csrf(client), "revision": selected["revision"], "article_id": selected["article_id"],
    }, follow_redirects=False)
    assert resumed.status_code == 303
    app.state.autopilot.future.result(timeout=15)
    scripted = app.state.autopilot.snapshot(identifier)
    assert scripted["status"] == "waiting_review" and scripted["current_stage"] == "script"
    page = client.get(response.headers["location"]).text
    assert "대본의 사실·출처를 확인해야" in page and 'id="job-script"' in page
    assert "게시 승인이나 저작권 확인으로 기록되지 않습니다" in page
    with app.state.sessions() as session:
        assert session.get(ContentDraft, scripted["content_draft_id"]).review_status == "review_required"
        assert session.get(AppSetting, "studio_provider").value == "codex"
        assert session.get(AppSetting, "autopilot_ai").value == "openai"


@pytest.mark.parametrize("voice,available", [("missing-local-voice", False), ("elevenlabs", True)])
def test_unavailable_or_external_voice_never_silently_falls_back(client, app, monkeypatch, voice, available):
    save(app, video_default_voice=voice)
    monkeypatch.setattr(app.state.video, "voice_available", lambda _: available)
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": csrf(client), "source": "sample", "duration": 30,
    }, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"].startswith("/autopilot/start?guide=voice&flow=")
    page = client.get(response.headers["location"]).text
    assert "다른 음성이나 무음으로 바꾸지 않았어요" in page
    assert job_count(app) == 0
    with app.state.sessions() as session:
        assert session.get(AppSetting, "video_default_voice").value == voice


def test_available_local_voice_is_forwarded_without_new_provider_settings(client, app, monkeypatch):
    save(app, video_default_voice="supertonic:F1", studio_provider="offline")
    monkeypatch.setattr(app.state.video, "voice_available", lambda _: True)
    start = Mock(return_value="test-job")
    monkeypatch.setattr(app.state.autopilot, "start", start)
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": csrf(client), "source": "sample", "duration": 45,
    }, follow_redirects=False)
    assert response.status_code == 303
    assert start.call_args.kwargs == {
        "mode": "guided", "source": "sample", "duration": 45, "platform": "youtube",
        "content_mode": "trial", "ai_mode": "offline", "voice": "supertonic:F1",
    }


def test_openai_without_existing_approval_stops_before_collection(client, app):
    enabled_source(app)
    save(app, studio_provider="openai")
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": csrf(client), "source": "feeds", "duration": 60,
    }, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"].startswith("/autopilot/start?guide=approval&flow=")
    assert job_count(app) == 0


def test_approved_provider_still_enters_existing_guided_review_engine(client, app, monkeypatch):
    from newsflow.gui import autopilot_routes

    enabled_source(app)
    save(app, studio_provider="openai", video_default_voice="offline-silence")
    monkeypatch.setattr(autopilot_routes, "external_ready", lambda *_: {"ready": True})
    start = Mock(return_value="test-job")
    monkeypatch.setattr(app.state.autopilot, "start", start)
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": csrf(client), "source": "feeds", "duration": 60,
    }, follow_redirects=False)
    assert response.status_code == 303
    assert start.call_args.kwargs["mode"] == "guided"
    assert start.call_args.kwargs["ai_mode"] == "openai"
    assert start.call_args.kwargs["content_mode"] == "real"


@pytest.mark.parametrize("origin,token", [("https://foreign.example", True), ("http://127.0.0.1", False)])
def test_quick_start_keeps_csrf_and_origin_guards(client, app, origin, token):
    data = {"source": "sample", "duration": 30}
    if token:
        data["csrf_token"] = csrf(client)
    assert client.post("/autopilot/quick-start", data=data, headers={"Origin": origin}).status_code == 403
    assert job_count(app) == 0


@pytest.mark.parametrize("source,duration", [("invalid", 30), ("sample", 31)])
def test_invalid_quick_choices_do_not_create_job(client, app, source, duration):
    assert client.post("/autopilot/quick-start", data={
        "csrf_token": csrf(client), "source": source, "duration": duration,
    }).status_code == 422
    assert job_count(app) == 0


def test_task_views_keep_advanced_routes_and_real_progress_copy(client):
    start = client.get("/autopilot/start").text
    assert 'action="/autopilot/quick-start"' not in start
    assert 'action="/autopilot/start"' not in start and "제작 시작은 홈에서" in start
    advanced = client.get("/autopilot/start?advanced=true").text
    assert 'action="/autopilot/start"' in advanced and "고급 제작 설정" in advanced
    tasks = client.get("/autopilot/jobs").text
    assert "작업 현황" in tasks
    assert "설정의 고급 관리" in tasks
