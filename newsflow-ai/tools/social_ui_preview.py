"""Isolated, clearly labelled social-workspace screenshots. No production data.

Reuses the existing network/process-guarded preview and actual silent FFmpeg media.
Run with --data-dir pointing to a NEW temporary directory; existing paths refused.
"""

from __future__ import annotations

import importlib.util
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select

from newsflow.db.models import PlatformAccount, PublishDraft, PublishJob, RenderJob, VideoProject, utcnow
from newsflow.publishing.analytics import MONETARY, SCOPES, AnalyticsAdapter, AnalyticsService
from newsflow.publishing.media import FakeMediaInspector
from newsflow.publishing.service import hash_file

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "visual_fixture", root / "docs/reports/evidence/dashboard-implementation/preview_fixture.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class SyntheticMetricTransport:
    def __init__(self, records):
        self.records = records

    def request(self, method, url, **kwargs):
        assert method == "GET" and urlsplit(url).hostname in {
            "www.googleapis.com",
            "youtubeanalytics.googleapis.com",
        }
        query = parse_qs(urlsplit(url).query)
        remote_id = query["id"][0] if "id" in query else query["filters"][0].split("==")[1]
        row = self.records[remote_id]
        if "id" in query:
            return {
                "items": [
                    {
                        "id": remote_id,
                        "snippet": {
                            "channelId": "synthetic-channel",
                            "publishedAt": row["published"].isoformat(),
                        },
                    }
                ]
            }
        from zoneinfo import ZoneInfo

        first = row["published"].astimezone(ZoneInfo("America/Los_Angeles")).date()
        return {
            "columnHeaders": [
                {"name": n}
                for n in ("day", "views", "subscribersGained", "subscribersLost", "estimatedRevenue")
            ],
            "rows": [
                [(first + timedelta(days=d)).isoformat(), row["views"] + d * 11, 3 + d, d % 2, 0.25 + d / 100]
                for d in range(7)
            ],
        }


def seed(app, temporary):
    fixture.visual_seed(app, temporary)
    now = utcnow()
    records, bindings = {}, {}
    with app.state.sessions.begin() as session:
        account = PlatformAccount(
            platform="youtube",
            label="UI 데모 채널 · 실제 연결 아님",
            account_type="youtube_channel",
            status="not_connected",
            scopes=[],
            api_ready=False,
        )
        session.add(account)
        session.flush()
        account_id = account.id
        renders = list(session.scalars(select(RenderJob).order_by(RenderJob.id)))
        for i in range(12):
            render = renders[i % len(renders)]
            project = session.get(VideoProject, render.project_id)
            draft = PublishDraft(
                render_job_id=render.id,
                platform="youtube",
                title="합성 성과 " + str(i + 1),
                description="UI 데모",
                hashtags=[],
                account_id=account.id,
                sources=project.sources,
                media_sha256=hash_file(app.state.video.outputs / render.output_name),
                content_reviewed=False,
                copyright_confirmed=False,
                sources_confirmed=False,
                ai_disclosure="disclose",
            )
            session.add(draft)
            session.flush()
            job = PublishJob(
                draft_id=draft.id,
                platform="youtube",
                status="ext_simulated",
                message="UI 데모 · 실제 게시 아님",
                idempotency_key=f"synthetic-metric-{i}",
            )
            session.add(job)
            session.flush()
            published = (now - timedelta(days=10 + i)).replace(
                hour=[0, 4, 10, 13][i % 4], minute=0, second=0, microsecond=0
            )
            records[f"synthetic-video-{i}"] = {"published": published, "views": [80, 130, 230, 170][i % 4]}
            bindings[job.id] = {
                "job_id": job.id,
                "account_id": account_id,
                "platform": "youtube",
                "synthetic": True,
                "remote_id": f"synthetic-video-{i}",
                "identity": "synthetic-channel",
                "scopes": SCOPES["youtube"] | {MONETARY},
            }
    metrics = AnalyticsService(
        app.state.sessions,
        synthetic_binding=lambda job: bindings[job],
        adapters={"youtube": AnalyticsAdapter("youtube", SyntheticMetricTransport(records))},
    )
    for job_id in bindings:
        metrics.collect(job_id, (now - timedelta(days=30)).date(), now.date(), consent=True)
    read_dashboard = metrics.dashboard
    # Preview-only override. Application route never exposes a synthetic toggle.
    metrics.dashboard = lambda **kw: read_dashboard(
        **{**kw, "synthetic": True, "account_id": kw.get("account_id") or account_id}
    )
    app.state.social_analytics = metrics
    app.state.unified_publishing.local.inspector = FakeMediaInspector()
    for i, render in enumerate(renders):
        cohort = app.state.unified_publishing.save_review(
            render.id,
            {"youtube": account_id},
            title=f"UI 데모 게시 계획 {i + 1}",
            content_reviewed=True,
            copyright_confirmed=True,
            sources_confirmed=True,
            ai_disclosure="disclose",
        )
        app.state.publishing_calendar.save(cohort, now + timedelta(days=i * 2 + 1))


if __name__ == "__main__":
    fixture.demo.seed = seed
    fixture.demo.main()
