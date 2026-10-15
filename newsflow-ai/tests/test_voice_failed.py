"""Voice generation failures get their own code; only length problems stay speech_too_long."""

from __future__ import annotations

import pytest
from conftest import csrf

from newsflow.db.models import NewsSource
from newsflow.video.engine import FakeRenderAdapter, RenderError
from newsflow.video.tts import FakeTTS, TTSError


class BrokenVoice(FakeRenderAdapter):
    def render(self, plan, work, tts, progress, cancel):
        raise TTSError("음성이 생성되지 않았습니다. 선택한 음성이 한국어 문장을 읽는지 확인하세요.")


class TooLong(FakeRenderAdapter):
    def render(self, plan, work, tts, progress, cancel):
        raise RenderError("전체 음성이 영상 길이를 3.2초 초과했습니다.", kind="audio")


def _real_job(client, app, engine):
    with app.state.sessions.begin() as session:
        session.add(NewsSource(name="Fixture", url="https://example.com/rss", enabled=True))
    app.state.video.tts, app.state.video.engine = FakeTTS(), engine
    response = client.post("/autopilot/start", data={"csrf_token": csrf(client), "source": "feeds", "mode": "easy", "ai": "offline"}, follow_redirects=False)
    assert response.status_code == 303
    app.state.autopilot.future.result(timeout=20)
    job_id = response.headers["location"].rsplit("/", 1)[1]
    snapshot = app.state.autopilot.snapshot(job_id)
    assert snapshot["status"] == "waiting_review" and snapshot["current_stage"] == "script"
    app.state.autopilot.resume(job_id, snapshot["revision"])
    app.state.autopilot.future.result(timeout=20)
    return job_id, app.state.autopilot.snapshot(job_id)


@pytest.mark.parametrize("engine,code,link", [(BrokenVoice(), "voice_failed", "음성 설정 →"), (TooLong(), "speech_too_long", "음성 설정 →")])
def test_render_failures_map_to_distinct_codes_and_guidance(client, app, engine, code, link):
    job_id, snapshot = _real_job(client, app, engine)
    assert snapshot["status"] == "failed" and snapshot["error_code"] == code and snapshot["retryable"]
    page = client.get(f"/autopilot/jobs/{job_id}")
    assert page.status_code == 200 and link in page.text and snapshot["solution"] in page.text
    if code == "voice_failed":
        assert "PowerShell 실행 상태" in page.text and "미리 듣기로 음성이 소리를 내는지" in page.text
    else:
        assert "대본 수정에서 문장을 줄이거나" in page.text
