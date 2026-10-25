"""Phase 5D: AI video settings, model catalog, cost limits, prompt policy, key store and migration 0010.

Everything here is offline: a temporary SQLite database migrated with the real Alembic scripts,
a FakeCipher (or a test cipher) for the key file, and no provider, network or real API key.
"""

from __future__ import annotations

import hashlib
import itertools
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, select, text

import newsflow.db.session as db_session
from newsflow.db.models import (
    AIVideoPlan,
    AIVideoScene,
    AppSetting,
    ContentDraft,
    IntelligenceRun,
    VideoAIModel,
    VideoAIUsage,
)
from newsflow.intelligence.credentials import AIKeyStore, CredentialError, FakeCipher, _entropy
from newsflow.video.ai import policy
from newsflow.video.ai import settings as video_settings
from newsflow.video.ai.costs import (
    CURRENCIES,
    MAX_CLIP_SECONDS,
    MAX_LIMIT,
    MAX_PRICE_PER_SECOND,
    CostError,
    clip_seconds,
    money,
    parse_durations,
    parse_money,
    scene_cost,
)
from newsflow.video.ai.keys import VIDEO_ENV_NAME, VideoAIKeyStore
from newsflow.video.ai.policy import (
    DEFAULT_PROMPT,
    PROMPT_MAX_CHARS,
    SCENE_LABEL,
    STYLE_GUARD,
    VIDEO_NOTICE,
    PromptPolicyError,
    check_prompt,
    provider_prompt,
)
from newsflow.video.ai.settings import (
    COUNTED,
    CURRENCY_CHANGED,
    HOSTS,
    MODEL_LIMIT,
    PROVIDERS,
    RESOLUTIONS,
    VideoAISettings,
    VideoSettingsError,
    check_budget,
    delete_model,
    find_model,
    list_models,
    month_start,
    plan_currency_mismatch,
    plan_spent,
    read_settings,
    readiness,
    save_model,
    usage_this_month,
    validate_path,
    write_settings,
)
from newsflow.video.engine import AI_SCENE_LABEL

PATH = "fixture/model/text-to-video"  # Synthetic catalog, never a live vendor model
OTHER_PATH = "bytedance/seedance-2.0/text-to-video"
VIDEO_KEY = "abcd1234:secretvalue123"
OPENAI_KEY = "sk-synthetic-not-a-real-key-0123456789abcdef"
MIGRATIONS = Path(db_session.__file__).resolve().parent / "migrations"

# Fixed Korean messages, copied from the source modules.
MSG_PROVIDER = "AI 영상 공급사를 다시 선택하세요."
MSG_HOST = "API 호스트는 목록에서만 선택할 수 있습니다."
MSG_CURRENCY = "통화는 USD 또는 KRW 중에서 선택하세요."
MSG_MONEY_FORMAT = "금액은 0 이상의 숫자(소수점 4자리까지)로 입력하세요."
MSG_MAX_ACTIVE = "동시 생성 수는 1~4 사이여야 합니다."
MSG_TIMEOUT = "장면별 제한시간은 5~120분 사이여야 합니다."
MSG_POLL = "상태 확인 간격은 5~60초 사이여야 합니다."
MSG_APPROVAL_LIMITS = "유료 생성을 승인하려면 0보다 큰 작업별 한도와 월 한도를 함께 설정하세요."
MSG_JOB_OVER_MONTH = "작업별 한도는 월 한도보다 클 수 없습니다."
MSG_CURRENCY_LOCKED = "이번 달 사용 기록이 있어 통화를 바꿀 수 없습니다. 다음 달에 바꾸세요."
MSG_PATH = "모델 경로는 공식 문서의 소문자 경로 형식(예: vendor/model/text-to-video)으로 입력하세요."
MSG_LABEL = "표시 이름은 1~80자로 입력하세요."
MSG_RESOLUTION = "해상도는 480p·720p·1080p 중에서 선택하세요."
MSG_CONFIRM_PRICE = "공식 문서 확인을 표시하려면 0보다 큰 초당 단가를 함께 입력하세요."
MSG_DUPLICATE = "이미 등록된 모델 경로입니다."
MSG_MODEL_LIMIT = "모델은 최대 10개까지 등록할 수 있습니다."
MSG_NOT_FOUND = "모델을 찾지 못했습니다."
MSG_DURATIONS = "허용 길이는 쉼표로 구분한 초 단위 정수로 입력하세요. 예: 5,10"
MSG_DURATION_RANGE = "허용 길이는 1~30초 사이여야 합니다."
MSG_NO_LIMITS = "작업별 한도와 월 한도가 설정되지 않아 AI 영상을 생성하지 않습니다."
MSG_PROMPT_EMPTY = "AI 생성 장면의 프롬프트를 입력하세요."
MSG_PROMPT_LONG = "프롬프트는 600자 이내로 입력하세요."
MSG_PROMPT_CONTROL = "프롬프트에 제어 문자를 넣을 수 없습니다."
MSG_PROMPT_BLOCKED = (
    "실제 뉴스 현장·기록 영상이나 실존 인물처럼 보이게 하는 표현은 사용할 수 없습니다. "
    "추상적인 배경·상징 화면으로 바꿔 쓰세요."
)
MSG_VIDEO_KEY_FORMAT = "open.higgsfield.ai에서 복사한 API 키를 공백·줄바꿈 없이 그대로 붙여 넣으세요(8~520자)."
MSG_AI_KEY_FORMAT = "API 키 형식을 확인하세요. 공백 없이 20자 이상이어야 합니다."
REASON_OFF = "AI 영상 공급사가 '사용 안 함'입니다. 기본 FFmpeg 제작만 사용합니다."
REASON_APPROVAL = "AI 영상 유료 생성 승인이 저장되지 않았습니다."
REASON_LIMITS = "작업별 한도와 월 한도가 없습니다."
REASON_EXHAUSTED = "이번 달 AI 영상 한도를 모두 사용했습니다."
REASON_KEY = "AI 영상 API 키가 없습니다."
REASON_MODEL = "공식 문서 확인과 초당 단가를 입력한 모델이 없습니다."


# --------------------------------------------------------------------------- helpers


def message(excinfo: pytest.ExceptionInfo) -> str:
    return str(excinfo.value)


