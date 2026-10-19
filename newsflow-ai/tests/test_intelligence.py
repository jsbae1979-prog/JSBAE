import json
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import csrf
from sqlalchemy import select, text

from newsflow.db.models import ContentDraft, IntelligenceRun, NewsArticle, NewsSource
from newsflow.db.session import migrate
from newsflow.intelligence.provider import (
    FakeProvider,
    OfflineProvider,
    OpenAIProvider,
    Options,
    ProviderError,
)
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.intelligence.settings import write_settings


@pytest.fixture
def intelligence(app):
    with app.state.sessions.begin() as session:
        source = session.scalar(select(NewsSource))
        session.add(
            NewsArticle(
                title="한국 우주 기술 발표",
                summary="관계 기관에서 신규 연구 계획을 발표했다고 보도했습니다.",
                url="https://example.com/news/1",
                canonical_url="https://example.com/news/1",
                source_id=source.id,
                publisher="합성 출처 A",
            )
        )
        session.add(
            NewsArticle(
                title="한국 우주 기술 발표 소식",
                summary="독립 사실 확인되지 않은 합성 RSS 요약",
                url="https://example.org/news/2",
                canonical_url="https://example.org/news/2",
                source_id=source.id,
                publisher="합성 출처 B",
            )
        )
    # Phase 5C: external mode additionally requires the stored approval and a monthly limit.
    write_settings(app.state.sessions, "openai", "gpt-4o-mini", True, 1_000_000, 20)
    return IntelligenceService(app.state.sessions)


def test_analysis_preserves_unknown_and_groups(intelligence, app):
    identifier = intelligence.analyze([1, 2])
    with app.state.sessions() as session:
        run = session.get(IntelligenceRun, identifier)
        assert run.status == "success"
        assert run.evidence["groups"] == [[1, 2]]
        article = run.evidence["articles"][0]
        assert article["published_at"] is None and article["score"] is None
        assert article["verification"] == "unverified" and article["confidence"] == "미평가"
        assert article["sources"][0]["url"] == "https://example.com/news/1"
        assert "미측정" in article["popularity"]


@pytest.mark.parametrize("ids", [[], [1, 1], [999], list(range(11))])
def test_invalid_selection(intelligence, ids):
    with pytest.raises(IntelligenceError):
        intelligence.analyze(ids)


@pytest.mark.parametrize("duration", [30, 45, 60])
def test_offline_script_sources_and_draft(intelligence, app, duration):
    identifier = intelligence.generate(intelligence.analyze([1, 2]), duration)
    with app.state.sessions() as session:
        draft = session.get(ContentDraft, identifier)
        assert sum(s["seconds"] for s in draft.content["scenes"]) == duration
        assert draft.review_status == "review_required"
        assert len(draft.sources["articles"]) == 2
        assert "원문 전체 복제 금지" in draft.sources["caution"]
        assert session.get(IntelligenceRun, draft.run_id).provider == "offline"


def test_fake_adapter(intelligence, app):
    fake = FakeProvider()
    identifier = intelligence.analyze([1])
    intelligence.provider = fake
    intelligence.generate(identifier, 30)
    assert fake.calls == 1


@pytest.mark.parametrize("error", [TimeoutError("SECRET"), ProviderError("SECRET"), RuntimeError("SECRET")])
def test_provider_failure_history_no_sensitive_data(intelligence, app, error):
    identifier = intelligence.analyze([1])
    intelligence.provider = FakeProvider(error)
    with pytest.raises(IntelligenceError):
        intelligence.generate(identifier, 30)
    with app.state.sessions() as session:
        run = session.scalar(select(IntelligenceRun).where(IntelligenceRun.kind == "script"))
        assert run.status == "failed" and run.finished_at
        assert "SECRET" not in run.message
        assert session.scalar(select(ContentDraft)) is None


def test_external_consent_and_missing_key(intelligence, monkeypatch):
    monkeypatch.delenv("NEWSFLOW_AI_API_KEY", raising=False)
    identifier = intelligence.analyze([1])
    with patch("urllib.request.OpenerDirector.open") as call:
        with pytest.raises(IntelligenceError):
            intelligence.generate(identifier, 30, "openai")
        with pytest.raises(IntelligenceError):
            intelligence.generate(identifier, 30, "openai", True)
        call.assert_not_called()


@pytest.mark.parametrize(
    "options", [{"model": "../secret"}, {"temperature": 2}, {"timeout": 0}, {"max_tokens": 99999}]
)
def test_option_validation(options):
    with pytest.raises(ValueError):
        Options(**options)


