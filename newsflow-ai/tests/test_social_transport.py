import io
import ssl

import pytest
from pydantic import SecretStr

from newsflow.publishing.official_transport import OfficialHTTPS, TransportOutcomeUnknown, allowed_request
from newsflow.publishing.platforms import PlatformBlocked
from newsflow.publishing.service import PublishingError


class Connection:
    def __init__(self, status=200, body=b'{"success":true}'):
        self.status, self.body, self.calls, self.headers, self.closed = status, body, [], {}, False
        self.host = None

    def factory(self, host, timeout, context):
        assert timeout == 30 and context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        self.host = host
        return self

    def putrequest(self, *args, **kwargs):
        self.calls.append(args)

    def putheader(self, key, value):
        self.headers[key] = value

    def endheaders(self):
        pass

    def send(self, value):
        pass

    def getresponse(self):
        return self

    def read(self, limit):
        return self.body[:limit]

    def close(self):
        self.closed = True


@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 403, 408, 429, 500, 503])
def test_no_redirect_or_replay_for_ambiguous_http(status):
    connection = Connection(status)
    transport = OfficialHTTPS(
        "facebook", SecretStr("nf-synthetic-never-sent"), synthetic_connection=connection.factory
    )
    with pytest.raises(TransportOutcomeUnknown):
        transport.request(
            "POST", "https://graph.facebook.com/v26.0/123/video_reels", payload={"upload_phase": "start"}
        )
    assert len(connection.calls) == 1 and connection.closed


def test_production_code_boundary_not_environment_flag(monkeypatch):
    monkeypatch.setenv("NEWSFLOW_REAL_OAUTH", "1")
    monkeypatch.setenv("NEWSFLOW_REAL_PUBLISHING", "1")
    with pytest.raises(PlatformBlocked):
        OfficialHTTPS("facebook", SecretStr("nf-synthetic-never-sent"))
    with pytest.raises(PlatformBlocked):
        OfficialHTTPS(
            "facebook", SecretStr("not-a-synthetic-token"), synthetic_connection=Connection().factory
        )


def test_upload_url_capability_does_not_receive_bearer_header():
    connection = Connection(201, b"")
    transport = OfficialHTTPS(
        "tiktok", SecretStr("nf-synthetic-never-sent"), synthetic_connection=connection.factory
    )
    assert transport.request(
        "PUT",
        "https://open-upload.tiktokapis.com/video/?upload_token=synthetic",
        stream=io.BytesIO(b"video"),
        headers={"Content-Length": "5", "Content-Type": "video/mp4", "Content-Range": "bytes 0-4/5"},
    ) == {"success": True}
    assert "Authorization" not in connection.headers and connection.closed


@pytest.mark.parametrize(
    "url",
    [
        "http://graph.facebook.com/v26.0/123/video_reels",
        "https://graph.facebook.com.evil/v26.0/123/video_reels",
        "https://127.0.0.1/v26.0/123/video_reels",
        "https://graph.facebook.com/v26.0/me/friends",
        "https://graph.facebook.com/v26.0/123/video_reels?access_token=secret",
        "https://graph.facebook.com:8765/v26.0/123/video_reels",
        "https://user:pass@graph.facebook.com/v26.0/123/video_reels",
    ],
)
def test_untrusted_endpoint_is_rejected_before_http(url):
    with pytest.raises(PublishingError):
        allowed_request("facebook", "POST", url)


@pytest.mark.parametrize("body", [b"not-json", b"[]", b"x" * (2 * 1024 * 1024 + 1)])
def test_bad_response_is_redacted_not_success(body):
    connection = Connection(200, body)
    transport = OfficialHTTPS(
        "youtube", SecretStr("nf-synthetic-never-sent"), synthetic_connection=connection.factory
    )
    with pytest.raises(TransportOutcomeUnknown) as exc:
        transport.request("GET", "https://www.googleapis.com/youtube/v3/videos?part=snippet&id=synthetic")
    assert "nf-synthetic" not in str(exc.value)
    assert connection.closed
