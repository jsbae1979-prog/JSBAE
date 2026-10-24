"""Claude SVG cards: no external clients, browser execution or operating data."""
import copy
from io import BytesIO
from xml.sax.saxutils import escape

import pytest
from conftest import csrf
from PIL import Image
from sqlalchemy import select
from test_claude_feed_cards import KEY, MODEL, FakeCard
from test_claude_feed_cards import prepared as card_fixture

from newsflow.db.models import APIRequestReservation, AppSetting, IntelligenceRun
from newsflow.intelligence.provider import Options
from newsflow.publishing.claude_cards import ClaudeCardAdapter
from newsflow.publishing.image_artwork import card_artwork
from newsflow.publishing.service import PublishingError
from newsflow.publishing.svg_cards import DISCLOSURE, render_svg

TITLE = "책으로 만나는 새로운 이웃"
BODY = "도서관 독서 모임을 소개하는 합성 뉴스입니다."


def document(*, accent="#6ee6c4", title=TITLE, body=BODY, publisher="합성 출처", motif="book"):
    illustration = ('''<path d="M 170 380 Q 330 280 520 380 L 520 710 Q 330 610 170 710 Z" fill="{accent}"/>
<path d="M 560 380 Q 740 280 910 380 L 910 710 Q 740 610 560 710 Z" fill="{accent}"/>
<path d="M 540 380 C 530 470 550 560 540 720" fill="none" stroke="#ffffff" stroke-width="8"/>'''
        if motif == "book" else
        '''<circle cx="540" cy="530" r="210" fill="{accent}"/>
<path d="M 410 560 L 500 650 L 690 430" fill="none" stroke="#10283a" stroke-width="22"/>''')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1350" viewBox="0 0 1080 1350">
<rect x="0" y="0" width="1080" height="1350" fill="#10283a"/>
<g>{illustration.format(accent=accent)}</g>
<text id="title" x="66" y="180" fill="#ffffff" font-size="52">{escape(title)}</text>
<text id="body" x="66" y="970" fill="#ffffff" font-size="32">{escape(body)}</text>
<text id="source" x="66" y="1220" fill="#ffffff" font-size="26">출처: {escape(publisher)}</text>
<text id="disclosure" x="66" y="1300" fill="#ffffff" font-size="24">{DISCLOSURE}</text>
</svg>'''


class FakeSVG(FakeCard):
    def plan_svg(self, source, options):
        self.calls.append((copy.deepcopy(source), options))
        if self.failure:
            raise self.failure
        self.last_usage = {"prompt_tokens": 200, "completion_tokens": 1500, "total_tokens": 1700}
        return {"title": TITLE, "body": BODY, "source_article_ids": source["source_article_ids"],
                "svg": document(publisher=source["publisher"])} | self.change


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("No external call allowed in SVG card tests")
    monkeypatch.setattr("urllib.request.OpenerDirector.open", denied)
    monkeypatch.setattr("newsflow.publishing.instagram.MetaUploadTransport.request", denied)


@pytest.fixture
def prepared(app):
    service, article = card_fixture.__wrapped__(app)
    service.adapter = FakeSVG()
    return service, article


def call(service, article, **kwargs):
    return service.generate(article, **({"model": MODEL, "purpose": "svg_card", "consent": True} | kwargs))


def test_entire_svg_controls_pixels_curves_text_no_template():
    first = render_svg(document(), title=TITLE, body=BODY, publisher="합성 출처")
    second = render_svg(document(accent="#f5be81", motif="shield"),
                        title=TITLE, body=BODY, publisher="합성 출처")
    assert first != second
    with Image.open(BytesIO(first)) as image:
        assert image.size == (1080, 1350) and image.format == "JPEG" and not image.getexif()
        assert image.getpixel((200, 500))[1] > 180
    # Saved SVG results use the same full canvas, with no separate template overlay.
    assert card_artwork(TITLE, BODY, "합성 출처", {"title": TITLE, "body": BODY, "svg": document()}) == first


@pytest.mark.parametrize("payload", [
    '<script>alert(1)</script>', '<image href="file:///secret"/>',
    '<image href="https://example.com/a.jpg"/>', '<foreignObject>unsafe</foreignObject>',
    '<use href="#somewhere"/>', '<animate attributeName="x"/>',
    '<style>text {display:none}</style>', '<rect width="1" height="1" onload="bad()"/>',
    '<g transform="scale(1000)"></g>', '<rect width="1" height="1" fill="url(https://example.com)"/>',
    '<path d="M 0 0 A 200 200 0 0 0 500 500"/>', '<text id="extra">추가 사실</text>',
    '<g xmlns="https://evil.example"><rect/></g>',
])
def test_reject_executable_external_or_unsupported_svg(payload):
    svg = document().replace('<g>', payload + '<g>', 1)
    with pytest.raises(PublishingError):
        render_svg(svg, title=TITLE, body=BODY, publisher="합성 출처")


@pytest.mark.parametrize("mutate", [
    lambda s: '<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///secret">]>' + s,
    lambda s: '<?xml-stylesheet href="https://example.com/a"?>' + s,
    lambda s: s.replace('width="1080"', 'width="1000000000"', 1),
    lambda s: s.replace('font-size="52"', 'font-size="1"'),
    lambda s: s.replace('y="180"', 'y="1349"'),
    lambda s: s.replace('y="970"', 'y="180"'),
    lambda s: s.replace('id="body"', 'id="title"'),
    lambda s: s.replace(TITLE, '없는 사실을 추가한 제목'),
    lambda s: s.replace(DISCLOSURE, ''),
    lambda s: s.replace('출처: 합성 출처', '출처: 다른 곳'),
    lambda s: s.replace('fill="#ffffff"', 'fill="#10283a"'),
    lambda s: s.replace('</svg>', '<rect width="1080" height="1350" fill="#ffffff"/></svg>'),
    lambda s: s.replace('<g>', '<g>' * 10).replace('</g>', '</g>' * 10),
    lambda s: s.replace('<g>', '<g>' + '<circle cx="20" cy="20" r="1"/>' * 161),
    lambda s: s + ' ' * 32001,
])
def test_bounds_text_source_disclosure_contrast_and_complexity(mutate):
    with pytest.raises(PublishingError):
        render_svg(mutate(document()), title=TITLE, body=BODY, publisher="합성 출처")


def test_multiline_explicit_tspan_validated_and_rendered():
    svg = document().replace(escape(BODY),
        '<tspan x="66" y="970">도서관 독서 모임을 소개하는</tspan>'
        '<tspan x="66" y="1030">합성 뉴스입니다.</tspan>')
    assert render_svg(svg, title=TITLE, body=BODY, publisher="합성 출처")
    with pytest.raises(PublishingError):
        render_svg(svg.replace('y="1030"', 'y="970"'), title=TITLE, body=BODY, publisher="합성 출처")


@pytest.mark.parametrize("path", [
    "M 100 300 L 200 300 L 200 400 Z M 300 300 L 400 300 L 400 400 Z",
    "M 100 300 L 200 300 L 200 400 Z L 300 300",
])
def test_compound_fill_or_missing_moveto_rejected_without_different_rendering(path):
    svg = document().replace('<g>', f'<g><path d="{path}" fill="#ffffff"/>')
    with pytest.raises(PublishingError):
        render_svg(svg, title=TITLE, body=BODY, publisher="합성 출처")


def test_saved_svg_preserved_without_new_claude_image_requests(app, prepared):
    service, article = prepared
    source = service.context(article, None, None, None)
    plan = FakeSVG().plan_svg(source, Options(model=MODEL))
    with service.sessions.begin() as session:
        row = IntelligenceRun(kind="feed_card", provider="claude_api", status="success",
            options={"article_id": article, "analysis_id": None, "rank": None,
                     "draft_id": None, "purpose": "svg_card", "model": MODEL},
            evidence=source, result={"plan": plan}, message="기존 SVG 결과")
        session.add(row)
        session.flush()
        identifier = row.id
    with service.sessions() as session:
        before = {s.key: s.value for s in session.scalars(select(AppSetting))}
    with pytest.raises(PublishingError):
        call(service, article)
    assert not service.adapter.calls
    assert not app.state.api_keys["openai"].status()["configured"]
    args = {"title": TITLE, "body": BODY, "card_id": identifier,
            "reviewed": True, "rights": True, "sources_confirmed": True}
    with pytest.raises(PublishingError):
        app.state.image_posts.create(article, **(args | {"reviewed": False}))
    with pytest.raises(PublishingError):
        app.state.image_posts.create(article, **(args | {"title": "다른 문구"}))
    post_id = app.state.image_posts.create(article, **args)
    post = app.state.image_posts.get(post_id)
    assert post.sources["claude_svg_card"] and post.sources["claude_card_run_id"] == identifier
    assert "https://example.com/image-news" in post.caption and post.ai_disclosure == "disclose"
    assert app.state.image_posts.path(post_id).read_bytes() == render_svg(
        plan["svg"], title=TITLE, body=BODY, publisher="합성 출처")
    with service.sessions() as session:
        after = {s.key: s.value for s in session.scalars(select(AppSetting))}
        assert before == after
        assert session.scalar(select(APIRequestReservation)) is None
        assert session.get(IntelligenceRun, identifier).result == {"plan": plan}
    with service.sessions.begin() as session:
        row = session.get(IntelligenceRun, identifier)
        row.result = {"plan": plan | {"svg": '<svg><script/></svg>'}}
    with pytest.raises(PublishingError):
        app.state.image_posts.create(article, **args)


@pytest.mark.parametrize("bad", ["timeout", "svg", "key"])
def test_retired_svg_requests_blocked_before_adapter_or_record_changes(prepared, bad):
    service, article = prepared
    service.adapter.failure = TimeoutError("SECRET_REPLY")
    service.adapter.change = {"svg": KEY if bad == "key" else '<svg><script/></svg>'}
    with pytest.raises(PublishingError):
        call(service, article)
    service.recover()
    with pytest.raises(PublishingError):
        call(service, article)
    assert not service.adapter.calls and not service.recent(article)


def test_retired_svg_adapter_cannot_dispatch_even_when_called_directly(monkeypatch):
    adapter, calls = ClaudeCardAdapter(lambda: KEY), []
    def wire(*args, **kwargs):
        calls.append(True)
        raise AssertionError("No Claude image request")
    monkeypatch.setattr(adapter, "_open", wire)
    with pytest.raises(PublishingError):
        adapter.plan_svg({"source_article_ids": [1]}, Options(model=MODEL))
    assert calls == []


def test_gui_removes_claude_image_choices_and_blocks_stale_forms(client, prepared):
    service, article = prepared
    page = client.get(f"/image-posts?article_id={article}")
    assert 'value="svg_card"' not in page.text and 'id="card-method"' not in page.text
    assert "Claude API만으로 제작" not in page.text
    assert "Claude 문구·이미지 지시문 작성 1회" in page.text
    assert "OpenAI 이미지 생성" in page.text
    assert not service.adapter.calls
    data = {"article_id": article, "model": MODEL, "consent": "true", "purpose": "svg_card"}
    assert client.post('/image-posts/claude-card', data=data).status_code == 403
    data["csrf_token"] = csrf(client)
    for purpose in ("svg_card", "local_card"):
        response = client.post('/image-posts/claude-card', data=data | {"purpose": purpose})
        assert response.status_code == 422 and "문구·이미지 지시문만 작성" in response.text
    assert not service.adapter.calls and not service.recent(article)