@pytest.mark.parametrize(
    "output",
    [
        None,
        {"title": "incomplete"},
        {"title": "x", "hook": "x", "summary": "x", "scenes": []},
        {
            "title": "x",
            "hook": "x",
            "summary": "x",
            "scenes": [{"seconds": 30, "narration": "x", "caption": "x", "material": "x"}],
            "verified": True,
        },
    ],
)
def test_invalid_response(intelligence, output):
    identifier = intelligence.analyze([1])
    intelligence.provider = FakeProvider(output if output is not None else {"bad": "response"})
    with pytest.raises(IntelligenceError):
        intelligence.generate(identifier, 30)


def test_edit_revision_and_sources_immutable(intelligence, app):
    identifier = intelligence.generate(intelligence.analyze([1]), 30)
    with app.state.sessions() as session:
        draft = session.get(ContentDraft, identifier)
        content, sources = draft.content, draft.sources
    content["title"] = "수정한 검토용 제목"
    intelligence.edit(identifier, 1, content)
    with pytest.raises(IntelligenceError):
        intelligence.edit(identifier, 1, content)
    with app.state.sessions() as session:
        draft = session.get(ContentDraft, identifier)
        assert (
            draft.revision == 2
            and draft.sources == sources
            and draft.content["title"] == "수정한 검토용 제목"
        )
        assert draft.review_status == "review_required"


def test_secret_and_sensational_output_blocked(intelligence, monkeypatch):
    monkeypatch.setenv("NEWSFLOW_AI_API_KEY", "TEST-KEY-DO-NOT-EXPOSE")
    output = OfflineProvider().complete({"articles": [{"title": "주제"}]}, 30, Options())
    identifier = intelligence.analyze([1])
    for title in ["TEST-KEY-DO-NOT-EXPOSE", "충격! 확정 뉴스", "100% 확실"]:
        output["title"] = title
        intelligence.provider = FakeProvider(output)
        with pytest.raises(IntelligenceError):
            intelligence.generate(identifier, 30)


def test_gui_analysis_generate_edit_and_key_hidden(intelligence, client, monkeypatch):
    monkeypatch.setenv("NEWSFLOW_AI_API_KEY", "SECRET-NEVER-HTML")
    assert client.get("/ai").status_code == 200
    response = client.post("/ai/analyze", data={"csrf_token": csrf(client), "article_ids": ["1", "2"]})
    assert response.status_code == 200 and "사실 확인: 미확인" in response.text
    response = client.post(
        "/ai/generate", data={"csrf_token": csrf(client), "analysis_id": 1, "duration": 45}
    )
    assert (
        response.status_code == 200 and "45초" in response.text and "SECRET-NEVER-HTML" not in response.text
    )
    with intelligence.sessions() as session:
        content = session.get(ContentDraft, 1).content
    content["title"] = "<script>alert(1)</script>"
    response = client.post(
        "/ai/drafts/1", data={"csrf_token": csrf(client), "revision": 1, "content": json.dumps(content)}
    )
    assert response.status_code == 200
    assert "&lt;script&gt;" in response.text and "<script>alert(1)</script>" not in response.text
    assert client.get("/ai?draft_id=999").status_code == 404
    assert client.get("/ai?analysis_id=999").status_code == 404


def test_ai_csrf_and_external_consent(intelligence, client):
    assert client.post("/ai/analyze", data={"article_ids": 1}).status_code == 403
    identifier = intelligence.analyze([1])
    token = csrf(client)
    assert (
        client.post(
            "/ai/generate",
            data={"csrf_token": token, "analysis_id": identifier, "duration": 30, "provider": "openai"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/ai/analyze", data={"csrf_token": token, "article_ids": 1}, headers={"Origin": "null"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/ai/generate", data={"csrf_token": token, "analysis_id": identifier, "duration": 29}
        ).status_code
        == 422
    )


def test_upgrade_phase1_preserves_data(app):
    from alembic import command
    from alembic.config import Config

    # A fresh Phase 1 schema upgraded with stored articles and settings.
    from newsflow.db.session import make_engine

    engine = make_engine(app.state.config.data_dir / "legacy.db")
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parents[1] / "src/newsflow/db/migrations"))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "0001")
        connection.execute(text("INSERT INTO app_settings (key,value) VALUES ('request_timeout','7')"))
    migrate(engine)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT value FROM app_settings WHERE key='request_timeout'")) == "7"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0014"
    engine.dispose()


def test_openai_timeout_and_safe_error(monkeypatch):
    monkeypatch.setenv("NEWSFLOW_AI_API_KEY", "SECRET")
    for error in [TimeoutError("SECRET"), RuntimeError("SECRET")]:
        with (
            patch("urllib.request.OpenerDirector.open", side_effect=error),
            pytest.raises(ProviderError) as raised,
        ):
            OpenAIProvider().complete({}, 30, Options())
        assert "SECRET" not in str(raised.value)


