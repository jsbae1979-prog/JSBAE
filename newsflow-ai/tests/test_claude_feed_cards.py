"""Claude card JSON + local raster, using synthetic credentials/data and Fake only."""
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from conftest import csrf
from PIL import Image
from sqlalchemy import select
from test_api_settings import configured
from test_image_posts import article
from test_image_selection import selected

from newsflow.db.models import APIRequestReservation, AppSetting, IntelligenceRun
from newsflow.intelligence.api_settings import APIBudgetService, FakeAPIBudgetService
from newsflow.intelligence.provider import Options
from newsflow.publishing.claude_cards import ClaudeCardAdapter
from newsflow.publishing.service import PublishingError

MODEL = "claude-sonnet-4-6"
KEY = "sk-fake-claude-card-not-a-real-key"
PLAN = {"title": "도서관에서 함께 읽는 책", "body": "도서관 독서 모임을 소개하는 합성 자료입니다.",
        "palette": "teal", "icon": "book", "source_article_ids": [1],
        "design": {"version": 2, "layout": "visual_first", "accent": "mint", "elements": [
            {"kind": "symbol", "x": 250, "y": 100, "width": 500, "height": 800,
             "color": "accent", "symbol": "book", "points": [], "line_width": 4}]}}


class FakeCard:
    def __init__(self):
        self.calls, self.change, self.failure = [], {}, None
        self.last_usage = None
        self.last_elapsed_ms = 1

    def plan(self, source, options):
        self.calls.append((source, options))
        if self.failure:
            raise self.failure
        self.last_usage = {"prompt_tokens": 150, "completion_tokens": 100, "total_tokens": 250}
        return {**PLAN, "source_article_ids": source["source_article_ids"], **self.change}

    def plan_image(self, source, options):
        result = self.plan(source, options)
        return {"title": result["title"], "body": result["body"],
                "source_article_ids": result["source_article_ids"],
                "image_prompt": "도서관과 책을 중심으로 그림과 한글 제목을 배치한 전체 뉴스 이미지를 구성한다."}


