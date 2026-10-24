"""Codex Studio choices are durable UI preferences, not execution or billing consent."""

import pytest
from conftest import csrf
from fastapi.testclient import TestClient
from sqlalchemy import select

from newsflow.config import Settings
from newsflow.db.models import AIUsage, CollectionRun, ContentDraft, IntelligenceRun, NewsArticle, NewsSource
from newsflow.intelligence import claude_code, codex
from newsflow.intelligence.presentation import presentation
from newsflow.intelligence.provider import FakeProvider, OpenAIProvider, Options
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.intelligence.settings import (
    SettingsError,
    read_settings,
    read_studio_settings,
    write_settings,
    write_studio_settings,
)
from newsflow.main import create_app
from newsflow.news.collector import Collector
from newsflow.news.service import NewsService
from newsflow.video.tts import WindowsTTS


def test_codex_defaults_restart_without_cli_or_approval_changes(tmp_path, fake, monkeypatch):
    monkeypatch.setattr(codex.CODEX_PROVIDER, "status", lambda: pytest.fail("automatic Codex check"))
    monkeypatch.setattr(codex.CODEX_PROVIDER, "analyze", lambda *a, **k: pytest.fail("implicit analysis"))
    monkeypatch.setattr(codex.CODEX_PROVIDER, "complete", lambda *a, **k: pytest.fail("implicit script"))
    config = Settings(data_dir=tmp_path / "persistent")
    original = None
    for restart in (False, True):
        app = create_app(config, fake)
        with TestClient(app, base_url="http://127.0.0.1") as client:
            token = csrf(client)
            if not restart:
                write_settings(app.state.sessions, "openai", "gpt-4o-mini", True, 1000, 20)
                original = read_settings(app.state.sessions)
                write_studio_settings(app.state.sessions, "claude_code", "opus")
                response = client.post("/ai/preferences", data={"csrf_token": token,
                                       "provider": "codex", "model": "default"})
                assert response.status_code == 200
                assert response.url.fragment == "codex-connection"
            saved = read_studio_settings(app.state.sessions)
            assert saved["provider"] == "codex" and saved["model"] == "default"
            assert saved["models"]["claude_code"] == "opus"
            assert read_settings(app.state.sessions) == original
            page = client.get("/ai")
            assert page.status_code == 200
            assert 'value="codex" selected' in page.text and 'value="default"' in page.text
            assert "RSS 자료 분석" in page.text and "웹 검색을 실행하지 않습니다" in page.text
            assert "무료·무제한이 아닙니다" in page.text
            assert 'href="/simple-settings#connections"' in page.text
            settings = client.get("/simple-settings")
            assert settings.status_code == 200
            assert 'action="/ai/codex/status"' in settings.text
            assert 'action="/ai/claude/login"' in settings.text
            assert 'action="/ai/codex/login"' not in settings.text
            assert 'value="codex" selected' in settings.text and 'value="default"' in settings.text
            assert "content-security-policy" in page.headers


@pytest.mark.parametrize("model", ["../secret", "model;command", "", "a" * 81])
def test_codex_model_validation_is_atomic(app, model):
    write_studio_settings(app.state.sessions, "claude_code", "sonnet")
    with pytest.raises(SettingsError):
        write_studio_settings(app.state.sessions, "codex", model)
    assert read_studio_settings(app.state.sessions)["provider"] == "claude_code"


def test_codex_custom_model_preserves_provider_models(app):
    write_studio_settings(app.state.sessions, "codex", "account-model-v1")
    write_studio_settings(app.state.sessions, "claude_code", "sonnet")
    values = read_studio_settings(app.state.sessions)
    assert values["model"] == "sonnet"
    assert values["models"]["codex"] == "account-model-v1"


@pytest.mark.parametrize("path", ["/ai/codex/status", "/ai/codex/cancel"])
def test_codex_status_cancel_csrf_and_origin(client, path):
    assert client.post(path, data={}).status_code == 403
    assert client.post(path, data={"csrf_token": csrf(client)},
                       headers={"Origin": "https://attacker.invalid"}).status_code == 403


def test_codex_explicit_status_cache_cancel_without_inference(client, app, monkeypatch):
    calls = []
    result = {"state": "ready", "installed": True, "authenticated": True, "ready": True,
              "version": "1.2.3", "checked_at": "2026-10-16T00:00:00+00:00",
              "message": "연결 준비 완료", "web_search_verified": False}
    monkeypatch.setattr(codex.CODEX_PROVIDER, "status", lambda: calls.append("status") or result.copy())
    monkeypatch.setattr(codex.CODEX_PROVIDER, "cancel", lambda: calls.append("cancel") or False)
    monkeypatch.setattr(codex.CODEX_PROVIDER, "analyze", lambda *a, **k: pytest.fail("implicit analysis"))
    monkeypatch.setattr(codex.CODEX_PROVIDER, "complete", lambda *a, **k: pytest.fail("implicit script"))
    token = csrf(client)
    assert client.get("/ai").status_code == 200 and not calls
    status = client.post("/ai/codex/status", data={"csrf_token": token})
    assert status.status_code == 200 and status.json()["ready"] is True
    assert status.json()["web_search_verified"] is False
    assert status.json()["local_usage"]["calls"] == 0
    assert app.state.codex_status == result
    assert "연결 준비 완료" in client.get("/simple-settings").text
    assert calls == ["status"]
    assert client.post("/ai/codex/cancel", data={"csrf_token": token}).json() == {"cancel_requested": False}
    assert calls == ["status", "cancel"]