@pytest.fixture
def engine(tmp_path: Path):
    engine = db_session.make_engine(tmp_path / "db" / "newsflow.db")
    db_session.migrate(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def sessions(engine):
    return db_session.session_factory(engine)


@pytest.fixture
def clock(monkeypatch):
    """Strictly increasing UTC clock for timestamps written by settings.py."""
    ticks = itertools.count(1)
    base = datetime(2026, 10, 15, 0, 0, tzinfo=UTC)

    def now() -> datetime:
        return base + timedelta(minutes=next(ticks))

    monkeypatch.setattr(video_settings, "utcnow", now)
    return now


@pytest.fixture(autouse=True)
def no_key_environment(monkeypatch):
    monkeypatch.delenv(VIDEO_ENV_NAME, raising=False)
    monkeypatch.delenv("NEWSFLOW_AI_API_KEY", raising=False)


def save_settings(sessions, **overrides) -> VideoAISettings:
    values = {
        "provider": "higgsfield", "host": HOSTS[0], "approved": True, "monthly_limit": "100", "job_limit": "10",
        "currency": "USD", "max_active": 2, "timeout_minutes": 30, "poll_seconds": 10,
    }
    values.update(overrides)
    return write_settings(sessions, **values)


def add_model(sessions, **overrides):
    values = {
        "path": PATH, "label": "합성 계약 모델", "price_per_second": "0.05", "durations": "5,10",
        "resolution": "720p", "confirmed": True,
    }
    values.update(overrides)
    return save_model(sessions, **values)


def confirmed_at(sessions, model_id: int) -> datetime | None:
    with sessions() as session:
        return session.get(VideoAIModel, model_id).confirmed_at


def make_plan(sessions) -> int:
    with sessions.begin() as session:
        run = IntelligenceRun(
            kind="generate", status="success", provider="offline", options={}, evidence={}, result={}, message="",
        )
        session.add(run)
        session.flush()
        draft = ContentDraft(run_id=run.id, duration=30, content={}, sources={})
        session.add(draft)
        session.flush()
        plan = AIVideoPlan(
            draft_id=draft.id, draft_revision=1, duration=30, provider="higgsfield", status="draft",
            currency="USD", message="",
        )
        session.add(plan)
        session.flush()
        return plan.id


def add_usage(
    sessions, plan_id: int, cost: str, status: str = "reserved", created_at: datetime | None = None,
    currency: str = "USD",
):
    created = created_at or datetime.now(UTC)
    with sessions.begin() as session:
        position = len(list(session.scalars(select(AIVideoScene.id).where(AIVideoScene.plan_id == plan_id))))
        scene = AIVideoScene(
            plan_id=plan_id, position=position, start_ms=0, end_ms=5000, narration="내레이션", caption="자막",
            source="ai", status="waiting",
        )
        session.add(scene)
        session.flush()
        session.add(VideoAIUsage(
            plan_id=plan_id, scene_id=scene.id, attempt=1, provider="higgsfield", model_path=PATH, seconds=5,
            estimated_cost=cost, currency=currency, status=status, created_at=created, updated_at=created,
        ))


def last_month() -> datetime:
    return month_start() - timedelta(days=1)


# --------------------------------------------------------------------------- settings: defaults and reads


def test_defaults_provider_off_not_approved_and_no_limits(sessions):
    current = read_settings(sessions)
    assert current == VideoAISettings()
    assert current.provider == "off" and not current.approved and current.approved_at is None
    assert current.monthly_limit == Decimal(0) and current.job_limit == Decimal(0)
    assert current.host == HOSTS[0] == "api.higgsfield.ai" and current.currency == "USD"
    assert (current.max_active, current.timeout_minutes, current.poll_seconds) == (2, 30, 10)
    assert set(PROVIDERS) == {"off", "higgsfield"}
    assert HOSTS == ("api.higgsfield.ai",)
    assert CURRENCIES == ("USD", "KRW")
    assert list_models(sessions) == []
    assert usage_this_month(sessions)["spent"] == Decimal(0)
    assert usage_this_month(sessions)["requests"] == 0


def test_read_settings_falls_back_to_safe_defaults_for_tampered_rows(sessions):
    tampered = {
        "provider": "evil", "host": "evil.example.com", "currency": "EUR", "monthly_limit": "-5",
        "job_limit": "1e9", "max_active": "9", "timeout_minutes": "abc", "poll_seconds": "4", "approved_at": "",
    }
    with sessions.begin() as session:
        for key, value in tampered.items():
            session.add(AppSetting(key=f"video_ai_{key}", value=value))
    assert read_settings(sessions) == VideoAISettings()


# --------------------------------------------------------------------------- settings: write validation


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"provider": "openai"}, MSG_PROVIDER),
        ({"provider": ""}, MSG_PROVIDER),
        ({"host": "evil.example.com"}, MSG_HOST),
        ({"host": "api.higgsfield.ai.evil.example"}, MSG_HOST),
        ({"currency": "EUR"}, MSG_CURRENCY),
        ({"currency": "usd"}, MSG_CURRENCY),
        ({"monthly_limit": "-1"}, MSG_MONEY_FORMAT),
        ({"monthly_limit": "abc"}, MSG_MONEY_FORMAT),
        ({"job_limit": "1.23456"}, MSG_MONEY_FORMAT),
        ({"job_limit": "1e3"}, MSG_MONEY_FORMAT),
        ({"monthly_limit": "10000001"}, "금액은 10000000 이하로 입력하세요."),
        ({"max_active": 0}, MSG_MAX_ACTIVE),
        ({"max_active": 5}, MSG_MAX_ACTIVE),
        ({"max_active": True}, MSG_MAX_ACTIVE),
        ({"max_active": "2"}, MSG_MAX_ACTIVE),
        ({"timeout_minutes": 4}, MSG_TIMEOUT),
        ({"timeout_minutes": 121}, MSG_TIMEOUT),
        ({"poll_seconds": 4}, MSG_POLL),
        ({"poll_seconds": 61}, MSG_POLL),
        ({"monthly_limit": "0"}, MSG_APPROVAL_LIMITS),
        ({"job_limit": ""}, MSG_APPROVAL_LIMITS),
        ({"monthly_limit": "", "job_limit": ""}, MSG_APPROVAL_LIMITS),
        ({"monthly_limit": "10", "job_limit": "20"}, MSG_JOB_OVER_MONTH),
        ({"approved": False, "monthly_limit": "10", "job_limit": "10.0001"}, MSG_JOB_OVER_MONTH),
    ],
)
def test_write_settings_rejects_invalid_values_and_stores_nothing(sessions, overrides, expected):
    # Historical parameter IDs retained. Blank speculative caps are valid settings,
    # while saving them does not plan/submit a paid video request.
    if expected == MSG_APPROVAL_LIMITS:
        saved = save_settings(sessions, **overrides)
        assert read_settings(sessions) == saved and saved.approved
        assert saved.monthly_limit == Decimal(overrides.get("monthly_limit", "100") or "0")
        assert saved.job_limit == Decimal(overrides.get("job_limit", "10") or "0")
        with sessions() as session:
            assert session.scalar(select(AIVideoPlan)) is None
            assert session.scalar(select(VideoAIUsage)) is None
        return
    with pytest.raises(VideoSettingsError) as excinfo:
        save_settings(sessions, **overrides)
    assert message(excinfo) == expected
    assert read_settings(sessions) == VideoAISettings()
    with sessions() as session:
        assert session.scalars(select(AppSetting).where(AppSetting.key.like("video_ai_%"))).all() == []


@pytest.mark.parametrize(
    ("max_active", "timeout_minutes", "poll_seconds"), [(1, 5, 5), (4, 120, 60)],
)
def test_write_settings_accepts_bounds(sessions, max_active, timeout_minutes, poll_seconds):
    saved = save_settings(
        sessions, max_active=max_active, timeout_minutes=timeout_minutes, poll_seconds=poll_seconds,
    )
    assert (saved.max_active, saved.timeout_minutes, saved.poll_seconds) == (max_active, timeout_minutes, poll_seconds)
    assert read_settings(sessions) == saved


def test_write_settings_normalizes_limits_and_round_trips(sessions):
    saved = save_settings(
        sessions, host=HOSTS[0], monthly_limit=" 1,000.5 ", job_limit="12.50", currency="KRW", max_active=3,
    )
    assert saved.provider == "higgsfield" and saved.host == "api.higgsfield.ai"
    assert saved.monthly_limit == Decimal("1000.5") and saved.job_limit == Decimal("12.5")
    assert saved.currency == "KRW" and saved.max_active == 3 and saved.approved
    with sessions() as session:
        stored = {row.key: row.value for row in session.scalars(select(AppSetting))}
    assert stored["video_ai_monthly_limit"] == "1000.5"
    assert stored["video_ai_job_limit"] == "12.5"
    assert stored["video_ai_provider"] == "higgsfield"
    assert read_settings(sessions) == saved


def test_job_limit_equal_to_monthly_limit_is_allowed(sessions):
    saved = save_settings(sessions, monthly_limit="10", job_limit="10")
    assert saved.job_limit == saved.monthly_limit == Decimal(10)


def test_off_provider_never_stores_an_approval(sessions):
    saved = save_settings(sessions, provider="off", approved=True, monthly_limit="", job_limit="")
    assert saved.provider == "off" and not saved.approved and saved.approved_at is None
    saved = save_settings(sessions, provider="off", approved=True)
    assert not saved.approved
    with sessions() as session:
        assert session.get(AppSetting, "video_ai_approved_at").value == ""


