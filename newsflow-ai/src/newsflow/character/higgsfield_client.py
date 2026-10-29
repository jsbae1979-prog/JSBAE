"""Reference-to-video contract checked 2026-10-23; extends the existing REST adapter."""
from __future__ import annotations

import json
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

from newsflow.video.ai.contracts import ERROR_MESSAGES, ClipStatus, ProviderAmbiguousSubmit, ProviderResponseError
from newsflow.video.ai.download import safe_url
from newsflow.video.ai.higgsfield import REQUEST_ID, HiggsfieldProvider, _NotSent, video_url

from .schema import CharacterError

MODEL = 'bytedance/seedance-2.0/reference-to-video'
MODEL_DOC = 'https://docs.higgsfield.ai/docs/models/seedance-2/reference-to-video'
SAFE_ERROR_CODES = frozenset({
    'authentication_error', 'authorization_error', 'invalid_api_key', 'unauthorized', 'forbidden',
    'permission_denied', 'insufficient_credits', 'insufficient_balance', 'model_not_found',
    'invalid_request', 'invalid_request_error', 'validation_error', 'rate_limit_exceeded',
    'rate_limit_error', 'too_many_requests', 'request_timeout', 'internal_server_error',
    'server_error', 'service_unavailable',
})


def _response_diagnostics(status, data, error_code, protected=()):
    """Retain only bounded machine facts from this request's response, never provider prose."""
    result = {'error_code': error_code if error_code in ERROR_MESSAGES else ProviderResponseError.code}
    if type(status) is int and 100 <= status <= 599:
        result['http_status'] = status
    secrets = tuple(part for value in protected if isinstance(value, str)
                    for part in (value, *value.split(':')) if part)

    def unprotected(value):
        return isinstance(value, str) and not any(secret in value for secret in secrets)

    error = data.get('error')
    for code in (data.get('error_code'), data.get('code'), error.get('code') if isinstance(error, dict) else None):
        if isinstance(code, str) and code in SAFE_ERROR_CODES and unprotected(code):
            result['error_code'] = code
            break
    for field in ('request_id', 'correlation_id'):
        value = data.get(field)
        if unprotected(value) and REQUEST_ID.fullmatch(value):
            result[field] = value
    return result


def amount(value):
    try:
        text = str(value)
        if not re.fullmatch(r'[0-9]{1,6}(\.[0-9]{1,8})?', text):
            raise ValueError
        result = Decimal(text)
        if not result.is_finite() or result <= 0:
            raise ValueError
        return result
    except (ValueError, InvalidOperation):
        raise CharacterError('budget') from None


def reference_bytes(path: Path) -> bytes:
    try:
        if path.is_symlink() or not 1 <= path.stat().st_size <= 10*1024*1024:
            raise ValueError
        raw = path.read_bytes()
        with Image.open(path) as image:
            if image.format != 'PNG' or not (128 <= image.width <= 4096 and 128 <= image.height <= 4096):
                raise ValueError
            image.verify()
        return raw
    except (OSError, ValueError, Image.DecompressionBombError):
        raise CharacterError('reference') from None


def request_url(url, request_id):
    if not REQUEST_ID.fullmatch(request_id or '') or url != f'https://api.higgsfield.ai/requests/{request_id}/status':
        raise ProviderAmbiguousSubmit()
    return url


