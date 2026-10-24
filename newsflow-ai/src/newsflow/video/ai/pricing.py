"""Explicit, estimate-only model registration. Never touches generation or usage ledgers.

Official source (2026-10-22): docs.higgsfield.ai/docs/concepts/billing-and-retention.
Use the four fields the existing adapter sends, with a fixed non-news example prompt.
All registered durations are quoted once. A ceiling rate covers every quoted duration;
this is a conservative estimate conversion, not a guarantee of a later supplier bill.
"""
from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
from threading import Lock

from sqlalchemy import select

from newsflow.db.models import VideoAIModel, utcnow

from .contracts import ClipRequest
from .higgsfield import HiggsfieldProvider
from .model_contracts import check_model_contract
from .settings import (
    MODEL_LIMIT,
    VideoSettingsError,
    model_version,
    read_settings,
    save_model,
    validate_model_fields,
)

PRICE_PROMPT = "An abstract blue geometric background with gentle camera movement."


class ModelPricingService:
    def __init__(self, sessions, keys, *, requester=None):
        self.sessions, self.keys, self.requester = sessions, keys, requester
        self.guard = Lock()

    def register(self, *, path, label, durations, resolution, consent, model_id=None):
        if not consent:
            raise VideoSettingsError("공식 견적 조회를 승인해 주세요. 영상 생성 승인은 별개입니다.")
        path, label, allowed = validate_model_fields(path, label, durations, resolution)
        if check_model_contract(path, allowed, resolution)[0] != "PASS":
            raise VideoSettingsError("자동 견적을 지원하는 공식 모델·길이·해상도를 선택하세요. 기존 수동 설정은 유지됩니다.")
        settings = read_settings(self.sessions)
        if settings.currency != "USD":
            raise VideoSettingsError("공식 견적은 USD입니다. KRW로 자동 환산하지 않습니다. 기존 통화와 가격은 유지됩니다.")
        with self.sessions() as session:
            rows = list(session.scalars(select(VideoAIModel).where(VideoAIModel.provider == "higgsfield")))
            existing = next((row for row in rows if row.id == model_id), None)
            if model_id is not None and existing is None:
                raise VideoSettingsError("모델을 찾지 못했습니다.")
            if any(row.path == path and row.id != model_id for row in rows):
                raise VideoSettingsError("이미 등록된 모델 경로입니다.")
            if model_id is None and len(rows) >= MODEL_LIMIT:
                raise VideoSettingsError(f"모델은 최대 {MODEL_LIMIT}개까지 등록할 수 있습니다.")
            version = model_version(existing) if existing is not None else None
        if not self.keys.status().get("configured"):
            raise VideoSettingsError("Higgsfield API 키를 먼저 등록하세요. 키는 화면에 입력하지 않습니다.")
        if not self.guard.acquire(blocking=False):
            raise VideoSettingsError("견적 조회가 진행 중입니다. 다시 보내지 말고 완료 후 상태를 확인하세요.")
        try:
            try:
                credential = self.keys.key()
            except Exception:  # noqa: BLE001 - credential error details are private
                raise VideoSettingsError("저장된 Higgsfield 키를 읽을 수 없습니다. 키 설정을 확인하세요.") from None
            provider = HiggsfieldProvider(lambda: credential, host=settings.host, timeout=15, requester=self.requester)
            prices = []
            for seconds in allowed:
                try:
                    total = provider.estimate_usd(ClipRequest(path, PRICE_PROMPT, seconds, resolution))
                except Exception:  # noqa: BLE001 - never expose supplier text, keys or response bodies
                    raise VideoSettingsError(
                        "공식 견적을 확인하지 못했습니다. 기존 모델·가격을 유지했고 자동 재시도하지 않았습니다."
                    ) from None
                prices.append((seconds, total))
            rate = max(total / seconds for seconds, total in prices).quantize(Decimal("0.0001"), rounding=ROUND_CEILING)
            price_text = format(rate, "f").rstrip("0").rstrip(".")
            quote = {
                "source": "higgsfield_estimate", "checked_at": utcnow().isoformat(), "currency": "USD",
                "path": path, "resolution": resolution, "aspect_ratio": "9:16",
                "durations": ",".join(map(str, allowed)), "unit_price": price_text,
                "rate_kind": "ceiling_per_second", "prompt_kind": "fixed_abstract_example",
                "amounts": [{"seconds": seconds, "usd": format(total, "f")} for seconds, total in prices],
            }
            try:
                same_key = self.keys.key() == credential
            except Exception:  # noqa: BLE001 - do not expose key-store internals
                same_key = False
            if not same_key:
                raise VideoSettingsError("견적 조회 중 키가 바뀌었습니다. 기존 가격을 유지했습니다. 새로고침해 확인하세요.")
            return save_model(
                self.sessions, path=path, label=label, price_per_second=price_text, durations=quote["durations"],
                resolution=resolution, confirmed=True, model_id=model_id, official_quote=quote,
                expected_version=version, expected_currency="USD",
            )
        finally:
            self.guard.release()
