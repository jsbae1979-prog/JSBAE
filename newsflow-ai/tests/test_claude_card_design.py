"""Structured Claude design with Fake responses only; never operating data or APIs."""
import copy
import json
from io import BytesIO

import pytest
import test_claude_feed_cards as cards
from PIL import Image

from newsflow.db.models import IntelligenceRun
from newsflow.intelligence.api_providers import _output_schema
from newsflow.publishing.card_design import CardDesign, designed_panel
from newsflow.publishing.claude_cards import DesignedCardPlan
from newsflow.publishing.image_artwork import card_artwork
from newsflow.publishing.service import PublishingError

PLAN, call = cards.PLAN, cards.call
prepared, deny_external = cards.prepared, cards.deny_external


def design(**changes):
    value = copy.deepcopy(PLAN["design"])
    value.update(changes)
    return value


@pytest.mark.parametrize("change", [
    {"x": -1}, {"x": 900}, {"x": True}, {"width": 1000000}, {"height": 0},
    {"color": "https://example.com/image"}, {"symbol": "../../secret"},
    {"kind": "svg"}, {"script": "print('unsafe')"}, {"line_width": 1000},
    {"points": [{"x": 0, "y": 0}]},
])
def test_invalid_model_design_preserves_failure_and_never_retries(prepared, change):
    service, article = prepared
    spec = design()
    spec["elements"][0].update(change)
    service.adapter.change = {"design": spec}
    identifier = call(service, article)
    assert service.get(identifier).status == "unknown"
    assert call(service, article) == identifier
    assert len(service.adapter.calls) == 1
    assert "https://" not in json.dumps(service.get(identifier).result)


@pytest.mark.parametrize("spec", [None, {}, design(version=3), design(elements=[]),
    design(elements=PLAN["design"]["elements"] * 9), design(layout="custom_html"),
    design(url="https://example.com/picture"), design(accent="#fff")])
def test_saved_design_revalidated_without_legacy_fallback(spec):
    with pytest.raises(PublishingError):
        card_artwork(PLAN["title"], PLAN["body"], "합성 출처", {**PLAN, "design": spec})


def test_missing_design_in_new_api_result_is_not_locally_substituted(prepared):
    service, article = prepared
    def legacy_only(source, options):
        return {key: value for key, value in PLAN.items() if key != "design"}
    service.adapter.plan = legacy_only
    assert service.get(call(service, article)).status == "unknown"


def test_saved_legacy_success_reused_without_api_and_old_artwork_preserved(app, prepared):
    service, article = prepared
    identifier = call(service, article)
    with service.sessions.begin() as session:
        run = session.get(IntelligenceRun, identifier)
        legacy = dict(run.result["plan"])
        legacy.pop("design")
        run.result = {"plan": legacy}
    first = app.state.image_posts.create(article, card_id=identifier, title=PLAN["title"],
        body=PLAN["body"], reviewed=True, rights=True, sources_confirmed=True)
    original = app.state.image_posts.path(first).read_bytes()
    assert call(service, article) == identifier and len(service.adapter.calls) == 1
    second = app.state.image_posts.create(article, card_id=identifier, title="수정 제목",
        body=PLAN["body"], reviewed=True, rights=True, sources_confirmed=True)
    assert second != first and app.state.image_posts.path(first).read_bytes() == original


def test_claude_geometry_and_layout_control_pixels_not_title_keywords():
    a = design()
    b = design(layout="headline_first", accent="amber")
    b["elements"][0].update(symbol="shield", x=80, width=340)
    first = card_artwork("동일한 제목", "동일한 내용", "합성 출처", {**PLAN, "design": a})
    second = card_artwork("동일한 제목", "동일한 내용", "합성 출처", {**PLAN, "design": b})
    assert first != second
    for raw in (first, second):
        with Image.open(BytesIO(raw)) as image:
            assert image.size == (1080, 1350) and image.format == "JPEG" and not image.getexif()


@pytest.mark.parametrize("kind,points", [
    ("ellipse", []), ("rectangle", []),
    ("line", [{"x": 0, "y": 0}, {"x": 1000, "y": 1000}]),
    ("polygon", [{"x": 0, "y": 1000}, {"x": 500, "y": 0}, {"x": 1000, "y": 1000}]),
])
def test_bounded_geometry_shapes(kind, points):
    spec = design()
    spec["elements"][0].update(kind=kind, symbol="none", points=points)
    panel, validated = designed_panel(spec)
    assert panel.size == (948, 420) and validated.version == 2


def test_request_schema_requires_design_without_executable_fields():
    schema = _output_schema(DesignedCardPlan)
    assert "design" in schema["required"]
    element = schema["$defs"]["DrawingElement"]
    assert element["additionalProperties"] is False
    assert not {"url", "html", "svg", "code", "path", "text"} & element["properties"].keys()
    assert CardDesign.model_validate(design()).version == 2


def test_saved_plan_geometry_and_source_link_survive_local_creation(app, prepared):
    service, article = prepared
    service.adapter.change = {"design": design(layout="headline_first", accent="amber")}
    identifier = call(service, article)
    saved = copy.deepcopy(service.get(identifier).result)
    assert saved["plan"]["design"]["layout"] == "headline_first"
    post_id = app.state.image_posts.create(article, card_id=identifier, title=PLAN["title"],
        body=PLAN["body"], reviewed=True, rights=True, sources_confirmed=True)
    post = app.state.image_posts.get(post_id)
    assert post.sources["claude_card_run_id"] == identifier
    assert "https://example.com/image-news" in post.caption
    assert service.get(identifier).result == saved and len(service.adapter.calls) == 1
