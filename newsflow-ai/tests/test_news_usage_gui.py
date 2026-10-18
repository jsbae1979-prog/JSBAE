"""News-use choices and review notices; isolated data and no provider calls."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import csrf
from test_single_workspace import save_values, stored_values

from newsflow.db.models import NewsSource
from newsflow.gui.production_context import context_json, parse_context, validate_context
from newsflow.intelligence.settings import write_studio_settings
from newsflow.video.supertonic_tts import SupertonicTTS
from newsflow.video.tts import WindowsTTS


@pytest.fixture(autouse=True)
def local_fixture_voice_catalog(monkeypatch):
    monkeypatch.setattr(WindowsTTS, "voice_details", lambda self: [])
    monkeypatch.setattr(SupertonicTTS, "voices", lambda self: [])


@pytest.fixture
def capture_start(app, monkeypatch):
    write_studio_settings(app.state.sessions, "offline", "offline")
    save_values(app, video_default_voice="offline-silence", autopilot_acquisition_policy="rss")
    with app.state.sessions.begin() as session:
        session.add(NewsSource(name="Fixture source", url="https://example.com/news-use-rss", enabled=True))
    calls = []

    def start(**kwargs):
        calls.append(kwargs)
        return "f" * 32

    monkeypatch.setattr(app.state.autopilot, "start", start)
    return calls


def initial_context():
    return {"source": "feeds", "initial_duration": 30, "initial_provider": "offline",
            "initial_model": "offline", "initial_voice": "offline-silence", "acquisition_policy": "rss"}


def test_workspace_offers_one_news_usage_choice_with_standard_default(client, app):
    before = stored_values(app)
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert html.count('name="news_usage"') == 1
    choice = re.search(r'<select id="quick-news-usage"[^>]*>(.*?)</select>', html, re.DOTALL).group(1)
    assert re.findall(r'<option value="([^"]+)"', choice) == ["QUICK", "STANDARD"]
    assert '<option value="STANDARD" selected>' in choice
    assert all(label in choice for label in ("빠른 제작", "균형 제작"))
    assert "검증 우선" not in choice  # unsupported for new production; historical cases below remain covered
    assert 'aria-describedby="news-usage-help"' in html
    assert "목록 페이지는 주제 참고용" in html
    assert "선택한 AI" in html and "이번 분석 · 대본" not in html
    assert "API 선택 시 해당 API로 분석·대본을 만듭니다" in html
    assert stored_values(app) == before


@pytest.mark.parametrize("source", ["sample", "feeds"])
@pytest.mark.parametrize("mode", ["QUICK", "STANDARD", "VERIFIED"])
def test_workspace_passes_news_usage_to_coordinator_without_changing_settings(client, app, capture_start, source, mode):
    before = stored_values(app)
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": csrf(client), "source": source, "duration": 45, "workspace": "true",
        "acquisition_policy": "rss", "news_usage": mode,
    }, follow_redirects=False)
    assert response.status_code == 303
    assert capture_start[0]["news_usage"] == mode
    assert capture_start[0]["duration"] == 45 and capture_start[0]["source"] == source
    assert len(capture_start) == 1 and stored_values(app) == before


def test_legacy_workspace_post_defaults_to_standard(client, capture_start):
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": csrf(client), "source": "sample", "duration": 30,
    }, follow_redirects=False)
    assert response.status_code == 303 and capture_start[0]["news_usage"] == "STANDARD"
    assert validate_context(initial_context())["news_usage"] == "STANDARD"


@pytest.mark.parametrize("mode", ["quick", "FAST", "VERIFIED_PASS", "<script>"])
def test_invalid_news_usage_never_starts_work(client, capture_start, mode):
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": csrf(client), "source": "sample", "duration": 30, "news_usage": mode,
    }, follow_redirects=False)
    assert response.status_code == 422 and capture_start == []


@pytest.mark.parametrize("mode", ["QUICK", "STANDARD", "VERIFIED"])
def test_context_preserves_news_usage_and_ignores_claimed_verification(mode):
    value = {**initial_context(), "news_usage": mode, "news_usage_result": {"verification_status": "PASS"}}
    restored = parse_context(context_json(value))
    assert restored["news_usage"] == mode
    assert "news_usage_result" not in restored


@pytest.mark.parametrize("mode", ["QUICK", "VERIFIED"])
def test_external_consent_preserves_mode_and_does_not_grant_any_saved_approval(
    client, app, capture_start, monkeypatch, mode,
):
    write_studio_settings(app.state.sessions, "claude_api", "claude-sonnet-4-6")
    # Presentation gate fixture: no authentication lookup, CLI, API or inference.
    gate = {"ready": True, "authentication_verified": True, "reasons": [],
            "settings": {"request_limit_usd": "3.10", "monthly_limit_usd": "100"}}
    monkeypatch.setattr("newsflow.gui.autopilot_routes.readiness", lambda request: {
        "voice": {"name": "offline-silence", "silent": True, "installed": True},
        "rss": {"enabled": 1, "tested": 0, "ready": True}, "ai": {"reasons": []},
        "apis": {"claude_api": {"analysis": gate, "search": gate}},
    })
    before = stored_values(app)
    token = csrf(client)
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": token, "source": "feeds", "duration": 30, "workspace": "true",
        "acquisition_policy": "ai_web", "news_usage": mode,
    }, follow_redirects=False)
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["guide"] == ["consent"] and capture_start == []
    flow = query["flow"][0]
    assert parse_context(flow)["news_usage"] == mode
    guide = client.get(response.headers["location"])
    assert guide.status_code == 200
    if mode == "VERIFIED":
        assert '<option value="VERIFIED"' not in guide.text
        assert "검증 우선" in guide.text  # preserve the legacy flow record, never offer it for new production
    else:
        assert f'<option value="{mode}" selected>' in guide.text
    assert "검색 도구 최대 1회" in guide.text and "자동 재검색은 없습니다" in guide.text
    assert "기사 비교·분석 1회" in guide.text and "대본 1회" in guide.text
    assert "분석·대본의 추가 AI 호출과 자동 재검색은 없습니다" not in guide.text
    if mode == "VERIFIED":
        assert "독립적인 원문·발행일·핵심 사실 확인 근거가 없으면 대본 제작을 중단" in guide.text
        assert "신규 API 제작은 실행하지 않습니다" in guide.text
    else:
        assert "실패 시 로컬 템플릿이나 다른 Provider로 전환하지 않습니다" in guide.text
    data = {"csrf_token": token, "flow": flow, "workspace": "true"}
    assert client.post("/autopilot/confirm-start", data=data).status_code == 422
    assert capture_start == []
    approved = client.post("/autopilot/confirm-start", data={**data, "consent": "true"}, follow_redirects=False)
    assert approved.status_code == 303 and len(capture_start) == 1
    assert capture_start[0]["news_usage"] == mode
    assert capture_start[0]["external_consent"] is True and capture_start[0]["acquisition_policy"] == "ai_web"
    assert stored_values(app) == before


@pytest.mark.parametrize("mode,approach", [("QUICK", "topic"), ("STANDARD", "topic"), ("VERIFIED", "blocked")])
def test_saved_task_shows_mode_and_application_without_verified_pass(client, app, monkeypatch, mode, approach):
    identifier = "a" * 32
    snapshot = {
        "id": identifier, "status": "failed" if approach == "blocked" else "waiting_review",
        "current_stage": "script", "stage_label": "대본 작성", "stage_results": {},
        "ai_mode": "claude_api", "ai_model": "claude-sonnet-4-6", "duration": 30,
        "progress": 35, "updated_at": "2026-10-17T00:00:00+00:00", "source": "feeds",
        "content_mode": "real", "mode": "guided", "platform": "youtube", "voice": "offline-silence",
        "revision": 1, "review_pauses": ["script", "validate"], "retryable": False,
        "content_draft_id": None, "render_job_id": None, "article_id": None,
        "analysis_run_id": None, "search_run_id": None, "script_run_id": None,
        "message": "합성 UI 기록", "candidates": [], "news_usage": mode,
        "error_code": "news_evidence_required" if approach == "blocked" else None,
        "news_usage_result": {"mode": mode, "approach": approach, "source_kind": "collection",
                              "verification_status": "NOT VERIFIED", "message": "원문 미검증 · 합성 UI 결과"},
    }
    if approach == "topic":
        snapshot["script_method"] = "local_topic_template"
    monkeypatch.setattr(app.state.autopilot, "list_jobs", lambda limit=100: [snapshot])
    monkeypatch.setattr(app.state.autopilot, "snapshot", lambda job_id: dict(snapshot))
    before = stored_values(app)
    for path in (f"/?task={identifier}", f"/autopilot/jobs/{identifier}"):
        response = client.get(path)
        assert response.status_code == 200
        assert "뉴스 활용 수준:" in response.text and mode in response.text
        assert "원문 미검증 · 합성 UI 결과" in response.text and "NOT VERIFIED" in response.text
        assert "VERIFIED PASS" not in response.text
        if approach == "topic":
            assert "주제 설명 템플릿 · 추가 AI 호출 없음" in response.text
    assert stored_values(app) == before
