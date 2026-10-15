"""Phase 5D: HiggsfieldProvider request contract and SafeDownloader rules, fully offline.

Every requester, opener, DNS answer and connection here is a fake; the real ``http.client``
serialiser is used only against an in-memory socket so the exact bytes on the wire can be read.
The key below is synthetic and never leaves the process.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import socket
import ssl
import traceback
from dataclasses import dataclass
from threading import Event

import pytest

from newsflow.intelligence.credentials import CredentialError, FakeCipher
from newsflow.news.rss_adapter import URLPolicyError, validate_url
from newsflow.video.ai import download, higgsfield
from newsflow.video.ai.contracts import (
    ASPECT_RATIO,
    CANCELED,
    COMPLETED,
    FAILED,
    IN_PROGRESS,
    NSFW,
    QUEUED,
    ClipDownloadError,
    ClipRequest,
    ClipStatus,
    FetchResult,
    ProviderAmbiguousSubmit,
    ProviderAuthError,
    ProviderCreditError,
    ProviderInputError,
    ProviderModelError,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderResponseError,
    ProviderUnavailable,
    Submission,
    VideoProviderError,
)
from newsflow.video.ai.download import MAX_CLIP_BYTES, MAX_REDIRECTS, SafeDownloader, safe_url
from newsflow.video.ai.higgsfield import (
    MAX_RESPONSE_BYTES,
    USER_AGENT,
    HiggsfieldProvider,
    _NotSent,
    pinned_requester,
    video_url,
)
from newsflow.video.ai.keys import VIDEO_ENV_NAME, VideoAIKeyStore
from newsflow.video.ai.settings import HOSTS

KEY_ID = "nfvidkey01"
KEY_SECRET = "nfvidsecret-0123456789"
KEY = f"{KEY_ID}:{KEY_SECRET}"  # synthetic, matches VideoAIKeyStore.PATTERN
MODEL = "kling-video/v2.6/pro/text-to-video"
PROMPT = "서울 도심의 출근길을 표현한 추상적 일러스트 [STYLE GUARD]"
REQUEST_ID = "3f2c1a9e-7d4b-4b6b-9c1d-0123456789ab"
CLIP_URL = "https://cdn.example.com/clips/a.mp4?Expires=1700000000&Signature=abc&Key-Pair-Id=K1"
PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any real DNS lookup or TCP connect is recorded (and refused) and fails the test."""
    attempts: list[tuple] = []

    def blocked(*args, **kwargs):
        attempts.append(args[:2])
        raise OSError("network blocked in tests")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield
    assert attempts == []


# --------------------------------------------------------------------------- helpers


@dataclass
class Call:
    host: str
    method: str
    path: str
    body: bytes | None
    headers: dict
    timeout: float


