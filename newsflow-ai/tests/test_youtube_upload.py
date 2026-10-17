"""Official upload wire contract tested only through an injected in-memory transport."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from newsflow.oauth.contracts import YOUTUBE_UPLOAD_SCOPE
from newsflow.publishing.auth import TokenBundle
from newsflow.publishing.youtube import (
    UPLOAD_URL,
    GoogleUploadTransport,
    UploadHTTPResponse,
    YouTubeUploadAdapter,
    YouTubeUploadError,
    _session_url,
)

CHANNEL = "UC" + "a" * 22
VIDEO = "abcDEF_1234"
SESSION = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=fixture-only"


class Transport:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def request(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def reply(status=200, *, headers=None, data=None):
    return UploadHTTPResponse(status, headers or {}, json.dumps(data or {}).encode())


@pytest.fixture
def media(tmp_path):
    path = tmp_path / "fixture.mp4"
    path.write_bytes(b"synthetic media bytes")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def bundle():
    return TokenBundle(access_token=SecretStr("nf-synthetic-access-never-sent"),
                       expires_at=datetime.now(UTC) + timedelta(hours=1), scopes=(YOUTUBE_UPLOAD_SCOPE,))


def payload(**changes):
    return {"title": "합성 뉴스", "description": "출처와 내용을 검토했습니다.", "hashtags": ["뉴스"],
            "ai_disclosure": "disclose", "privacy": "private", "made_for_kids": False,
            "upload_approved": True, **changes}


def successful_transport():
    return Transport([reply(headers={"location": SESSION}),
                      reply(201, data={"id": VIDEO, "snippet": {"channelId": CHANNEL},
                                       "status": {"privacyStatus": "private", "uploadStatus": "uploaded"}})])


def test_official_resumable_post_and_put_metadata_once(media, bundle):
    path, digest = media
    transport = successful_transport()
    result = YouTubeUploadAdapter(transport).upload(path, payload(), bundle, CHANNEL, digest)
    assert result.video_id == VIDEO and result.url == "https://www.youtube.com/watch?v=" + VIDEO
    assert result.privacy == "private"
    assert [item[0] for item in transport.calls] == ["POST", "PUT"]
    assert transport.calls[0][1] == UPLOAD_URL
    metadata = json.loads(transport.calls[0][3])
    assert metadata["snippet"]["title"] == "합성 뉴스"
    assert metadata["snippet"]["categoryId"] == "25"
    assert metadata["snippet"]["description"].endswith("#뉴스")
    assert metadata["status"] == {"privacyStatus": "private", "containsSyntheticMedia": True,
                                   "selfDeclaredMadeForKids": False}
    assert transport.calls[1][2]["Content-Range"] == f"bytes 0-{path.stat().st_size - 1}/{path.stat().st_size}"
    assert transport.calls[1][3] == path.read_bytes()


@pytest.mark.parametrize("changes", [{"upload_approved": False}, {"privacy": "public"},
                                    {"privacy": "unlisted"}, {"privacy": "invalid"}])
def test_consent_is_required_before_transport(media, bundle, changes):
    transport = successful_transport()
    with pytest.raises(YouTubeUploadError, match="승인"):
        YouTubeUploadAdapter(transport).upload(media[0], payload(**changes), bundle, CHANNEL, media[1])
    assert transport.calls == []


@pytest.mark.parametrize("privacy", ["public", "unlisted"])
def test_public_or_unlisted_requires_separate_consent(media, bundle, privacy):
    transport = successful_transport()
    YouTubeUploadAdapter(transport).upload(media[0], payload(privacy=privacy, public_approved=True),
                                          bundle, CHANNEL, media[1])
    assert json.loads(transport.calls[0][3])["status"]["privacyStatus"] == privacy


def test_expired_token_or_reduced_scope_blocks_without_request(media, bundle):
    transport = successful_transport()
    for bad in (bundle.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}),
                bundle.model_copy(update={"scopes": ()})):
        with pytest.raises(YouTubeUploadError):
            YouTubeUploadAdapter(transport).upload(media[0], payload(), bad, CHANNEL, media[1])
    assert transport.calls == []


def test_changed_media_rejected_before_initialization(media, bundle):
    transport = successful_transport()
    media[0].write_bytes(b"different fixture")
    with pytest.raises(YouTubeUploadError) as error:
        YouTubeUploadAdapter(transport).upload(media[0], payload(), bundle, CHANNEL, media[1])
    assert error.value.code == "media_changed" and transport.calls == []


@pytest.mark.parametrize("url", ["https://attacker.example/upload?upload_id=x",
    "http://www.googleapis.com/upload/youtube/v3/videos?upload_id=x",
    "https://www.googleapis.com.evil.example/upload/youtube/v3/videos?upload_id=x",
    "https://www.googleapis.com@evil.example/upload/youtube/v3/videos?upload_id=x",
    "https://www.googleapis.com/upload/other?upload_id=x",
    "https://www.googleapis.com/upload/youtube/v3/videos", SESSION + "#fragment",
    SESSION + "&upload_id=duplicate"])
def test_session_location_cannot_redirect_media_or_bearer(media, bundle, url):
    transport = Transport([reply(headers={"location": url})])
    with pytest.raises(YouTubeUploadError) as error:
        YouTubeUploadAdapter(transport).upload(media[0], payload(), bundle, CHANNEL, media[1])
    assert error.value.unknown and len(transport.calls) == 1
    assert url not in str(error.value)


def test_chunks_use_exact_acknowledged_ranges_without_replaying(media, bundle):
    size = 256 * 1024
    media[0].write_bytes(b"f" * (size + 5))
    digest = hashlib.sha256(media[0].read_bytes()).hexdigest()
    transport = Transport([reply(headers={"location": SESSION}), reply(308, headers={"range": f"bytes=0-{size-1}"}),
                           reply(201, data={"id": VIDEO, "snippet": {"channelId": CHANNEL},
                                            "status": {"privacyStatus": "private"}})])
    YouTubeUploadAdapter(transport, chunk_bytes=size).upload(media[0], payload(), bundle, CHANNEL, digest)
    assert [call[0] for call in transport.calls] == ["POST", "PUT", "PUT"]
    assert transport.calls[1][2]["Content-Range"] == f"bytes 0-{size-1}/{size+5}"
    assert transport.calls[2][2]["Content-Range"] == f"bytes {size}-{size+4}/{size+5}"


@pytest.mark.parametrize("ack", [None, "bytes=0-1", "bytes=1-262143"])
def test_unexpected_chunk_ack_is_unknown_not_retried(media, bundle, ack):
    media[0].write_bytes(b"f" * (256 * 1024 + 5))
    transport = Transport([reply(headers={"location": SESSION}), reply(308, headers={"range": ack})])
    with pytest.raises(YouTubeUploadError) as error:
        YouTubeUploadAdapter(transport, chunk_bytes=256 * 1024).upload(
            media[0], payload(), bundle, CHANNEL, hashlib.sha256(media[0].read_bytes()).hexdigest())
    assert error.value.unknown and len(transport.calls) == 2


@pytest.mark.parametrize("status,code,unknown", [(401, "authentication", False), (403, "permission", False),
    (400, "rejected", False), (429, "unknown", True), (503, "unknown", True), (302, "unknown", True)])
def test_api_errors_are_safe_and_never_retried(media, bundle, status, code, unknown):
    transport = Transport([reply(status, data={"error": "secret raw provider body"})])
    with pytest.raises(YouTubeUploadError) as error:
        YouTubeUploadAdapter(transport).upload(media[0], payload(), bundle, CHANNEL, media[1])
    assert error.value.code == code and error.value.unknown is unknown
    assert "secret" not in str(error.value) and len(transport.calls) == 1


@pytest.mark.parametrize("outcome", [TimeoutError("secret request"), reply(308),
    reply(data={"id": "invalid"}), reply(data={"id": VIDEO, "snippet": {"channelId": "UC" + "b" * 22}}),
    reply(data={"id": VIDEO, "status": {"privacyStatus": "public"}})])
def test_uncertain_final_response_is_unknown_without_second_upload(media, bundle, outcome):
    transport = Transport([reply(headers={"location": SESSION}), outcome])
    with pytest.raises(YouTubeUploadError) as error:
        YouTubeUploadAdapter(transport).upload(media[0], payload(), bundle, CHANNEL, media[1])
    assert error.value.unknown and len(transport.calls) == 2 and "secret" not in str(error.value)


def test_transport_has_no_redirect_or_unpinned_target(monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail("unexpected provider request")
    monkeypatch.setattr("urllib.request.OpenerDirector.open", no_network)
    with pytest.raises(YouTubeUploadError):
        GoogleUploadTransport().request("POST", "https://attacker.example", {}, b"")
    assert _session_url(SESSION) == SESSION