def test_approval_timestamp_kept_on_resave_and_cleared_when_unchecked_or_off(sessions, clock):
    first = save_settings(sessions)
    assert first.approved and first.approved_at == datetime(2026, 10, 15, 0, 1, tzinfo=UTC).isoformat()

    again = save_settings(sessions, monthly_limit="200", job_limit="20", host=HOSTS[0], poll_seconds=30)
    assert again.approved_at == first.approved_at
    assert again.monthly_limit == Decimal(200) and again.poll_seconds == 30

    unchecked = save_settings(sessions, approved=False)
    assert not unchecked.approved and unchecked.approved_at is None

    renewed = save_settings(sessions)
    assert renewed.approved and renewed.approved_at != first.approved_at
    assert datetime.fromisoformat(renewed.approved_at) > datetime.fromisoformat(first.approved_at)

    switched_off = save_settings(sessions, provider="off")
    assert switched_off.provider == "off" and not switched_off.approved and switched_off.approved_at is None
    back_on = save_settings(sessions)
    assert back_on.approved_at not in (first.approved_at, renewed.approved_at)


def test_currency_change_blocked_by_counted_usage_this_month(sessions):
    save_settings(sessions, currency="USD")
    plan = make_plan(sessions)
    add_usage(sessions, plan, "1.5", status="reserved")
    with pytest.raises(VideoSettingsError) as excinfo:
        save_settings(sessions, currency="KRW")
    assert message(excinfo) == MSG_CURRENCY_LOCKED
    assert read_settings(sessions).currency == "USD"
    # Re-saving with the same currency still works.
    assert save_settings(sessions, currency="USD", monthly_limit="50").monthly_limit == Decimal(50)


@pytest.mark.parametrize("status", sorted(COUNTED))
def test_every_counted_status_locks_the_currency(sessions, status):
    save_settings(sessions)
    add_usage(sessions, make_plan(sessions), "1", status=status)
    with pytest.raises(VideoSettingsError) as excinfo:
        save_settings(sessions, currency="KRW")
    assert message(excinfo) == MSG_CURRENCY_LOCKED


def test_currency_change_allowed_with_only_not_sent_or_last_month_usage(sessions):
    save_settings(sessions)
    plan = make_plan(sessions)
    add_usage(sessions, plan, "3", status="not_sent")
    add_usage(sessions, plan, "4", status="completed", created_at=last_month())
    assert save_settings(sessions, currency="KRW").currency == "KRW"


def test_currency_change_blocked_even_before_first_save(sessions):
    add_usage(sessions, make_plan(sessions), "1")
    with pytest.raises(VideoSettingsError) as excinfo:
        save_settings(sessions, currency="KRW")
    assert message(excinfo) == MSG_CURRENCY_LOCKED


# --------------------------------------------------------------------------- model catalog


@pytest.mark.parametrize(
    "path",
    [
        PATH,
        OTHER_PATH,
        "minimax/hailuo-2.3/standard/text-to-video",
        "a/b",
        "  vendor/model/text-to-video  ",
        "/".join(["seg"] * 7),
        "a" * 41 + "/model",
    ],
)
def test_validate_path_accepts_official_lowercase_paths(path):
    assert validate_path(path) == path.strip()


@pytest.mark.parametrize(
    "path",
    [
        "",
        "   ",
        "vendor",
        "Vendor/Model",
        "vendor/Model/text-to-video",
        "/vendor/model",
        "vendor/model/",
        "vendor//model",
        "vendor/../model",
        "vendor/a..b",
        "../etc/passwd",
        "https://evil.example/model",
        "vendor/model?x=1",
        "vendor/model#frag",
        "vendor/mo del",
        "vendor/mo\ndel",
        "vendor\\model",
        "-vendor/model",
        "vendor/.model",
        "/".join(["seg"] * 8),
        "a" * 42 + "/model",
        "/".join(["a" * 41] * 4),
        None,
    ],
)
def test_validate_path_rejects_everything_else(path):
    with pytest.raises(VideoSettingsError) as excinfo:
        validate_path(path)
    assert message(excinfo) == MSG_PATH


def test_save_model_stores_parsed_values_and_is_usable(sessions):
    entry = add_model(sessions, label="  합성 계약 모델  ", price_per_second="0.0512", durations="10, 5,5",
                      resolution="1080p")
    assert entry.provider == "higgsfield" and entry.path == PATH and entry.label == "합성 계약 모델"
    assert entry.price_per_second == Decimal("0.0512") and entry.durations == (5, 10)
    assert entry.resolution == "1080p" and entry.confirmed and entry.usable
    with sessions() as session:
        row = session.get(VideoAIModel, entry.id)
        assert (row.price_per_second, row.durations, row.label) == ("0.0512", "5,10", "합성 계약 모델")
        assert row.confirmed_at is not None and row.confirmed_at.tzinfo is not None
    assert list_models(sessions) == [entry]
    assert find_model(sessions, PATH) == entry
    assert find_model(sessions, OTHER_PATH) is None
    assert list_models(sessions, provider="other") == []


@pytest.mark.parametrize("resolution", RESOLUTIONS)
def test_every_listed_resolution_is_accepted(sessions, resolution):
    assert add_model(sessions, resolution=resolution).resolution == resolution


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"path": "Vendor/Model"}, MSG_PATH),
        ({"label": ""}, MSG_LABEL),
        ({"label": "    "}, MSG_LABEL),
        ({"label": "가" * 81}, MSG_LABEL),
        ({"label": "a\x01b"}, MSG_LABEL),
        ({"label": "a\tb"}, MSG_LABEL),
        ({"resolution": "4k"}, MSG_RESOLUTION),
        ({"resolution": "720P"}, MSG_RESOLUTION),
        ({"price_per_second": "0.05123"}, MSG_MONEY_FORMAT),
        ({"price_per_second": "-0.05"}, MSG_MONEY_FORMAT),
        ({"price_per_second": "abc"}, MSG_MONEY_FORMAT),
        ({"price_per_second": "1000.0001"}, "금액은 1000 이하로 입력하세요."),
        ({"durations": ""}, MSG_DURATIONS),
        ({"durations": "5.5"}, MSG_DURATIONS),
        ({"durations": "five"}, MSG_DURATIONS),
        ({"durations": "0"}, MSG_DURATION_RANGE),
        ({"durations": "5,31"}, MSG_DURATION_RANGE),
        ({"price_per_second": "", "confirmed": True}, MSG_CONFIRM_PRICE),
        ({"price_per_second": "0", "confirmed": True}, MSG_CONFIRM_PRICE),
        ({"price_per_second": "0.0000", "confirmed": True}, MSG_CONFIRM_PRICE),
    ],
)
def test_save_model_rejects_invalid_values(sessions, overrides, expected):
    if expected == MSG_CONFIRM_PRICE:
        entry = add_model(sessions, **overrides)
        assert entry.confirmed and not entry.usable
        assert entry.price_per_second == (None if overrides["price_per_second"] == "" else Decimal(0))
        assert list_models(sessions) == [entry]
        with sessions() as session:
            assert session.scalar(select(VideoAIUsage)) is None
        return
    with pytest.raises(VideoSettingsError) as excinfo:
        add_model(sessions, **overrides)
    assert message(excinfo) == expected
    assert list_models(sessions) == []


def test_label_limits(sessions):
    assert add_model(sessions, label="가" * 80).label == "가" * 80
    assert add_model(sessions, path=OTHER_PATH, label="x").label == "x"


@pytest.mark.parametrize("durations", ["²", "①", "5,²"])
def test_save_model_rejects_unicode_digit_durations_with_settings_error(sessions, durations):
    # str.isdigit() accepts superscripts and circled digits, but int() cannot parse them; the GUI
    # route catches only VideoSettingsError, so anything else becomes a 500.
    with pytest.raises(VideoSettingsError) as excinfo:
        add_model(sessions, durations=durations)
    assert message(excinfo) == MSG_DURATIONS
    assert list_models(sessions) == []


def test_unconfirmed_model_may_have_no_price_and_is_not_usable(sessions):
    entry = add_model(sessions, price_per_second="", confirmed=False)
    assert entry.price_per_second is None and not entry.confirmed and not entry.usable
    zero = add_model(sessions, path=OTHER_PATH, price_per_second="0", confirmed=False)
    assert zero.price_per_second == Decimal(0) and not zero.usable
    with sessions() as session:
        assert session.get(VideoAIModel, entry.id).price_per_second == ""
        assert session.get(VideoAIModel, entry.id).confirmed_at is None


