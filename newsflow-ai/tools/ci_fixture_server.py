"""Synthetic CI server using the public app factory; no production bypass flag.

``--fake-video-provider`` injects the offline Fake AI video provider (Phase 5D) exactly as the
tests do: nothing leaves the machine, the provider is labelled as a test provider on every page
and it can never be selected in the settings of a normal ``run.bat`` start.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import uvicorn

from newsflow.config import Settings
from newsflow.main import create_app
from newsflow.news.rss_adapter import FakeRSSAdapter


class SlowFake(FakeRSSAdapter):
    def fetch(self, url: str, timeout: int) -> bytes:
        time.sleep(1)  # Makes the genuine background running state observable.
        return super().fetch(url, timeout)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--fake-video-provider", action="store_true")
    args = parser.parse_args()
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/normal.xml"
    video_provider = None
    if args.fake_video_provider:
        from newsflow.video.ai.fake import FakeVideoProvider

        video_provider = FakeVideoProvider(steps=2)
    app = create_app(
        Settings(data_dir=args.data_dir), SlowFake({"https://example.com/rss": fixture.read_bytes()}),
        video_provider=video_provider,
    )
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