def test_codex_rss_analysis_script_and_video_flow(client, app, fake, monkeypatch):
    """Exercise the real collector/storage/service/routes with an explicitly fake Codex."""
    news = NewsService(app.state.sessions, Collector(fake))
    with app.state.sessions.begin() as session:
        source = session.scalar(select(NewsSource).where(NewsSource.url == "https://example.com/rss"))
        if source is None:
            source = NewsSource(name="합성 RSS 검증", url="https://example.com/rss", enabled=True)
            session.add(source)
            session.flush()
        source_id = source.id
    for repeat in (False, True):
        with app.state.sessions.begin() as session:
            run = CollectionRun()
            session.add(run)
            session.flush()
            collection_id = run.id
        news.collect(collection_id, [source_id])
        with app.state.sessions() as session:
            run = session.get(CollectionRun, collection_id)
            assert run.status == "success" and run.failed == 0
            assert (run.added, run.duplicates) == ((0, 3) if repeat else (3, 0))
            ids = list(session.scalars(select(NewsArticle.id).order_by(NewsArticle.id)))
            assert len(ids) == 3

    # FakeProvider uses OfflineProvider's schema-valid analysis/script implementation.
    fake_codex = FakeProvider(usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12})
    fake_codex.last_model = "fixture-codex"
    original_claude = claude_code.CLAUDE_PROVIDER
    monkeypatch.setattr(codex, "CODEX_PROVIDER", fake_codex)
    monkeypatch.setattr(original_claude, "analyze", lambda *a, **k: pytest.fail("Claude was selected"))
    monkeypatch.setattr(original_claude, "complete", lambda *a, **k: pytest.fail("Claude was selected"))
    monkeypatch.setattr(OpenAIProvider, "analyze", lambda *a, **k: pytest.fail("OpenAI was selected"))
    monkeypatch.setattr(OpenAIProvider, "complete", lambda *a, **k: pytest.fail("OpenAI was selected"))
    monkeypatch.setattr(WindowsTTS, "voice_details", lambda self: [])
    original_settings = read_settings(app.state.sessions)
    assert original_settings.provider == "offline" and not original_settings.approved
    intelligence = IntelligenceService(app.state.sessions)
    with pytest.raises(IntelligenceError) as denied:
        intelligence.analyze(ids, "codex", False, Options(model="default"))
    assert denied.value.code == "ai_consent" and fake_codex.calls == 0

    token = csrf(client)
    response = client.post("/ai/analyze", data={"csrf_token": token, "article_ids": ids,
                           "provider": "codex", "consent": "true", "model": "default"})
    assert response.status_code == 200
    analysis_id = int(response.url.params["analysis_id"])
    with app.state.sessions() as session:
        analysis = session.get(IntelligenceRun, analysis_id)
        assert analysis.status == "success" and analysis.provider == "codex"
        evidence = analysis.evidence
        assert {item["id"] for item in evidence["articles"]} == set(ids)
        assert {source["url"] for item in evidence["articles"] for source in item["sources"]} == {
            "https://example.com/news/1", "https://example.com/news/2", "https://example.com/news/3",
        }
        assert evidence["articles"][2]["published_at"] is None
        assert all(item["verification"] == "unverified" for item in evidence["articles"])
    with pytest.raises(IntelligenceError) as denied:
        intelligence.generate(analysis_id, 30, "codex", False, Options(model="default"))
    assert denied.value.code == "ai_consent" and fake_codex.calls == 1

    for duration in (30, 45, 60):
        response = client.post("/ai/generate", data={"csrf_token": token, "analysis_id": analysis_id,
                               "duration": duration, "provider": "codex", "consent": "true", "model": "default"})
        assert response.status_code == 200
        draft_id = int(response.url.params["draft_id"])
        with app.state.sessions() as session:
            draft = session.get(ContentDraft, draft_id)
            assert draft.duration == duration
            assert draft.sources == {**evidence, "presentation": presentation()}
            assert draft.review_status == "review_required"
            assert sum(scene["seconds"] for scene in draft.content["scenes"]) == duration
            assert session.get(IntelligenceRun, draft.run_id).provider == "codex"
        assert f'href="/video?draft_id={draft_id}"' in response.text
        video = client.get(f"/video?draft_id={draft_id}")
        assert video.status_code == 200 and f'value="{duration}" selected' in video.text
        assert f'name="draft_id" value="{draft_id}"' in video.text
        assert 'value="offline-silence" selected' in video.text

    assert fake_codex.calls == 4 and claude_code.CLAUDE_PROVIDER is original_claude
    assert read_settings(app.state.sessions) == original_settings
    with app.state.sessions() as session:
        usage = list(session.scalars(select(AIUsage)))
        assert len(usage) == 4 and all(row.provider == "codex" for row in usage)
        assert all(row.model == "fixture-codex" and row.status == "success" for row in usage)
        assert sum(row.total_tokens for row in usage) == 48
