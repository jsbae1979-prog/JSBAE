"""Synthetic data and fake transports only; never touch operating data or keys."""
import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from conftest import csrf
from PIL import Image
from sqlalchemy import select
from test_claude_feed_cards import MODEL, FakeCard
from test_claude_feed_cards import prepared as card_fixture
from test_image_generation import KEY, FakeImage, jpeg

from newsflow.db.models import AppSetting, IntelligenceRun
from newsflow.intelligence.provider import Options
from newsflow.publishing.claude_cards import ClaudeCardAdapter, FullImagePlan
from newsflow.publishing.image_generation import ImageGenerationService
from newsflow.publishing.service import PublishingError

PLAN = {"title": "책과 함께하는 도서관", "body": "도서관 독서 모임을 소개하는 합성 뉴스입니다.",
        "source_article_ids": [1],
        "image_prompt": "책과 열린 도서관을 따뜻한 수채 일러스트로 배치하고 한글 제목과 요약을 읽기 쉽게 구성한다."}


class FakePlanner(FakeCard):
    def plan_image(self, source, options):
        self.calls.append((source, options))
        if self.failure:
            raise self.failure
        self.last_usage = {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300}
        return PLAN | {"source_article_ids": source["source_article_ids"]} | self.change


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("No external calls in full image tests")
    monkeypatch.setattr("urllib.request.OpenerDirector.open", denied)
    monkeypatch.setattr("newsflow.publishing.instagram.MetaUploadTransport.request", denied)


@pytest.fixture
def pipeline(app):
    cards, news = card_fixture.__wrapped__(app)
    cards.adapter = FakePlanner()
    images = app.state.image_generation
    images.keys = SimpleNamespace(key=lambda: KEY, status=lambda: {"configured": True})
    images.adapter = FakeImage()
    return cards, images, news


def plan(cards, news):
    return cards.generate(news, model=MODEL, consent=True, purpose="full_image")


def generate(images, news, card, **kwargs):
    return images.generate_card(news, **({"card_id": card, "consent": True,
                                          "plan_reviewed": True} | kwargs))


def test_two_separate_approvals_preserve_settings_and_entire_pixels(app, pipeline, monkeypatch):
    cards, images, news = pipeline
    with app.state.sessions() as session:
        settings = {s.key: s.value for s in session.scalars(select(AppSetting))}
    with pytest.raises(PublishingError):
        cards.generate(news, model=MODEL, purpose="full_image")
    card = plan(cards, news)
    assert cards.get(card).status == "success" and not images.adapter.calls
    for changes in ({"consent": False}, {"plan_reviewed": False}):
        with pytest.raises(PublishingError):
            generate(images, news, card, **changes)
    assert not images.adapter.calls
    identifier = generate(images, news, card)
    run = images.get(identifier)
    assert run.status == "success" and run.options["claude_card_run_id"] == card
    assert PLAN["image_prompt"] in images.adapter.calls[0]
    assert "COMPLETE finished" in images.adapter.calls[0]
    assert run.options["style"] == "full_card" and run.options["images"] == 1
    assert run.evidence["source"]["source"]["url"] == "https://example.com/image-news"

    # Rebuilt services must not replay either successful stage.
    rebuilt = ImageGenerationService(images.sessions, images.outputs.parent.parent, images.keys,
                                    adapter=images.adapter, cards=cards)
    rebuilt.recover()
    assert generate(rebuilt, news, card) == identifier
    assert plan(cards, news) == card
    assert len(cards.adapter.calls) == len(images.adapter.calls) == 1

    args = {"title": PLAN["title"], "body": PLAN["body"], "generated_id": identifier,
            "reviewed": True, "rights": True, "sources_confirmed": True, "ai_disclosure": "not_required"}
    with pytest.raises(PublishingError):
        app.state.image_posts.create(news, **(args | {"reviewed": False}))
    with pytest.raises(PublishingError):
        app.state.image_posts.create(news, **(args | {"title": "이미지와 다른 제목"}))
    def no_template(*args, **kwargs):
        raise AssertionError("Full image must never use a local card overlay")
    monkeypatch.setattr("newsflow.publishing.image_posts.artwork", no_template)
    monkeypatch.setattr("newsflow.publishing.image_posts.card_artwork", no_template)
    post_id = app.state.image_posts.create(news, **args)
    post = app.state.image_posts.get(post_id)
    assert post.sources["claude_card_run_id"] == card and post.sources["full_image"]
    assert "https://example.com/image-news" in post.caption and "AI 생성 이미지" in post.caption
    with Image.open(images.path(identifier)) as image:
        expected = BytesIO()
        image.convert("RGB").resize((1080, 1350), Image.Resampling.LANCZOS).save(
            expected, format="JPEG", quality=90)
    assert app.state.image_posts.path(post_id).read_bytes() == expected.getvalue()
    with app.state.sessions() as session:
        after = {s.key: s.value for s in session.scalars(select(AppSetting))}
        assert all(after[k] == v for k, v in settings.items())