@pytest.fixture(autouse=True)
def deny_external(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("External network forbidden")
    monkeypatch.setattr("urllib.request.OpenerDirector.open", deny)


@pytest.fixture
def prepared(app):
    service = app.state.claude_cards
    service.keys = SimpleNamespace(key=lambda: KEY, status=lambda: {"configured": True})
    service.adapter = FakeCard()
    service.budget = FakeAPIBudgetService(app.state.sessions)
    configured(app.state.sessions, search_approved=False)
    return service, article(app)


def call(service, news, **changes):
    return service.generate(news, **({"model": MODEL, "consent": True} | changes))


def test_no_openai_required_single_call_and_settings_unchanged(app, prepared):
    service, news = prepared
    with app.state.sessions() as session:
        before = {s.key: s.value for s in session.scalars(select(AppSetting))}
    identifier = call(service, news)
    assert call(service, news) == identifier and len(service.adapter.calls) == 1
    run = service.get(identifier)
    assert run.status == "success" and run.provider == "claude_api"
    assert run.options["model"] == MODEL and run.result["plan"]["palette"] == "teal"
    with app.state.sessions() as session:
        rows = {s.key: s.value for s in session.scalars(select(AppSetting))}
        assert all(rows[k] == v for k, v in before.items())
        record = session.scalar(select(APIRequestReservation))
        assert record.request_id == f"feed-card:{identifier}"
        assert record.kind == "script" and record.usage["search_calls"] == 0
        assert Decimal(record.reserved_usd) == Decimal('0.222000') and record.status == "success"
    assert not app.state.api_keys["openai"].status()["configured"]


def test_consent_model_and_actual_auth_gate(prepared):
    service, news = prepared
    with pytest.raises(PublishingError):
        call(service, news, consent=False)
    with pytest.raises(PublishingError):
        call(service, news, model="some-other-model")
    service.budget = APIBudgetService(service.sessions)
    result = call(service, news)
    assert service.get(result).status == "blocked"
    assert not service.adapter.calls


@pytest.mark.parametrize("change", [
    {"source_article_ids": [999]}, {"source_article_ids": [1, 1]},
    {"palette": "javascript:evil"}, {"icon": "external-svg"},
    {"title": "가" * 61}, {"body": "나" * 201},
    {"image_url": "https://example.com/picture"}, {"body": KEY},
])
def test_invalid_output_safe_and_not_retried(prepared, change):
    service, news = prepared
    service.adapter.change = change
    identifier = call(service, news)
    assert service.get(identifier).status == "unknown"
    assert call(service, news) == identifier and len(service.adapter.calls) == 1
    assert KEY not in json.dumps(service.get(identifier).result)


def test_timeout_keeps_history_blocks_new_call_and_no_fallback(prepared, app):
    service, news = prepared
    service.adapter.failure = TimeoutError("SENSITIVE RESPONSE")
    identifier = call(service, news)
    assert service.get(identifier).status == "unknown"
    assert "SENSITIVE" not in service.get(identifier).message
    assert call(service, news) == identifier
    assert len(service.adapter.calls) == 1
    with app.state.sessions() as session:
        before = session.scalar(select(APIRequestReservation))
        original = (before.id, before.status, before.reserved_usd)
    # A changed input is not permission to bypass the existing unknown-request gate.
    with app.state.sessions.begin() as session:
        from newsflow.db.models import NewsArticle
        session.get(NewsArticle, news).title = "다른 합성 제목"
    second = call(service, news)
    assert service.get(second).status == "blocked" and len(service.adapter.calls) == 1
    with app.state.sessions() as session:
        old = session.get(APIRequestReservation, original[0])
        assert (old.id, old.status, old.reserved_usd) == original


def test_render_edit_review_sources_and_disclosure(app, prepared):
    service, news = prepared
    identifier = call(service, news)
    args = {"card_id": identifier, "title": "수정한 카드 제목", "body": "사용자가 검토할 합성 요약입니다.",
            "rights": True, "reviewed": True, "sources_confirmed": True, "ai_disclosure": "not_required"}
    with pytest.raises(PublishingError):
        app.state.image_posts.create(news, **(args | {"reviewed": False}))
    post_id = app.state.image_posts.create(news, **args)
    post = app.state.image_posts.get(post_id)
    assert post.ai_disclosure == "disclose" and post.sources["claude_card_run_id"] == identifier
    assert "AI 구성 뉴스 카드" in post.caption and "https://example.com/image-news" in post.caption
    with Image.open(app.state.image_posts.path(post_id)) as image:
        assert image.size == (1080, 1350) and image.format == "JPEG"
    with pytest.raises(PublishingError):
        app.state.image_posts.create(news, **(args | {"body": "가" * 201}))
    with pytest.raises(PublishingError):
        service.get(identifier, article_id=news + 1)
    assert len(service.adapter.calls) == 1


def test_top_three_reuses_existing_draft_and_source_ids(app, monkeypatch, prepared):
    service, _news = prepared
    analysis_id, ids, draft_id = selected.__wrapped__(app, monkeypatch)
    identifier = call(service, ids[0], analysis_id=analysis_id, rank=1, draft_id=draft_id)
    run = service.get(identifier)
    assert run.evidence["summary"] == "저장한 릴스 대본입니다."
    assert run.result["plan"]["source_article_ids"] == ids[:2]
    post_id = app.state.image_posts.create(ids[0], card_id=identifier, analysis_id=analysis_id, rank=1,
        draft_id=draft_id, title=PLAN["title"], body=PLAN["body"],
        reviewed=True, rights=True, sources_confirmed=True)
    assert len(app.state.image_posts.get(post_id).sources["articles"]) == 2


def test_restart_recovers_unknown_without_replay(app, prepared):
    from newsflow.config import Settings
    from newsflow.main import create_app
    from newsflow.news.rss_adapter import FakeRSSAdapter

    service, news = prepared
    identifier = call(service, news)
    with app.state.sessions.begin() as session:
        run = session.get(IntelligenceRun, identifier)
        run.status = "running"
        session.scalar(select(APIRequestReservation)).status = "reserved"
    rebuilt = create_app(Settings(data_dir=app.state.image_generation.outputs.parent.parent), FakeRSSAdapter({}))
    target = rebuilt.state.claude_cards
    target.keys, target.adapter, target.budget = service.keys, service.adapter, service.budget
    assert target.get(identifier).status == "unknown"
    assert call(target, news) == identifier and len(service.adapter.calls) == 1
    rebuilt.state.engine.dispose()


def test_official_messages_wire_one_call_no_tools(monkeypatch):
    adapter = ClaudeCardAdapter(lambda: KEY)
    calls = []
    def fake_open(request, timeout, limit):
        calls.append(json.loads(request.data))
        assert request.full_url == "https://api.anthropic.com/v1/messages"
        return json.dumps({"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps(PLAN)}],
            "usage": {"input_tokens": 100, "output_tokens": 80}}).encode()
    monkeypatch.setattr(adapter, "_open", fake_open)
    assert adapter.plan({"source_article_ids": [1]}, Options(model=MODEL)) == PLAN
    assert len(calls) == 1 and "tools" not in calls[0]
    assert calls[0]["output_config"]["format"]["type"] == "json_schema"
    assert adapter.last_usage["prompt_tokens"] == 100


def test_gui_no_calls_get_create_preview_and_csrf(client, prepared):
    service, news = prepared
    page = client.get(f"/image-posts?article_id={news}")
    assert page.status_code == 200 and "Claude 키와 OpenAI 이미지 API 키가 각각 필요" in page.text
    assert not service.adapter.calls
    data = {"article_id": news, "model": MODEL, "consent": "true"}
    assert client.post("/image-posts/claude-card", data=data).status_code == 403
    data["csrf_token"] = csrf(client)
    response = client.post("/image-posts/claude-card", data=data)
    assert response.status_code == 200 and "아직 이미지가 아닙니다" in response.text
    run = service.recent(news)[0]
    preview = client.get(f"/image-posts/cards/{run.id}/preview")
    assert preview.status_code == 404
    assert client.post("/image-posts/claude-card", data=data).status_code == 200
    assert len(service.adapter.calls) == 1