class HiggsfieldVideoClient(HiggsfieldProvider):
    def __init__(self, credential=None, **kwargs):
        # No SDK installation, new key store, or browser credential handling.
        super().__init__(credential or (lambda: os.environ.get('HF_KEY', '')), **kwargs)

    def _safe_call(self, method, path, payload=None, extra=None, *, _diagnostics=None):
        status, data = self._call(method, path, payload, extra)
        submit = path == '/'+getattr(self, 'model', MODEL)
        try:
            key = self.credential().strip()
        except Exception:  # A second key-store read cannot replace an already received HTTP failure.
            key = ''
        error = self._error(status, submit=submit) if not 200 <= status < 300 else None
        diagnostics = _response_diagnostics(
            status, data, error.code if error else ProviderAmbiguousSubmit.code if submit else ProviderResponseError.code,
            (key, (extra or {}).get('Idempotency-Key')),
        )
        if _diagnostics is not None:
            _diagnostics.update(diagnostics)
        if error:
            error.safe_diagnostics = diagnostics
            raise error
        if key and key in json.dumps(data):
            error = ProviderResponseError()
            diagnostics['error_code'] = error.code
            if _diagnostics is not None:
                _diagnostics.update(diagnostics)
            error.safe_diagnostics = diagnostics
            raise error
        return data

    def upload_reference(self, path: Path) -> str:
        raw = reference_bytes(path)
        data = self._safe_call('POST', '/files/generate-upload-url', {'content_type': 'image/png'})
        upload, public = safe_url(data.get('upload_url')), safe_url(data.get('public_url'))
        headers = data.get('upload_headers')
        if not isinstance(headers, dict) or headers.get('Content-Type') != 'image/png':
            raise ProviderResponseError()
        # Forward signed storage requirements, never provider authorization/cookies/Host.
        for k, v in headers.items():
            if (not isinstance(k, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,80}', k)
                    or not isinstance(v, str) or len(v) > 2048 or any(ord(c) < 32 for c in v)
                    or k.lower() in {'authorization', 'proxy-authorization', 'cookie', 'host'}):
                raise ProviderResponseError()
        if self.credential().strip() in json.dumps(headers):
            raise ProviderResponseError()
        u = urlsplit(upload)
        status, _ = self.requester(u.hostname, 'PUT', u.path+('?' + u.query if u.query else ''),
                                   raw, headers, self.timeout)
        if not 200 <= status < 300:
            raise ProviderResponseError()
        return public

    @staticmethod
    def payload(prompt, seconds, reference):
        if type(seconds) is not int or not 4 <= seconds <= 10 or not isinstance(prompt, str) or len(prompt) > 5000:
            raise CharacterError()
        return {'prompt': prompt, 'duration': seconds, 'resolution': '720p', 'aspect_ratio': '9:16',
                'image_urls': [safe_url(reference)], 'generate_audio': False}

    def estimate(self, payload) -> str:
        result = self._safe_call('POST', '/estimate/'+MODEL, payload)
        return str(amount(result.get('usd')))

    def submit_scene(self, payload, idem_key):
        if not re.fullmatch(r'[a-f0-9-]{8,64}', idem_key):
            raise CharacterError()
        diagnostics = {}
        try:
            data = self._safe_call('POST', '/'+getattr(self, 'model', MODEL), payload,
                                   {'Idempotency-Key': idem_key}, _diagnostics=diagnostics)
            rid = data.get('request_id')
            status_url = request_url(data.get('status_url'), rid)
            if data.get('status') not in {'queued', 'in_progress', 'completed', 'failed', 'nsfw', 'canceled'}:
                raise ProviderAmbiguousSubmit()
            return {'request_id': rid, 'status_url': status_url}
        except _NotSent:
            raise
        except ProviderAmbiguousSubmit as exc:
            exc.safe_diagnostics = diagnostics or {'error_code': ProviderAmbiguousSubmit.code}
            raise
        except (ConnectionError, ProviderResponseError, TypeError):
            error = ProviderAmbiguousSubmit()
            error.safe_diagnostics = diagnostics or {'error_code': error.code}
            raise error from None

    def _observe_status(self, handle, *, protected=(), include_media=False):
        url = request_url(handle.get('status_url'), handle.get('request_id'))
        data = self._safe_call('GET', urlsplit(url).path)
        state = data.get('status')
        if state not in {'queued', 'in_progress', 'completed', 'failed', 'nsfw', 'canceled'}:
            raise ProviderResponseError()
        from .status_diagnostics import facts
        key = self.credential().strip()
        protected = (*protected, key, *key.split(':'), handle.get('request_id'), handle.get('status_url'))
        details = facts(data.get('error'), protected)
        if state == 'completed' and include_media:
            return ClipStatus(state, safe_url(video_url(data)), details)
        return ClipStatus(state, facts=details)

    def check(self, handle, *, protected=()):
        return self._observe_status(handle, protected=protected, include_media=True)

    def diagnose(self, handle, *, protected=()):
        # Same registered status GET; never result download or another generation.
        return self._observe_status(handle, protected=protected)
