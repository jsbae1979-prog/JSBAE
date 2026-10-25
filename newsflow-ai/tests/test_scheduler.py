"""Offline clock, crash-window and approval-boundary regressions. No provider network."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
from filelock import FileLock
from sqlalchemy import func, select
from test_autopilot_state import harness, settled  # noqa: F401 - shared synthetic coordinator fixture

from newsflow.autopilot.contracts import AutopilotConflict, BackendError
from newsflow.db.models import AutopilotJob, ProductionSchedule, ScheduledRun
from newsflow.scheduler.service import Scheduler
from newsflow.scheduler.timing import KST, ScheduleError, next_time, validate

NOW = datetime(2026, 10, 16, 23, 59, tzinfo=UTC)  # Saturday 08:59 KST
VALUES = {'name': '아침 뉴스', 'kind': 'daily', 'local_time': '09:00', 'weekdays': [], 'once_date': None,
              'source': 'sample', 'duration': 30, 'platform': 'youtube', 'voice': 'offline-silence'}


@pytest.fixture
def scheduler(request):
    coordinator, backend, sessions, root = request.getfixturevalue("harness")
    clock = [NOW]
    service = Scheduler(sessions, root, coordinator, clock=lambda: clock[0], interval=0.01)
    yield service, clock, coordinator, backend, sessions, root
    service.close()


def row(service, identifier):
    with service.sessions() as session:
        return session.get(ProductionSchedule, identifier)


def add(service, **changes):
    return service.save(**{**VALUES, **changes})


def enable(service, identifier):
    service.change(identifier, row(service, identifier).revision, 'enable')


def occurrence(service):
    return service.view()['runs'][0]['run']


def fire(scheduler, **changes):
    service, clock, coordinator, *_ = scheduler
    identifier = add(service, **changes)
    enable(service, identifier)
    clock[0] += timedelta(minutes=1)
    service.tick()
    occurrence(service)
    if coordinator.future:
        coordinator.future.result(timeout=10)
    service.tick()
    return identifier, occurrence(service)


@pytest.mark.parametrize(('kind','days','once','after','expected'), [
    ('daily', [], None, NOW, '2026-10-17T00:00:00+00:00'),
    ('daily', [], None, NOW + timedelta(minutes=1), '2026-10-18T00:00:00+00:00'),
    ('weekly', [0], None, NOW, '2026-10-19T00:00:00+00:00'),
    ('weekly', [5], None, NOW, '2026-10-17T00:00:00+00:00'),
    ('weekly', [5], None, NOW + timedelta(minutes=1), '2026-10-24T00:00:00+00:00'),
    ('once', [], '2026-10-17', NOW, '2026-10-17T00:00:00+00:00'),
    ('once', [], '2026-10-16', NOW, None),
    ('daily', [], None, datetime(2026, 3, 8, 0, tzinfo=UTC), '2026-03-09T00:00:00+00:00'),
    ('daily', [], None, datetime(2026, 11, 1, 0, tzinfo=UTC), '2026-11-02T00:00:00+00:00'),
    ('once', [], '2028-02-29', NOW, '2028-02-29T00:00:00+00:00'),
])
def test_kst_future_time_and_no_machine_dst(kind, days, once, after, expected):
    result = next_time(kind, '09:00', days, once, after)
    assert (result.isoformat() if result else None) == expected
    assert next_time(kind, '09:00', days, once, after.astimezone(KST)) == result


def test_naive_clock_rejected():
    with pytest.raises(ScheduleError):
        next_time('daily', '09:00', [], None, datetime(2026, 1, 1))


@pytest.mark.parametrize('change', [
    {'name':''}, {'name':'a'*81}, {'name':'bad\nname'}, {'kind':'monthly'}, {'local_time':'24:00'},
    {'local_time':'9:00'}, {'local_time':'10:60'}, {'weekdays':[True]}, {'weekdays':[7]},
    {'kind':'weekly','weekdays':[]}, {'kind':'once','once_date':'2026-02-30'},
    {'kind':'once','once_date':'1999-01-01'}, {'kind':'once','once_date':None},
    {'source':'http://private'}, {'duration':True}, {'duration':29}, {'platform':'shell'},
    {'voice':'external-paid-tts'},
])
def test_invalid_settings_rejected(change):
    with pytest.raises(ScheduleError):
        validate(**{**VALUES, **change})


def test_paused_default_crud_duplicate_cas_and_history_preservation(scheduler):
    service, clock, *_ = scheduler
    identifier = add(service)
    assert row(service, identifier).status == 'paused'
    clock[0] += timedelta(minutes=2)
    service.tick()
    assert not service.view()['runs']
    with pytest.raises(ScheduleError):
        add(service, name='다른 이름', kind='weekly', weekdays=list(range(7)))
    revision = row(service, identifier).revision
    service.save(**{**VALUES, 'local_time':'10:00'}, schedule_id=identifier, revision=revision)
    with pytest.raises(ScheduleError):
        service.change(identifier, revision, 'enable')
    enable(service, identifier)
    service.change(identifier, row(service, identifier).revision, 'pause')
    service.change(identifier, row(service, identifier).revision, 'remove')
    assert not service.view()['schedules']
    assert row(service, identifier).status == 'removed'
    assert add(service, local_time='10:00') != identifier


def test_once_expired_not_enabled(scheduler):
    service, clock, *_ = scheduler
    identifier = add(service, kind='once', once_date='2026-10-17')
    clock[0] += timedelta(minutes=2)
    with pytest.raises(ScheduleError):
        enable(service, identifier)


def test_full_synthetic_run_is_one_job_and_preserves_review_queue(scheduler):
    service, clock, coordinator, backend, sessions, _ = scheduler
    identifier, run = fire(scheduler)
    result = coordinator.snapshot(run.job_id)
    assert run.status == 'completed' and result['publish_draft_id'] == 501
    assert result['stage_results']['queue']['external_publishing_enabled'] is False
    assert all(ctx['scheduled'] and ctx['ai_mode'] == 'offline' for _, ctx in backend.calls)
    for _ in range(3):
        service.tick()
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AutopilotJob)) == 1
        assert session.scalar(select(func.count()).select_from(ScheduledRun)) == 1
    assert row(service, identifier).next_run_at > clock[0]
    # Wall-clock rollback cannot replay an already consumed occurrence.
    clock[0] -= timedelta(days=1)
    service.tick()
    assert len(service.view()['runs']) == 1


def test_once_finishes_without_disabling_result(scheduler):
    service = scheduler[0]
    identifier, run = fire(scheduler, kind='once', once_date='2026-10-17')
    assert row(service, identifier).status == 'finished'
    assert row(service, identifier).next_run_at is None and run.status == 'completed'


@pytest.mark.parametrize('days', [1, 365, 3650])
def test_missed_period_collapses_no_unbounded_catchup(scheduler, days):
    service, clock, coordinator, *_ = scheduler
    identifier = add(service)
    enable(service, identifier)
    clock[0] += timedelta(days=days, minutes=3)
    service.tick()
    assert occurrence(service).status == 'skipped' and coordinator.future is None
    assert len(service.view()['runs']) == 1
    assert row(service, identifier).next_run_at > clock[0]


@pytest.mark.parametrize(('seconds','status'), [(90,'completed'),(91,'skipped')])
def test_grace_boundary(scheduler, seconds, status):
    service, clock, coordinator, *_ = scheduler
    identifier = add(service)
    enable(service, identifier)
    clock[0] += timedelta(minutes=1, seconds=seconds)
    service.tick()
    if coordinator.future:
        coordinator.future.result(timeout=10)
    service.tick()
    assert occurrence(service).status == status


def test_real_news_cannot_bypass_script_or_final_review(scheduler):
    service, _clock, coordinator, backend, *_ = scheduler
    _, run = fire(scheduler, source='feeds')
    state = coordinator.snapshot(run.job_id)
    assert run.status == 'waiting_review' and state['current_stage'] == 'script'
    assert 'render' not in [stage for stage, _ in backend.calls]
    coordinator.resume(run.job_id, state['revision'])
    state = settled(coordinator, run.job_id)
    service.tick()
    assert state['current_stage'] == 'validate' and state['status'] == 'waiting_review'
    assert 'queue' not in [stage for stage, _ in backend.calls]


def test_busy_is_recorded_not_queued_and_explicit_retry_only(scheduler):
    service, _clock, coordinator, *_ = scheduler
    manual = coordinator.start(mode='guided')
    settled(coordinator, manual)
    _, run = fire(scheduler)
    assert run.status == 'blocked'
    coordinator.cancel(manual, coordinator.snapshot(manual)['revision'])
    service.tick()
    assert occurrence(service).status == 'blocked'
    coordinator.backend.article_ids.reverse()  # cancelled job retains its original article claim
    service.retry(run.id, run.revision)
    settled(coordinator, run.job_id)
    service.tick()
    assert occurrence(service).status == 'completed'


def test_two_schedulers_and_lock_cannot_duplicate(scheduler):
    service, clock, coordinator, _backend, sessions, root = scheduler
    identifier = add(service)
    enable(service, identifier)
    clock[0] += timedelta(minutes=1)
    second = Scheduler(sessions, root, coordinator, clock=lambda: clock[0])
    with FileLock(str(root/'scheduler.lock')), pytest.raises(ScheduleError):
        service.tick()
    service.tick()
    second.tick()
    settled(coordinator, occurrence(service).job_id)
    assert len(service.view()['runs']) == 1
    second.close()


def test_dispatch_crash_before_insert_stays_unknown_until_manual_retry(scheduler, monkeypatch):
    service, _clock, coordinator, backend, *_ = scheduler
    original = coordinator.start
    def crash(**kwargs):
        raise RuntimeError('secret-token-must-not-appear')
    monkeypatch.setattr(coordinator, 'start', crash)
    _, run = fire(scheduler)
    assert run.status == 'interrupted' and not backend.calls
    assert 'secret-token' not in run.message
    monkeypatch.setattr(coordinator, 'start', original)
    service.tick()
    assert not backend.calls
    service.retry(run.id, run.revision)
    settled(coordinator, run.job_id)
    service.tick()
    assert occurrence(service).status == 'completed'


def test_dispatch_crash_after_insert_reconciles_same_job(scheduler, monkeypatch):
    _service, _clock, coordinator, backend, sessions, _ = scheduler
    original = coordinator.start
    def commit_then_crash(**kwargs):
        original(**kwargs)
        raise RuntimeError('unknown result')
    monkeypatch.setattr(coordinator, 'start', commit_then_crash)
    _, run = fire(scheduler)
    assert run.status == 'completed'
    assert len(backend.calls) == 6
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AutopilotJob)) == 1


def test_restart_dispatching_without_job_never_autoretries(scheduler):
    service, clock, coordinator, backend, sessions, root = scheduler
    identifier = add(service)
    with sessions.begin() as session:
        session.add(ScheduledRun(id=uuid4().hex, schedule_id=identifier, scheduled_for=NOW,
                                 job_id=uuid4().hex, options=VALUES_OPTIONS(), status='dispatching', message=''))
    restarted = Scheduler(sessions, root, coordinator, clock=lambda: clock[0])
    restarted.tick()
    assert occurrence(service).status == 'interrupted' and not backend.calls
    restarted.tick()
    assert not backend.calls
    restarted.close()


def VALUES_OPTIONS():
    return {k: VALUES[k] for k in ('source','duration','platform','voice')}


@pytest.mark.parametrize('stage', ['collect','script','render','validate','queue'])
def test_failure_requires_explicit_safe_retry_and_preserves_artifacts(scheduler, stage):
    service, _clock, coordinator, backend, *_ = scheduler
    backend.fail_stage, backend.failure = stage, BackendError(code='stage_failed', retryable=True)
    _, run = fire(scheduler)
    before = coordinator.snapshot(run.job_id)
    assert run.status == 'failed'
    service.tick()
    assert len(backend.calls) == len(before['attempts'])
    backend.fail_stage = None
    service.retry(run.id, run.revision)
    after = settled(coordinator, run.job_id)
    service.tick()
    assert occurrence(service).status == 'completed'
    assert all(after['stage_results'][k] == value for k, value in before['stage_results'].items())


def test_unknown_stage_cannot_be_automatically_or_manually_replayed(scheduler):
    service, _, coordinator, backend, *_ = scheduler
    backend.fail_stage, backend.failure = 'render', BackendError(code='outcome_unknown', retryable=False, outcome_unknown=True)
    _, run = fire(scheduler)
    calls = len(backend.calls)
    with pytest.raises(ScheduleError):
        service.retry(run.id, run.revision)
    service.tick()
    assert len(backend.calls) == calls and coordinator.snapshot(run.job_id)['error_code'] == 'outcome_unknown'


def test_cancel_does_not_delete_outputs_or_future_schedule(scheduler):
    service, clock, coordinator, backend, *_ = scheduler
    backend.block_stage = 'render'
    identifier = add(service)
    enable(service, identifier)
    clock[0] += timedelta(minutes=1)
    service.tick()
    assert backend.entered.wait(5)
    run = occurrence(service)
    service.cancel(run.id, run.revision)
    settled(coordinator, run.job_id)
    service.tick()
    assert occurrence(service).status == 'cancelled'
    assert coordinator.snapshot(run.job_id)['content_draft_id'] == 201
    assert row(service, identifier).status == 'active'


def test_same_article_not_rendered_twice(scheduler):
    service, clock, coordinator, backend, *_ = scheduler
    fire(scheduler)
    clock[0] += timedelta(days=1)
    service.tick()
    settled(coordinator, occurrence(service).job_id)
    service.tick()
    assert occurrence(service).status == 'failed'
    assert [stage for stage, _ in backend.calls].count('render') == 1


def test_corrupt_paid_settings_fail_closed(scheduler):
    service, clock, _coordinator, backend, sessions, _ = scheduler
    identifier = add(service)
    enable(service, identifier)
    with sessions.begin() as session:
        value = session.get(ProductionSchedule, identifier)
        value.options = {**value.options, 'ai_mode':'openai', 'paid_approved':True}
    clock[0] += timedelta(minutes=1)
    service.tick()
    assert occurrence(service).status == 'failed'
    assert not backend.calls


def test_scheduled_context_rejects_paid_mode_after_restart(scheduler):
    _service, _clock, coordinator, backend, sessions, _ = scheduler
    _, run = fire(scheduler, source='feeds')
    with sessions.begin() as session:
        job = session.get(AutopilotJob, run.job_id)
        job.ai_mode = 'openai'
    with sessions() as session, pytest.raises(BackendError):
        coordinator._context(session, session.get(AutopilotJob, run.job_id))
    assert all(ctx['ai_mode'] == 'offline' for _, ctx in backend.calls)


def test_autopilot_request_identity_returns_existing_without_running(scheduler):
    _service, _clock, coordinator, backend, *_ = scheduler
    _, run = fire(scheduler)
    assert coordinator.start(request_id=run.job_id, voice='offline-silence') == run.job_id
    assert len(backend.calls) == 6
    with pytest.raises(AutopilotConflict):
        coordinator.start(request_id=run.job_id, duration=60, voice='offline-silence')


def test_scheduler_background_lifecycle(scheduler):
    service, *_ = scheduler
    fired = Event()
    original = service.tick
    def tick():
        original()
        fired.set()
    service.tick = tick
    service.start()
    thread = service.thread
    service.start()
    assert service.thread is thread and fired.wait(5)
    service.close()
    assert not thread.is_alive()


def test_database_copy_preserves_original_and_pauses_copy(scheduler, tmp_path):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    from newsflow.db import session as db_session
    from newsflow.db.session import make_engine, session_factory
    from newsflow.migrate_data import migrate_data

    _service, clock, coordinator, backend, _sessions, _root = scheduler
    root = tmp_path / "지원 계약 0015"
    source_engine = make_engine(root / "newsflow.db")
    config = Config()
    config.set_main_option("script_location", str(Path(db_session.__file__).parent / "migrations").replace("%", "%%"))
    service = Scheduler(session_factory(source_engine), root, coordinator, clock=lambda: clock[0])
    try:
        with source_engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0015")
        identifier = add(service)
        enable(service, identifier)
        source_engine.dispose()
        original_db = (root / "newsflow.db").read_bytes()
        target = tmp_path/'다른 사용자 폴더'
        migrate_data(root, target)
        assert (root / "newsflow.db").read_bytes() == original_db
        engine = make_engine(target/'newsflow.db')
        try:
            with session_factory(engine)() as session:
                copied = session.get(ProductionSchedule, identifier)
                assert copied.status == 'paused'
                assert copied.options == row(service, identifier).options
                assert copied.revision == row(service, identifier).revision+1
            assert row(service, identifier).status == 'active'
            with source_engine.connect() as connection:
                assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "0015"
            with engine.connect() as connection:
                assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "0015"
                assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
                assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
            assert backend.calls == []
        finally:
            engine.dispose()
    finally:
        service.close()
        source_engine.dispose()


def test_restart_recovers_job_without_recreating_completed_stages(scheduler):
    from newsflow.autopilot.service import AutopilotCoordinator

    service, clock, coordinator, backend, sessions, root = scheduler
    backend.block_stage = 'render'
    identifier = add(service)
    enable(service, identifier)
    clock[0] += timedelta(minutes=1)
    service.tick()
    assert backend.entered.wait(5)
    run = occurrence(service)
    coordinator.close()
    recovered = AutopilotCoordinator(sessions, root, backend)
    scheduler2 = Scheduler(sessions, root, recovered, clock=lambda:clock[0])
    try:
        recovered.recover()
        scheduler2.tick()
        assert occurrence(scheduler2).status == 'interrupted'
        assert recovered.snapshot(run.job_id)['content_draft_id'] == 201
        assert recovered.future is None
        backend.block_stage = None
        run = occurrence(scheduler2)
        scheduler2.retry(run.id, run.revision)
        settled(recovered, run.job_id)
        scheduler2.tick()
        assert occurrence(scheduler2).status == 'completed'
        assert [stage for stage,_ in backend.calls].count('script') == 1
    finally:
        scheduler2.close()
        recovered.close()


def test_additive_migration_0011_preserves_legacy_settings_and_sources(tmp_path):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect, text

    from newsflow.db.session import make_engine, migrate

    engine = make_engine(tmp_path/'old.sqlite')
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).parents[1]/'src/newsflow/db/migrations'))
    try:
        with engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config,'0011')
            connection.execute(text("INSERT INTO app_settings(key,value) VALUES ('legacy','preserved')"))
        migrate(engine)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT value FROM app_settings WHERE key='legacy'")) == 'preserved'
            assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0018'
        assert {'production_schedules','scheduled_runs'} <= set(inspect(engine).get_table_names())
        migrate(engine)
    finally:
        engine.dispose()
