"""Home keeps one flow, explicit acquisition/consent and durable engine choices."""

import json
import re
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import csrf
from sqlalchemy import select

from newsflow.db.models import AppSetting, NewsSource
from newsflow.gui.production_context import context_json, parse_context
from newsflow.intelligence.settings import write_studio_settings


def save(app, **values):
    with app.state.sessions.begin() as session:
        for key, value in values.items():
            row = session.get(AppSetting, key)
            if row:
                row.value = value
            else:
                session.add(AppSetting(key=key, value=value))


def settings(app):
    with app.state.sessions() as session:
        return {row.key: row.value for row in session.scalars(select(AppSetting))}


def source(app):
    with app.state.sessions.begin() as session:
        session.add(NewsSource(name="Fixture RSS", url="https://example.com/automation-rss", enabled=True))


def test_new_user_defaults_to_blocked_ai_web_without_silently_running_rss(client, app, monkeypatch):
    start = Mock()
    monkeypatch.setattr(app.state.autopilot, "start", start)
    token = csrf(client)
    before = settings(app)
    home = client.get("/").text
    assert 'value="feeds" selected' in home and 'value="ai_web" selected' in home
    assert "AI 웹 뉴스 조사 BLOCKED" in home
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": token, "source": "feeds", "duration": 30,
    }, follow_redirects=False)
    assert response.status_code == 303 and "guide=search" in response.headers["location"]
    assert settings(app) == before and start.call_count == 0


def test_saved_rss_and_sample_selection_survive_new_ai_web_default(client, app):
    save(app, autopilot_acquisition_policy="rss", autopilot_source="sample")
    before = settings(app)
    home = client.get("/").text
    assert 'value="sample" selected' in home and 'value="rss" selected' in home
    settings_page = client.get("/simple-settings").text
    assert 'value="sample" selected' in settings_page and 'value="rss" selected' in settings_page
    assert settings(app) == before


def test_home_policy_change_has_matching_readiness_and_notice_without_execution(client, app, monkeypatch):
    source(app)
    save(app, autopilot_source="feeds", video_default_voice="offline-silence")
    start = Mock()
    monkeypatch.setattr(app.state.autopilot, "start", start)
    home = client.get("/").text
    states = json.loads(re.search(r"data-home-policy-states='([^']+)'", home).group(1))
    assert states["rss"]["supported"] is True
    assert states["rss"]["title"] == "RSS 분석·대본 제작 지원"
    assert "RSS 확보 → 같은 AI" in states["rss"]["notice"]
    assert states["ai_web"]["supported"] is False
    assert states["hybrid"]["title"] == "AI 웹 뉴스 조사 BLOCKED"
    assert 'data-home-policy-title>AI 웹 뉴스 조사 BLOCKED' in home
    assert 'data-home-policy-notice' in home and 'data-home-policy-detail' in home
    script = client.get("/static/js/home_production.js").text
    assert 'acquisitionChoice.addEventListener("change"' in script
    assert 'for (const key of ["title", "detail", "notice"])' in script
    assert 'refreshPolicyReadiness();' in script
    assert start.call_count == 0