@pytest.mark.parametrize(
    "change",
    [
        {"path": OTHER_PATH},
        {"price_per_second": "0.06"},
        {"durations": "5,10,15"},
        {"resolution": "1080p"},
    ],
)
def test_any_billing_change_redates_confirmation(sessions, clock, change):
    entry = add_model(sessions)
    first = confirmed_at(sessions, entry.id)
    assert first is not None
    updated = add_model(sessions, model_id=entry.id, **change)
    assert updated.confirmed and updated.id == entry.id
    assert confirmed_at(sessions, entry.id) > first


def test_label_or_equivalent_values_keep_confirmation_date(sessions, clock):
    entry = add_model(sessions, price_per_second="0.05", durations="5,10")
    first = confirmed_at(sessions, entry.id)
    same = add_model(
        sessions, model_id=entry.id, label="새 이름", price_per_second="0.0500", durations="10,5", path=f" {PATH} ",
    )
    assert same.label == "새 이름" and same.confirmed
    assert confirmed_at(sessions, entry.id) == first


def test_unchecking_clears_confirmation_and_rechecking_redates(sessions, clock):
    entry = add_model(sessions)
    first = confirmed_at(sessions, entry.id)
    cleared = add_model(sessions, model_id=entry.id, confirmed=False)
    assert not cleared.confirmed and not cleared.usable
    assert confirmed_at(sessions, entry.id) is None
    rechecked = add_model(sessions, model_id=entry.id, confirmed=True)
    assert rechecked.confirmed and confirmed_at(sessions, entry.id) > first


def test_duplicate_path_rejected_with_message_not_integrity_error(sessions):
    first = add_model(sessions)
    with pytest.raises(VideoSettingsError) as excinfo:
        add_model(sessions, label="duplicate")
    assert message(excinfo) == MSG_DUPLICATE
    second = add_model(sessions, path=OTHER_PATH)
    with pytest.raises(VideoSettingsError) as excinfo:
        add_model(sessions, model_id=second.id, path=PATH)
    assert message(excinfo) == MSG_DUPLICATE
    # Saving a model under its own path is not a clash.
    assert add_model(sessions, model_id=first.id, label="renamed").label == "renamed"
    assert [m.path for m in list_models(sessions)] == [PATH, OTHER_PATH]
    # The same path under another provider is a separate catalog.
    other = add_model(sessions, provider="other")
    assert other.provider == "other" and [m.path for m in list_models(sessions, "other")] == [PATH]


def test_model_limit_of_ten(sessions):
    assert MODEL_LIMIT == 10
    created = [add_model(sessions, path=f"vendor/model-{n}/text-to-video") for n in range(MODEL_LIMIT)]
    with pytest.raises(VideoSettingsError) as excinfo:
        add_model(sessions, path="vendor/model-extra/text-to-video")
    assert message(excinfo) == MSG_MODEL_LIMIT
    assert len(list_models(sessions)) == MODEL_LIMIT
    # Editing is still allowed at the limit; deleting frees a slot.
    assert add_model(sessions, model_id=created[-1].id, label="edited").label == "edited"
    delete_model(sessions, created[0].id)
    assert add_model(sessions, path="vendor/model-extra/text-to-video").path == "vendor/model-extra/text-to-video"
    # Another provider has its own limit.
    assert add_model(sessions, provider="other").provider == "other"


def test_delete_model_and_missing_models(sessions):
    entry = add_model(sessions)
    delete_model(sessions, entry.id)
    assert list_models(sessions) == [] and find_model(sessions, PATH) is None
    for call in (
        lambda: delete_model(sessions, entry.id),
        lambda: delete_model(sessions, 999),
        lambda: add_model(sessions, model_id=999),
    ):
        with pytest.raises(VideoSettingsError) as excinfo:
            call()
        assert message(excinfo) == MSG_NOT_FOUND
    kept = add_model(sessions)
    with pytest.raises(VideoSettingsError) as excinfo:
        delete_model(sessions, kept.id, provider="other")
    assert message(excinfo) == MSG_NOT_FOUND
    with pytest.raises(VideoSettingsError) as excinfo:
        add_model(sessions, model_id=kept.id, provider="other", path=OTHER_PATH)
    assert message(excinfo) == MSG_NOT_FOUND
    assert [m.id for m in list_models(sessions)] == [kept.id]


def test_tampered_catalog_row_is_listed_but_never_usable(sessions):
    entry = add_model(sessions)
    with sessions.begin() as session:
        row = session.get(VideoAIModel, entry.id)
        row.price_per_second, row.durations = "-1", "zero"
    listed = find_model(sessions, PATH)
    assert listed.price_per_second is None and listed.durations == (5,) and listed.confirmed
    assert not listed.usable


# --------------------------------------------------------------------------- usage, budget, readiness


def test_month_start_is_first_day_utc():
    start = month_start(datetime(2026, 10, 15, 23, 59, tzinfo=UTC))
    assert start == datetime(2026, 10, 1, tzinfo=UTC)
    assert month_start().day == 1 and month_start().tzinfo is UTC


def test_usage_this_month_counts_every_status_except_not_sent(sessions):
    assert set(COUNTED) == {"reserved", "submitted", "completed", "failed", "unknown", "canceled"}
    plan = make_plan(sessions)
    for status in COUNTED:
        add_usage(sessions, plan, "1.25", status=status)
    add_usage(sessions, plan, "100", status="not_sent")
    add_usage(sessions, plan, "100", status="completed", created_at=last_month())
    add_usage(sessions, plan, "broken", status="reserved")
    usage = usage_this_month(sessions)
    assert usage["spent"] == Decimal("7.5")
    assert usage["requests"] == len(COUNTED) + 1
    assert usage["since"] == month_start().date().isoformat()


def test_plan_spent_is_per_plan_and_ignores_not_sent(sessions):
    plan, other = make_plan(sessions), make_plan(sessions)
    add_usage(sessions, plan, "2", status="reserved")
    add_usage(sessions, plan, "3.5", status="failed")
    add_usage(sessions, plan, "1", status="completed", created_at=last_month())
    add_usage(sessions, plan, "50", status="not_sent")
    add_usage(sessions, other, "9", status="completed")
    with sessions() as session:
        assert plan_spent(session, plan) == Decimal("6.5")
        assert plan_spent(session, other) == Decimal(9)
        assert plan_spent(session, 999) == Decimal(0)


def limits(job: str = "10", monthly: str = "20", currency: str = "KRW") -> VideoAISettings:
    return VideoAISettings(
        provider="higgsfield", approved_at="2026-10-01T00:00:00+00:00", monthly_limit=Decimal(monthly),
        job_limit=Decimal(job), currency=currency,
    )


@pytest.mark.parametrize(("job", "monthly"), [("0", "20"), ("10", "0"), ("0", "0")])
def test_check_budget_requires_both_limits(sessions, job, monthly):
    plan = make_plan(sessions)
    with sessions() as session, pytest.raises(VideoSettingsError) as excinfo:
        check_budget(session, limits(job, monthly), plan, Decimal("0.01"))
    assert message(excinfo) == MSG_NO_LIMITS


def test_check_budget_job_limit_message_with_numbers(sessions):
    plan = make_plan(sessions)
    add_usage(sessions, plan, "8.5", currency="KRW")
    add_usage(sessions, plan, "100", status="not_sent", currency="KRW")
    with sessions() as session:
        check_budget(session, limits(), plan, Decimal("1.5"))  # exactly at the job limit is allowed
        with pytest.raises(VideoSettingsError) as excinfo:
            check_budget(session, limits(), plan, Decimal(2))
    assert message(excinfo) == (
        "작업별 한도를 넘습니다: 이 작업 사용 8.5 + 이번 요청 예상 2 > 한도 10 KRW. "
        "장면 수를 줄이거나 한도를 확인하세요."
    )


