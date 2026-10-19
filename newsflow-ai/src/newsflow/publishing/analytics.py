"""Provider-defined social metrics. No invented revenue or cross-platform totals."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from statistics import median
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from newsflow.db.models import (
    PublishDraft,
    PublishJob,
    SocialMetric,
    SocialMetricRun,
    utcnow,
)

from .calendar import KST
from .platforms import BlockedTransport, PlatformBlocked, identifier
from .service import PublishingError

SCOPES = {
    "youtube": {
        "https://www.googleapis.com/auth/yt-analytics.readonly",
        "https://www.googleapis.com/auth/youtube.readonly",
    },
    "instagram": {"instagram_basic", "instagram_manage_insights", "pages_read_engagement"},
    "tiktok": {"video.list"},
    "facebook": {"read_insights", "pages_read_engagement"},
}
MONETARY = "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"
METRICS = {
    "youtube": {
        "views": "조회수",
        "subscribersGained": "구독 증가",
        "subscribersLost": "구독 감소",
        "estimatedRevenue": "추정 수익",
    },
    "instagram": {
        "views": "조회수",
        "reach": "도달",
        "likes": "좋아요",
        "comments": "댓글",
        "saved": "저장",
        "shares": "공유",
    },
    "tiktok": {
        "view_count": "조회수",
        "like_count": "좋아요",
        "comment_count": "댓글",
        "share_count": "공유",
    },
    "facebook": {"total_video_views": "동영상 조회", "total_video_views_unique": "순 시청자"},
}


def number(value: object) -> str:
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise TypeError
        decimal = Decimal(str(value))
        if not decimal.is_finite() or decimal < 0 or decimal > Decimal("1e18"):
            raise ValueError
        return str(decimal)
    except (TypeError, ValueError, InvalidOperation):
        raise PublishingError("성과 응답에 유효하지 않은 숫자가 있습니다.") from None


class AnalyticsAdapter:
    def __init__(self, platform: str, transport=None):
        if platform not in METRICS:
            raise ValueError("Unsupported analytics platform")
        self.platform, self.transport = platform, transport or BlockedTransport()

    def fetch(self, remote_id: str, identity: str, scopes: set[str], start: date, end: date) -> dict:
        remote_id, identity = identifier(remote_id), identifier(identity)
        if not SCOPES[self.platform] <= scopes:
            raise PublishingError("성과 조회 권한이 필요합니다. 게시 권한과 별도로 확인하세요.")
        if start > end or (end - start).days > 90 or end > utcnow().date():
            raise PublishingError("성과 조회 기간은 과거 90일 범위로 선택하세요.")
        published_at = None
        metrics = METRICS[self.platform]
        if self.platform == "youtube":
            # Verify publication ownership instead of accepting a user-supplied video ID.
            video = self.transport.request(
                "GET",
                "https://www.googleapis.com/youtube/v3/videos?"
                + urlencode({"part": "snippet", "id": remote_id}),
            )
            items = video.get("items", [])
            if (
                len(items) != 1
                or items[0].get("id") != remote_id
                or items[0].get("snippet", {}).get("channelId") != identity
            ):
                raise PublishingError("영상과 연결 채널이 일치하지 않습니다.")
            stamp = datetime.fromisoformat(items[0]["snippet"]["publishedAt"])
            if stamp.tzinfo is None:
                raise PublishingError("공개 시각을 확인하지 못했습니다.")
            published_at = stamp.astimezone(UTC).isoformat()
            requested = [name for name in metrics if name != "estimatedRevenue" or MONETARY in scopes]
            query = urlencode(
                {
                    "ids": "channel==" + identity,
                    "startDate": start.isoformat(),
                    "endDate": end.isoformat(),
                    "metrics": ",".join(requested),
                    "dimensions": "day",
                    "filters": "video==" + remote_id,
                    "currency": "USD",
                }
            )
            result = self.transport.request(
                "GET", "https://youtubeanalytics.googleapis.com/v2/reports?" + query
            )
            headers = [h.get("name") for h in result.get("columnHeaders", [])]
            if len(headers) != len(set(headers)) or (result.get("rows") and "day" not in headers):
                raise PublishingError("성과 보고서의 열 구성을 확인하지 못했습니다.")
            daily = []
            for row in result.get("rows", []):
                if len(row) != len(headers):
                    raise PublishingError("성과 보고서의 행 구성을 확인하지 못했습니다.")
                item = dict(zip(headers, row, strict=True))
                day = date.fromisoformat(item["day"])
                if not start <= day <= end:
                    raise PublishingError("조회 기간 밖의 성과 응답입니다.")
                daily.append(
                    {
                        "start": day.isoformat(),
                        "end": day.isoformat(),
                        "values": {
                            key: number(item[key])
                            for key in requested
                            if key in item and item[key] is not None
                        },
                    }
                )
            if len({d["start"] for d in daily}) != len(daily):
                raise PublishingError("중복된 성과 날짜입니다.")
            return {"windows": daily, "basis": "America/Los_Angeles", "published_at": published_at}
        if self.platform == "tiktok":
            result = self.transport.request(
                "POST",
                "https://open.tiktokapis.com/v2/video/query/?"
                + urlencode({"fields": "id," + ",".join(metrics)}),
                payload={"filters": {"video_ids": [remote_id]}},
            )
            videos = result.get("data", {}).get("videos", [])
            if (
                result.get("error", {}).get("code") != "ok"
                or len(videos) != 1
                or videos[0].get("id") != remote_id
            ):
                raise PublishingError("연결 계정 소유의 TikTok 영상 성과를 확인하지 못했습니다.")
            values = {k: number(videos[0][k]) for k in metrics if videos[0].get(k) is not None}
        else:
            suffix = "insights" if self.platform == "instagram" else "video_insights"
            query = urlencode({"metric": ",".join(metrics), "period": "lifetime"})
            result = self.transport.request(
                "GET", f"https://graph.facebook.com/v26.0/{remote_id}/{suffix}?{query}"
            )
            if "error" in result or not isinstance(result.get("data"), list):
                raise PublishingError("플랫폼 성과 조회에 실패했습니다.")
            values = {}
            for item in result["data"]:
                if item.get("name") not in metrics:
                    continue
                series = item.get("values", [])
                if len(series) == 1 and series[0].get("value") is not None:
                    values[item["name"]] = number(series[0]["value"])
                elif (
                    isinstance(item.get("total_value"), dict) and item["total_value"].get("value") is not None
                ):
                    values[item["name"]] = number(item["total_value"]["value"])
        # Lifetime counters are snapshots, never relabel as selected date-range performance.
        today = utcnow().date().isoformat()
        return {
            "windows": [{"start": today, "end": today, "values": values}],
            "basis": "lifetime_snapshot",
            "published_at": None,
        }


class AnalyticsService:
    def __init__(self, sessions, *, synthetic_binding=None, adapters=None):
        self.sessions, self.binding = sessions, synthetic_binding
        self.adapters = adapters or {p: AnalyticsAdapter(p) for p in METRICS}

    def collect(self, job_id: int, start: date, end: date, *, consent=False) -> int:
        if consent is not True:
            raise PublishingError("선택한 계정의 성과 조회에 동의하세요.")
        if self.binding is None:
            raise PlatformBlocked(
                "성과 계정 연결과 읽기 권한 확인이 필요합니다. 실제 조회는 아직 차단되어 있습니다."
            )
        with self.sessions() as session:
            job = session.get(PublishJob, job_id)
            draft = session.get(PublishDraft, job.draft_id) if job else None
            if not draft or job.status not in {
                "uploaded",
                "ig_published",
                "ig_published_no_link",
                "ext_simulated",
            }:
                raise PublishingError("게시 결과가 확인된 영상만 성과를 조회할 수 있습니다.")
            binding = self.binding(job_id)
            if (
                binding.get("synthetic") is not True
                or binding.get("account_id") != draft.account_id
                or binding.get("platform") != job.platform
                or binding.get("job_id") != job_id
            ):
                raise PlatformBlocked("성과 계정과 게시 기록이 일치하지 않습니다.")
            platform, account_id = job.platform, draft.account_id
            previous = list(session.scalars(select(SocialMetric).where(SocialMetric.job_id == job_id)))
            duplicate = session.scalar(
                select(SocialMetric.id)
                .where(
                    SocialMetric.job_id != job_id,
                    SocialMetric.platform == platform,
                    SocialMetric.account_id == account_id,
                    SocialMetric.remote_id == binding["remote_id"],
                )
                .limit(1)
            )
            if duplicate or any(
                row.remote_id != binding["remote_id"] or row.account_id != account_id for row in previous
            ):
                raise PublishingError("성과와 게시 영상의 연결이 변경되었거나 중복되었습니다.")
        try:
            result = self.adapters[platform].fetch(
                binding["remote_id"], binding["identity"], set(binding["scopes"]), start, end
            )
            count = 0
            with self.sessions.begin() as session:
                # Obtain the write lock before read/insert to prevent duplicate concurrent snapshots.
                session.execute(
                    update(PublishJob).where(PublishJob.id == job_id).values(message=PublishJob.message)
                )
                for window in result["windows"]:
                    for metric, value in window["values"].items():
                        row = session.scalar(
                            select(SocialMetric).where(
                                SocialMetric.job_id == job_id,
                                SocialMetric.metric == metric,
                                SocialMetric.period_start == window["start"],
                                SocialMetric.period_end == window["end"],
                                SocialMetric.synthetic.is_(True),
                            )
                        )
                        if row is None:
                            row = SocialMetric(
                                job_id=job_id,
                                account_id=account_id,
                                platform=platform,
                                remote_id=binding["remote_id"],
                                metric=metric,
                                period_start=window["start"],
                                period_end=window["end"],
                                synthetic=True,
                            )
                            session.add(row)
                        row.value, row.unit = (
                            number(value),
                            "USD estimate" if metric == "estimatedRevenue" else "count",
                        )
                        row.period_basis, row.fetched_at = result["basis"], utcnow()
                        row.published_at = (
                            datetime.fromisoformat(result["published_at"]) if result["published_at"] else None
                        )
                        count += 1
                session.add(
                    SocialMetricRun(
                        job_id=job_id,
                        status="synthetic" if count else "empty",
                        synthetic=True,
                        message="합성 성과 저장" if count else "반환된 성과 없음 · 0으로 채우지 않음",
                    )
                )
            return count
        except Exception:  # noqa: BLE001 - preserve previous metrics, never log raw response
            with self.sessions.begin() as session:
                session.add(
                    SocialMetricRun(
                        job_id=job_id,
                        status="failed",
                        synthetic=True,
                        message="성과 조회 실패 · 기존 수치 보존 · 자동 재시도 안 함",
                    )
                )
            raise PublishingError("성과 조회에 실패했습니다. 기존 기록은 보존됩니다.") from None

    def dashboard(self, *, platform="youtube", account_id=None, synthetic=False) -> dict:
        if platform not in METRICS:
            raise PublishingError("지원하는 플랫폼을 선택하세요.")
        with self.sessions() as session:
            query = select(SocialMetric).where(
                SocialMetric.platform == platform, SocialMetric.synthetic.is_(synthetic)
            )
            if account_id is not None:
                query = query.where(SocialMetric.account_id == account_id)
            rows = list(session.scalars(query.order_by(SocialMetric.fetched_at.desc()).limit(2000)))
        # Never sum lifetime snapshots; keep latest measurement for each video/metric.
        if platform != "youtube":
            seen, latest = set(), []
            for row in rows:
                key = (row.job_id, row.metric)
                if key not in seen:
                    seen.add(key)
                    latest.append(row)
            rows = latest
        totals = {m: None for m in METRICS[platform]}
        days = defaultdict(Decimal)
        for row in rows:
            totals[row.metric] = (totals[row.metric] or Decimal(0)) + Decimal(row.value)
            if row.metric == "views" and row.period_basis == "America/Los_Angeles":
                days[row.period_start] += Decimal(row.value)
        points = sorted(days.items())[-30:]
        maximum = max([Decimal(1)] + [v for _, v in points])
        chart = [
            {
                "date": d,
                "value": str(v),
                "x": 20 + i * 480 / max(1, len(points) - 1),
                "y": float(112 - v / maximum * 100),
            }
            for i, (d, v) in enumerate(points)
        ]
        # Classify each video once from its preserved publication evidence, never current news.
        with self.sessions() as session:
            sources = dict(session.execute(
                select(PublishJob.id, PublishDraft.sources).join(PublishDraft, PublishJob.draft_id == PublishDraft.id)
                .where(PublishJob.id.in_({row.job_id for row in rows}))
            ).all()) if rows else {}
        categories = category_performance(rows, sources, platform)
        recommendation = recommend(rows, account_id=account_id)
        return {
            "platform": platform,
            "metrics": METRICS[platform],
            "totals": totals,
            "rows": rows[:100],
            "chart": chart,
            "categories": categories,
            "points": " ".join(f"{p['x']},{p['y']}" for p in chart),
            "synthetic": synthetic,
            "recommendation": recommendation,
            "account_id": account_id,
        }


def recommend(rows: list, *, account_id: int | None, now=None) -> dict:
    """YouTube only: compare complete first-seven-Pacific-day windows per account.

    An observational median, not a causal prediction. Synthetic data stays synthetic.
    """
    fallback = {
        "ready": False,
        "reason": "계정별 7일 성과가 있는 영상 10개 이상과 시간대별 3개 이상의 표본이 필요합니다.",
        "hours": [],
        "samples": 0,
    }
    if account_id is None:
        return {**fallback, "reason": "추천을 보려면 하나의 계정을 선택하세요."}
    grouped = defaultdict(dict)
    for row in rows:
        if (
            row.account_id == account_id
            and row.platform == "youtube"
            and row.metric == "views"
            and row.period_basis == "America/Los_Angeles"
            and row.published_at
        ):
            grouped[row.job_id][row.period_start] = row
    bins = defaultdict(list)
    for days in grouped.values():
        example = next(iter(days.values()))
        if example.published_at > (now or utcnow()) - timedelta(days=8):
            continue
        first = example.published_at.astimezone(ZoneInfo("America/Los_Angeles")).date()
        expected = [(first + timedelta(days=i)).isoformat() for i in range(7)]
        if not all(d in days for d in expected):
            continue
        hour = example.published_at.astimezone(KST).hour
        bins[hour].append(sum(Decimal(days[d].value) for d in expected))
    count = sum(len(values) for values in bins.values())
    if count < 10 or sum(len(v) >= 3 for v in bins.values()) < 2:
        return {**fallback, "samples": count}
    ranked = sorted(
        (
            {"hour": hour, "samples": len(values), "median": str(median(values))}
            for hour, values in bins.items()
            if len(values) >= 3
        ),
        key=lambda item: Decimal(item["median"]),
        reverse=True,
    )
    return {
        "ready": True,
        "hours": ranked[:3],
        "samples": count,
        "reason": "동일 계정의 첫 7일 조회수 중앙값 비교 · KST · 인과관계·성과 보장 아님",
    }


def category_performance(rows: list, sources: dict[int, dict], platform: str) -> list[dict]:
    """One bucket per published video, no multiplication for multi-source stories.

    Input rows are the same platform/account/cohort and deduplicated snapshots used by dashboard.
    A category is not a growth/quality prediction; zero and missing remain distinct.
    """
    metric = {"youtube": "views", "instagram": "views", "tiktok": "view_count",
              "facebook": "total_video_views"}[platform]
    aliases = {"it": "IT·과학", "IT": "IT·과학", "IT/과학": "IT·과학", "IT·과학": "IT·과학", "AI": "IT·과학",
               "economy": "경제", "politics": "정치", "society": "사회", "world": "국제",
               "경제": "경제", "정치": "정치", "사회": "사회", "국제": "국제",
               "스포츠": "스포츠", "문화": "문화", "연예": "연예"}
    totals, videos = defaultdict(Decimal), defaultdict(set)
    for row in rows:
        if row.metric != metric:
            continue
        evidence = sources.get(row.job_id, {})
        articles = evidence.get("articles", []) if isinstance(evidence, dict) else []
        categories = {aliases.get(a.get("category"), "미분류") for a in articles if isinstance(a, dict)}
        category = next(iter(categories)) if len(categories) == 1 else "복합 주제" if categories else "미분류"
        totals[category] += Decimal(row.value)
        videos[category].add(row.job_id)
    total = sum(totals.values(), Decimal(0))
    return [{"name": name, "views": value, "videos": len(videos[name]),
             "percent": float(value / total * 100) if total else 0}
            for name, value in sorted(totals.items(), key=lambda item: (-item[1], item[0]))]