class FakeRequester:
    """Injectable ``requester(host, method, path, body, headers, timeout) -> (status, bytes)``."""

    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[Call] = []

    def __call__(self, host, method, path, body, headers, timeout):
        self.calls.append(Call(host, method, path, body, dict(headers), timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        status, payload = outcome
        return status, payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")


def make(*outcomes, credential=None, **kwargs) -> tuple[HiggsfieldProvider, FakeRequester]:
    requester = FakeRequester(*outcomes)
    return HiggsfieldProvider(credential or (lambda: KEY), requester=requester, **kwargs), requester


def clip_request(model: str = MODEL, seconds: int = 5) -> ClipRequest:
    return ClipRequest(model, PROMPT, seconds, "720p")


def accepted(request_id: str = REQUEST_ID, state: str | None = "queued") -> tuple[int, dict]:
    body = {
        "request_id": request_id,
        "status_url": f"https://api.higgsfield.ai/requests/{request_id}/status",
        "cancel_url": f"https://api.higgsfield.ai/requests/{request_id}/cancel",
    }
    if state is not None:
        body["status"] = state
    return 200, body


def assert_no_secret(*objects) -> None:
    for obj in objects:
        if isinstance(obj, BaseException):
            texts = [str(obj), repr(obj), repr(obj.args), "".join(traceback.format_exception(obj))]
        else:
            texts = [repr(obj)]
        for text in texts:
            assert KEY_SECRET not in text
            assert KEY not in text


class FakeSocket:
    """In-memory socket for the real http.client: records what is sent, serves a canned reply."""

    def __init__(self, response: bytes, send_error: BaseException | None = None) -> None:
        self.response, self.send_error = response, send_error
        self.sent = bytearray()
        self.closed = False

    def sendall(self, data) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent += data

    def makefile(self, mode, *args, **kwargs):
        return io.BytesIO(self.response)

    def close(self) -> None:
        self.closed = True


class Wire:
    """Stands in for ``PinnedConnection`` while keeping http.client's real request serialisation."""

    def __init__(self, response: bytes = b"", *, connect_error=None, send_error=None) -> None:
        self.response, self.connect_error, self.send_error = response, connect_error, send_error
        self.created: list[tuple] = []
        self.sockets: list[FakeSocket] = []
        wire = self

        class FakePinned(http.client.HTTPConnection):
            def __init__(self, host, ip, port, timeout, tls):
                super().__init__(host, port, timeout=timeout)
                wire.created.append((host, ip, port, timeout, tls))

            def connect(self):
                if wire.connect_error is not None:
                    raise wire.connect_error
                self.sock = FakeSocket(wire.response, wire.send_error)
                wire.sockets.append(self.sock)

        self.connection = FakePinned

    @property
    def sent(self) -> bytes:
        return b"".join(bytes(s.sent) for s in self.sockets)

    def parsed(self) -> tuple[str, list[tuple[str, str]], bytes]:
        head, _, body = self.sent.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        headers = [tuple(part.strip() for part in line.split(":", 1)) for line in lines[1:]]
        return lines[0], headers, body


def http_reply(status: int, body: bytes, content_type: str = "application/json") -> bytes:
    head = f"HTTP/1.1 {status} X\r\nContent-Type: {content_type}\r\nContent-Length: {len(body)}\r\n\r\n"
    return head.encode("ascii") + body


def install(monkeypatch, module, wire: Wire, addresses=(PUBLIC_IP,)) -> list[tuple]:
    lookups: list[tuple] = []

    def fake_public(host, port, timeout=10):
        lookups.append((host, port, timeout))
        return list(addresses)

    monkeypatch.setattr(module, "public_addresses", fake_public)
    monkeypatch.setattr(module, "PinnedConnection", wire.connection)
    return lookups


def header_values(headers: list[tuple[str, str]], name: str) -> list[str]:
    return [value for key, value in headers if key.lower() == name.lower()]


class FakeResponse:
    def __init__(self, status: int = 200, headers: dict | None = None, chunks=(), on_read=None, error=None):
        self.status = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.chunks = list(chunks)
        self.on_read, self.error = on_read, error
        self.reads = 0

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name.lower(), default)

    def read1(self, amount: int) -> bytes:
        self.reads += 1
        if self.on_read is not None:
            self.on_read(self)
        if self.error is not None and not self.chunks:
            raise self.error
        return self.chunks.pop(0) if self.chunks else b""


def ok(*chunks: bytes, length: str | None = "auto", kind: str = "video/mp4", **extra) -> FakeResponse:
    headers = {"Content-Type": kind, **extra}
    if length == "auto":
        headers["Content-Length"] = str(sum(len(c) for c in chunks))
    elif length is not None:
        headers["Content-Length"] = length
    return FakeResponse(200, headers, chunks)


def redirect(location: str | None, status: int = 302) -> FakeResponse:
    return FakeResponse(status, {"Location": location} if location is not None else {})


class FakeOpener:
    """``opener(url, method, timeout) -> (response, close)``; it has no way to receive headers."""

    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.calls: list[tuple] = []
        self.closed = 0

    def __call__(self, *args):
        self.calls.append(args)
        response = self.responses.pop(0)

        def close() -> None:
            self.closed += 1

        return response, close


# --------------------------------------------------------------------------- submit


def test_submit_sends_one_exact_request_with_key_header_and_json_body():
    provider, requester = make(accepted(), timeout=12.5)
    submission = provider.submit(clip_request())
    assert submission == Submission(REQUEST_ID, QUEUED)
    assert len(requester.calls) == 1
    call = requester.calls[0]
    assert (call.host, call.method, call.path, call.timeout) == ("api.higgsfield.ai", "POST", f"/{MODEL}", 12.5)
    assert call.headers == {
        "Authorization": f"Key {KEY_ID}:{KEY_SECRET}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "identity",
    }
    assert json.loads(call.body.decode("utf-8")) == {
        "prompt": PROMPT, "duration": 5, "aspect_ratio": "9:16", "resolution": "720p",
    }
    assert ASPECT_RATIO == "9:16"
    # UTF-8 JSON, not ASCII escapes; the credential is a header only, never part of the body.
    assert "서울".encode() in call.body and b"\\u" not in call.body
    assert KEY_SECRET.encode() not in call.body


def test_submit_duration_is_an_integer_and_model_path_is_trimmed():
    provider, requester = make(accepted())
    provider.submit(ClipRequest(f"  {MODEL}\n", PROMPT, 10, "1080p"))
    call = requester.calls[0]
    assert call.path == f"/{MODEL}"
    body = json.loads(call.body)
    assert body["duration"] == 10 and isinstance(body["duration"], int)
    assert body["resolution"] == "1080p" and body["aspect_ratio"] == "9:16"


def test_host_must_be_an_official_higgsfield_host():
    # The official SDK BASE_URL and the official app templates' HF_API_BASE_URL agree on one host;
    # platform.higgsfield.ai appeared only in a docs search summary and is not allowed.
    assert HOSTS == ("api.higgsfield.ai",)
    provider, requester = make(accepted(), host="api.higgsfield.ai")
    provider.submit(clip_request())
    assert requester.calls[0].host == "api.higgsfield.ai"
    for host in ("evil.example.com", "api.higgsfield.ai.evil.example", "API.HIGGSFIELD.AI", "", "platform.higgsfield.ai"):
        with pytest.raises(ValueError):
            HiggsfieldProvider(lambda: KEY, host=host, requester=FakeRequester())


def test_default_provider_uses_the_pinned_requester_and_safe_downloader():
    provider = HiggsfieldProvider(lambda: KEY)
    assert provider.requester is pinned_requester
    assert isinstance(provider.downloader, SafeDownloader)
    assert provider.downloader.opener is download.pinned_opener
    assert provider.downloader.max_bytes == MAX_CLIP_BYTES
    assert provider.timeout == 30 and provider.host == "api.higgsfield.ai"


@pytest.mark.parametrize(
    ("state", "expected"),
    [("queued", QUEUED), ("in_progress", IN_PROGRESS), ("weird", QUEUED), (None, QUEUED), ("QUEUED", QUEUED)],
)
def test_submit_state_is_read_from_known_states_only(state, expected):
    provider, _ = make(accepted(state=state))
    assert provider.submit(clip_request()) == Submission(REQUEST_ID, expected)


BAD_MODEL_PATHS = [
    "../secret/text-to-video",
    "kling-video/../../admin",
    "kling-video/v2..6/pro",
    "kling-video/v2.6?debug=1",
    "kling-video/v2.6/pro#frag",
    "Kling-Video/v2.6/pro/text-to-video",
    "kling-video/V2.6",
    "/kling-video/v2.6",
    "kling-video/v2.6/",
    "kling-video//v2.6",
    "kling-video",
    "kling video/v2.6",
    "kling-video/v2.6%2f..%2fadmin",
    "https://evil.example.com/kling",
    "kling-video\\v2.6",
    "",
    "a/" + "b" * 50,
]


@pytest.mark.parametrize("path", BAD_MODEL_PATHS)
def test_invalid_model_path_is_never_sent(path):
    provider, requester = make(accepted())
    with pytest.raises(Exception):  # noqa: B017 - the classification is checked separately below
        provider.submit(clip_request(model=path))
    assert requester.calls == []


@pytest.mark.parametrize("path", ["../secret/text-to-video", "kling-video/v2.6?debug=1", "Kling-Video/v2"])
def test_invalid_model_path_is_a_not_sent_provider_error(path):
    """The coordinator treats any non-provider exception from submit as 'sent, outcome unknown'."""
    provider, requester = make(accepted())
    with pytest.raises(VideoProviderError) as caught:
        provider.submit(clip_request(model=path))
    assert caught.value.sent is False
    assert requester.calls == []


@pytest.mark.parametrize(
    "request_id",
    [None, 12345678, "", "short", "a" * 101, "../../../etc/passwd", "abc/def-ghij", "abcdefgh?x=1",
     "abcd efgh", "abcdefgh\n", "요청아이디요청아이디"],
)
def test_submit_with_unreadable_request_id_is_ambiguous(request_id):
    provider, requester = make((200, {"request_id": request_id, "status": "queued"}))
    with pytest.raises(ProviderAmbiguousSubmit) as caught:
        provider.submit(clip_request())
    assert caught.value.sent is True and caught.value.status_code == 200
    assert len(requester.calls) == 1


@pytest.mark.parametrize("data", [b"", b"not json", b"[1, 2]", b"\xff\xfe", b'"text"'])
def test_submit_accepted_with_unreadable_body_is_ambiguous(data):
    provider, requester = make((201, data))
    with pytest.raises(ProviderAmbiguousSubmit):
        provider.submit(clip_request())
    assert len(requester.calls) == 1


SUBMIT_ERRORS = [
    (401, ProviderAuthError), (402, ProviderCreditError), (403, ProviderCreditError), (404, ProviderModelError),
    (400, ProviderInputError), (422, ProviderInputError), (408, ProviderRateLimited), (429, ProviderRateLimited),
    (500, ProviderAmbiguousSubmit), (502, ProviderAmbiguousSubmit), (503, ProviderAmbiguousSubmit),
    (504, ProviderAmbiguousSubmit), (409, ProviderResponseError), (302, ProviderResponseError),
]


@pytest.mark.parametrize(("status", "error"), SUBMIT_ERRORS)
def test_submit_http_errors_map_to_fixed_messages_and_are_never_retried(status, error):
    echo = {"detail": f"bad key {KEY} for account secret {KEY_SECRET}", "request_id": REQUEST_ID}
    provider, requester = make((status, echo), accepted())
    with pytest.raises(VideoProviderError) as caught:
        provider.submit(clip_request())
    exc = caught.value
    assert type(exc) is error
    assert exc.status_code == status and exc.sent is True
    assert str(exc) == error.message
    assert len(requester.calls) == 1  # the queued success reply is never consumed: no retry
    assert_no_secret(exc)


def test_submit_server_error_wording_is_the_no_retry_message():
    provider, requester = make((503, b"upstream"), accepted())
    with pytest.raises(ProviderAmbiguousSubmit) as caught:
        provider.submit(clip_request())
    assert caught.value.code == "video_ai_unknown_submit"
    assert str(caught.value) == (
        "생성 요청을 보냈지만 결과를 확인하지 못했습니다. 중복 과금을 막기 위해 자동으로 다시 보내지 않습니다. "
        "공급사 대시보드에서 확인한 뒤 '결과 불명을 실패로 확정'을 누르면 장면을 다시 생성하거나 카드로 바꿀 수 있습니다."
    )
    assert len(requester.calls) == 1


def test_submit_not_sent_failure_is_unavailable_with_sent_false():
    provider, requester = make(_NotSent(), accepted())
    with pytest.raises(ProviderUnavailable) as caught:
        provider.submit(clip_request())
    assert caught.value.sent is False and caught.value.retryable is True
    assert str(caught.value) == "AI 영상 공급사에 연결하지 못했거나 서버 오류가 발생했습니다. 잠시 후 다시 시도하세요."
    assert len(requester.calls) == 1


@pytest.mark.parametrize(
    "failure",
    [ConnectionError(f"reset while sending Key {KEY}"), ConnectionResetError(), ProviderResponseError()],
)
def test_submit_failure_after_sending_is_ambiguous_and_not_retried(failure):
    provider, requester = make(failure, accepted())
    with pytest.raises(ProviderAmbiguousSubmit) as caught:
        provider.submit(clip_request())
    assert caught.value.sent is True
    assert caught.value.__cause__ is None and caught.value.__suppress_context__ is True
    assert len(requester.calls) == 1
    assert_no_secret(caught.value)


def test_submit_rate_limit_is_not_retried_internally():
    provider, requester = make((429, {}), accepted())
    with pytest.raises(ProviderRateLimited) as caught:
        provider.submit(clip_request())
    assert caught.value.retryable is True
    assert len(requester.calls) == 1


# --------------------------------------------------------------------------- credential


def _raise_credential_error():
    raise CredentialError("저장된 키를 읽지 못했습니다. 키를 다시 저장하세요.")


def _raise_with_secret():
    raise RuntimeError(f"DPAPI failure while reading {KEY}")


@pytest.mark.parametrize(
    "credential",
    [lambda: "", lambda: None, lambda: "has space in-this-key", lambda: "short", _raise_credential_error,
     _raise_with_secret],
    ids=["empty", "none", "space", "too-short", "credential-error", "error-with-secret"],
)
@pytest.mark.parametrize("action", ["submit", "status", "cancel"])
def test_missing_credential_is_not_configured_and_nothing_is_requested(credential, action):
    provider, requester = make(accepted(), credential=credential)
    calls = {
        "submit": lambda: provider.submit(clip_request()),
        "status": lambda: provider.status(REQUEST_ID),
        "cancel": lambda: provider.cancel(REQUEST_ID),
    }
    with pytest.raises(ProviderNotConfigured) as caught:
        calls[action]()
    exc = caught.value
    assert exc.sent is False
    assert exc.code == "video_ai_key_missing"
    assert str(exc) == "AI 영상 API 키가 설정되지 않았습니다. AI 영상 설정에서 키를 저장하세요."
    assert requester.calls == []
    assert exc.__context__ is None and exc.__cause__ is None
    assert_no_secret(exc)


def test_key_store_with_fake_cipher_feeds_the_authorization_header(tmp_path, monkeypatch):
    monkeypatch.delenv(VIDEO_ENV_NAME, raising=False)
    store = VideoAIKeyStore(tmp_path, FakeCipher())
    store.save(KEY)
    assert KEY_SECRET.encode() not in store.path.read_bytes()
    provider, requester = make(accepted(), credential=store.key)
    provider.submit(clip_request())
    assert requester.calls[-1].headers["Authorization"] == f"Key {KEY}"

    store.clear()
    monkeypatch.setenv(VIDEO_ENV_NAME, f"  {KEY_ID}:env-secret-0123456789  ")
    provider, requester = make(accepted(), credential=store.key)
    provider.submit(clip_request())
    assert requester.calls[-1].headers["Authorization"] == f"Key {KEY_ID}:env-secret-0123456789"

    monkeypatch.delenv(VIDEO_ENV_NAME)
    provider, requester = make(accepted(), credential=store.key)
    with pytest.raises(ProviderNotConfigured):
        provider.submit(clip_request())
    assert requester.calls == []


def test_unreadable_stored_key_is_not_configured(tmp_path, monkeypatch):
    monkeypatch.delenv(VIDEO_ENV_NAME, raising=False)
    store = VideoAIKeyStore(tmp_path, FakeCipher())
    store.save(KEY)
    broken = VideoAIKeyStore(tmp_path, FakeCipher(fail=True))
    provider, requester = make(accepted(), credential=broken.key)
    with pytest.raises(ProviderNotConfigured) as caught:
        provider.submit(clip_request())
    assert requester.calls == []
    assert_no_secret(caught.value)


@pytest.mark.parametrize("action", ["submit", "status"])
def test_malformed_credential_never_reaches_the_wire(monkeypatch, action):
    """A CR/LF in an environment key must fail as a classified, secret-free provider error."""
    wire = Wire(http_reply(200, json.dumps({"request_id": REQUEST_ID, "status": "queued"}).encode()))
    install(monkeypatch, higgsfield, wire)
    provider = HiggsfieldProvider(lambda: f"{KEY}\r\nX-Injected: 1")
    with pytest.raises(VideoProviderError) as caught:
        provider.submit(clip_request()) if action == "submit" else provider.status(REQUEST_ID)
    if action == "submit":
        assert caught.value.sent is False
    assert_no_secret(caught.value)
    assert b"X-Injected" not in wire.sent


# --------------------------------------------------------------------------- status


@pytest.mark.parametrize("state", [QUEUED, IN_PROGRESS, FAILED, NSFW, CANCELED])
def test_status_reads_non_completed_states(state):
    provider, requester = make((200, {"status": state, "request_id": REQUEST_ID}))
    result = provider.status(REQUEST_ID)
    assert result == ClipStatus(state)
    assert result.video_url is None and result.facts == {}
    call = requester.calls[0]
    assert (call.method, call.path, call.body) == ("GET", f"/requests/{REQUEST_ID}/status", None)
    assert call.headers["Authorization"] == f"Key {KEY}"


def test_canceled_is_spelled_with_one_l():
    assert CANCELED == "canceled"
    provider, _ = make((200, {"status": "canceled"}), (200, {"status": "cancelled"}))
    assert provider.status(REQUEST_ID).state == "canceled"
    with pytest.raises(ProviderResponseError) as caught:
        provider.status(REQUEST_ID)
    assert caught.value.status_code == 200


@pytest.mark.parametrize("payload", [
    {"status": "done"}, {"status": "COMPLETED"}, {"status": "Queued"}, {"status": None}, {"status": 3},
    {}, {"state": "completed"}, [{"status": "completed"}], "completed",
])
def test_unknown_status_is_a_response_error(payload):
    provider, _ = make((200, payload))
    with pytest.raises(ProviderResponseError) as caught:
        provider.status(REQUEST_ID)
    assert caught.value.code == "video_ai_bad_response"
    assert str(caught.value) == "AI 영상 공급사 응답 형식을 확인하지 못했습니다. 해당 장면을 카드로 바꾸거나 다시 시도하세요."


@pytest.mark.parametrize("data", [b"", b"<html>oops</html>", b"\xff"])
def test_status_with_unreadable_body_is_a_response_error(data):
    provider, _ = make((200, data))
    with pytest.raises(ProviderResponseError):
        provider.status(REQUEST_ID)


def test_completed_with_video_url():
    provider, _ = make((200, {"status": "completed", "video": {"url": CLIP_URL}, "request_id": REQUEST_ID}))
    result = provider.status(REQUEST_ID)
    assert result == ClipStatus(COMPLETED, CLIP_URL, {"result_shape": "video.url"})


def test_completed_with_videos_list_url():
    provider, _ = make((200, {"status": "completed", "videos": [{"url": CLIP_URL}, {"url": "https://x.example/2"}]}))
    result = provider.status(REQUEST_ID)
    assert result == ClipStatus(COMPLETED, CLIP_URL, {"result_shape": "videos[0].url"})


def test_video_url_prefers_video_object():
    assert video_url({"video": {"url": "https://a.example/v"}, "videos": [{"url": "https://b.example/v"}]}) == (
        "https://a.example/v")
    assert video_url({"images": [{"url": "https://a.example/i.png"}]}) is None


@pytest.mark.parametrize("payload", [
    {"status": "completed"},
    {"status": "completed", "video": {}},
    {"status": "completed", "video": {"url": 5}},
    {"status": "completed", "video": CLIP_URL},
    {"status": "completed", "videos": []},
    {"status": "completed", "videos": [{}]},
    {"status": "completed", "videos": [CLIP_URL]},
    {"status": "completed", "videos": {"url": CLIP_URL}},
    {"status": "completed", "images": [{"url": CLIP_URL}]},
])
def test_completed_without_a_video_url_is_a_response_error(payload):
    provider, _ = make((200, payload))
    with pytest.raises(ProviderResponseError) as caught:
        provider.status(REQUEST_ID)
    assert caught.value.status_code == 200


STATUS_ERRORS = [
    (401, ProviderAuthError), (402, ProviderCreditError), (403, ProviderCreditError), (400, ProviderInputError),
    (422, ProviderInputError), (408, ProviderRateLimited), (429, ProviderRateLimited), (500, ProviderUnavailable),
    (502, ProviderUnavailable), (503, ProviderUnavailable), (504, ProviderUnavailable), (409, ProviderResponseError),
]


@pytest.mark.parametrize(("status", "error"), STATUS_ERRORS)
def test_status_http_errors(status, error):
    provider, requester = make((status, {"detail": f"echo {KEY}"}))
    with pytest.raises(VideoProviderError) as caught:
        provider.status(REQUEST_ID)
    assert type(caught.value) is error
    assert caught.value.status_code == status
    assert str(caught.value) == error.message
    assert len(requester.calls) == 1
    assert_no_secret(caught.value)


def test_status_server_error_is_unavailable_not_ambiguous():
    provider, _ = make((500, b""))
    with pytest.raises(ProviderUnavailable) as caught:
        provider.status(REQUEST_ID)
    assert not isinstance(caught.value, ProviderAmbiguousSubmit)
    assert caught.value.retryable is True


@pytest.mark.parametrize("failure", [_NotSent(), ConnectionError(f"dropped {KEY}"), ConnectionAbortedError()])
def test_status_transport_failures_are_unavailable(failure):
    provider, requester = make(failure)
    with pytest.raises(ProviderUnavailable) as caught:
        provider.status(REQUEST_ID)
    assert len(requester.calls) == 1
    assert_no_secret(caught.value)


BAD_REQUEST_IDS = [None, 42, "", "short", "a" * 101, "../../admin", "abcdefgh/../x", "abcdefgh?x=1",
                   "abcdefgh#x", "abcd efgh", "abcdefgh\r\n", "abcdefgh%2f", "abc_defgh"]


@pytest.mark.parametrize("request_id", BAD_REQUEST_IDS)
@pytest.mark.parametrize("action", ["status", "cancel"])
def test_request_id_is_validated_before_any_request(request_id, action):
    provider, requester = make((200, {"status": "queued"}))
    with pytest.raises(ProviderResponseError) as caught:
        getattr(provider, action)(request_id)
    assert caught.value.sent is False
    assert requester.calls == []


@pytest.mark.parametrize("request_id", ["abcdefgh", "A1-b2-C3-d4", "a" * 100, REQUEST_ID])
def test_valid_request_ids_build_the_status_path(request_id):
    provider, requester = make((200, {"status": "queued"}))
    provider.status(request_id)
    assert requester.calls[0].path == f"/requests/{request_id}/status"


# --------------------------------------------------------------------------- cancel


@pytest.mark.parametrize("status", [200, 202, 204])
def test_cancel_accepted(status):
    provider, requester = make((status, b""))
    assert provider.cancel(REQUEST_ID) is True
    call = requester.calls[0]
    assert (call.method, call.path, call.body) == ("POST", f"/requests/{REQUEST_ID}/cancel", None)
    assert call.headers["Authorization"] == f"Key {KEY}"


def test_cancel_of_a_started_request_returns_false():
    provider, requester = make((400, {"detail": "already in progress"}))
    assert provider.cancel(REQUEST_ID) is False
    assert len(requester.calls) == 1


@pytest.mark.parametrize(
    ("status", "error"), [(401, ProviderAuthError), (429, ProviderRateLimited), (503, ProviderUnavailable)],
)
def test_cancel_errors(status, error):
    provider, _ = make((status, b""))
    with pytest.raises(error):
        provider.cancel(REQUEST_ID)


@pytest.mark.parametrize("failure", [_NotSent(), ConnectionError()])
def test_cancel_transport_failures_are_unavailable(failure):
    provider, _ = make(failure)
    with pytest.raises(ProviderUnavailable):
        provider.cancel(REQUEST_ID)


# --------------------------------------------------------------------------- facts / fetch


def test_credential_never_appears_in_status_facts_or_results():
    provider, _ = make(
        accepted(), (200, {"status": "completed", "video": {"url": CLIP_URL}, "echo": KEY, "auth": f"Key {KEY}"}),
    )
    submission = provider.submit(clip_request())
    result = provider.status(submission.request_id)
    assert result.facts == {"result_shape": "video.url"}
    assert all(isinstance(v, str) and len(v) < 40 for v in result.facts.values())
    assert CLIP_URL not in json.dumps(result.facts)
    assert_no_secret(submission, result, result.facts)


def test_fetch_hands_only_the_url_to_the_downloader_without_the_credential(tmp_path):
    used = []

    def credential():
        used.append(1)
        return KEY

    opener = FakeOpener(ok(b"mp4-bytes"))
    provider = HiggsfieldProvider(credential, requester=FakeRequester(), downloader=SafeDownloader(opener))
    target = tmp_path / "clip.mp4"
    result = provider.fetch(ClipStatus(COMPLETED, CLIP_URL), target, Event())
    assert result.bytes == 9 and target.read_bytes() == b"mp4-bytes"
    assert used == []  # the API key is not even read for the download
    assert opener.calls == [(CLIP_URL, "GET", 20)]  # url, method, timeout: no header channel at all


@pytest.mark.parametrize("status", [ClipStatus(QUEUED, CLIP_URL), ClipStatus(COMPLETED), ClipStatus(COMPLETED, "")])
def test_fetch_requires_a_completed_status_with_url(tmp_path, status):
    opener = FakeOpener()
    provider = HiggsfieldProvider(lambda: KEY, requester=FakeRequester(), downloader=SafeDownloader(opener))
    with pytest.raises(ProviderResponseError) as caught:
        provider.fetch(status, tmp_path / "clip.mp4", Event())
    assert caught.value.sent is False
    assert opener.calls == []
    assert not (tmp_path / "clip.mp4").exists()


# --------------------------------------------------------------------------- pinned requester (real http.client)


def test_pinned_requester_writes_exact_request_bytes(monkeypatch):
    reply = json.dumps({"request_id": REQUEST_ID, "status": "queued"}).encode()
    wire = Wire(http_reply(200, reply))
    lookups = install(monkeypatch, higgsfield, wire)
    provider = HiggsfieldProvider(lambda: KEY, timeout=7)
    assert provider.submit(clip_request()) == Submission(REQUEST_ID, QUEUED)
    assert lookups == [("api.higgsfield.ai", 443, 7)]
    assert wire.created == [("api.higgsfield.ai", PUBLIC_IP, 443, 7, True)]
    line, headers, body = wire.parsed()
    assert line == f"POST /{MODEL} HTTP/1.1"
    assert header_values(headers, "Authorization") == [f"Key {KEY}"]
    assert header_values(headers, "Content-Type") == ["application/json"]
    assert header_values(headers, "Accept") == ["application/json"]
    assert header_values(headers, "User-Agent") == [USER_AGENT]
    assert header_values(headers, "Accept-Encoding") == ["identity"]
    assert header_values(headers, "Content-Length") == [str(len(body))]
    assert len(header_values(headers, "Host")) == 1
    assert header_values(headers, "Host")[0].split(":")[0] == "api.higgsfield.ai"
    assert json.loads(body) == {"prompt": PROMPT, "duration": 5, "aspect_ratio": "9:16", "resolution": "720p"}
    assert all(s.closed for s in wire.sockets)


def test_pinned_requester_status_and_cancel_lines(monkeypatch):
    wire = Wire(http_reply(200, b'{"status": "in_progress"}'))
    install(monkeypatch, higgsfield, wire)
    provider = HiggsfieldProvider(lambda: KEY)
    assert provider.status(REQUEST_ID) == ClipStatus(IN_PROGRESS)
    assert wire.parsed()[0] == f"GET /requests/{REQUEST_ID}/status HTTP/1.1"
    assert header_values(wire.parsed()[1], "Content-Length") == []

    wire = Wire(http_reply(400, b'{"detail": "started"}'))
    install(monkeypatch, higgsfield, wire)
    assert provider.cancel(REQUEST_ID) is False
    assert wire.parsed()[0] == f"POST /requests/{REQUEST_ID}/cancel HTTP/1.1"


@pytest.mark.parametrize("stage", ["dns", "policy", "connect-os", "connect-tls"])
def test_pinned_requester_failures_before_sending_are_not_sent(monkeypatch, stage):
    wire = Wire(
        http_reply(200, b"{}"),
        connect_error={"connect-os": ConnectionRefusedError(), "connect-tls": ssl.SSLError("handshake")}.get(stage),
    )
    install(monkeypatch, higgsfield, wire)
    if stage in ("dns", "policy"):
        def failing(host, port, timeout=10):
            from newsflow.news.rss_adapter import FeedError

            raise FeedError("dns") if stage == "dns" else URLPolicyError("private")

        monkeypatch.setattr(higgsfield, "public_addresses", failing)
    provider = HiggsfieldProvider(lambda: KEY)
    with pytest.raises(ProviderUnavailable) as caught:
        provider.submit(clip_request())
    assert caught.value.sent is False
    assert wire.sent == b""
    if stage in ("dns", "policy"):
        assert wire.created == []


@pytest.mark.parametrize("reply", [None, b"NOT AN HTTP REPLY\r\n\r\n", b""])
def test_pinned_requester_failures_after_connect_are_ambiguous_on_submit(monkeypatch, reply):
    if reply is None:
        wire = Wire(b"", send_error=ConnectionResetError())
    else:
        wire = Wire(reply)
    install(monkeypatch, higgsfield, wire)
    provider = HiggsfieldProvider(lambda: KEY)
    with pytest.raises(ProviderAmbiguousSubmit) as caught:
        provider.submit(clip_request())
    assert caught.value.sent is True
    assert len(wire.created) == 1  # exactly one connection: never resent
    assert all(s.closed for s in wire.sockets)
    assert_no_secret(caught.value)


def test_pinned_requester_bounds_the_response(monkeypatch):
    big = b'{"request_id": "' + b"a" * MAX_RESPONSE_BYTES + b'"}'
    wire = Wire(http_reply(200, big))
    install(monkeypatch, higgsfield, wire)
    provider = HiggsfieldProvider(lambda: KEY)
    with pytest.raises(ProviderAmbiguousSubmit):
        provider.submit(clip_request())
    install(monkeypatch, higgsfield, Wire(http_reply(200, big)))
    with pytest.raises(ProviderResponseError):
        provider.status(REQUEST_ID)


# --------------------------------------------------------------------------- SafeDownloader: success


def test_download_streams_to_target_and_reports_hash_size_host(tmp_path):
    chunks = [b"\x00\x00\x00\x18ftypmp42", b"x" * 1000, b"tail"]
    opener = FakeOpener(ok(*chunks))
    downloader = SafeDownloader(opener, connect_timeout=4)
    target = tmp_path / "clip-1.mp4"
    result = downloader.fetch(CLIP_URL, target, Event())
    data = b"".join(chunks)
    assert result == FetchResult(target, len(data), hashlib.sha256(data).hexdigest(), "cdn.example.com")
    assert target.read_bytes() == data
    assert opener.calls == [(CLIP_URL, "GET", 4)]
    assert opener.closed == 1


@pytest.mark.parametrize(
    "kind", ["video/mp4", "video/quicktime", "video/webm", "application/octet-stream", "binary/octet-stream",
             "Video/MP4", "video/mp4; codecs=avc1"],
)
def test_download_accepts_video_content_types(tmp_path, kind):
    opener = FakeOpener(ok(b"data", kind=kind, **{"Content-Encoding": " Identity "}))
    assert SafeDownloader(opener).fetch(CLIP_URL, tmp_path / "c.mp4", Event()).bytes == 4


def test_download_without_content_length_is_bounded_by_stream(tmp_path):
    opener = FakeOpener(ok(b"abc", b"def", length=None))
    result = SafeDownloader(opener).fetch(CLIP_URL, tmp_path / "c.mp4", Event())
    assert result.bytes == 6


def test_explicit_default_port_is_normalised(tmp_path):
    opener = FakeOpener(ok(b"data"))
    SafeDownloader(opener).fetch("https://cdn.example.com:443/a.mp4", tmp_path / "c.mp4", Event())
    assert opener.calls[0][0] == "https://cdn.example.com/a.mp4"


# --------------------------------------------------------------------------- SafeDownloader: URL policy


@pytest.mark.parametrize("url", [
    "http://cdn.example.com/a.mp4", "file:///etc/passwd", "file://C:/Windows/win.ini", "ftp://cdn.example.com/a.mp4",
    "HTTP://cdn.example.com/a.mp4", "//cdn.example.com/a.mp4", "cdn.example.com/a.mp4", "", "data:video/mp4,AAAA",
    "javascript:alert(1)", " https://cdn.example.com/a.mp4",
])
def test_only_https_urls_are_fetched(tmp_path, url):
    opener = FakeOpener(ok(b"data"))
    with pytest.raises(ClipDownloadError):
        SafeDownloader(opener).fetch(url, tmp_path / "c.mp4", Event())
    assert opener.calls == []


@pytest.mark.parametrize("url", [
    "https://user:pass@cdn.example.com/a.mp4", "https://user@cdn.example.com/a.mp4", "https://:pw@cdn.example.com/",
])
def test_userinfo_is_rejected(tmp_path, url):
    opener = FakeOpener(ok(b"data"))
    with pytest.raises(ClipDownloadError):
        SafeDownloader(opener).fetch(url, tmp_path / "c.mp4", Event())
    assert opener.calls == []


@pytest.mark.parametrize("url", [
    "https://cdn.example.com:8443/a.mp4", "https://cdn.example.com:80/a.mp4", "https://cdn.example.com:0/a.mp4",
    "https://cdn.example.com:99999/a.mp4",
])
def test_non_default_port_is_rejected(tmp_path, url):
    opener = FakeOpener(ok(b"data"))
    with pytest.raises(ClipDownloadError):
        SafeDownloader(opener).fetch(url, tmp_path / "c.mp4", Event())
    assert opener.calls == []


PRIVATE_URLS = [
    "https://127.0.0.1/a.mp4", "https://127.1.2.3/a.mp4", "https://10.0.0.8/a.mp4", "https://172.16.4.4/a.mp4",
    "https://192.168.1.10/a.mp4", "https://169.254.169.254/latest/meta-data/", "https://100.64.0.1/a.mp4",
    "https://0.0.0.0/a.mp4", "https://[::1]/a.mp4", "https://[fd00::1]/a.mp4", "https://[fe80::1]/a.mp4",
    "https://[::ffff:127.0.0.1]/a.mp4", "https://localhost/a.mp4", "https://cdn.localhost/a.mp4",
    "https://media.internal/a.mp4", "https://nas.local/a.mp4", "https://intranet/a.mp4", "https://224.0.0.1/a.mp4",
]


@pytest.mark.parametrize("url", PRIVATE_URLS)
def test_private_and_loopback_hosts_are_rejected_by_validate_url(tmp_path, url):
    with pytest.raises(URLPolicyError):
        validate_url(url)
    with pytest.raises(ClipDownloadError):
        safe_url(url)
    opener = FakeOpener(ok(b"data"))
    with pytest.raises(ClipDownloadError):
        SafeDownloader(opener).fetch(url, tmp_path / "c.mp4", Event())
    assert opener.calls == []


@pytest.mark.parametrize("url", [
    "https://cdn.example.com/a.mp4#t=1", "https://cdn.example.com/a.mp4?x=1#t=1",
    "https://cdn.exa mple.com/a.mp4", "https://cdn.example.com\\@evil/", "https://cdn.example.com/a.mp4?x=a b",
    "https://cdn.example.com/a.mp4?x=\u00e9", "https://cdn.example.com/" + "a" * 2100,
    "https://cdn.example.com/a.mp4?" + "x" * 6001, "https://user:pw@cdn.example.com/a.mp4?sig=1",
    "https://cdn.example.com:8443/a.mp4?sig=1", "https://127.0.0.1/a.mp4?sig=1",
])
def test_other_unsafe_url_forms_are_rejected(url):
    with pytest.raises(ClipDownloadError) as caught:
        safe_url(url)
    assert str(caught.value) == "생성된 영상을 안전하게 내려받지 못했습니다. 주소·크기·형식 검사를 통과하지 못했습니다."
    assert caught.value.code == "video_ai_download_failed"


@pytest.mark.parametrize("query", [
    "token=abc", "X-Amz-Signature=0a1b&X-Amz-Expires=3600", "Expires=1&Signature=a~b_c&Key-Pair-Id=K1",
])
def test_signed_result_urls_keep_their_query(query):
    """A result URL may be a signed CDN address; its query is kept (never stored or logged)."""
    assert safe_url(f"https://cdn.example.com/a.mp4?{query}") == f"https://cdn.example.com/a.mp4?{query}"



# --------------------------------------------------------------------------- SafeDownloader: redirects


def test_up_to_three_redirects_are_followed_and_each_hop_is_closed(tmp_path):
    assert MAX_REDIRECTS == 3
    opener = FakeOpener(
        redirect("https://media.example.org/b.mp4", 302),
        redirect("/c.mp4?sig=1", 301),
        redirect("https://files.example.net/d.mp4", 307),
        ok(b"clip"),
    )
    result = SafeDownloader(opener).fetch(CLIP_URL, tmp_path / "c.mp4", Event())
    assert [c[0] for c in opener.calls] == [
        CLIP_URL, "https://media.example.org/b.mp4", "https://media.example.org/c.mp4?sig=1",
        "https://files.example.net/d.mp4",
    ]
    assert result.host == "files.example.net"
    assert opener.closed == 4


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_each_redirect_status_is_followed(tmp_path, status):
    opener = FakeOpener(redirect("https://media.example.org/b.mp4", status), ok(b"clip"))
    assert SafeDownloader(opener).fetch(CLIP_URL, tmp_path / "c.mp4", Event()).host == "media.example.org"


def test_fourth_redirect_is_rejected(tmp_path):
    opener = FakeOpener(*(redirect(f"https://hop{i}.example.com/a.mp4") for i in range(4)), ok(b"clip"))
    target = tmp_path / "c.mp4"
    with pytest.raises(ClipDownloadError):
        SafeDownloader(opener).fetch(CLIP_URL, target, Event())
    assert len(opener.calls) == 4
    assert opener.closed == 4
    assert len(opener.responses) == 1  # the final 200 was never requested
    assert not target.exists()


@pytest.mark.parametrize("location", [
    "http://media.example.org/b.mp4", "https://127.0.0.1/b.mp4", "https://169.254.169.254/latest/",
    "https://[::1]/b.mp4", "https://localhost/b.mp4", "https://user:pw@media.example.org/b.mp4",
    "https://media.example.org:8443/b.mp4", "file:///etc/passwd", "ftp://media.example.org/b.mp4",
    "//10.0.0.1/b.mp4",
])
def test_redirect_to_unsafe_target_is_rejected(tmp_path, location):
    opener = FakeOpener(redirect(location), ok(b"clip"))
    target = tmp_path / "c.mp4"
    with pytest.raises(ClipDownloadError):
        SafeDownloader(opener).fetch(CLIP_URL, target, Event())
    assert len(opener.calls) == 1
    assert opener.closed == 1
    assert not target.exists()


@pytest.mark.parametrize("location", [None, ""])
def test_redirect_without_location_is_rejected(tmp_path, location):
    opener = FakeOpener(redirect(location), ok(b"clip"))
    with pytest.raises(ClipDownloadError):
        SafeDownloader(opener).fetch(CLIP_URL, tmp_path / "c.mp4", Event())
    assert len(opener.calls) == 1 and opener.closed == 1


# --------------------------------------------------------------------------- SafeDownloader: response checks


@pytest.mark.parametrize("status", [201, 204, 206, 304, 400, 403, 404, 500, 503])
def test_non_200_final_status_is_rejected(tmp_path, status):
    response = FakeResponse(status, {"Content-Type": "video/mp4", "Content-Length": "4"}, [b"data"])
    opener = FakeOpener(response)
    target = tmp_path / "c.mp4"
    with pytest.raises(ClipDownloadError):
        SafeDownloader(opener).fetch(CLIP_URL, target, Event())
    assert response.reads == 0 and opener.closed == 1
    assert not target.exists()


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate", "x-gzip", "gzip, identity"])
def test_compressed_responses_are_rejected(tmp_path, encoding):
    response = ok(b"data", **{"Content-Encoding": encoding})
    target = tmp_path / "c.mp4"
    with pytest.raises(ClipDownloadError):
        SafeDownloader(FakeOpener(response)).fetch(CLIP_URL, target, Event())
    assert response.reads == 0
    assert not target.exists()


@pytest.mark.parametrize("kind", ["text/html", "text/html; charset=utf-8", "application/json", "image/png",
                                  "video/mp4x", "", None])
def test_non_video_content_types_are_rejected(tmp_path, kind):
    headers = {"Content-Length": "4"} | ({"Content-Type": kind} if kind is not None else {})
    response = FakeResponse(200, headers, [b"data"])
    target = tmp_path / "c.mp4"
    with pytest.raises(ClipDownloadError):
        SafeDownloader(FakeOpener(response)).fetch(CLIP_URL, target, Event())
    assert response.reads == 0
    assert not target.exists()


def test_declared_length_over_limit_is_rejected_before_reading(tmp_path):
    response = ok(b"x" * 11, length="11")
    target = tmp_path / "c.mp4"
    with pytest.raises(ClipDownloadError):
        SafeDownloader(FakeOpener(response), max_bytes=10).fetch(CLIP_URL, target, Event())
    assert response.reads == 0
    assert not target.exists()


def test_declared_length_at_limit_is_accepted(tmp_path):
    result = SafeDownloader(FakeOpener(ok(b"x" * 10)), max_bytes=10).fetch(CLIP_URL, tmp_path / "c.mp4", Event())
    assert result.bytes == 10


@pytest.mark.parametrize("length", ["abc", "-1", "1e3", "", "4.0", "0x10", " "])
def test_malformed_content_length_is_rejected(tmp_path, length):
    response = ok(b"data", length=length)
    target = tmp_path / "c.mp4"
    with pytest.raises(ClipDownloadError):
        SafeDownloader(FakeOpener(response)).fetch(CLIP_URL, target, Event())
    assert response.reads == 0
    assert not target.exists()


@pytest.mark.parametrize("length", ["\xb2", "\xb3", "1\xb9"])
def test_content_length_with_non_ascii_digit_is_rejected(tmp_path, length):
    """HTTP headers decode as latin-1; '²' passes str.isdigit() but int() rejects it."""
    response = ok(b"data", length=length)
    target = tmp_path / "c.mp4"
    with pytest.raises(ClipDownloadError):
        SafeDownloader(FakeOpener(response)).fetch(CLIP_URL, target, Event())
    assert not target.exists()


def test_streamed_size_over_limit_is_rejected_and_partial_file_removed(tmp_path):
    response = ok(b"x" * 6, b"x" * 6, b"x" * 6, length=None)
    target = tmp_path / "c.mp4"
    with pytest.raises(ClipDownloadError):
        SafeDownloader(FakeOpener(response), max_bytes=10).fetch(CLIP_URL, target, Event())
    assert response.reads == 2  # stops at the chunk that crosses the limit
    assert not target.exists()


@pytest.mark.parametrize(("length", "chunks"), [("10", [b"12345"]), ("3", [b"12345"]), ("0", []), (None, [])])
def test_size_mismatch_or_empty_body_is_rejected_and_file_removed(tmp_path, length, chunks):
    response = ok(*chunks, length=length)
    target = tmp_path / "c.mp4"
    with pytest.raises(ClipDownloadError):
        SafeDownloader(FakeOpener(response)).fetch(CLIP_URL, target, Event())
    assert not target.exists()


@pytest.mark.parametrize("error", [OSError("reset"), TimeoutError(), ssl.SSLError("bad record"),
                                   http.client.IncompleteRead(b"x")])
def test_read_failures_remove_the_partial_file(tmp_path, error):
    response = FakeResponse(200, {"Content-Type": "video/mp4"}, [b"first"], error=error)
    target = tmp_path / "c.mp4"
    with pytest.raises(ClipDownloadError) as caught:
        SafeDownloader(FakeOpener(response)).fetch(CLIP_URL, target, Event())
    assert caught.value.__cause__ is None
    assert not target.exists()


def test_cancel_during_stream_aborts_and_removes_file(tmp_path):
    cancel = Event()

    def on_read(response):
        if response.reads == 2:
            cancel.set()

    response = ok(b"a" * 10, b"b" * 10, b"c" * 10, length=None)
    response.on_read = on_read
    target = tmp_path / "c.mp4"
    opener = FakeOpener(response)
    with pytest.raises(ClipDownloadError):
        SafeDownloader(opener).fetch(CLIP_URL, target, cancel)
    assert response.reads == 2
    assert opener.closed == 1
    assert not target.exists()


def test_cancel_before_start_never_opens(tmp_path):
    cancel = Event()
    cancel.set()
    opener = FakeOpener(ok(b"data"))
    with pytest.raises(ClipDownloadError):
        SafeDownloader(opener).fetch(CLIP_URL, tmp_path / "c.mp4", cancel)
    assert opener.calls == []


def test_cancel_between_redirects_stops_following(tmp_path):
    cancel = Event()

    class Opener(FakeOpener):
        def __call__(self, *args):
            result = super().__call__(*args)
            cancel.set()
            return result

    opener = Opener(redirect("https://media.example.org/b.mp4"), ok(b"clip"))
    with pytest.raises(ClipDownloadError):
        SafeDownloader(opener).fetch(CLIP_URL, tmp_path / "c.mp4", cancel)
    assert len(opener.calls) == 1 and opener.closed == 1


def test_expired_deadline_never_opens(tmp_path):
    opener = FakeOpener(ok(b"data"))
    with pytest.raises(ClipDownloadError):
        SafeDownloader(opener, timeout=-1).fetch(CLIP_URL, tmp_path / "c.mp4", Event())
    assert opener.calls == []


def test_existing_target_is_never_overwritten(tmp_path):
    target = tmp_path / "c.mp4"
    target.write_bytes(b"keep me")
    response = ok(b"new data")
    with pytest.raises(ClipDownloadError):
        SafeDownloader(FakeOpener(response)).fetch(CLIP_URL, target, Event())
    assert target.read_bytes() == b"keep me"
    assert response.reads == 0


def test_missing_target_directory_is_a_download_error(tmp_path):
    with pytest.raises(ClipDownloadError):
        SafeDownloader(FakeOpener(ok(b"data"))).fetch(CLIP_URL, tmp_path / "missing" / "c.mp4", Event())


# --------------------------------------------------------------------------- default pinned opener


def test_default_opener_pins_dns_and_never_sends_authorization(monkeypatch, tmp_path):
    wire = Wire(http_reply(200, b"\x00\x00\x00\x18ftypmp42", "video/mp4"))
    lookups = install(monkeypatch, download, wire)
    provider = HiggsfieldProvider(lambda: KEY, requester=FakeRequester())
    provider.downloader = SafeDownloader(connect_timeout=6)
    target = tmp_path / "c.mp4"
    result = provider.fetch(ClipStatus(COMPLETED, CLIP_URL), target, Event())
    assert result.bytes == 12 and result.host == "cdn.example.com"
    assert lookups == [("cdn.example.com", 443, 6)]
    assert wire.created == [("cdn.example.com", PUBLIC_IP, 443, 6, True)]
    line, headers, body = wire.parsed()
    assert line == "GET /clips/a.mp4?Expires=1700000000&Signature=abc&Key-Pair-Id=K1 HTTP/1.1"
    assert body == b""
    names = {name.lower() for name, _ in headers}
    assert "authorization" not in names and "cookie" not in names
    assert header_values(headers, "Accept-Encoding") == ["identity"]
    assert header_values(headers, "User-Agent") == [download.USER_AGENT]
    assert header_values(headers, "Accept") == ["video/*, application/octet-stream"]
    assert KEY_SECRET.encode() not in wire.sent and KEY_ID.encode() not in wire.sent
    assert all(s.closed for s in wire.sockets)


def test_default_opener_sends_bare_host_header(monkeypatch, tmp_path):
    """Signed CDN URLs (S3/GCS SigV4) sign the Host header; https clients send it without ':443'."""
    wire = Wire(http_reply(200, b"data", "video/mp4"))
    install(monkeypatch, download, wire)
    SafeDownloader().fetch(CLIP_URL, tmp_path / "c.mp4", Event())
    assert header_values(wire.parsed()[1], "Host") == ["cdn.example.com"]


def test_default_opener_follows_redirect_with_a_new_pinned_connection(monkeypatch, tmp_path):
    replies = [
        b"HTTP/1.1 302 Found\r\nLocation: https://media.example.org/v.mp4\r\nContent-Length: 0\r\n\r\n",
        http_reply(200, b"clip", "video/mp4"),
    ]
    created: list[tuple] = []
    sent: list[bytes] = []

    class Pinned(http.client.HTTPConnection):
        def __init__(self, host, ip, port, timeout, tls):
            super().__init__(host, port, timeout=timeout)
            created.append((host, ip, port, tls))

        def connect(self):
            self.sock = FakeSocket(replies.pop(0))
            self._fake = self.sock

        def close(self):
            if getattr(self, "_fake", None) is not None:
                sent.append(bytes(self._fake.sent))
            super().close()

    monkeypatch.setattr(download, "PinnedConnection", Pinned)
    monkeypatch.setattr(download, "public_addresses", lambda host, port, timeout=10: [PUBLIC_IP])
    result = SafeDownloader().fetch(CLIP_URL, tmp_path / "c.mp4", Event())
    assert result.host == "media.example.org" and result.bytes == 4
    assert created == [("cdn.example.com", PUBLIC_IP, 443, True), ("media.example.org", PUBLIC_IP, 443, True)]
    assert sent[-1].startswith(b"GET /v.mp4 HTTP/1.1\r\n")
    assert all(b"authorization" not in s.lower() for s in sent)


@pytest.mark.parametrize("answers", [["10.0.0.7"], [PUBLIC_IP, "127.0.0.1"], ["169.254.169.254"], ["::1"]])
def test_default_opener_rejects_hosts_resolving_to_private_addresses(monkeypatch, tmp_path, answers):
    def resolver(host, port, *args, **kwargs):
        family = socket.AF_INET6 if ":" in answers[0] else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in answers]

    def never(*args, **kwargs):
        raise AssertionError("no connection may be built for a private answer")

    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    monkeypatch.setattr(download, "PinnedConnection", never)
    target = tmp_path / "c.mp4"
    with pytest.raises(ClipDownloadError):
        SafeDownloader(connect_timeout=2).fetch(CLIP_URL, target, Event())
    assert not target.exists()


