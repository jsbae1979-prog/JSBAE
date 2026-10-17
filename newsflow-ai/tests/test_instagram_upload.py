"""Official Facebook Login Reels wire contract: all network responses are Fake."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import pytest
from pydantic import SecretStr

from newsflow.publishing.auth import TokenBundle
from newsflow.publishing.instagram import (
    GRAPH,
    RUPLOAD,
    InstagramHTTPResponse,
    InstagramUploadAdapter,
    InstagramUploadError,
    MetaUploadTransport,
    _allowed_url,
)

ACCOUNT = "17841400000000001"
CONTAINER = "17900000000000001"
MEDIA = "18000000000000001"
PERMALINK = "https://www.instagram.com/reel/FakeNews123/"


class Transport:
    def __init__(self, responses):
        self.responses, self.calls, self.read_sizes = list(responses), [], []

    def request(self, method, url, headers, body):
        if not isinstance(body, bytes):
            chunks = []
            while chunk := body.read(128 * 1024):
                self.read_sizes.append(len(chunk))
                chunks.append(chunk)
            body = b"".join(chunks)
        self.calls.append((method, url, headers, body))
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def reply(data=None, status=200):
    return InstagramHTTPResponse(status, json.dumps({} if data is None else data).encode())


@pytest.fixture
def bundle():
    return TokenBundle(access_token=SecretStr("nf-synthetic-page-access-never-sent"),
                       expires_at=datetime.now(UTC) + timedelta(hours=1),
                       scopes=("instagram_basic", "instagram_content_publish", "pages_read_engagement"))


@pytest.fixture
def media(tmp_path):
    path = tmp_path / "synthetic.mp4"
    path.write_bytes(b"synthetic media" * 50000)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def payload(**changes):
    return {"title": "뉴스 쇼츠", "description": "검토한 설명과 출처", "hashtags": ["뉴스"],
            "ai_disclosure": "disclose", "upload_approved": True, **changes}


def test_container_upload_status_and_publication_are_separate(media, bundle):
    transport = Transport([reply({"id": CONTAINER, "uri": f"{RUPLOAD}/{CONTAINER}"}),
                           reply({"success": True}), reply({"id": CONTAINER, "status_code": "FINISHED"}),
                           reply({"id": MEDIA}),
                           reply({"id": MEDIA, "permalink": PERMALINK, "owner": {"id": ACCOUNT}})])
    adapter = InstagramUploadAdapter(transport)
    container = adapter.create_container(payload(), bundle, ACCOUNT)
    assert container.container_id == CONTAINER and len(transport.calls) == 1
    metadata = parse_qs(transport.calls[0][3].decode())
    assert metadata["media_type"] == ["REELS"] and metadata["upload_type"] == ["resumable"]
    assert "뉴스 쇼츠" in metadata["caption"][0] and "#뉴스" in metadata["caption"][0]
    assert "AI로 생성" in metadata["caption"][0] and metadata["is_ai_generated"] == ["true"]
    adapter.upload(media[0], bundle, container.container_id, media[1])
    assert len(transport.calls) == 2 and "media_publish" not in transport.calls[1][1]
    uploaded = transport.calls[1]
    assert uploaded[1] == f"{RUPLOAD}/{CONTAINER}" and uploaded[3] == media[0].read_bytes()
    assert uploaded[2]["offset"] == "0" and uploaded[2]["file_size"] == str(media[0].stat().st_size)
    assert uploaded[2]["Authorization"].startswith("OAuth ") and max(transport.read_sizes) <= 128 * 1024
    identifier = adapter.publish(bundle, ACCOUNT, CONTAINER, public_approved=True)
    assert identifier == MEDIA and len(transport.calls) == 4
    assert transport.calls[2][:2] == ("GET", f"{GRAPH}/{CONTAINER}?fields=status_code")
    assert parse_qs(transport.calls[3][3].decode()) == {"creation_id": [CONTAINER]}
    result = adapter.result(bundle, MEDIA, ACCOUNT)
    assert (result.media_id, result.url, result.account_id) == (MEDIA, PERMALINK, ACCOUNT)


def test_upload_consent_and_separate_public_consent_fail_before_network(bundle):
    transport = Transport([])
    adapter = InstagramUploadAdapter(transport)
    with pytest.raises(InstagramUploadError, match="승인"):
        adapter.create_container(payload(upload_approved=False), bundle, ACCOUNT)
    with pytest.raises(InstagramUploadError, match="승인"):
        adapter.publish(bundle, ACCOUNT, CONTAINER, public_approved=False)
    assert transport.calls == []


def test_existing_not_required_disclosure_value_is_preserved(bundle):
    transport = Transport([reply({"id": CONTAINER, "uri": f"{RUPLOAD}/{CONTAINER}"})])
    InstagramUploadAdapter(transport).create_container(payload(ai_disclosure="not_required"), bundle, ACCOUNT)
    caption = parse_qs(transport.calls[0][3].decode())["caption"][0]
    assert "AI로 생성" not in caption
    assert parse_qs(transport.calls[0][3].decode())["is_ai_generated"] == ["false"]


@pytest.mark.parametrize("changes", [{"title": ""}, {"hashtags": [1]}, {"description": None},
                                     {"description": "x" * 2200}, {"ai_disclosure": "unreviewed"},
                                     {"hashtags": ["tag"] * 31}])
def test_invalid_caption_and_unreviewed_disclosure_block_before_creation(bundle, changes):
    transport = Transport([])
    with pytest.raises(InstagramUploadError) as error:
        InstagramUploadAdapter(transport).create_container(payload(**changes), bundle, ACCOUNT)
    assert error.value.code == "invalid_input" and transport.calls == []


def test_expired_token_or_instagram_login_scopes_cannot_use_facebook_flow(bundle):
    transport = Transport([])
    for changed in (bundle.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}),
                    bundle.model_copy(update={"scopes": ("instagram_business_basic",
                                                          "instagram_business_content_publish")})):
        with pytest.raises(InstagramUploadError) as error:
            InstagramUploadAdapter(transport).create_container(payload(), changed, ACCOUNT)
        assert error.value.code == "authentication"
    assert transport.calls == []


@pytest.mark.parametrize("uri", ["https://attacker.example/upload", f"{RUPLOAD}/{CONTAINER}?token=secret",
                                 f"{RUPLOAD}/{CONTAINER}#fragment", f"{RUPLOAD}/999",
                                 f"http://rupload.facebook.com/ig-api-upload/v25.0/{CONTAINER}"])
def test_container_upload_url_must_be_exact_official_target(bundle, uri):
    transport = Transport([reply({"id": CONTAINER, "uri": uri})])
    with pytest.raises(InstagramUploadError) as error:
        InstagramUploadAdapter(transport).create_container(payload(), bundle, ACCOUNT)
    assert error.value.unknown and len(transport.calls) == 1 and uri not in str(error.value)


def test_changed_media_never_transmitted(media, bundle):
    transport = Transport([])
    media[0].write_bytes(b"changed since review")
    with pytest.raises(InstagramUploadError) as error:
        InstagramUploadAdapter(transport).upload(media[0], bundle, CONTAINER, media[1])
    assert error.value.code == "media_changed" and transport.calls == []


@pytest.mark.parametrize("outcome", [TimeoutError("raw secret request"), reply({}),
                                     reply({"success": False}), reply({"success": "true"})])
def test_uncertain_transfer_never_replayed(media, bundle, outcome):
    transport = Transport([outcome])
    with pytest.raises(InstagramUploadError) as error:
        InstagramUploadAdapter(transport).upload(media[0], bundle, CONTAINER, media[1])
    assert error.value.unknown and len(transport.calls) == 1 and "secret" not in str(error.value)


@pytest.mark.parametrize("state,code", [("IN_PROGRESS", "not_ready"), ("ERROR", "rejected"),
                                       ("EXPIRED", "rejected"), ("PUBLISHED", "unknown")])
def test_no_publication_before_finished_or_after_already_published(bundle, state, code):
    transport = Transport([reply({"id": CONTAINER, "status_code": state})])
    with pytest.raises(InstagramUploadError) as error:
        InstagramUploadAdapter(transport).publish(bundle, ACCOUNT, CONTAINER, public_approved=True)
    assert error.value.code == code and [call[0] for call in transport.calls] == ["GET"]


@pytest.mark.parametrize("status,provider_code,expected,unknown", [
    (401, None, "authentication", False), (400, 190, "authentication", False),
    (403, 200, "permission", False), (429, 4, "limit", False),
    (400, 100, "rejected", False), (500, None, "unknown", True), (302, None, "unknown", True),
])
def test_errors_are_classified_redacted_and_not_retried(bundle, status, provider_code, expected, unknown):
    transport = Transport([reply({"error": {"code": provider_code, "message": "secret raw response"}}, status)])
    with pytest.raises(InstagramUploadError) as error:
        InstagramUploadAdapter(transport).create_container(payload(), bundle, ACCOUNT)
    assert error.value.code == expected and error.value.unknown is unknown
    assert len(transport.calls) == 1 and "secret" not in str(error.value)


@pytest.mark.parametrize("changes", [{"id": "999"}, {"owner": {"id": "999"}},
    {"permalink": "https://evil.example/reel/Fake123/"},
    {"permalink": "https://www.instagram.com.evil.example/reel/Fake123/"},
    {"permalink": "https://www.instagram.com/reel/Fake123/?access_token=secret"},
    {"permalink": "https://user@www.instagram.com/reel/Fake123/"}])
def test_result_link_and_account_binding_cannot_be_substituted(bundle, changes):
    data = {"id": MEDIA, "permalink": PERMALINK, "owner": {"id": ACCOUNT}, **changes}
    transport = Transport([reply(data)])
    with pytest.raises(InstagramUploadError) as error:
        InstagramUploadAdapter(transport).result(bundle, MEDIA, ACCOUNT)
    assert error.value.unknown and len(transport.calls) == 1


def test_valid_bare_instagram_permalink_is_normalized_for_saved_result(bundle):
    transport = Transport([reply({"id": MEDIA, "permalink": "https://instagram.com/reel/FakeNews123/",
                                  "owner": {"id": ACCOUNT}})])
    result = InstagramUploadAdapter(transport).result(bundle, MEDIA, ACCOUNT)
    assert result.url == PERMALINK and result.account_id == ACCOUNT
    assert len(transport.calls) == 1


@pytest.mark.parametrize("method,url", [
    ("POST", f"https://graph.instagram.com/v25.0/{ACCOUNT}/media"),
    ("POST", f"{GRAPH}/{ACCOUNT}/media?access_token=secret"),
    ("POST", f"{RUPLOAD}/{CONTAINER}?next=elsewhere"),
    ("POST", f"https://rupload.facebook.com/ig-api-upload/v25x0/{CONTAINER}"),
    ("GET", f"{GRAPH}/{ACCOUNT}?fields=access_token"),
    ("DELETE", f"{GRAPH}/{MEDIA}"),
])
def test_transport_rejects_unpinned_targets_without_opening_connection(monkeypatch, method, url):
    def no_network(*args, **kwargs):
        pytest.fail("unexpected provider network call")
    monkeypatch.setattr("urllib.request.OpenerDirector.open", no_network)
    assert not _allowed_url(method, url)
    with pytest.raises(InstagramUploadError):
        MetaUploadTransport().request(method, url, {}, b"")


def test_status_has_no_hidden_polling(bundle):
    transport = Transport([reply({"id": CONTAINER, "status_code": "IN_PROGRESS"})])
    assert InstagramUploadAdapter(transport).status(bundle, CONTAINER) == "IN_PROGRESS"
    assert len(transport.calls) == 1
