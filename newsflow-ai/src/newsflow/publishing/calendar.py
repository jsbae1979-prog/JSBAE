"""One-shot local publishing calendar. Missed runs never burst or replay.

Production dispatch is a separate code boundary, not a GUI/environment switch.
The existing unified coordinator owns per-platform consent and delivery journals.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from threading import Event, Thread

from sqlalchemy import select, update

from newsflow.db.models import PublishSchedule, utcnow

from .service import ConflictError, PublishingError

KST = timezone(timedelta(hours=9))
OPTIONS = {
    "approval_token",
    "consent",
    "privacy",
    "made_for_kids",
    "youtube_public_consent",
    "instagram_public_consent",
    "extension_options",
}


def local_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None or parsed.second or parsed.microsecond:
            raise ValueError
        return parsed.replace(tzinfo=KST).astimezone(UTC)
    except ValueError:
        raise PublishingError("한국 시간으로 예약 날짜와 시각을 입력하세요.") from None


class PublishingCalendar:
    def __init__(self, sessions, unified, *, synthetic_dispatch=None):
        self.sessions, self.unified = sessions, unified
        self.dispatch = synthetic_dispatch
        self.stop = Event()
        self.thread = None

    def save(self, cohort_id: int, due_at: datetime, *, revision: int | None = None, now=None) -> int:
        now = now or utcnow()
        if due_at.tzinfo is None or not now + timedelta(minutes=1) <= due_at <= now + timedelta(days=29):
            raise PublishingError("1분 이후부터 29일 이내의 한국 시간으로 예약하세요.")
        cohort = self.unified.get(cohort_id)
        if cohort["locked"] or not cohort["reviewed"] or not cohort["can_execute"]:
            raise PublishingError("게시할 영상·출처·권리를 검토한 후 예약하세요.")
        with self.sessions.begin() as session:
            # Serializes inserts and edits; the unique cohort ID also protects duplicate plans.
            session.execute(
                update(PublishSchedule)
                .values(revision=PublishSchedule.revision)
                .where(PublishSchedule.cohort_id == cohort_id)
            )
            row = session.scalar(select(PublishSchedule).where(PublishSchedule.cohort_id == cohort_id))
            if row:
                if revision != row.revision or row.status not in {
                    "paused",
                    "armed",
                    "missed",
                    "cancelled",
                    "blocked",
                }:
                    raise ConflictError("예약이 변경되었거나 실행 중입니다. 새로고침하세요.")
                row.due_at, row.status, row.approval = due_at, "paused", {}
                row.revision += 1
                row.updated_at = now
                row.message = "시간 변경 · 게시 승인을 다시 확인하세요."
            else:
                row = PublishSchedule(
                    cohort_id=cohort_id,
                    due_at=due_at,
                    status="paused",
                    approval={},
                    message="일정 저장 · 실행 승인 전",
                )
                session.add(row)
            session.flush()
            return row.id

    def arm(self, identifier: int, revision: int, approval: dict, *, now=None) -> None:
        if self.dispatch is None:
            raise PublishingError("실제 예약 전송은 아직 활성화되지 않았습니다. 일정 저장만 가능합니다.")
        if set(approval) - OPTIONS or approval.get("consent") is not True:
            raise PublishingError("예약 게시의 대상·공개 범위·전송 승인 항목을 확인하세요.")
        with self.sessions() as session:
            row = session.get(PublishSchedule, identifier)
            if not row or row.due_at <= (now or utcnow()):
                raise PublishingError("예약 시간을 다시 선택하세요.")
            _payload, state = self.unified._preflight(row.cohort_id, approval.get("approval_token", ""))
            active = set(state["targets"])
            if "tiktok" in active:
                raise PublishingError(
                    "TikTok은 최신 계정 조건과 직접 게시 선택이 필요해 무인 예약에서 제외합니다."
                )
            if "youtube" in active and (
                type(approval.get("made_for_kids")) is not bool
                or approval.get("privacy") not in {"private", "unlisted", "public"}
                or (approval["privacy"] != "private" and approval.get("youtube_public_consent") is not True)
            ):
                raise PublishingError("YouTube 공개 범위와 아동용 여부 승인이 필요합니다.")
            if "instagram" in active and approval.get("instagram_public_consent") is not True:
                raise PublishingError("Instagram 공개 게시 승인이 필요합니다.")
            if "facebook" in active:
                self.unified.extensions["facebook"].validate_options(
                    approval.get("extension_options", {}).get("facebook", {})
                )
        self._change(
            identifier,
            revision,
            {"paused"},
            status="armed",
            approval=approval,
            message="합성 예약 승인 · 실제 전송 아님",
        )

    def cancel(self, identifier: int, revision: int) -> None:
        self._change(
            identifier,
            revision,
            {"paused", "armed", "missed", "blocked"},
            status="cancelled",
            approval={},
            message="예약 해제 · 영상과 게시 기록 보존",
        )

    def _change(self, identifier: int, revision: int, states: set[str], **values) -> None:
        with self.sessions.begin() as session:
            changed = session.execute(
                update(PublishSchedule)
                .where(
                    PublishSchedule.id == identifier,
                    PublishSchedule.revision == revision,
                    PublishSchedule.status.in_(states),
                )
                .values(**values, revision=revision + 1, updated_at=utcnow())
            )
            if changed.rowcount != 1:
                raise ConflictError("예약 상태가 변경되었습니다. 새로고침하세요.")

    def tick(self, *, now=None) -> int:
        now = now or utcnow()
        with self.sessions() as session:
            due = list(
                session.scalars(
                    select(PublishSchedule)
                    .where(PublishSchedule.status == "armed", PublishSchedule.due_at <= now)
                    .order_by(PublishSchedule.due_at)
                    .limit(20)
                )
            )
        count = 0
        for row in due:
            state = (
                "missed"
                if row.due_at < now - timedelta(minutes=2)
                else "blocked"
                if self.dispatch is None
                else "running"
            )
            try:
                self._change(
                    row.id,
                    row.revision,
                    {"armed"},
                    status=state,
                    message="예정 시각을 놓쳤습니다. 직접 새 일정을 선택하세요."
                    if state == "missed"
                    else "예약 실행 상태 확인",
                )
            except ConflictError:
                continue
            count += 1
            if state != "running":
                continue
            try:
                result = self.dispatch(row.cohort_id, **row.approval)
                states = {target["status"] for target in result["targets"]}
                final = "simulated" if states and states <= {"complete", "simulated"} else "attention"
                message = "플랫폼별 결과 확인 · 완료 대상 재게시 안 함"
            except Exception:  # noqa: BLE001 - no provider exceptions in logs, no replay
                final, message = "unknown", "예약 실행 결과 불명 · 자동 재실행 안 함"
            self._change(row.id, row.revision + 1, {"running"}, status=final, message=message)
        return count

    def recover(self, *, now=None) -> None:
        now = now or utcnow()
        with self.sessions.begin() as session:
            session.execute(
                update(PublishSchedule)
                .where(PublishSchedule.status == "running")
                .values(
                    status="unknown",
                    revision=PublishSchedule.revision + 1,
                    message="중단된 예약 · 결과 확인 필요",
                    updated_at=now,
                )
            )
            # Any offline occurrence is missed, even within the regular worker's two-minute grace.
            session.execute(
                update(PublishSchedule)
                .where(PublishSchedule.status == "armed", PublishSchedule.due_at <= now)
                .values(
                    status="missed",
                    revision=PublishSchedule.revision + 1,
                    message="앱 종료 중 지난 예약 · 자동 실행 안 함",
                    updated_at=now,
                )
            )

    def rows(self) -> list:
        with self.sessions() as session:
            return list(
                session.scalars(select(PublishSchedule).order_by(PublishSchedule.due_at.desc()).limit(100))
            )

    def start(self) -> None:
        if self.thread is not None:
            return

        def run():
            while not self.stop.wait(20):
                self.tick()

        self.thread = Thread(target=run, daemon=True, name="publish-calendar")
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=3)


def month_view(rows: list, month: str | None = None) -> dict:
    import calendar as dates

    today = utcnow().astimezone(KST).date()
    try:
        first = datetime.strptime(month, "%Y-%m").date().replace(day=1) if month else today.replace(day=1)
        if not 2000 <= first.year <= 2100:
            raise ValueError
    except ValueError:
        raise PublishingError("달력 월은 YYYY-MM 형식으로 선택하세요.") from None
    weeks = []
    for week in dates.Calendar(firstweekday=6).monthdatescalendar(first.year, first.month):
        weeks.append(
            [
                {
                    "day": d.day,
                    "date": d.isoformat(),
                    "current": d.month == first.month,
                    "today": d == today,
                    "count": sum(
                        r.due_at.astimezone(KST).date() == d and r.status != "cancelled" for r in rows
                    ),
                }
                for d in week
            ]
        )
    previous = (first - timedelta(days=1)).strftime("%Y-%m")
    following = (first.replace(day=28) + timedelta(days=4)).strftime("%Y-%m")
    return {"label": first.strftime("%Y년 %m월"), "weeks": weeks, "previous": previous, "next": following}
