"""Future KST wall-clock schedules. KST is fixed UTC+09:00, without daylight-saving transitions.

Aware UTC instants are persisted. Never use the machine's timezone or enumerate old days.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), "KST")


class ScheduleError(ValueError):
    pass


def validate(name: str, kind: str, local_time: str, weekdays: list[int], once_date: str | None,
             source: str, duration: int, platform: str, voice: str) -> dict:
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(unicodedata.category(c).startswith("C") for c in name):
        raise ScheduleError("예약 이름은 1~80자의 일반 문자로 입력하세요.")
    if kind not in {"daily", "weekly", "once"} or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", local_time):
        raise ScheduleError("예약 종류와 시각을 확인하세요.")
    if not isinstance(weekdays, list) or any(type(d) is not int or d not in range(7) for d in weekdays):
        raise ScheduleError("요일을 다시 선택하세요.")
    days = sorted(set(weekdays)) if kind == "weekly" else list(range(7)) if kind == "daily" else []
    if kind == "weekly" and not days:
        raise ScheduleError("요일을 하나 이상 선택하세요.")
    if kind == "once":
        try:
            if not isinstance(once_date, str) or not re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", once_date):
                raise ValueError
            date.fromisoformat(once_date)
        except ValueError:
            raise ScheduleError("한 번 실행할 날짜를 확인하세요.") from None
    else:
        once_date = None
    if source not in {"sample", "feeds"} or type(duration) is not int or duration not in {30, 45, 60}:
        raise ScheduleError("뉴스 종류와 영상 길이를 확인하세요.")
    if platform not in {"youtube", "instagram"} or voice not in {"offline-silence", "default"}:
        raise ScheduleError("목적지와 음성 설정을 확인하세요.")
    options = {"source": source, "duration": duration, "platform": platform, "voice": voice}
    # Every-day and weekly/all-days are the same reservation, regardless of its display name.
    identity = ["once" if kind == "once" else "repeat", local_time, days, once_date, options]
    return {"name": name.strip(), "kind": kind, "local_time": local_time, "weekdays": days,
            "once_date": once_date, "options": options,
            "fingerprint": hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()}


def next_time(kind: str, local_time: str, weekdays: list[int], once_date: str | None,
              after: datetime) -> datetime | None:
    if after.tzinfo is None:
        raise ScheduleError("시간대가 있는 시각이 필요합니다.")
    local = after.astimezone(KST)
    hour, minute = map(int, local_time.split(":"))
    start = date.fromisoformat(once_date) if kind == "once" else local.date()
    for offset in range(1 if kind == "once" else 8):
        day = start + timedelta(days=offset)
        if kind == "weekly" and day.weekday() not in weekdays:
            continue
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=KST)
        if candidate > after:
            return candidate.astimezone(UTC)
    return None
