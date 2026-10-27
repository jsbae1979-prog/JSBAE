"""Explicit one-JPEG upload to a separately deployed HTTPS delivery service."""
import hashlib
import json
import re
from urllib.parse import urlsplit

from newsflow.intelligence.credentials import AIKeyStore
from newsflow.news.rss_adapter import FeedError, PinnedConnection, public_addresses, validate_url

from .service import PublishingError


class ImageDeliveryKeys(AIKeyStore):
    FILE = "feed-delivery-key.dpapi"
    ENV = "NEWSFLOW_IMAGE_DELIVERY_KEY"
    ENTROPY = b"NewsFlowAI:ImageDelivery"


def delivery_origin(value):
    try:
        value = validate_url(value)
        parts = urlsplit(value)
        if parts.scheme != "https" or parts.path != "/" or parts.query:
            raise ValueError
        return value.rstrip("/")
    except (ValueError, FeedError):
        raise PublishingError("이미지 전달 서버의 공개 HTTPS 도메인이 필요합니다. 인증 중계 주소와 구분하세요.") from None


class HTTPSImageDelivery:
    def __init__(self, sessions, root, *, keys=None, transport=None):
        self.sessions, self.keys, self.transport = sessions, keys or ImageDeliveryKeys(root), transport or self._upload

    def origin(self):
        from newsflow.db.models import AppSetting
        with self.sessions() as session:
            row = session.get(AppSetting, "feed_delivery_origin")
            return delivery_origin(row.value) if row and row.value else None

    def ready(self):
        try:
            return bool(self.origin() and self.keys.status().get("configured"))
        except PublishingError:
            return False

    def _upload(self, origin, raw, secret):
        host = urlsplit(origin).hostname
        addresses = public_addresses(host, 443, 30)
        connection = PinnedConnection(host, addresses[0], 443, 30, True)
        try:
            connection.request("POST", "/v1/images", body=raw, headers={
                "Content-Type": "image/jpeg", "Authorization": "Bearer " + secret})
            response = connection.getresponse()
            if response.status != 200 or response.getheader("Content-Encoding"):
                raise ValueError
            payload = response.read(8193)
        finally:
            connection.close()
        if len(payload) > 8192:
            raise ValueError
        return json.loads(payload)

    def upload(self, path, expected_sha):
        from .image_delivery_server import validate_jpeg
        origin = self.origin()
        if not origin or not self.keys.status().get("configured"):
            raise PublishingError("BLOCKED · HTTPS 이미지 전달 서버와 보호 키를 먼저 준비하세요. 로컬 이미지는 저장할 수 있습니다.")
        raw = path.read_bytes()
        validate_jpeg(raw)
        if hashlib.sha256(raw).hexdigest() != expected_sha:
            raise PublishingError("검토한 JPG가 변경되었습니다.")
        try:
            result = self.transport(origin, raw, self.keys.key())  # single POST; never retry
            url = result.get("url", "")
            if (not re.fullmatch(re.escape(origin) + r"/images/[a-f0-9]{32}\.jpg", url)
                    or result.get("sha256") != expected_sha):
                raise ValueError
            return url
        except Exception:  # noqa: BLE001 - upload may have completed; preserve delivery claim and never replay
            raise PublishingError("이미지 전달 결과를 확인하지 못했습니다. 자동 재전송하지 않습니다.") from None