def test_default_opener_request_failure_is_a_download_error_and_closes(monkeypatch, tmp_path):
    wire = Wire(b"", send_error=ConnectionResetError())
    install(monkeypatch, download, wire)
    target = tmp_path / "c.mp4"
    with pytest.raises(ClipDownloadError) as caught:
        SafeDownloader().fetch(CLIP_URL, target, Event())
    assert caught.value.__cause__ is None
    assert all(s.closed for s in wire.sockets)
    assert not target.exists()


def test_download_error_messages_never_carry_url_or_credential(tmp_path):
    opener = FakeOpener(redirect(f"https://user:{KEY_SECRET}@media.example.org/b.mp4"))
    with pytest.raises(ClipDownloadError) as caught:
        SafeDownloader(opener).fetch(CLIP_URL, tmp_path / "c.mp4", Event())
    assert_no_secret(caught.value)
    assert "cdn.example.com" not in str(caught.value) and "Signature" not in str(caught.value)


# --------------------------------------------------------------------------- Idempotency-Key and 404 on requests


def test_submit_sends_the_scene_attempt_idempotency_key_only_when_it_is_well_formed():
    """Whether Higgsfield honours Idempotency-Key is NOT VERIFIED; it is sent but nothing relies on it."""
    key = "0123456789abcdef0123456789abcdef"
    provider, requester = make(accepted(), accepted(), accepted())
    provider.submit(ClipRequest(MODEL, PROMPT, 5, "720p", idempotency_key=key))
    provider.submit(ClipRequest(MODEL, PROMPT, 5, "720p", idempotency_key="bad key\r\nX: 1"))
    provider.submit(clip_request())
    assert requester.calls[0].headers["Idempotency-Key"] == key
    assert "Idempotency-Key" not in requester.calls[1].headers and "Idempotency-Key" not in requester.calls[2].headers
    assert all(call.method == "POST" for call in requester.calls) and len(requester.calls) == 3


@pytest.mark.parametrize("action", ["status", "cancel"])
def test_404_on_a_request_means_the_provider_no_longer_knows_it(action):
    from newsflow.video.ai.contracts import ProviderRequestMissing

    provider, requester = make((404, {"detail": "Not found"}))
    with pytest.raises(ProviderRequestMissing) as caught:
        provider.status(REQUEST_ID) if action == "status" else provider.cancel(REQUEST_ID)
    assert caught.value.code == "video_ai_request_missing" and caught.value.status_code == 404
    assert "Not found" not in str(caught.value) and len(requester.calls) == 1