@pytest.mark.parametrize("stage", ["claude", "image"])
def test_failure_preserves_unknown_and_does_not_replay_or_fallback(pipeline, stage):
    cards, images, news = pipeline
    (cards.adapter if stage == "claude" else images.adapter).failure = TimeoutError("SECRET_RESPONSE")
    card = plan(cards, news)
    if stage == "claude":
        assert cards.get(card).status == "unknown"
        with pytest.raises(PublishingError):
            generate(images, news, card)
        assert plan(cards, news) == card and not images.adapter.calls
    else:
        identifier = generate(images, news, card)
        images.recover()
        assert generate(images, news, card) == identifier
        assert images.get(identifier).status == "unknown"
        assert len(images.adapter.calls) == 1
        assert "SECRET_RESPONSE" not in json.dumps(images.get(identifier).result)
    assert len(cards.adapter.calls) == 1


def test_legacy_card_and_other_article_cannot_be_sent_as_full_plan(app, pipeline):
    cards, images, news = pipeline
    legacy = cards.generate(news, model=MODEL, consent=True)
    with pytest.raises(PublishingError):
        generate(images, news, legacy)
    card = plan(cards, news)
    assert legacy != card and cards.get(legacy).status == "success"
    with pytest.raises(PublishingError):
        generate(images, news + 1, card)
    with pytest.raises(PublishingError):
        generate(images, news, card, draft_id=99)
    with pytest.raises(PublishingError):
        app.state.image_posts.create(news, title=PLAN["title"], body=PLAN["body"], card_id=card,
                                    reviewed=True, rights=True, sources_confirmed=True)
    assert not images.adapter.calls


@pytest.mark.parametrize("change", [{"image_prompt": "short"}, {"source_article_ids": [99]},
                                   {"image_prompt": KEY}, {"extra": "not allowed"}])
def test_bad_plan_no_image_call_no_sensitive_result(pipeline, change):
    cards, images, news = pipeline
    cards.adapter.change = change
    card = plan(cards, news)
    assert cards.get(card).status == "unknown"
    assert not images.adapter.calls and KEY not in json.dumps(cards.get(card).result)


def test_full_plan_wire_schema_and_no_tools(monkeypatch):
    adapter = ClaudeCardAdapter(lambda: KEY)
    calls = []
    def wire(request, timeout, limit):
        calls.append(json.loads(request.data))
        return json.dumps({"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps(PLAN)}],
            "usage": {"input_tokens": 100, "output_tokens": 100}}).encode()
    monkeypatch.setattr(adapter, "_open", wire)
    assert adapter.plan_image({"source_article_ids": [1]}, Options(model=MODEL)) == PLAN
    assert "image_prompt" in calls[0]["output_config"]["format"]["schema"]["properties"]
    assert "tools" not in calls[0] and len(calls) == 1
    assert FullImagePlan.model_validate(PLAN)


def test_gui_plan_review_image_review_csrf_no_get_calls(client, pipeline):
    cards, images, news = pipeline
    assert "Claude가 뉴스 문구" in client.get(f"/image-posts?article_id={news}").text
    assert not cards.adapter.calls and not images.adapter.calls
    token = csrf(client)
    data = {"article_id": news, "model": MODEL, "consent": "true", "purpose": "full_image"}
    assert client.post("/image-posts/claude-card", data=data).status_code == 403
    data["csrf_token"] = token
    page = client.post("/image-posts/claude-card", data=data)
    assert page.status_code == 200 and "아직 이미지가 아닙니다" in page.text
    assert "전체 이미지 1장 생성" in page.text and "data-image-form" not in page.text
    card = cards.recent(news)[0].id
    assert client.get(f"/image-posts/cards/{card}/preview").status_code == 404
    data = {"article_id": news, "card_id": card, "consent": "true", "plan_reviewed": "true"}
    url = "/image-posts/generate-card-image"
    assert client.post(url, data=data).status_code == 403
    data["csrf_token"] = token
    assert client.post(url, data=data, headers={"Origin": "https://evil.example"}).status_code == 403
    page = client.post(url, data=data)
    assert page.status_code == 200 and "검토한 전체 이미지 저장" in page.text
    assert 'name="title" readonly' in page.text
    assert client.get(str(page.url)).status_code == 200
    assert client.post(url, data=data).status_code == 200
    assert len(cards.adapter.calls) == len(images.adapter.calls) == 1


def test_tampered_generated_file_cannot_be_saved(app, pipeline):
    cards, images, news = pipeline
    card = plan(cards, news)
    identifier = generate(images, news, card)
    images.path(identifier).write_bytes(jpeg() + b"modified")
    with pytest.raises(PublishingError):
        app.state.image_posts.create(news, title=PLAN["title"], body=PLAN["body"], generated_id=identifier,
                                    reviewed=True, rights=True, sources_confirmed=True)
    with app.state.sessions() as session:
        assert session.get(IntelligenceRun, card).status == "success"
