"""Official platform contracts. New production connections remain explicitly blocked.

No HTTP client is constructed here. Test transports are injected, never selected by
an environment variable or a browser flag. Public documentation checked 2026-10-19.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import BinaryIO, Protocol
from urllib.parse import urlsplit

from .service import PublishingError

LABELS = {
    "youtube": "YouTube Shorts",
    "instagram": "Instagram Reels",
    "tiktok": "TikTok",
    "facebook": "Facebook Reels",
}
REQUIREMENTS = {
    "tiktok": {
        "scopes": ["video.publish"],
        "account": "TikTok creator",
        "reason": "공개 게시 앱 심사 필요. 개인·팀 전용 업로드 도구는 심사 대상에 맞지 않을 수 있습니다.",
        "url": "https://developers.tiktok.com/doc/content-sharing-guidelines",
    },
    "facebook": {
        "scopes": ["pages_show_list", "pages_read_engagement", "pages_manage_posts"],
        "account": "Facebook Page / CREATE_CONTENT",
        "reason": "Page 권한·앱 검수와 공개 게시 승인이 필요합니다. 개인 프로필은 지원하지 않습니다.",
        "url": "https://developers.facebook.com/documentation/video-api/guides/reels-publishing",
    },
}


class PlatformBlocked(PublishingError):
    pass


class PlatformTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        payload: dict | None = None,
        stream: BinaryIO | None = None,
        headers: dict | None = None,
    ) -> dict: ...


class BlockedTransport:
    """Only a subsequent reviewed production activation may replace this boundary."""

    def request(self, *args, **kwargs) -> dict:
        raise PlatformBlocked("실계정 연결·외부 전송은 아직 활성화되지 않았습니다.")


@dataclass(frozen=True)
class UploadSession:
    reference: str
    upload_url: str

    def __repr__(self) -> str:
        return "UploadSession(<redacted>)"


def identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.~-]{0,159}", value):
        raise PublishingError("플랫폼 응답 식별자를 확인하지 못했습니다.")
    return value


def upload_url(value: object, host: str) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise PublishingError("업로드 주소를 확인하지 못했습니다.")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise PublishingError("업로드 주소 형식이 올바르지 않습니다.") from None
    if (
        parsed.scheme != "https"
        or parsed.hostname != host
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.fragment
        or not parsed.path.startswith("/")
    ):
        raise PublishingError("허용하지 않은 업로드 주소입니다.")
    return value


class TikTokPublisher:
    platform = "tiktok"
    base = "https://open.tiktokapis.com/v2/post/publish"

    def __init__(self, transport: PlatformTransport | None = None):
        self.transport = transport or BlockedTransport()

    def creator(self) -> dict:
        data = self.transport.request("POST", self.base + "/creator_info/query/", payload={})
        self._ok(data)
        creator = data.get("data", {})
        if (
            not isinstance(creator.get("creator_nickname"), str)
            or not isinstance(creator.get("privacy_level_options"), list)
            or type(creator.get("max_video_post_duration_sec")) is not int
        ):
            raise PublishingError("TikTok 계정의 최신 게시 조건을 확인하지 못했습니다.")
        return creator

    @staticmethod
    def _ok(data: dict) -> None:
        if not isinstance(data, dict) or data.get("error", {}).get("code") != "ok":
            raise PublishingError("TikTok 요청을 확인하지 못했습니다. 자동 재전송하지 않습니다.")

    def initialize(
        self, *, account: str, caption: str, size: int, duration: int, options: dict, ai_generated: bool
    ) -> UploadSession:
        creator = self.creator()
        if (
            options.get("privacy") not in creator["privacy_level_options"]
            or options.get("music_consent") is not True
            or duration > creator["max_video_post_duration_sec"]
            or len(caption.encode("utf-16-le")) // 2 > 2200
            or not 0 < size <= 64 * 1024 * 1024
        ):
            raise PublishingError("TikTok 공개 범위·음악 동의·길이·64MB 전송 프로파일을 확인하세요.")
        if options.get("branded") and (
            options["privacy"] == "SELF_ONLY" or options.get("brand_consent") is not True
        ):
            raise PublishingError("유료 파트너십의 공개 범위와 정책 동의를 확인하세요.")
        post = {
            "title": caption,
            "privacy_level": options["privacy"],
            "is_aigc": ai_generated,
            "brand_content_toggle": options.get("branded") is True,
            "brand_organic_toggle": options.get("own_brand") is True,
        }
        for name in ("comment", "duet", "stitch"):
            enabled = options.get("allow_" + name) is True
            if enabled and creator.get(name + "_disabled") is not False:
                raise PublishingError("계정에서 허용하지 않은 상호작용입니다.")
            post["disable_" + name] = not enabled
        result = self.transport.request(
            "POST",
            self.base + "/video/init/",
            payload={
                "post_info": post,
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": size,
                    "total_chunk_count": 1,
                },
            },
        )
        self._ok(result)
        data = result.get("data", {})
        return UploadSession(
            identifier(data.get("publish_id")),
            upload_url(data.get("upload_url"), "open-upload.tiktokapis.com"),
        )

    def upload(self, upload: UploadSession, stream: BinaryIO, size: int) -> None:
        self.transport.request(
            "PUT",
            upload_url(upload.upload_url, "open-upload.tiktokapis.com"),
            stream=stream,
            headers={
                "Content-Type": "video/mp4",
                "Content-Length": str(size),
                "Content-Range": f"bytes 0-{size - 1}/{size}",
            },
        )

    def check(self, reference: str) -> dict:
        result = self.transport.request(
            "POST", self.base + "/status/fetch/", payload={"publish_id": identifier(reference)}
        )
        self._ok(result)
        data = result.get("data", {})
        status = data.get("status")
        public_ids = data.get("publicaly_available_post_id", [])
        remote_id = None
        if status == "PUBLISH_COMPLETE" and isinstance(public_ids, list) and len(public_ids) == 1:
            remote_id = identifier(str(public_ids[0]))
        return {
            "status": "complete"
            if status == "PUBLISH_COMPLETE"
            else "failed"
            if status == "FAILED"
            else "waiting"
            if status in {"PROCESSING_UPLOAD", "PROCESSING_DOWNLOAD", "SEND_TO_USER_INBOX"}
            else "unknown",
            "remote_id": remote_id,
        }  # publish_id is a request ID, never pretend it is a video ID.


class FacebookPublisher:
    platform = "facebook"
    base = "https://graph.facebook.com/v26.0"

    def __init__(self, transport: PlatformTransport | None = None):
        self.transport = transport or BlockedTransport()

    def initialize(
        self, *, account: str, caption: str, size: int, duration: int, options: dict, ai_generated: bool
    ) -> UploadSession:
        if not re.fullmatch(r"[0-9]{1,40}", account) or options.get("public_consent") is not True:
            raise PublishingError("Facebook Page와 공개 게시 동의를 확인하세요.")
        if not 3 <= duration <= 90:
            raise PublishingError("Facebook Reels 길이를 확인하세요.")
        result = self.transport.request(
            "POST", f"{self.base}/{account}/video_reels", payload={"upload_phase": "start"}
        )
        reference = identifier(result.get("video_id"))
        if not reference.isdigit():
            raise PublishingError("Facebook 영상 식별자가 올바르지 않습니다.")
        url = upload_url(result.get("upload_url"), "rupload.facebook.com")
        if not urlsplit(url).path.endswith("/" + reference):
            raise PublishingError("Facebook 업로드 대상이 일치하지 않습니다.")
        return UploadSession(reference, url)

    def upload(self, upload: UploadSession, stream: BinaryIO, size: int) -> None:
        response = self.transport.request(
            "POST",
            upload_url(upload.upload_url, "rupload.facebook.com"),
            stream=stream,
            headers={"offset": "0", "file_size": str(size), "Content-Type": "application/octet-stream"},
        )
        if response.get("success") is not True:
            raise PublishingError("Facebook 파일 전송 결과를 확인하지 못했습니다.")

    def finish(self, account: str, reference: str, caption: str, ai_generated: bool) -> None:
        response = self.transport.request(
            "POST",
            f"{self.base}/{identifier(account)}/video_reels",
            payload={
                "upload_phase": "finish",
                "video_id": identifier(reference),
                "video_state": "PUBLISHED",
                "description": caption,
                "is_ai_generated": ai_generated,
            },
        )
        if response.get("success") is not True:
            raise PublishingError("Facebook 게시 접수 결과를 확인하지 못했습니다.")

    def check(self, reference: str) -> dict:
        response = self.transport.request("GET", f"{self.base}/{identifier(reference)}?fields=status")
        state = response.get("status", {})
        phase = state.get("publishing_phase", {})
        complete = phase.get("status") == "completed" and phase.get("publish_status") == "published"
        return {
            "status": "complete"
            if complete
            else "failed"
            if state.get("video_status") in {"error", "expired", "upload_failed"}
            else "waiting"
            if state.get("video_status") in {"processing", "ready", "uploading", "upload_complete"}
            else "unknown",
            "remote_id": identifier(reference) if complete else None,
        }
