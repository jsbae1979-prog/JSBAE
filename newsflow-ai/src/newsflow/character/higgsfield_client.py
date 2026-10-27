"""Reference-to-video contract checked 2026-10-23; extends the existing REST adapter."""
from __future__ import annotations

import json
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

from newsflow.video.ai.contracts import ClipStatus, ProviderAmbiguousSubmit, ProviderResponseError
from newsflow.video.ai.download import safe_url
from newsflow.video.ai.higgsfield import REQUEST_ID, HiggsfieldProvider, _NotSent, video_url

from .schema import CharacterError

MODEL = 'bytedance/seedance-2.0/reference-to-video'
MODEL_DOC = 'https://docs.higgsfield.ai/docs/models/seedance-2/reference-to-video'


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

    def _safe_call(self, method, path, payload=None, extra=None):
        status, data = self._call(method, path, payload, extra)
        if not 200 <= status < 300:
            raise self._error(status, submit=path == '/'+MODEL)
        key = self.credential().strip()
        if key and key in json.dumps(data):
            raise ProviderResponseError()
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
        try:
            data = self._safe_call('POST', '/'+MODEL, payload, {'Idempotency-Key': idem_key})
            rid = data.get('request_id')
            status_url = request_url(data.get('status_url'), rid)
            if data.get('status') not in {'queued', 'in_progress', 'completed', 'failed', 'nsfw', 'canceled'}:
                raise ProviderAmbiguousSubmit()
            return {'request_id': rid, 'status_url': status_url}
        except _NotSent:
            raise
        except (ConnectionError, ProviderResponseError, TypeError):
            raise ProviderAmbiguousSubmit() from None

    def check(self, handle):
        url = request_url(handle.get('status_url'), handle.get('request_id'))
        data = self._safe_call('GET', urlsplit(url).path)
        state = data.get('status')
        if state not in {'queued', 'in_progress', 'completed', 'failed', 'nsfw', 'canceled'}:
            raise ProviderResponseError()
        if state == 'completed':
            return ClipStatus(state, safe_url(video_url(data)))
        return ClipStatus(state)