def test_check_budget_refuses_a_plan_whose_spend_is_in_another_currency(sessions):
    # Last month's USD spend on this plan cannot be added to a KRW job limit: the sums would mix units.
    plan = make_plan(sessions)
    add_usage(sessions, plan, "1", created_at=last_month(), currency="USD")
    with sessions() as session:
        assert plan_currency_mismatch(session, plan, "KRW")
        assert not plan_currency_mismatch(session, plan, "USD")
        with pytest.raises(VideoSettingsError) as excinfo:
            check_budget(session, limits(), plan, Decimal(1))
    assert message(excinfo) == CURRENCY_CHANGED
    other = make_plan(sessions)
    add_usage(sessions, other, "1", created_at=last_month(), currency="USD", status="not_sent")
    with sessions() as session:
        check_budget(session, limits(), other, Decimal(1))  # never-sent rows are not counted spend


def test_check_budget_monthly_message_with_numbers(sessions):
    plan, other = make_plan(sessions), make_plan(sessions)
    add_usage(sessions, other, "15")
    add_usage(sessions, other, "500", created_at=last_month())
    add_usage(sessions, other, "500", status="not_sent")
    with sessions() as session:
        check_budget(session, limits(), plan, Decimal(5))  # 15 + 5 == 20 is allowed
        with pytest.raises(VideoSettingsError) as excinfo:
            check_budget(session, limits(), plan, Decimal(6))
    assert message(excinfo) == "이번 달 AI 영상 한도를 넘습니다: 사용 15 + 이번 요청 예상 6 > 한도 20 KRW."


def test_check_budget_reports_job_limit_before_monthly_limit(sessions):
    plan = make_plan(sessions)
    add_usage(sessions, plan, "19.9999")
    with sessions() as session, pytest.raises(VideoSettingsError) as excinfo:
        check_budget(session, limits("20", "20", "USD"), plan, Decimal("0.0002"))
    assert message(excinfo).startswith("작업별 한도를 넘습니다: 이 작업 사용 19.9999 + 이번 요청 예상 0.0002")
    assert message(excinfo).endswith("> 한도 20 USD. 장면 수를 줄이거나 한도를 확인하세요.")


def test_readiness_lists_every_missing_condition_by_default(sessions, tmp_path):
    result = readiness(sessions, None)
    assert not result["ready"]
    assert result["reasons"] == [REASON_OFF, REASON_APPROVAL, REASON_LIMITS, REASON_KEY, REASON_MODEL]
    assert result["provider"] == "off" and result["key"] == {"configured": False}
    assert result["remaining"] == Decimal(0) and result["models"] == []
    store = VideoAIKeyStore(tmp_path / "keys", FakeCipher())
    assert readiness(sessions, store)["reasons"] == result["reasons"]


def test_readiness_ready_when_every_condition_holds(sessions, tmp_path):
    store = VideoAIKeyStore(tmp_path / "keys", FakeCipher())
    save_settings(sessions, monthly_limit="30", job_limit="10")
    add_model(sessions)
    assert readiness(sessions, store)["reasons"] == [REASON_KEY]
    store.save(VIDEO_KEY)
    add_usage(sessions, make_plan(sessions), "12.5")
    result = readiness(sessions, store)
    assert result["ready"] and result["reasons"] == []
    assert result["provider"] == "higgsfield" and result["key"]["configured"]
    assert result["remaining"] == Decimal("17.5") and result["usage"]["spent"] == Decimal("12.5")
    assert [m.path for m in result["models"]] == [PATH]


def test_readiness_each_condition_individually(sessions, tmp_path, monkeypatch):
    store = VideoAIKeyStore(tmp_path / "keys", FakeCipher())
    monkeypatch.setenv(VIDEO_ENV_NAME, VIDEO_KEY)
    save_settings(sessions, monthly_limit="20", job_limit="10")
    add_model(sessions, confirmed=False)
    assert readiness(sessions, store)["reasons"] == [REASON_MODEL]
    add_model(sessions, path=OTHER_PATH)
    assert readiness(sessions, store)["ready"]

    save_settings(sessions, approved=False)
    assert readiness(sessions, store)["reasons"] == [REASON_APPROVAL]
    save_settings(sessions, approved=False, monthly_limit="", job_limit="")
    assert readiness(sessions, store)["reasons"] == [REASON_APPROVAL, REASON_LIMITS]
    save_settings(sessions, provider="off", approved=False)
    assert readiness(sessions, store)["reasons"] == [REASON_OFF, REASON_APPROVAL]

    save_settings(sessions, monthly_limit="20", job_limit="10")
    add_usage(sessions, make_plan(sessions), "20")
    exhausted = readiness(sessions, store)
    assert exhausted["reasons"] == [REASON_EXHAUSTED] and exhausted["remaining"] == Decimal(0)

    monkeypatch.delenv(VIDEO_ENV_NAME)
    assert readiness(sessions, store)["reasons"] == [REASON_EXHAUSTED, REASON_KEY]


def test_provider_override_skips_provider_and_key_checks_only(sessions):
    assert readiness(sessions, None, provider_override="fake")["reasons"] == [
        REASON_APPROVAL, REASON_LIMITS, REASON_MODEL,
    ]
    save_settings(sessions)
    add_model(sessions)
    assert readiness(sessions, None)["reasons"] == [REASON_KEY]
    result = readiness(sessions, None, provider_override="fake")
    assert result["ready"] and result["reasons"] == [] and result["provider"] == "fake"


# --------------------------------------------------------------------------- costs


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("0", Decimal(0)),
        ("12.5", Decimal("12.5")),
        (" 7 ", Decimal(7)),
        ("1,234.5678", Decimal("1234.5678")),
        ("0.0001", Decimal("0.0001")),
        ("10000000", MAX_LIMIT),
        ("00012", Decimal(12)),
        ("１２.５", Decimal("12.5")),
    ],
)
def test_parse_money_accepts(raw, expected):
    assert parse_money(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["-1", "+1", "1e3", "1.", ".5", "1.23456", "123456789", "abc", "NaN", "Infinity", "1 000", "1..2", "0x10", "١٢٣٤٥٦٧٨٩"],
)
def test_parse_money_rejects_bad_formats(raw):
    with pytest.raises(CostError) as excinfo:
        parse_money(raw)
    assert message(excinfo) == MSG_MONEY_FORMAT


def test_parse_money_limits_and_blank_rules():
    with pytest.raises(CostError) as excinfo:
        parse_money("10000000.0001")
    assert message(excinfo) == "금액은 10000000 이하로 입력하세요."
    with pytest.raises(CostError) as excinfo:
        parse_money("1000.0001", maximum=MAX_PRICE_PER_SECOND)
    assert message(excinfo) == "금액은 1000 이하로 입력하세요."
    assert parse_money("1000", maximum=MAX_PRICE_PER_SECOND) == Decimal(1000)
    for blank in ("", "  ", None):
        with pytest.raises(CostError) as excinfo:
            parse_money(blank, blank=False)
        assert message(excinfo) == "금액을 입력하세요."
    assert issubclass(CostError, ValueError)


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal(10), "10"),
        (Decimal(0), "0"),
        (Decimal("100.5000"), "100.5"),
        (Decimal("1E+3"), "1000"),
        (Decimal("1.23455"), "1.2346"),
        (Decimal("1.23454"), "1.2345"),
        (Decimal("0.00005"), "0.0001"),
        (Decimal("0.00004"), "0"),
        (Decimal("12345678.9"), "12345678.9"),
        (Decimal("0.25"), "0.25"),
    ],
)
def test_money_formatting(amount, expected):
    assert money(amount) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("5,10", (5, 10)),
        ("10,5,5", (5, 10)),
        (" 5 , 10 ,", (5, 10)),
        ("1", (1,)),
        ("30", (30,)),
        ("1,2,3,4,5,6,7,8", (1, 2, 3, 4, 5, 6, 7, 8)),
        ("５,１０", (5, 10)),
    ],
)
def test_parse_durations_accepts(raw, expected):
    assert parse_durations(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", MSG_DURATIONS),
        (None, MSG_DURATIONS),
        (",,", MSG_DURATIONS),
        ("5.5", MSG_DURATIONS),
        ("-5", MSG_DURATIONS),
        ("a", MSG_DURATIONS),
        ("5;10", MSG_DURATIONS),
        ("1,2,3,4,5,6,7,8,9", MSG_DURATIONS),
        ("0", MSG_DURATION_RANGE),
        ("31", MSG_DURATION_RANGE),
        ("0,5", MSG_DURATION_RANGE),
        ("5,31", MSG_DURATION_RANGE),
    ],
)
def test_parse_durations_rejects(raw, expected):
    assert MAX_CLIP_SECONDS == 30
    with pytest.raises(CostError) as excinfo:
        parse_durations(raw)
    assert message(excinfo) == expected