def test_external_analysis_consent_and_failure(intelligence, app):
    fake = FakeProvider()
    intelligence.provider = fake
    with pytest.raises(IntelligenceError):
        intelligence.analyze([1], "openai", False)
    assert fake.calls == 0
    identifier = intelligence.analyze([1, 2], "openai", True)
    assert fake.calls == 1
    with app.state.sessions() as session:
        run = session.get(IntelligenceRun, identifier)
        assert run.provider == "openai" and run.status == "success"
        assert "미확인" in run.result["comparisons"][0]["uncertainties"]
    intelligence.provider = FakeProvider(TimeoutError("SECRET"))
    with pytest.raises(IntelligenceError):
        intelligence.analyze([1], "openai", True)
    with app.state.sessions() as session:
        run = session.scalar(select(IntelligenceRun).order_by(IntelligenceRun.id.desc()))
        assert run.status == "failed" and "SECRET" not in run.message


def test_analysis_unknown_citations_blocked(intelligence):
    intelligence.provider = FakeProvider(
        {
            "overview": "가짜 근거",
            "comparisons": [{"article_ids": [999], "reason": "설명", "uncertainties": "미확인"}],
        }
    )
    with pytest.raises(IntelligenceError):
        intelligence.analyze([1])


def test_full_summary_copy_blocked(intelligence, app):
    summary = "저작권 보호 뉴스의 긴 요약을 그대로 복제하지 않도록 확인하는 테스트입니다." * 4
    with app.state.sessions.begin() as session:
        session.get(NewsArticle, 1).summary = summary
    analysis_id = intelligence.analyze([1])
    output = OfflineProvider().complete({"articles": [{"title": "주제"}]}, 30, Options())
    output["summary"] = summary
    intelligence.provider = FakeProvider(output)
    with pytest.raises(IntelligenceError):
        intelligence.generate(analysis_id, 30)


def test_gui_structured_editor(intelligence, client):
    identifier = intelligence.generate(intelligence.analyze([1]), 30)
    response = client.post(
        f"/ai/drafts/{identifier}",
        data={
            "csrf_token": csrf(client),
            "revision": 1,
            "title": "구조화된 수정",
            "hook": "후킹 문구",
            "summary": "검토 요약",
            "seconds": ["10", "10", "10"],
            "narration": ["미확인 보도 소개"] * 3,
            "caption": ["검토 필요"] * 3,
            "material": ["직접 제작할 소재"] * 3,
        },
    )
    assert response.status_code == 200 and "구조화된 수정" in response.text


def test_openai_fixed_tls_destination_and_json(monkeypatch):
    from io import BytesIO

    monkeypatch.setenv("NEWSFLOW_AI_API_KEY", "SYNTHETIC-API-KEY")
    response = BytesIO(
        json.dumps(
            {
                "choices": [
                    {"message": {"content": json.dumps({"overview": "보도 기반 검토", "comparisons": []})}}
                ]
            }
        ).encode()
    )
    with patch("urllib.request.OpenerDirector.open", return_value=response) as call:
        result = OpenAIProvider().analyze({"articles": []}, Options(timeout=7))
    assert result["overview"] == "보도 기반 검토"
    request = call.call_args.args[0]
    assert request.full_url == "https://api.openai.com/v1/chat/completions"
    assert call.call_args.kwargs["timeout"] == 7
    payload = json.loads(request.data)
    assert payload["messages"][1]["content"] == json.dumps({"evidence": {"articles": []}}, ensure_ascii=False)
    assert "SYNTHETIC-API-KEY" not in request.data.decode()
    from newsflow.intelligence.provider import NoRedirect

    assert NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://evil.example") is None


def test_analysis_preserves_provenance_and_score(intelligence, app):
    from newsflow.db.models import ArticleMention, ArticleScore

    with app.state.sessions.begin() as session:
        session.add(
            ArticleMention(
                article_id=1, source_id=1, publisher="추가 보도", url="https://source.example/original"
            )
        )
        session.add(
            ArticleScore(
                article_id=1,
                total=10,
                assessed_max=30,
                components={"최신성": {"value": 10, "reason": "합성 근거"}},
            )
        )
    identifier = intelligence.analyze([1])
    with app.state.sessions() as session:
        article = session.get(IntelligenceRun, identifier).evidence["articles"][0]
        assert len(article["sources"]) == 2
        assert article["score"]["reasons"]["최신성"]["reason"] == "합성 근거"
        assert article["confidence"] == "미평가"


def test_interrupted_execution_is_not_retried(intelligence, app):
    from newsflow.main import create_app

    with app.state.sessions.begin() as session:
        session.add(
            IntelligenceRun(
                kind="script",
                provider="openai",
                status="running",
                options={},
                evidence={},
                result={},
                message="실행 중",
            )
        )
    restarted = create_app(app.state.config)
    with restarted.state.sessions() as session:
        run = session.scalar(select(IntelligenceRun))
        assert run.status == "interrupted" and run.finished_at
    restarted.state.coordinator.close()
    restarted.state.engine.dispose()
