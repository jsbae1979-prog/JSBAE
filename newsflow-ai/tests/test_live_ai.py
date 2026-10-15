"""Explicit opt-in only: one paid OpenAI script generation with a user-set token cap.

Never part of the default suite. The environment variables are the consent surface:
NEWSFLOW_AI_LIVE_TEST=1, NEWSFLOW_AI_API_KEY and NEWSFLOW_AI_LIVE_MAX_TOKENS (200..3000).
The fixture article (synthetic, non-sensitive test text) is sent to the provider exactly
once; the test writes approval and a monthly limit only into its own temporary database.
"""

from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import select

from newsflow.db.models import AIUsage, ContentDraft, NewsSource
from newsflow.intelligence.credentials import AIKeyStore
from newsflow.intelligence.service import IntelligenceService
from newsflow.intelligence.settings import write_settings

CAP = os.getenv("NEWSFLOW_AI_LIVE_MAX_TOKENS", "")


@pytest.mark.network
@pytest.mark.skipif(
    os.getenv("NEWSFLOW_AI_LIVE_TEST") != "1" or not os.getenv("NEWSFLOW_AI_API_KEY") or not CAP.isdigit(),
    reason="opt-in paid AI live test: set NEWSFLOW_AI_LIVE_TEST=1, NEWSFLOW_AI_API_KEY and NEWSFLOW_AI_LIVE_MAX_TOKENS",
)
def test_single_approved_openai_script_generation(app):
    cap = int(CAP)
    sessions = app.state.sessions
    with sessions.begin() as session:
        session.add(NewsSource(name="Fixture", url="https://example.com/rss", enabled=True))
    app.state.coordinator.start()
    app.state.coordinator.future.result(timeout=10)
    model = os.getenv("NEWSFLOW_AI_LIVE_MODEL", "gpt-4o-mini")
    settings = write_settings(sessions, "openai", model, True, 100_000, 30)
    store = AIKeyStore(app.state.config.data_dir)
    service = IntelligenceService(sessions, None, store)
    analysis_id = service.analyze([1], mode="offline")
    draft_id = service.generate(analysis_id, 30, mode="openai", consent=True, options=settings.options(max_tokens=cap))
    with sessions() as session:
        draft = session.get(ContentDraft, draft_id)
        rows = session.scalars(select(AIUsage).where(AIUsage.run_id == draft.run_id)).all()
        assert draft.review_status == "review_required" and sum(s["seconds"] for s in draft.content["scenes"]) == 30
        assert len(rows) == 1 and rows[0].status == "success" and 0 < rows[0].completion_tokens <= cap
        assert store.key() not in json.dumps(draft.content, ensure_ascii=False)
