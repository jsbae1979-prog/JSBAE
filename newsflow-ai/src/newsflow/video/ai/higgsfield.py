"""Higgsfield video provider over the request lifecycle shown in official Higgsfield code.

Verified from the official Python SDK wheel (PyPI ``higgsfield-client`` 0.2.0, author
support@higgsfield.ai) and the official app templates (github.com/higgsfield-ai/app-templates,
commit 1e15e22, 2026-10-06, ``generation/platform.ts``, ``credentials.ts``, ``catalog/``):
base ``https://api.higgsfield.ai``; header ``Authorization: Key <apiKey>``; submit =
``POST {base}/{model path}`` with a JSON body, answered by ``request_id``, ``status_url`` and
``cancel_url``; status = ``GET {base}/requests/{id}/status`` whose ``status`` is queued /
in_progress / completed / failed / nsfw / canceled, with the clip at ``video.url`` when completed;
cancel = ``POST {base}/requests/{id}/cancel`` (queued requests only; 202, then "canceled").
The templates' generic text-to-video body is ``prompt``, ``aspect_ratio``, ``resolution`` and
``duration`` (seconds, a number), which is what this client sends.

Official docs were rechecked on 2026-10-16 (see phase5d1_higgsfield_verification.md).
Their account-specific prices, permissions, refunds and idempotency behaviour have not been
exercised. The four-field body is checked against dated model contracts before submission.
A submit is never automatically retried, including HTTP 408/429. This limits client requests;
it does not claim verified supplier billing behaviour.
"""

from __future__ import annotations

import http.client
import json
import re
import ssl
from collections.abc import Callable
from pathlib import Path
from threading import Event

from newsflow.news.rss_adapter import (
    FeedError,
    PinnedConnection,
    URLPolicyError,
    public_addresses,
    validate_url,
)

from .contracts import (
    COMPLETED,
    PROVIDER_STATES,
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
    ProviderRequestMissing,
    ProviderResponseError,
    ProviderUnavailable,
    Submission,
    VideoProviderError,
)
from .download import SafeDownloader
from .keys import VideoAIKeyStore
from .model_contracts import check_model_contract
from .settings import HOSTS, VideoSettingsError, validate_path

USER_AGENT = "NewsFlowAI/0.6 (+local news briefing; Higgsfield REST)"
REQUEST_ID = re.compile(r"[A-Za-z0-9-]{8,100}")
IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9-]{8,64}")
MAX_RESPONSE_BYTES = 1024 * 1024

# (status, data) after reading the whole bounded response.
Requester = Callable[[str, str, str, bytes | None, dict, float], tuple[int, bytes]]


class _NotSent(Exception):
    """The request never left this computer (DNS, address policy, connect, TLS handshake)."""


def pinned_requester(host: str, method: str, path: str, body: bytes | None, headers: dict, timeout: float) -> tuple[int, bytes]:
    url = f"https://{host}{path}"
    try:
        validate_url(url)
        addresses = public_addresses(host, 443, timeout)
        connection = PinnedConnection(host, addresses[0], 443, timeout, True)
        connection.connect()
    except (URLPolicyError, FeedError, OSError, ssl.SSLError):
        raise _NotSent() from None
    try:
        # An explicit Host keeps http.client from sending 'host:443'. A ValueError comes from header
        # validation before anything is written to the socket, so the request was not sent.
        connection.request(method, path, body=body, headers={"Host": host, **headers})
    except ValueError:
        connection.close()
        raise _NotSent() from None
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        connection.close()
        raise ConnectionError() from exc
    try:
        response = connection.getresponse()
        data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise ProviderResponseError()
        return response.status, data
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise ConnectionError() from exc
    finally:
        connection.close()