@pytest.mark.parametrize("provider,model", [("claude_code", "sonnet"), ("codex", "default")])
@pytest.mark.parametrize("duration", [30, 45, 60])
def test_one_home_request_preserves_choices_and_requires_explicit_consent(
    client, app, monkeypatch, provider, model, duration,
):
    source(app)
    write_studio_settings(app.state.sessions, provider, model)
    save(app, video_default_voice="supertonic:F1", autopilot_platform="instagram")
    monkeypatch.setattr(app.state.video, "voice_available", lambda name: name == "supertonic:F1")
    start = Mock(return_value="job-fixture")
    monkeypatch.setattr(app.state.autopilot, "start", start)
    token = csrf(client)
    initial = settings(app)
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": token, "source": "feeds", "duration": duration,
        "acquisition_policy": "rss", "category": "it", "period": "24h",
    }, follow_redirects=False)
    assert response.status_code == 303 and "guide=consent" in response.headers["location"]
    flow = parse_qs(urlsplit(response.headers["location"]).query)["flow"][0]
    page = client.get(response.headers["location"])
    assert page.status_code == 200 and start.call_count == 0
    assert "기사 비교·분석 1회" in page.text and "계정 잔여량을 정확히 확인할 수 없습니다" in page.text
    assert "RSS 뉴스 수집" in page.text and "웹 검색을 실행하는 방식이 아닙니다" in page.text
    assert 'name="consent" value="true" required' in page.text
    assert settings(app) == initial
    assert client.post("/autopilot/confirm-start", data={"csrf_token": token, "flow": flow}).status_code == 422
    assert start.call_count == 0
    # Later global edits must not rewrite the already displayed confirmation.
    write_studio_settings(app.state.sessions, "offline", "offline")
    save(app, video_default_voice="offline-silence", autopilot_duration="30")
    response = client.post("/autopilot/confirm-start", data={
        "csrf_token": token, "flow": flow, "consent": "true",
    }, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/autopilot/jobs/job-fixture"
    assert start.call_count == 1
    assert start.call_args.kwargs == {
        "mode": "guided", "source": "feeds", "duration": duration, "platform": "instagram",
        "content_mode": "real", "ai_mode": provider, "ai_model": model, "voice": "supertonic:F1",
        "acquisition_policy": "rss", "category": "it", "period": "24h", "external_consent": True,
        "request_id": parse_context(flow)["request_id"],
    }
    assert settings(app)["studio_provider"] == "offline"  # job creation never rewrites defaults


@pytest.mark.parametrize("provider", ["offline", "claude_code", "codex", "openai"])
@pytest.mark.parametrize("policy", ["ai_web", "hybrid"])
def test_unavailable_search_policy_never_falls_back(client, app, monkeypatch, provider, policy):
    model = {"offline": "offline", "claude_code": "sonnet", "codex": "default", "openai": "gpt-4o-mini"}[provider]
    write_studio_settings(app.state.sessions, provider, model)
    save(app, video_default_voice="offline-silence", autopilot_acquisition_policy=policy)
    start = Mock()
    monkeypatch.setattr(app.state.autopilot, "start", start)
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": csrf(client), "source": "feeds", "duration": 30,
    }, follow_redirects=False)
    assert response.status_code == 303 and "guide=search" in response.headers["location"]
    page = client.get(response.headers["location"]).text
    assert "AI 웹 뉴스 조사 BLOCKED" in page and "RSS로 자동 전환하지 않았습니다" in page
    assert start.call_count == 0 and settings(app)["autopilot_acquisition_policy"] == policy


def test_rss_policy_save_is_canonical_and_read_only_get_does_not_infer(client, app, monkeypatch):
    start = Mock()
    monkeypatch.setattr(app.state.autopilot, "start", start)
    token = csrf(client)
    save(app, video_default_voice="offline-silence")
    response = client.post("/production/preferences", data={
        "csrf_token": token, "provider": "codex", "model": "default", "source": "feeds",
        "duration": 60, "platform": "youtube", "voice": "offline-silence", "rate": "0", "pause_ms": "250",
        "video_provider": "off", "acquisition_policy": "rss", "category": "world", "period": "today",
    })
    assert response.status_code == 200
    saved = settings(app)
    assert saved["autopilot_acquisition_policy"] == "rss" and saved["autopilot_category"] == "world"
    home = client.get("/").text
    assert 'name="acquisition_policy"' in home and 'value="world" selected' in home
    assert "RSS 분석·대본 통합 제작 지원" in response.text
    assert "웹 검색 BLOCKED" in response.text and "설치·인증 검사와 실제 생성 성공은 별개" in response.text
    assert start.call_count == 0 and settings(app) == saved
    blocked = client.post("/production/preferences", data={
        "csrf_token": token, "provider": "codex", "model": "default", "source": "feeds",
        "duration": 60, "platform": "youtube", "voice": "offline-silence", "rate": "0", "pause_ms": "250",
        "video_provider": "off", "acquisition_policy": "fake", "category": "world", "period": "today",
    })
    assert blocked.status_code == 422 and settings(app) == saved


def test_confirmation_retains_csrf_origin_and_context_validation(client, app, monkeypatch):
    start = Mock()
    monkeypatch.setattr(app.state.autopilot, "start", start)
    flow = context_json({"source": "feeds", "initial_duration": 45, "initial_provider": "codex",
                         "initial_model": "default", "initial_voice": "offline-silence",
                         "acquisition_policy": "rss", "category": "all", "period": "7d"})
    token = csrf(client)
    assert client.post("/autopilot/confirm-start", data={"flow": flow, "consent": "true"}).status_code == 403
    assert client.post("/autopilot/confirm-start", data={"csrf_token": token, "flow": flow, "consent": "true"},
                       headers={"Origin": "https://foreign.example"}).status_code == 403
    assert client.post("/autopilot/confirm-start", data={"csrf_token": token, "flow": "{}", "consent": "true"}
                       ).status_code == 422
    assert parse_context(flow)["initial_duration"] == 45 and start.call_count == 0


@pytest.mark.parametrize("field,value", [("category", "unknown"), ("period", "forever"),
                                         ("acquisition_policy", "fake")])
def test_bad_acquisition_choices_rejected_before_any_job(client, app, monkeypatch, field, value):
    start = Mock()
    monkeypatch.setattr(app.state.autopilot, "start", start)
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": csrf(client), "source": "feeds", "duration": 45, field: value,
    })
    assert response.status_code == 422 and start.call_count == 0