@pytest.mark.parametrize("raw", ["²", "①", "5,²"])
def test_parse_durations_rejects_unicode_digits_with_cost_error(raw):
    with pytest.raises(CostError) as excinfo:
        parse_durations(raw)
    assert message(excinfo) == MSG_DURATIONS


@pytest.mark.parametrize(
    ("scene", "allowed", "expected"),
    [
        (4.2, (5, 10), 5),
        (5.0, (5, 10), 5),
        (5.0000000005, (5, 10), 5),
        (5.01, (5, 10), 10),
        (10, (5, 10), 10),
        (12, (5, 10), 10),
        (45, (5, 10), 10),
        (0, (5, 10), 5),
        (0.4, (1, 2), 1),
        (3, (5,), 5),
        (7, (4, 6, 8, 10), 8),
    ],
)
def test_clip_seconds_shortest_covering_or_longest(scene, allowed, expected):
    assert clip_seconds(scene, allowed) == expected


def test_scene_cost():
    assert scene_cost(5, Decimal("0.05")) == Decimal("0.25")
    assert scene_cost(10, Decimal("12.3456")) == Decimal("123.456")
    assert scene_cost(0, Decimal(3)) == Decimal(0)
    assert money(scene_cost(clip_seconds(6.5, (5, 10)), Decimal("0.0333"))) == "0.333"


# --------------------------------------------------------------------------- prompt policy


@pytest.mark.parametrize("prompt", ["", "   ", "\n\t \r\n", None, "　"])
def test_check_prompt_empty(prompt):
    with pytest.raises(PromptPolicyError) as excinfo:
        check_prompt(prompt)
    assert message(excinfo) == MSG_PROMPT_EMPTY


def test_check_prompt_length_limit_after_whitespace_collapse():
    assert PROMPT_MAX_CHARS == 600
    assert check_prompt("가" * 600) == "가" * 600
    with pytest.raises(PromptPolicyError) as excinfo:
        check_prompt("가" * 601)
    assert message(excinfo) == MSG_PROMPT_LONG
    assert check_prompt("추상" + " " * 2000 + "배경") == "추상 배경"


def test_check_prompt_collapses_whitespace_and_normalizes():
    assert check_prompt("  푸른\t추상\n\n배경  ") == "푸른 추상 배경"
    assert check_prompt("ＡＢＣ　그래픽") == "ABC 그래픽"


@pytest.mark.parametrize("char", ["\x00", "\x01", "\x07", "\x08", "\x0e", "\x1b"])
def test_check_prompt_rejects_control_characters(char):
    with pytest.raises(PromptPolicyError) as excinfo:
        check_prompt(f"추상 배경{char}그래픽")
    assert message(excinfo) == MSG_PROMPT_CONTROL


@pytest.mark.parametrize("char", ["\x7f", "\x80", "\x9b"])
def test_check_prompt_rejects_del_and_c1_control_characters(char):
    with pytest.raises(PromptPolicyError) as excinfo:
        check_prompt(f"추상 배경{char}그래픽")
    assert message(excinfo) == MSG_PROMPT_CONTROL


@pytest.mark.parametrize(
    "phrase",
    [
        # footage-like realism (Korean / English)
        "실제 영상", "실제 현장", "현장 영상", "보도 영상", "뉴스 영상", "뉴스 화면", "실사", "다큐멘터리 영상",
        "real footage", "news footage", "actual footage", "documentary footage", "raw footage",
        "photorealistic", "photo-realistic", "hyperrealistic", "hyper-realistic", "realistic footage",
        # recording devices and live material
        "cctv", "블랙박스", "몰래카메라", "보디캠", "바디캠", "목격 영상", "생중계", "속보 화면",
        "eyewitness", "bodycam", "body cam", "body-cam", "dashcam", "dash cam", "security camera", "surveillance",
        "live broadcast", "breaking news",
        # real-person likeness
        "딥페이크", "얼굴 합성", "실존 인물", "대통령", "총리", "deepfake", "face swap", "lookalike", "look-alike",
    ],
)
def test_check_prompt_blocks_each_phrase_family(phrase):
    with pytest.raises(PromptPolicyError) as excinfo:
        check_prompt(f"도시 배경에 {phrase} 느낌을 넣어 주세요")
    assert message(excinfo) == MSG_PROMPT_BLOCKED


def full_width(text: str) -> str:
    return "".join("　" if c == " " else chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in text)


@pytest.mark.parametrize(
    "prompt",
    [
        "REAL FOOTAGE of a city",
        "Photorealistic street",
        "DeepFake anchor",
        "CCTV view",
        "Breaking News style",
        full_width("CCTV") + " 화면",
        full_width("real footage"),
        full_width("body-cam") + " shot",
        "실제　영상",
        "실제   영상",
        "real\nfootage",
        "news\tfootage",
    ],
)
def test_check_prompt_blocking_is_case_insensitive_and_nfkc(prompt):
    with pytest.raises(PromptPolicyError) as excinfo:
        check_prompt(prompt)
    assert message(excinfo) == MSG_PROMPT_BLOCKED


def test_every_blocked_phrase_is_normalized_and_matches():
    for phrase in policy._BLOCKED:
        assert phrase == policy._normal(phrase).casefold(), phrase
        with pytest.raises(PromptPolicyError):
            check_prompt(f"abstract {phrase.upper()} background")


@pytest.mark.parametrize(
    "prompt",
    ["실제영상", "현장영상", "뉴스영상", "보도영상", "photo realistic", "deep fake", "face-swap"],
)
def test_check_prompt_blocks_spacing_and_hyphen_variants(prompt):
    with pytest.raises(PromptPolicyError) as excinfo:
        check_prompt(f"도시 배경 {prompt} 느낌")
    assert message(excinfo) == MSG_PROMPT_BLOCKED


@pytest.mark.parametrize(
    "prompt",
    [
        DEFAULT_PROMPT,
        "푸른 색조의 추상적인 데이터 흐름 모션 그래픽",
        "경제 지표를 상징하는 막대 그래프 일러스트",
        "Abstract flowing lines and soft gradients, minimal geometric shapes",
        "Stylized illustration of rising arrows over a pastel background",
        "도시의 밤을 상징하는 기하학적 빛의 패턴",
    ],
)
def test_check_prompt_allows_abstract_prompts(prompt):
    assert check_prompt(prompt) == prompt


def test_provider_prompt_appends_style_guard_exactly():
    assert STYLE_GUARD == (
        "Stylized abstract illustration for a news briefing background. "
        "Not photorealistic, not documentary or news footage, no real people, no faces, "
        "no real places or landmarks, no logos, no on-screen text."
    )
    assert provider_prompt("  푸른   추상 배경 ") == "푸른 추상 배경\n\n" + STYLE_GUARD
    assert provider_prompt(DEFAULT_PROMPT) == f"{DEFAULT_PROMPT}\n\n{STYLE_GUARD}"
    assert provider_prompt(DEFAULT_PROMPT).count(STYLE_GUARD) == 1
    with pytest.raises(PromptPolicyError) as excinfo:
        provider_prompt("real footage")
    assert message(excinfo) == MSG_PROMPT_BLOCKED
    with pytest.raises(PromptPolicyError) as excinfo:
        provider_prompt("")
    assert message(excinfo) == MSG_PROMPT_EMPTY