class HiggsfieldProvider:
    name = "higgsfield"
    label = "Higgsfield"

    def __init__(
        self, credential: Callable[[], str], *, host: str = HOSTS[0], timeout: float = 30,
        requester: Requester | None = None, downloader: SafeDownloader | None = None,
    ) -> None:
        if host not in HOSTS:
            raise ValueError("unsupported Higgsfield host")
        self.credential, self.host, self.timeout = credential, host, timeout
        self.requester = requester or pinned_requester
        self.downloader = downloader or SafeDownloader()

    def _headers(self) -> dict:
        try:
            key = self.credential() or ""
        except Exception:  # noqa: BLE001 - a key store failure is reported without its text
            key = ""
        # The stored key was checked on save, but an environment value was not: anything other
        # than one printable ASCII token never reaches a header (no CR/LF header injection).
        if not isinstance(key, str) or not VideoAIKeyStore.PATTERN.fullmatch(key.strip()):
            raise ProviderNotConfigured(sent=False)
        key = key.strip()
        return {
            "Authorization": f"Key {key}", "Content-Type": "application/json", "Accept": "application/json",
            "User-Agent": USER_AGENT, "Accept-Encoding": "identity",
        }

    def _call(self, method: str, path: str, payload: dict | None = None, extra: dict | None = None) -> tuple[int, dict]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {**self._headers(), **(extra or {})}
        status, data = self.requester(self.host, method, path, body, headers, self.timeout)
        try:
            parsed = json.loads(data.decode("utf-8")) if data else {}
        except (UnicodeDecodeError, ValueError):
            parsed = None
        return status, parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _error(status: int, *, submit: bool) -> VideoProviderError:
        if status == 401:
            return ProviderAuthError(status_code=status)
        if status in (402, 403):
            return ProviderCreditError(status_code=status)
        if status == 404:
            return ProviderModelError(status_code=status)
        if status in (400, 422):
            return ProviderInputError(status_code=status)
        if status in (408, 429):
            return ProviderAmbiguousSubmit(status_code=status) if submit else ProviderRateLimited(status_code=status)
        if status >= 500 and submit:
            # The request reached a server that failed; it may still have been queued and billed.
            return ProviderAmbiguousSubmit(status_code=status)
        if status >= 500:
            return ProviderUnavailable(status_code=status)
        return ProviderResponseError(status_code=status)

    def submit(self, request: ClipRequest) -> Submission:
        try:
            path = "/" + validate_path(request.model_path)
        except VideoSettingsError:
            raise ProviderInputError(sent=False) from None
        if check_model_contract(request.model_path, (request.seconds,), request.resolution)[0] == "FAIL":
            raise ProviderInputError(sent=False)
        payload = {
            "prompt": request.prompt, "duration": int(request.seconds),
            "aspect_ratio": request.aspect_ratio, "resolution": request.resolution,
        }
        key = request.idempotency_key
        extra = {"Idempotency-Key": key} if key and IDEMPOTENCY_KEY.fullmatch(key) else None
        try:
            status, data = self._call("POST", path, payload, extra)
        except _NotSent:
            raise ProviderUnavailable(sent=False) from None
        except ConnectionError:
            raise ProviderAmbiguousSubmit() from None
        except ProviderResponseError:
            raise ProviderAmbiguousSubmit() from None
        if not 200 <= status < 300:
            raise self._error(status, submit=True)
        request_id = data.get("request_id")
        if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
            # Accepted (2xx) but unreadable: it may be running and billed.
            raise ProviderAmbiguousSubmit(status_code=status)
        state = data.get("status")
        return Submission(request_id, state if state in PROVIDER_STATES else "queued")

    def _request_path(self, request_id: str, action: str) -> str:
        if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
            raise ProviderResponseError(sent=False)
        return f"/requests/{request_id}/{action}"

    def status(self, request_id: str) -> ClipStatus:
        try:
            status, data = self._call("GET", self._request_path(request_id, "status"))
        except (_NotSent, ConnectionError):
            raise ProviderUnavailable() from None
        if not 200 <= status < 300:
            raise ProviderRequestMissing(status_code=status) if status == 404 else self._error(status, submit=False)
        state = data.get("status")
        if state not in PROVIDER_STATES:
            raise ProviderResponseError(status_code=status)
        if state != COMPLETED:
            return ClipStatus(state)
        url = video_url(data)
        if url is None:
            raise ProviderResponseError(status_code=status)
        return ClipStatus(state, url, {"result_shape": "video.url" if isinstance(data.get("video"), dict) else "videos[0].url"})

    def cancel(self, request_id: str) -> bool:
        try:
            status, _data = self._call("POST", self._request_path(request_id, "cancel"))
        except (_NotSent, ConnectionError):
            raise ProviderUnavailable() from None
        if 200 <= status < 300:
            return True
        if status == 400:
            return False  # Official SDK: requests that already started cannot be cancelled.
        raise ProviderRequestMissing(status_code=status) if status == 404 else self._error(status, submit=False)

    def fetch(self, status: ClipStatus, target: Path, cancel: Event) -> FetchResult:
        if status.state != COMPLETED or not status.video_url:
            raise ProviderResponseError(sent=False)
        # The signed result URL is fetched without the API credential.
        return self.downloader.fetch(status.video_url, target, cancel)


def video_url(data: dict) -> str | None:
    """``video.url`` (official JS SDK README sample) or ``videos[0].url`` (images use ``images[0].url``)."""
    video = data.get("video")
    if isinstance(video, dict) and isinstance(video.get("url"), str):
        return video["url"]
    videos = data.get("videos")
    if isinstance(videos, list) and videos and isinstance(videos[0], dict) and isinstance(videos[0].get("url"), str):
        return videos[0]["url"]
    return None
