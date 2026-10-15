"""Higgsfield API credential storage: Windows DPAPI file or environment, never SQLite or logs.

The official app templates (github.com/higgsfield-ai/app-templates, generation/credentials.ts) send
``Authorization: Key <apiKey>`` with the key pasted as copied from open.higgsfield.ai (printable
ASCII, no spaces); the older Python SDK (higgsfield-client 0.2.0) joins ``KEY_ID:KEY_SECRET``. Both
fit one protected value, stored in its own file, separate from the OpenAI key file.
"""

from __future__ import annotations

import re

from newsflow.intelligence.credentials import AIKeyStore

VIDEO_ENV_NAME = "NEWSFLOW_VIDEO_AI_KEY"


class VideoAIKeyStore(AIKeyStore):
    FILE = "video-ai-key.dpapi"
    ENV = VIDEO_ENV_NAME
    PATTERN = re.compile(r"[\x21-\x7E]{8,520}\Z")
    ENTROPY = b"NewsFlowAI:Phase5D:video-ai-key"
    FORMAT_MESSAGE = "open.higgsfield.ai에서 복사한 API 키를 공백·줄바꿈 없이 그대로 붙여 넣으세요(8~520자)."
