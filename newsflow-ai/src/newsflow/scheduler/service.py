"""Durable local scheduler. No provider, OAuth, publishing or OS task registration code.

A file lock serializes dispatch and explicit schedule mutations across processes. SQLite
occurrence uniqueness + deterministic Autopilot IDs protect a crash between both commits.
Unknown dispatch is never retried by the clock. Missed periods produce one skipped record.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Lock, Thread
from uuid import NAMESPACE_URL, uuid4, uuid5

from filelock import FileLock, Timeout
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from newsflow.autopilot.contracts import AutopilotBusy, AutopilotError
from newsflow.autopilot.service import AutopilotCoordinator
from newsflow.db.models import AutopilotJob, ProductionSchedule, ScheduledRun, utcnow

from .timing import ScheduleError, next_time, validate

GRACE = timedelta(seconds=90)
LABELS = {"paused": "일시 중지", "active": "예약 중", "finished": "예약 종료", "removed": "해제됨",
          "dispatching": "시작 확인 중", "running": "제작 중", "waiting_review": "직접 검토 필요",
          "completed": "완료", "failed": "실패", "interrupted": "중단 · 확인 필요", "cancelled": "취소됨",
          "skipped": "미실행 · 놓친 예약", "blocked": "다른 작업 확인 필요"}
RETRYABLE = {"blocked", "skipped", "interrupted", "failed", "cancelled"}


class Scheduler:
    def __init__(self, sessions: sessionmaker[Session], data_dir: Path, autopilot: AutopilotCoordinator,
                 *, clock: Callable[[], datetime] = utcnow, interval: float = 5) -> None:
        self.sessions, self.autopilot, self.clock, self.interval = sessions, autopilot, clock, interval
        self.lock = FileLock(str(data_dir / "scheduler.lock"))
        self.guard = Lock()
        self.stop = Event()
        self.thread: Thread | None = None
        self.last_error = ""

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        if not self.guard.acquire(blocking=False):
            raise ScheduleError("예약을 처리 중입니다. 잠시 후 다시 확인하세요.")
        try:
            try:
                with self.lock.acquire(timeout=0):
                    yield
            except Timeout:
                raise ScheduleError("다른 창에서 예약을 처리 중입니다. 잠시 후 다시 확인하세요.") from None
        finally:
            self.guard.release()

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        with self.sessions.begin() as session:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            yield session

    @staticmethod
    def _next(row: ProductionSchedule, now: datetime) -> datetime | None:
        return next_time(row.kind, row.local_time, row.weekdays, row.once_date, now)

    @staticmethod
    def _checked(row: object | None, revision: int) -> None:
        if row is None or type(revision) is not int or row.revision != revision:
            raise ScheduleError("예약 상태가 바뀌었습니다. 새로고침 후 다시 확인하세요.")

    def save(self, *, name: str, kind: str, local_time: str, weekdays: list[int], once_date: str | None = None,
             source: str = "sample", duration: int = 30, platform: str = "youtube", voice: str = "offline-silence",
             schedule_id: str | None = None, revision: int = 0) -> str:
        values = validate(name, kind, local_time, weekdays, once_date, source, duration, platform, voice)
        now = self.clock()
        due = next_time(kind, local_time, values["weekdays"], values["once_date"], now)
        if due is None:
            raise ScheduleError("다음에 실행할 미래 날짜와 시각을 선택하세요.")
        try:
            with self._exclusive(), self._transaction() as session:
                if schedule_id:
                    row = session.get(ProductionSchedule, schedule_id)
                    self._checked(row, revision)
                    if row.status == "removed":
                        raise ScheduleError("해제한 예약은 수정할 수 없습니다.")
                    for key, value in values.items():
                        setattr(row, key, value)
                    row.revision += 1
                    if row.status == "finished":
                        row.status = "paused"
                else:
                    count = session.scalar(select(func.count()).select_from(ProductionSchedule).where(
                        ProductionSchedule.status != "removed"))
                    if count >= 50:
                        raise ScheduleError("예약은 최대 50개입니다. 사용하지 않는 예약을 해제하세요.")
                    row = ProductionSchedule(id=uuid4().hex, status="paused", **values)
                    session.add(row)
                row.next_run_at, row.updated_at = due, now
                session.flush()
                return row.id
        except IntegrityError:
            raise ScheduleError("같은 시간과 제작 조건의 예약이 이미 있습니다. 기존 예약을 수정하세요.") from None

    def change(self, schedule_id: str, revision: int, action: str) -> None:
        if action not in {"enable", "pause", "remove"}:
            raise ScheduleError("예약 동작을 확인하세요.")
        with self._exclusive(), self._transaction() as session:
            row = session.get(ProductionSchedule, schedule_id)
            self._checked(row, revision)
            if row.status == "removed":
                raise ScheduleError("이미 해제한 예약입니다.")
            if action == "enable":
                row.next_run_at = self._next(row, self.clock())
                if row.next_run_at is None:
                    raise ScheduleError("실행 날짜가 지났습니다. 미래 시각으로 수정하세요.")
                row.status = "active"
            else:
                row.status = "paused" if action == "pause" else "removed"
                if action == "remove":
                    row.fingerprint, row.next_run_at = None, None
            row.revision += 1
            row.updated_at = self.clock()

    def _reconcile(self) -> None:
        with self._transaction() as session:
            rows = session.scalars(select(ScheduledRun).where(
                ScheduledRun.status.in_(("dispatching", "running", "waiting_review")))).all()
            for row in rows:
                job = session.get(AutopilotJob, row.job_id)
                if job:
                    status = "running" if job.status in {"queued", "running"} else job.status
                    message = "제작 결과를 확인하세요." if status == "completed" else job.message
                else:
                    status, message = "interrupted", "시작 결과를 확인하지 못했습니다. 작업 이력을 확인한 뒤 직접 다시 시도하세요."
                if (row.status, row.message) != (status, message):
                    row.status, row.message = status, message
                    row.revision += 1
                    row.updated_at = self.clock()

    @staticmethod
    def _options(raw: dict) -> dict:
        # Fail closed even for stale/corrupt stored options; never inherit global paid AI settings.
        if not isinstance(raw, dict) or set(raw) != {"source", "duration", "platform", "voice"}:
            raise ScheduleError("저장된 제작 설정을 확인하지 못했습니다. 예약을 다시 저장하세요.")
        return validate("검사", "daily", "00:00", [], None, **raw)["options"]

    def _dispatch(self, run_id: str) -> None:
        with self.sessions() as session:
            row = session.get(ScheduledRun, run_id)
            options, job_id = row.options, row.job_id
        try:
            options = self._options(options)
            self.autopilot.start(
                mode="easy", source=options["source"], duration=options["duration"], platform=options["platform"],
                ai_mode="offline", voice=None if options["voice"] == "default" else "offline-silence", request_id=job_id,
            )
        except AutopilotBusy:
            status, message = "blocked", "진행 중이거나 검토를 기다리는 작업이 있습니다. 먼저 확인한 뒤 직접 다시 시도하세요."
        except ScheduleError:
            status, message = "failed", "저장된 제작 설정이 올바르지 않습니다. 예약을 수정하세요."
        except Exception:  # noqa: BLE001 - no secret/provider traceback enters durable history
            # Start may have committed its job before raising. Preserve its identity and reconcile it.
            status, message = "interrupted", "시작 결과를 확인하지 못했습니다. 기존 작업을 먼저 확인하세요."
        else:
            status, message = "running", "예약한 제작을 시작했습니다."
        with self._transaction() as session:
            row = session.get(ScheduledRun, run_id)
            row.status, row.message, row.updated_at = status, message, self.clock()
            row.revision += 1
            if session.get(AutopilotJob, job_id):
                row.status = "running"  # reconciled from durable work, never called successful here
        self._reconcile()

    def tick(self) -> None:
        if self.stop.is_set():
            return
        with self._exclusive():
            self._reconcile()
            now = self.clock()
            with self.sessions() as session:
                ids = list(session.scalars(select(ProductionSchedule.id).where(
                    ProductionSchedule.status == "active", ProductionSchedule.next_run_at <= now,
                ).order_by(ProductionSchedule.next_run_at, ProductionSchedule.id).limit(50)))
            for schedule_id in ids:
                if self.stop.is_set():
                    break
                run_id = None
                with self._transaction() as session:
                    row = session.get(ProductionSchedule, schedule_id)
                    due = row.next_run_at
                    run_id = uuid5(NAMESPACE_URL, f"newsflow:{row.id}:{due.isoformat()}").hex
                    missed = now - due > GRACE
                    existing = session.get(ScheduledRun, run_id)
                    if existing is None:
                        session.add(ScheduledRun(
                            id=run_id, schedule_id=row.id, scheduled_for=due, job_id=run_id, options=dict(row.options),
                            status="skipped" if missed else "dispatching",
                            message="앱이 꺼져 있거나 지연되어 놓친 예약입니다. 지난 기간을 몰아서 제작하지 않습니다." if missed else "시작 확인 중",
                        ))
                    row.next_run_at = self._next(row, max(now, due))
                    if row.next_run_at is None:
                        row.status = "finished"
                    row.updated_at, row.revision = now, row.revision + 1
                    if missed or existing is not None:
                        run_id = None
                if run_id:
                    self._dispatch(run_id)
            self.last_error = ""

    def retry(self, run_id: str, revision: int) -> None:
        with self._exclusive():
            self._reconcile()
            with self._transaction() as session:
                row = session.get(ScheduledRun, run_id)
                self._checked(row, revision)
                if row.status not in RETRYABLE:
                    raise ScheduleError("실행 중이거나 완료한 작업은 다시 시작하지 않습니다.")
                schedule = session.get(ProductionSchedule, row.schedule_id)
                if schedule.status == "removed":
                    raise ScheduleError("해제한 예약은 다시 실행할 수 없습니다.")
                job = session.get(AutopilotJob, row.job_id)
                job_revision = job.revision if job else None
                job_id = row.job_id
                row.status, row.message = "dispatching", "직접 요청한 다시 시도를 확인합니다."
                row.revision += 1
            if job_revision is None:
                self._dispatch(run_id)
            else:
                try:
                    self.autopilot.retry(job_id, job_revision)
                except AutopilotError:
                    with self._transaction() as session:
                        row = session.get(ScheduledRun, run_id)
                        row.status, row.message = "running", "기존 작업의 안전한 재시도 조건을 확인하세요."
                    self._reconcile()
                    raise ScheduleError("안전하게 다시 시도할 수 없습니다. 기존 작업에서 이전 결과와 실패 원인을 확인하세요.") from None
                with self._transaction() as session:
                    session.get(ScheduledRun, run_id).status = "running"
                self._reconcile()

    def cancel(self, run_id: str, revision: int) -> None:
        with self._exclusive():
            with self.sessions() as session:
                row = session.get(ScheduledRun, run_id)
                self._checked(row, revision)
                job = session.get(AutopilotJob, row.job_id)
                job_id, job_revision = row.job_id, job.revision if job else None
            if job_revision is not None:
                try:
                    self.autopilot.cancel(job_id, job_revision)
                except AutopilotError:
                    raise ScheduleError("작업 상태가 바뀌었습니다. 제작 화면에서 현재 상태를 확인하세요.") from None
            else:
                with self._transaction() as session:
                    row = session.get(ScheduledRun, run_id)
                    row.status, row.message = "cancelled", "이번 실행을 취소했습니다. 예약 자체는 별도로 일시 중지할 수 있습니다."
                    row.revision += 1
            self._reconcile()

    def view(self) -> dict:
        # Reads do not dispatch, resume, approve or call providers.
        with self.sessions() as session:
            schedules = session.scalars(select(ProductionSchedule).where(
                ProductionSchedule.status != "removed").order_by(ProductionSchedule.created_at.desc())).all()
            runs = session.scalars(select(ScheduledRun).order_by(ScheduledRun.created_at.desc()).limit(100)).all()
            items = []
            for row in runs:
                job = session.get(AutopilotJob, row.job_id)
                items.append({"run": row, "job": job, "schedule": session.get(ProductionSchedule, row.schedule_id)})
            return {"schedules": schedules, "runs": items, "labels": LABELS, "scheduler_error": self.last_error}

    def _loop(self) -> None:
        while not self.stop.is_set():
            try:
                self.tick()
            except ScheduleError:
                pass  # another process owns dispatch; uniqueness and its lock remain authoritative
            except Exception:  # noqa: BLE001 - visible fixed message, no automatic uncertain replay
                self.last_error = "예약 확인을 마치지 못했습니다. 앱을 다시 열고 실행 이력을 확인하세요."
            self.stop.wait(self.interval)

    def start(self) -> None:
        if self.thread is None and not self.stop.is_set():
            self.thread = Thread(target=self._loop, name="newsflow-scheduler", daemon=True)
            self.thread.start()

    def close(self) -> None:
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=30)
