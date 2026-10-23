"""Fake-only feed backgrounds; actual API, credentials and production DB excluded."""
import base64
import json
import urllib.error
from io import BytesIO
from types import SimpleNamespace

import pytest
from conftest import csrf
from PIL import Image
from sqlalchemy import select
from test_image_posts import article

from newsflow.db.models import AIUsage, AppSetting, IntelligenceRun
from newsflow.publishing.image_generation import (
    MODEL,
    ImageGenerationError,
    ImageGenerationService,
    OpenAIImageAdapter,
    clean_image,
    safe_usage,
)
from newsflow.publishing.service import PublishingError

KEY = "sk-fake-only-never-production-123456"
USAGE = {"input_tokens": 100, "output_tokens": 400, "total_tokens": 500}


def jpeg():
    output = BytesIO()
    Image.new("RGB", (1024, 1280), "#498899").save(output, format="JPEG")
    return output.getvalue()


class FakeImage:
    def __init__(self, failure=None, usage=USAGE):
        self.calls = []
        self.failure, self.usage = failure, usage

    def generate(self, prompt, key):
        assert key == KEY
        self.calls.append(prompt)
        if self.failure:
            raise self.failure
        return jpeg(), self.usage


@pytest.fixture(autouse=True)
def deny_live(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Unexpected network")
    monkeypatch.setattr("urllib.request.OpenerDirector.open", denied)
    monkeypatch.setattr("newsflow.publishing.instagram.MetaUploadTransport.request", denied)


@pytest.fixture
def prepared(app):
    service = app.state.image_generation
    service.keys = SimpleNamespace(key=lambda: KEY, status=lambda: {"configured": True})
    service.adapter = FakeImage()
    return service, article(app)


def test_explicit_consent_and_key_required_no_claim(app, prepared):
    service, news = prepared
    with pytest.raises(PublishingError):
        service.generate(news)
    service.keys.key = lambda: ""
    with pytest.raises(PublishingError):
        service.generate(news, consent=True)
    assert service.adapter.calls == []
    assert service.recent(news) == []


def test_single_request_reused_after_restart_with_usage_and_no_settings_change(app, prepared):
    service, news = prepared
    with app.state.sessions.begin() as session:
        session.add(AppSetting(key="preserve_claude_test", value="claude-sonnet-4-6"))
    first = service.generate(news, consent=True)
    rebuilt = ImageGenerationService(app.state.sessions, service.outputs.parent.parent, service.keys,
                                    adapter=service.adapter)
    rebuilt.recover()
    assert rebuilt.generate(news, consent=True) == first
    assert len(service.adapter.calls) == 1
    run = service.get(first)
    assert run.provider == "openai" and run.status == "success"
    assert run.options["model"] == MODEL and run.result["usage"] == USAGE
    assert KEY not in json.dumps(run.evidence | run.options | run.result)
    with app.state.sessions() as session:
        usage = session.scalar(select(AIUsage).where(AIUsage.run_id == first))
        assert usage.total_tokens == 500
        assert session.get(AppSetting, "preserve_claude_test").value == "claude-sonnet-4-6"


@pytest.mark.parametrize("error,status", [
    (ImageGenerationError("authentication_failed", uncertain=False, http_status=401), "failed"),
    (TimeoutError("SECRET_API_RESPONSE"), "unknown"),
    (ImageGenerationError("invalid_image"), "unknown"),
])
def test_failure_unknown_never_retried_or_exposed(app, prepared, error, status):
    service, news = prepared
    service.adapter.failure = error
    first = service.generate(news, consent=True)
    service.recover()
    assert service.generate(news, consent=True) == first
    assert len(service.adapter.calls) == 1
    run = service.get(first)
    assert run.status == status
    assert "SECRET" not in json.dumps(run.result) + run.message


def test_restart_interruption_is_unknown_no_network(prepared, app):
    service, news = prepared
    first = service.generate(news, consent=True)
    with app.state.sessions.begin() as session:
        run = session.get(IntelligenceRun, first)
        run.status, run.result = "running", {}
    service.recover()
    assert service.get(first).status == "unknown"
    assert service.generate(news, consent=True) == first
    assert len(service.adapter.calls) == 1


def test_lock_blocks_parallel_generation(prepared):
    service, news = prepared
    other = ImageGenerationService(service.sessions, service.outputs.parent.parent, service.keys,
                                   adapter=service.adapter)
    with service.lock, pytest.raises(PublishingError):
        other.generate(news, consent=True)
    assert not service.adapter.calls


def test_generated_card_forces_disclosure_preserves_source_and_reviews(prepared, app):
    service, news = prepared
    first = service.generate(news, consent=True)
    options = {"title": "도서관 독서 모임", "body": "합성 뉴스 설명", "generated_id": first,
               "reviewed": True, "rights": True, "sources_confirmed": True, "ai_disclosure": "not_required"}
    with pytest.raises(PublishingError):
        app.state.image_posts.create(news, **(options | {"reviewed": False}))
    identifier = app.state.image_posts.create(news, **options)
    post = app.state.image_posts.get(identifier)
    assert post.ai_disclosure == "disclose"
    assert "AI 생성 이미지 · 실제 현장 사진 아님" in post.caption
    assert post.sources["generated_image_run_id"] == first
    assert post.sources["articles"][0]["id"] == news
    with Image.open(app.state.image_posts.path(identifier)) as image:
        assert image.size == (1080, 1350)
    with pytest.raises(PublishingError):
        app.state.image_posts.create(news, **(options | {"photo": jpeg()}))


def test_wrong_article_context_and_modified_file_rejected(prepared):
    service, news = prepared
    first = service.generate(news, consent=True)
    for kwargs in ({"article_id": news + 1}, {"article_id": news, "analysis_id": 99, "rank": 1}):
        with pytest.raises(PublishingError):
            service.path(first, **kwargs)
    path = service.path(first)
    path.write_bytes(b"modified")
    with pytest.raises(PublishingError):
        service.path(first)


def test_unknown_usage_not_zero_or_invoice(prepared, app):
    service, news = prepared
    service.adapter.usage = None
    first = service.generate(news, consent=True)
    assert service.get(first).result["usage"] is None
    with app.state.sessions() as session:
        assert session.scalar(select(AIUsage).where(AIUsage.run_id == first)) is None


def test_safe_usage_and_image_bounds():
    assert safe_usage(USAGE) == USAGE
    for invalid in ({}, {"input_tokens": True}, USAGE | {"total_tokens": 999},
                    USAGE | {"output_tokens": "SECRET"}):
        assert safe_usage(invalid) is None
    for raw in (b"not image", b"x" * (4 * 1024 * 1024 + 1)):
        with pytest.raises(ImageGenerationError):
            clean_image(raw)


class Wire:
    def __init__(self, data=None, failure=None):
        self.data = data or {"data": [{"b64_json": base64.b64encode(jpeg()).decode()}], "usage": USAGE}
        self.failure, self.calls = failure, []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.failure:
            raise self.failure
        return BytesIO(json.dumps(self.data).encode())


def test_official_wire_contract():
    wire = Wire()
    raw, usage = OpenAIImageAdapter(wire).generate("test prompt", KEY)
    assert raw == jpeg() and usage == USAGE
    request, timeout = wire.calls[0]
    assert request.full_url == "https://api.openai.com/v1/images/generations"
    assert timeout == 180 and request.get_method() == "POST"
    payload = json.loads(request.data)
    assert payload["model"] == MODEL and payload["n"] == 1
    assert payload["size"] == "1024x1280" and payload["moderation"] == "auto"
    assert "response_format" not in payload and "tools" not in payload


@pytest.mark.parametrize("status,code,uncertain", [
    (401, "authentication_failed", False), (403, "permission_denied", False),
    (429, "usage_limited", False), (500, "http_error", True), (302, "http_error", True),
])
def test_http_error_safe_once(status, code, uncertain):
    wire = Wire(failure=urllib.error.HTTPError(
        "https://api.openai.com/v1/images/generations", status, KEY, {}, BytesIO(KEY.encode())))
    with pytest.raises(ImageGenerationError) as caught:
        OpenAIImageAdapter(wire).generate("test", KEY)
    assert caught.value.code == code and caught.value.uncertain is uncertain
    assert KEY not in str(caught.value) and len(wire.calls) == 1


def test_response_url_is_not_fetched():
    wire = Wire({"data": [{"url": "http://127.0.0.1/secret"}]})
    with pytest.raises(ImageGenerationError):
        OpenAIImageAdapter(wire).generate("test", KEY)
    assert len(wire.calls) == 1


def test_gui_readonly_then_csrf_protected_single_request(client, prepared):
    service, news = prepared
    page = client.get(f"/image-posts?article_id={news}")
    assert page.status_code == 200
    assert "배경 1장 생성" in page.text and "등록만으로 생성 권한이 확인되지는 않습니다" in page.text
    assert "name=\"consent\" value=\"true\" required" in page.text
    assert service.adapter.calls == []
    url = "/image-posts/generate-background"
    assert client.post(url, data={"article_id": news, "consent": "true"}).status_code == 403
    token = csrf(client)
    data = {"article_id": news, "consent": "true", "csrf_token": token}
    assert client.post(url, data=data, headers={"Origin": "https://evil.example"}).status_code == 403
    response = client.post(url, data=data)
    assert response.status_code == 200
    assert "이 배경을 카드에 사용합니다." in response.text
    assert client.post(url, data=data).status_code == 200
    assert len(service.adapter.calls) == 1
    run = service.recent(news)[0]
    assert client.get(f"/image-posts/backgrounds/{run.id}/file").headers["content-type"] == "image/jpeg"
    assert client.get(str(response.url)).status_code == 200
    assert len(service.adapter.calls) == 1


def test_selection_context_bound_to_candidate_and_sources(app, monkeypatch):
    from test_image_selection import selected
    run_id, _rows, _ = selected.__wrapped__(app, monkeypatch)
    service = app.state.image_generation
    service.keys = SimpleNamespace(key=lambda: KEY, status=lambda: {"configured": True})
    service.adapter = FakeImage()
    group = app.state.image_posts.selection(run_id)
    item = group["items"][0]
    first = service.generate(item["article_id"], analysis_id=run_id, rank=1, consent=True)
    assert service.get(first).evidence["source"]["references"]
    assert service.get(first).options["analysis_id"] == run_id
    with pytest.raises(PublishingError):
        service.path(first, article_id=item["article_id"], analysis_id=run_id, rank=2)


def test_application_restart_does_not_misclassify_or_resubmit_image(app, prepared):
    from newsflow.config import Settings
    from newsflow.main import create_app
    from newsflow.news.rss_adapter import FakeRSSAdapter

    service, news = prepared
    first = service.generate(news, consent=True)
    with app.state.sessions.begin() as session:
        run = session.get(IntelligenceRun, first)
        run.status, run.result = "running", {}
    rebuilt = create_app(Settings(data_dir=service.outputs.parent.parent), FakeRSSAdapter({}))
    generation = rebuilt.state.image_generation
    generation.keys, generation.adapter = service.keys, service.adapter
    assert generation.get(first).status == "unknown"
    assert generation.generate(news, consent=True) == first
    assert len(service.adapter.calls) == 1
    rebuilt.state.engine.dispose()


def test_image_success_is_not_news_provider_success(app, prepared):
    from newsflow.gui.production_status import production_context

    service, news = prepared
    service.generate(news, consent=True)
    result = production_context(SimpleNamespace(app=app))
    assert result["provider_statuses"]["openai"]["last_success_at"] is None
