"""One workspace with the durable AI pipeline; all inference and RSS are injected fixtures."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import csrf
from sqlalchemy import func, select
from test_ai_news_automation_backend import automation  # noqa: F401 - shared synthetic coordinator fixture
from test_single_workspace import save_values, stored_values

from newsflow.autopilot.contracts import BackendError
from newsflow.db.models import AIUsage, AutopilotJob, ContentDraft, IntelligenceRun
from newsflow.gui.production_context import context_json, parse_context
from newsflow.intelligence.provider import ProviderTimeoutError
from newsflow.intelligence.settings import write_studio_settings


@pytest.fixture
def workspace_pipeline(automation, app, monkeypatch):  # noqa: F811 - pytest injects the imported fixture
    coordinator, backend, ai, sessions = automation
    monkeypatch.setattr(app.state, "autopilot", coordinator)
    monkeypatch.setattr(app.state, "autopilot_backend", backend)
    save_values(app, video_default_voice="offline-silence", autopilot_source="feeds",
                autopilot_acquisition_policy="rss", autopilot_platform="youtube")
    return coordinator, backend, ai, sessions


def inline_consent(client, app, provider="claude_code", duration=45):
    write_studio_settings(app.state.sessions, provider, "sonnet" if provider == "claude_code" else "default")
    token = csrf(client)
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": token, "source": "feeds", "duration": duration, "workspace": "true",
        "acquisition_policy": "rss", "category": "all", "period": "24h",
    }, follow_redirects=False)
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert location.path == "/" and location.fragment == "workspace-detail"
    query = parse_qs(location.query)
    assert query["guide"] == ["consent"]
    flow = query["flow"][0]
    assert parse_context(flow)["request_id"]
    return token, flow, response.headers["location"]


@pytest.mark.parametrize("provider", ["claude_code", "codex"])
@pytest.mark.parametrize("duration", [30, 45, 60])
def test_inline_consent_to_saved_script_stays_in_workspace_without_repeated_ai(
    client, app, workspace_pipeline, monkeypatch, provider, duration,
):
    coordinator, backend, ai, sessions = workspace_pipeline
    token, flow, guide_url = inline_consent(client, app, provider, duration)
    before = stored_values(app)
    for _ in range(2):
        guide = client.get(guide_url)
        assert guide.status_code == 200
        assert 'data-workspace-detail' in guide.text
        assert 'action="/autopilot/confirm-start"' in guide.text
        assert 'name="workspace" value="true"' in guide.text
        assert 'name="consent" value="true" required' in guide.text
        assert "기사 비교·분석 1회" in guide.text and "계정 잔여량을 정확히 확인할 수 없습니다" in guide.text
    assert ai.calls == [] and stored_values(app) == before
    assert client.post("/autopilot/confirm-start", data={
        "csrf_token": token, "flow": flow, "workspace": "true",
    }).status_code == 422
    assert ai.calls == []
    data = {"csrf_token": token, "flow": flow, "consent": "true", "workspace": "true"}
    started = client.post("/autopilot/confirm-start", data=data, follow_redirects=False)
    assert started.status_code == 303
    identifier = parse_context(flow)["request_id"]
    assert started.headers["location"] == f"/?task={identifier}#workspace-detail"
    coordinator.future.result(timeout=15)
    snapshot = coordinator.snapshot(identifier)
    assert (snapshot["status"], snapshot["current_stage"]) == ("waiting_review", "script")
    assert snapshot["duration"] == duration and snapshot["news_method"] == "rss"
    assert snapshot["analysis_provider"] == snapshot["script_provider"] == provider
    assert [call[0] for call in ai.calls] == ["analysis", "script"]
    with sessions() as session:
        analysis = session.get(IntelligenceRun, snapshot["analysis_run_id"])
        script = session.get(IntelligenceRun, snapshot["script_run_id"])
        draft = session.get(ContentDraft, snapshot["content_draft_id"])
        assert analysis.provider == script.provider == provider
        assert draft.run_id == script.id and draft.duration == duration
        assert draft.review_status == "review_required"
        assert sum(scene["seconds"] for scene in draft.content["scenes"]) == duration
        assert session.scalar(select(func.count()).select_from(AIUsage)) == 2
    detail = client.get(started.headers["location"])
    assert detail.status_code == 200 and 'id="job-script"' in detail.text
    assert f'action="/autopilot/jobs/{identifier}/resume"' in detail.text
    assert stored_values(app) == before
    # Browser refresh, repeated confirmation and a recovered review pause do not regenerate.
    repeated = client.post("/autopilot/confirm-start", data=data, follow_redirects=False)
    assert repeated.headers["location"] == started.headers["location"]
    assert coordinator.recover() == 0 and len(ai.calls) == 2
    captured = {}

    def stop_before_render(context, *_):
        captured.update(context)
        raise BackendError(code="render_failed", retryable=False)

    monkeypatch.setattr(backend, "_render", stop_before_render)
    resumed = client.post(f"/autopilot/jobs/{identifier}/resume", data={
        "csrf_token": token, "revision": snapshot["revision"], "workspace": "true",
    }, follow_redirects=False)
    assert resumed.headers["location"] == started.headers["location"]
    coordinator.future.result(timeout=15)
    assert captured["duration"] == duration and captured["voice"] == "offline-silence"
    assert captured["analysis_run_id"] == snapshot["analysis_run_id"]
    assert captured["content_draft_id"] == snapshot["content_draft_id"] and len(ai.calls) == 2


@pytest.mark.parametrize("policy", ["ai_web", "hybrid"])
def test_blocked_search_is_inline_without_rss_or_paid_fallback(client, app, workspace_pipeline, policy):
    coordinator, _, ai, sessions = workspace_pipeline
    write_studio_settings(sessions, "codex", "default")
    save_values(app, autopilot_acquisition_policy=policy)
    before = stored_values(app)
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": csrf(client), "source": "feeds", "duration": 60, "workspace": "true",
    }, follow_redirects=False)
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert location.path == "/" and parse_qs(location.query)["guide"] == ["search"]
    guide = client.get(response.headers["location"])
    assert "AI 웹 뉴스 조사 BLOCKED" in guide.text and "RSS로 자동 전환하지 않았습니다" in guide.text
    assert 'action="/autopilot/confirm-start"' not in guide.text
    assert ai.calls == [] and coordinator.future is None and stored_values(app) == before
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AutopilotJob)) == 0


def test_unknown_script_result_remains_stopped_after_refresh_reconfirm_and_recovery(client, app, workspace_pipeline):
    coordinator, _, ai, sessions = workspace_pipeline
    ai.fail_kind, ai.error = "script", ProviderTimeoutError()
    token, flow, _ = inline_consent(client, app, "codex")
    data = {"csrf_token": token, "flow": flow, "consent": "true", "workspace": "true"}
    response = client.post("/autopilot/confirm-start", data=data, follow_redirects=False)
    coordinator.future.result(timeout=15)
    identifier = parse_context(flow)["request_id"]
    failed = coordinator.snapshot(identifier)
    assert failed["status"] == "failed" and failed["retryable"] is False
    assert client.get(response.headers["location"]).status_code == 200
    assert client.post("/autopilot/confirm-start", data=data, follow_redirects=False).headers["location"] == response.headers["location"]
    assert client.post(f"/autopilot/jobs/{identifier}/retry", data={
        "csrf_token": token, "revision": failed["revision"], "workspace": "true",
    }).status_code == 409
    coordinator.recover()
    assert len(ai.calls) == 2
    with sessions() as session:
        assert session.get(IntelligenceRun, failed["analysis_run_id"]).status == "success"
        assert session.get(IntelligenceRun, failed["script_run_id"]).status == "failed"
        assert session.scalar(select(func.count()).select_from(ContentDraft)) == 0


def test_workspace_confirmation_keeps_origin_csrf_and_request_identity(client, app, workspace_pipeline):
    _, _, ai, _ = workspace_pipeline
    token, flow, _ = inline_consent(client, app)
    data = {"flow": flow, "consent": "true", "workspace": "true"}
    assert client.post("/autopilot/confirm-start", data=data).status_code == 403
    assert client.post("/autopilot/confirm-start", data={**data, "csrf_token": token},
                       headers={"Origin": "https://foreign.example"}).status_code == 403
    missing_identity = parse_context(flow)
    missing_identity.pop("request_id")
    assert client.post("/autopilot/confirm-start", data={
        **data, "csrf_token": token, "flow": context_json(missing_identity),
    }).status_code == 422
    assert ai.calls == []


@pytest.mark.parametrize("query", ["guide=consent", "guide=invalid", "guide=consent&flow={}",
                                   "guide=search&task=missing", "guide=search&video=1"])
def test_invalid_workspace_guide_never_runs_ai(client, workspace_pipeline, query):
    _, _, ai, _ = workspace_pipeline
    assert client.get("/?" + query).status_code == 422
    assert ai.calls == []
