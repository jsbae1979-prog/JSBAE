"""IANA/UTC/DST behavior using offline public tzdata; no OS timezone mutation."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from newsflow.publishing import analytics
from newsflow.publishing.calendar import KST, local_time
from newsflow.publishing.service import PublishingError


@pytest.mark.parametrize('stamp,hour,minute,offset,fold', [
    ('2026-03-08T09:59:00+00:00', 1, 59, -8, 0),
    ('2026-03-08T10:00:00+00:00', 3, 0, -7, 0),
    ('2026-11-01T08:30:00+00:00', 1, 30, -7, 0),
    ('2026-11-01T09:30:00+00:00', 1, 30, -8, 1),
])
def test_iana_pacific_dst_transition_and_fold(stamp, hour, minute, offset, fold):
    utc = datetime.fromisoformat(stamp)
    local = utc.astimezone(ZoneInfo('America/Los_Angeles'))
    assert (local.hour, local.minute, local.utcoffset(), local.fold) == (hour, minute, timedelta(hours=offset), fold)
    assert local.astimezone(UTC) == utc


@pytest.mark.parametrize('stamp', ['2026-03-08T10:00:00+00:00', '2026-11-01T09:30:00+00:00'])
def test_iana_seoul_agrees_with_existing_kst_and_calendar_stores_utc(stamp):
    utc = datetime.fromisoformat(stamp)
    seoul = utc.astimezone(ZoneInfo('Asia/Seoul'))
    assert seoul == utc.astimezone(KST) and seoul.utcoffset() == timedelta(hours=9)
    saved = local_time(seoul.strftime('%Y-%m-%dT%H:%M'))
    assert saved.tzinfo is UTC and saved == utc


@pytest.mark.parametrize('error', [ZoneInfoNotFoundError, ValueError, OSError])
def test_unavailable_or_corrupt_timezone_fails_explicitly_without_fallback(monkeypatch, error):
    original = datetime(2026, 9, 1, 1, tzinfo=UTC)
    row = SimpleNamespace(account_id=1, platform='youtube', metric='views', period_basis='America/Los_Angeles',
                          published_at=original, job_id=1, period_start='2026-08-31', value='10')
    calls = []
    def unavailable(name):
        calls.append(name)
        raise error('nf-synthetic-private-path')
    monkeypatch.setattr(analytics, 'ZoneInfo', unavailable)
    with pytest.raises(PublishingError, match='시간대 데이터.*tzdata') as caught:
        analytics.recommend([row], account_id=1, now=datetime(2026, 10, 19, tzinfo=UTC))
    assert 'nf-synthetic-private-path' not in str(caught.value)
    assert calls == ['America/Los_Angeles'] and row.published_at is original
    assert row.period_start == '2026-08-31' and row.value == '10'