def test_labels_are_fixed_and_shared_with_the_engine():
    assert SCENE_LABEL == "AI 생성 장면 · 실제 현장 영상 아님"
    assert AI_SCENE_LABEL == SCENE_LABEL
    assert VIDEO_NOTICE == "이 영상의 일부 장면은 AI로 생성한 연출 화면이며 실제 사건 현장이 아닙니다."
    assert check_prompt(DEFAULT_PROMPT) == "뉴스 브리핑 배경용 추상 모션 그래픽"


# --------------------------------------------------------------------------- key store


@pytest.mark.parametrize(
    "key",
    [VIDEO_KEY, f"  {VIDEO_KEY}\n", "KEY_id-1.x:Secret_Value-2.y", "a" * 200 + ":" + "b" * 300,
     # the official app templates paste one key as copied from open.higgsfield.ai (printable ASCII)
     "hf_0123456789abcdef", "abcd1234secretvalue123", "a" * 520, "abcd:1234:secretvalue123/+="],
)
def test_video_key_pattern_accepts_key_id_and_secret(key):
    assert VideoAIKeyStore.validate(key) == key.strip()


@pytest.mark.parametrize(
    "key",
    [
        "",
        "short",
        "abc:def",
        "abcd 1234:secretvalue123",
        "abcd1234:secret value123",
        "abcd1234 :secretvalue123",
        "abcd1234:secretvalue123\nextra",
        "abcd1234:secret\tvalue123",
        "abcd1234:secretvalue123\x7f",
        "a" * 521,
        "키아이디1234:secretvalue123",
        "abcd1234:secretvalue\u00e9",
    ],
)
def test_video_key_pattern_rejects_bad_keys(key):
    with pytest.raises(CredentialError) as excinfo:
        VideoAIKeyStore.validate(key)
    assert message(excinfo) == MSG_VIDEO_KEY_FORMAT


def test_video_key_store_file_and_env_are_separate_from_openai_key(tmp_path, monkeypatch):
    data = tmp_path / "data"
    video = VideoAIKeyStore(data, FakeCipher())
    openai = AIKeyStore(data, FakeCipher())
    assert video.path == data / "video-ai-key.dpapi" and openai.path == data / "ai-key.dpapi"
    assert VIDEO_ENV_NAME == VideoAIKeyStore.ENV == "NEWSFLOW_VIDEO_AI_KEY"
    assert not video.status()["configured"] and not openai.status()["configured"]

    monkeypatch.setenv("NEWSFLOW_AI_API_KEY", OPENAI_KEY)
    assert not video.status()["configured"] and video.key() == ""
    monkeypatch.setenv(VIDEO_ENV_NAME, f" {VIDEO_KEY} ")
    status = video.status()
    assert status["configured"] and status["source"] == "environment" and not status["stored"]
    assert video.key() == VIDEO_KEY and openai.key() == OPENAI_KEY
    monkeypatch.delenv("NEWSFLOW_AI_API_KEY")
    assert openai.status()["source"] is None and video.status()["source"] == "environment"

    video.save(VIDEO_KEY.replace("abcd", "wxyz"))
    openai.save(OPENAI_KEY)
    assert sorted(p.name for p in data.iterdir()) == ["ai-key.dpapi", "video-ai-key.dpapi"]
    assert b"secretvalue123" not in video.path.read_bytes()
    assert video.status()["source"] == "stored"
    assert video.key() == "wxyz1234:secretvalue123"  # stored key wins over the environment
    assert openai.key() == OPENAI_KEY

    video.clear()
    assert not video.path.exists() and openai.path.is_file()
    assert video.key() == VIDEO_KEY  # back to the environment value
    assert openai.key() == OPENAI_KEY
    monkeypatch.delenv(VIDEO_ENV_NAME)
    assert not video.status()["configured"] and video.key() == ""


def test_video_key_store_rejects_malformed_key_and_keeps_no_temp_file(tmp_path):
    store = VideoAIKeyStore(tmp_path, FakeCipher())
    with pytest.raises(CredentialError) as excinfo:
        store.save("has space key value")
    assert message(excinfo) == MSG_VIDEO_KEY_FORMAT
    assert list(tmp_path.iterdir()) == []
    store.save(VIDEO_KEY)
    assert [p.name for p in tmp_path.iterdir()] == ["video-ai-key.dpapi"]
    with pytest.raises(CredentialError):
        VideoAIKeyStore(tmp_path, FakeCipher(fail=True)).key()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has a real DPAPI cipher")
def test_video_key_store_fails_closed_without_dpapi(tmp_path):
    store = VideoAIKeyStore(tmp_path)
    assert not store.status()["storage_supported"]
    with pytest.raises(CredentialError) as excinfo:
        store.save(VIDEO_KEY)
    assert message(excinfo) == "키 저장은 Windows 계정 보호 저장소(DPAPI)가 있는 Windows에서만 지원합니다."
    assert list(tmp_path.iterdir()) == []


class EntropyBoundCipher:
    """Test cipher that, like DPAPI, refuses to unprotect with a different entropy."""

    def __init__(self) -> None:
        self.seen: list[bytes] = []

    def protect(self, payload: bytearray, entropy: bytearray) -> bytearray:
        self.seen.append(bytes(entropy))
        return bytearray(b"EB" + bytes(entropy) + bytes(b ^ 0x33 for b in payload))

    def unprotect(self, payload: bytearray, entropy: bytearray) -> bytearray:
        self.seen.append(bytes(entropy))
        if bytes(payload[2:34]) != bytes(entropy):
            raise CredentialError("저장된 키를 읽지 못했습니다. 키를 다시 저장하세요.")
        return bytearray(b ^ 0x33 for b in payload[34:])


def test_entropy_differs_and_openai_entropy_is_unchanged(tmp_path):
    assert VideoAIKeyStore.ENTROPY == b"NewsFlowAI:Phase5D:video-ai-key"
    assert AIKeyStore.ENTROPY == b"NewsFlowAI:Phase5C:ai-api-key"
    assert VideoAIKeyStore.ENTROPY != AIKeyStore.ENTROPY
    # Existing Phase 5C key files must still decrypt: the default entropy is unchanged.
    legacy = bytearray(hashlib.sha256(b"NewsFlowAI:Phase5C:ai-api-key").digest())
    assert _entropy() == legacy == _entropy(AIKeyStore.ENTROPY)
    assert _entropy(VideoAIKeyStore.ENTROPY) != legacy

    cipher = EntropyBoundCipher()
    video, openai = VideoAIKeyStore(tmp_path, cipher), AIKeyStore(tmp_path, cipher)
    video.save(VIDEO_KEY)
    openai.save(OPENAI_KEY)
    assert cipher.seen == [bytes(_entropy(VideoAIKeyStore.ENTROPY)), bytes(legacy)]
    assert video.key() == VIDEO_KEY and openai.key() == OPENAI_KEY

    # A file protected for one store cannot be read by the other.
    openai.path.write_bytes(video.path.read_bytes())
    with pytest.raises(CredentialError):
        openai.key()


def test_openai_key_store_behavior_unchanged(tmp_path):
    assert AIKeyStore.FILE == "ai-key.dpapi" and AIKeyStore.ENV == "NEWSFLOW_AI_API_KEY"
    assert AIKeyStore.FORMAT_MESSAGE == MSG_AI_KEY_FORMAT
    assert AIKeyStore.validate(f" {OPENAI_KEY} ") == OPENAI_KEY
    with pytest.raises(CredentialError) as excinfo:
        AIKeyStore.validate("short-key")
    assert message(excinfo) == MSG_AI_KEY_FORMAT
    with pytest.raises(CredentialError) as excinfo:
        AIKeyStore.validate("sk-synthetic not-a-real-key-0123456789")
    assert message(excinfo) == MSG_AI_KEY_FORMAT
    store = AIKeyStore(tmp_path, FakeCipher())
    store.save(OPENAI_KEY)
    assert store.path.name == "ai-key.dpapi" and store.key() == OPENAI_KEY
    assert not (tmp_path / "video-ai-key.dpapi").exists()


# --------------------------------------------------------------------------- migration 0010

NEW_TABLES = {"video_ai_models", "ai_video_plans", "ai_video_scenes", "video_ai_usage"}
NEW_COLUMNS = {("video_projects", "ai_plan_id"), ("video_scenes", "clip_name"), ("video_scenes", "ai_generated")}


def alembic_config(connection=None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS).replace("%", "%%"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def run_alembic(engine, action: str, revision: str) -> None:
    with engine.begin() as connection:
        getattr(command, action)(alembic_config(connection), revision)


def version(engine) -> str:
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def schema(engine) -> tuple[set[str], set[tuple[str, str]]]:
    with engine.connect() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        columns = {(table, column["name"]) for table in tables for column in inspector.get_columns(table)}
    return tables, columns


def seed_video(engine, *, render_job: bool) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO intelligence_runs (id, kind, status, provider, options, evidence, result, message, created_at)"
            " VALUES (1, 'generate', 'success', 'offline', '{}', '{}', '{}', '', '2026-10-01 00:00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO content_drafts (id, run_id, duration, content, sources, revision, review_status,"
            " created_at, updated_at) VALUES (1, 1, 30, '{}', '{}', 1, 'approved', '2026-10-01 00:00:00',"
            " '2026-10-01 00:00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO video_projects (id, draft_id, title, duration, snapshot, sources, created_at, preview_only)"
            " VALUES (1, 1, 't', 30, '{}', '{}', '2026-10-01 00:00:00', 0)"
        )
        connection.exec_driver_sql(
            "INSERT INTO video_scenes (project_id, position, start_ms, end_ms, narration, caption, material)"
            " VALUES (1, 0, 0, 10000, '내레이션', '자막', ''), (1, 1, 10000, 20000, '둘째', '자막', '')"
        )
        if render_job:
            connection.exec_driver_sql(
                "INSERT INTO render_jobs (project_id, status, progress, output_name, message, metadata_json,"
                " created_at) VALUES (1, 'success', 100, 'out.mp4', '', '{}', '2026-10-01 00:00:00')"
            )


def counts(engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: connection.scalar(text(f"SELECT count(*) FROM {table}"))
            for table in ("video_projects", "video_scenes", "render_jobs")
        }


def test_migration_head_is_0015_and_retains_ai_tables_and_columns(engine):
    assert ScriptDirectory.from_config(alembic_config()).get_current_head() == "0018"
    assert version(engine) == "0018"
    tables, columns = schema(engine)
    assert NEW_TABLES <= tables
    assert NEW_COLUMNS <= columns
    with engine.connect() as connection:
        inspector = inspect(connection)
        assert "ix_video_ai_usage_created_at" in {i["name"] for i in inspector.get_indexes("video_ai_usage")}
        uniques = {tuple(u["column_names"]) for u in inspector.get_unique_constraints("video_ai_models")}
        assert ("provider", "path") in uniques
        uniques = {tuple(u["column_names"]) for u in inspector.get_unique_constraints("video_ai_usage")}
        assert ("scene_id", "attempt") in uniques
    # The ORM models and the migration agree column by column.
    for model in (VideoAIModel, AIVideoPlan, AIVideoScene, VideoAIUsage):
        table = model.__table__.name
        assert {c.name for c in model.__table__.columns} == {c for t, c in columns if t == table}, table


def test_migration_defaults_for_existing_video_rows(engine):
    seed_video(engine, render_job=False)
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT clip_name, ai_generated FROM video_scenes")).all()
        project = connection.scalar(text("SELECT ai_plan_id FROM video_projects"))
    assert rows == [(None, 0), (None, 0)] and project is None


def test_downgrade_to_0009_and_upgrade_again(engine):
    run_alembic(engine, "downgrade", "0009")
    assert version(engine) == "0009"
    tables, columns = schema(engine)
    assert not NEW_TABLES & tables
    assert not NEW_COLUMNS & columns
    assert {"ai_usage", "video_projects", "video_scenes"} <= tables
    assert not any(t.startswith("_alembic_tmp") for t in tables)

    run_alembic(engine, "upgrade", "head")
    assert version(engine) == "0018"
    tables, columns = schema(engine)
    assert NEW_TABLES <= tables and NEW_COLUMNS <= columns
    db_session.migrate(engine)  # repeat is a no-op
    assert version(engine) == "0018"


def test_settings_work_after_downgrade_and_upgrade(engine):
    run_alembic(engine, "downgrade", "0009")
    run_alembic(engine, "upgrade", "head")
    sessions = db_session.session_factory(engine)
    assert save_settings(sessions).approved
    assert add_model(sessions).usable


def test_downgrade_0010_keeps_existing_video_scenes(engine):
    seed_video(engine, render_job=False)
    run_alembic(engine, "downgrade", "0009")
    assert version(engine) == "0009"
    assert counts(engine) == {"video_projects": 1, "video_scenes": 2, "render_jobs": 0}


def test_downgrade_0010_with_a_rendered_video_succeeds_and_keeps_rows(engine):
    seed_video(engine, render_job=True)
    run_alembic(engine, "downgrade", "0009")
    assert version(engine) == "0009"
    assert counts(engine) == {"video_projects": 1, "video_scenes": 2, "render_jobs": 1}
    tables, _ = schema(engine)
    assert not any(t.startswith("_alembic_tmp") for t in tables)


@pytest.mark.parametrize("prompt", [
    "https://example.com 같은 화면", "www.example.com 배경", "contact me@example.com", "news.example.kr 로고",
    "실\u200b제 영상", "real⁠footage",
])
def test_check_prompt_rejects_addresses_and_hidden_format_characters(prompt):
    with pytest.raises(PromptPolicyError):
        check_prompt(prompt)


def test_changing_the_currency_clears_every_model_confirmation(sessions):
    save_settings(sessions, currency="USD")
    model = save_model(sessions, path="vendor/model/text-to-video", label="모델", price_per_second="0.1",
                       durations="5", resolution="720p", confirmed=True)
    assert next(m for m in list_models(sessions) if m.id == model.id).usable
    save_settings(sessions, currency="KRW")
    assert not next(m for m in list_models(sessions) if m.id == model.id).usable
    save_model(sessions, path="vendor/model/text-to-video", label="모델", price_per_second="140", durations="5",
               resolution="720p", confirmed=True, model_id=model.id)
    save_settings(sessions, currency="KRW")  # same currency: confirmations stay
    assert next(m for m in list_models(sessions) if m.id == model.id).usable


def test_a_database_stamped_with_the_published_0010_gets_the_0011_reservation_columns(engine):
    """0010 shipped on the branch before these columns existed; 0011 must add them, not an edited 0010."""
    run_alembic(engine, "downgrade", "0010")
    _tables, columns = schema(engine)
    assert ("video_ai_usage", "resolution") not in columns and ("video_ai_usage", "approval") not in columns
    db_session.migrate(engine)
    assert version(engine) == "0018"
    _tables, columns = schema(engine)
    assert {("video_ai_usage", "resolution"), ("video_ai_usage", "approval")} <= columns



def test_0011_upgrades_a_0010_that_already_has_the_resolution_column(engine):
    """A development build (65a470c) created video_ai_usage.resolution inside 0010."""
    run_alembic(engine, "downgrade", "0010")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE video_ai_usage ADD COLUMN resolution VARCHAR(10) DEFAULT '' NOT NULL")
    db_session.migrate(engine)
    assert version(engine) == "0018"
    _tables, columns = schema(engine)
    assert {("video_ai_usage", "resolution"), ("video_ai_usage", "approval")} <= columns


def test_step13_incompatible_legacy_model_still_rejected(sessions):
    with pytest.raises(VideoSettingsError):
        add_model(sessions, path="kling-video/v2.6/pro/text-to-video")
    assert list_models(sessions) == []
