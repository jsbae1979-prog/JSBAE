"""Versioned, local model contracts. No discovery, credentials, approval or invoice claims."""
import hashlib
import json
from copy import deepcopy

from newsflow.character.higgsfield_client import MODEL as CHARACTER_MODEL
from newsflow.db.models import AppSetting
from newsflow.intelligence.api_providers import API_MODELS
from newsflow.publishing.image_generation import MODEL as IMAGE_MODEL

IMAGE_MODELS = (IMAGE_MODEL, "gpt-image-2.5-sunburst-2026-09-08")
IMAGE_SIZES = {"1024x1280": "4:5 · 피드", "1024x1024": "1:1 · 정사각형",
               "1024x1536": "2:3 · 세로", "1536x1024": "3:2 · 가로", "864x1536": "9:16 · 영상"}
IMAGE_QUALITIES = {"low": "초안", "medium": "표준 · 추천", "high": "고품질"}
IMAGE_DOC = "https://developers.openai.com/api/reference/resources/images/methods/generate"
CHARACTER_DOC = "https://open.higgsfield.ai/models/bytedance/seedance-2.0/reference-to-video/api-reference"
DEFAULTS = {
    "image": {"provider": "openai", "model": IMAGE_MODEL, "size": "1024x1280", "quality": "medium"},
    "character": {"script_provider": "claude_api", "script_model": "claude-sonnet-4-6",
                  "video_provider": "higgsfield", "video_model": CHARACTER_MODEL,
                  "resolution": "720p", "aspect_ratio": "9:16", "credential_source": "user_store"},
}

class SelectionError(ValueError):
    pass


def validate(mode, value):
    if mode not in DEFAULTS or not isinstance(value, dict) or set(value) != set(DEFAULTS[mode]):
        raise SelectionError("제작 모드의 설정 항목을 확인하세요.")
    value = deepcopy(value)
    if mode == "image":
        valid = (value["provider"] == "openai" and value["model"] in IMAGE_MODELS
                 and value["size"] in IMAGE_SIZES and value["quality"] in IMAGE_QUALITIES)
    else:
        valid = (value["script_provider"] == "claude_api" and value["script_model"] in API_MODELS["claude_api"]
                 and value["video_provider"] == "higgsfield" and value["video_model"] == CHARACTER_MODEL
                 and value["resolution"] == "720p" and value["aspect_ratio"] == "9:16"
                 and value["credential_source"] in {"user_store", "legacy_env"})
    if not valid:
        raise SelectionError("현재 Adapter에서 지원하는 모델·입력·출력 조합을 선택하세요.")
    return value


def read_defaults(sessions, mode):
    if mode not in DEFAULTS:
        raise SelectionError("제작 모드를 확인하세요.")
    with sessions() as session:
        row = session.get(AppSetting, "creation_" + mode + "_defaults")
        if not row:
            return deepcopy(DEFAULTS[mode])
        try:
            return validate(mode, json.loads(row.value))
        except (ValueError, TypeError):
            raise SelectionError("저장된 제작 설정을 확인하세요. 다른 기본값으로 대체하지 않습니다.") from None


def save_defaults(sessions, mode, value):
    value = validate(mode, value)
    with sessions.begin() as session:
        key = "creation_" + mode + "_defaults"
        row = session.get(AppSetting, key)
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if row:
            row.value = text
        else:
            session.add(AppSetting(key=key, value=text))
    return value


def snapshot(mode, value):
    result = {"version": 1, "mode": mode, **validate(mode, value),
              "contract_checked_on": "2026-10-26", "account_verified": False,
              "price_basis": {"amount": None, "currency": "USD", "status": "not_quoted",
                              "note": "실제 사용량·공식 견적 확인 전 총액 미확정. 실제 청구액과 구분합니다."}}
    result["fingerprint"] = fingerprint(result)
    return result


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def check_snapshot(value, mode):
    try:
        if value["version"] != 1 or value["mode"] != mode:
            raise ValueError
        supplied = value["fingerprint"]
        body = {k: v for k, v in value.items() if k != "fingerprint"}
        if fingerprint(body) != supplied:
            raise ValueError
        return validate(mode, {k: value[k] for k in DEFAULTS[mode]})
    except (KeyError, TypeError, ValueError):
        raise SelectionError("작업에 고정된 모델 설정이 변경됐습니다. 새 작업에서 확인하세요.") from None


def news_video_default(sessions):
    from newsflow.video.ai.production import DEFAULT_MODEL
    with sessions() as session:
        row = session.get(AppSetting, 'creation_news_video_model')
        return row.value if row else DEFAULT_MODEL


def save_news_video_default(sessions, model_path):
    from newsflow.video.ai.production import model_ready
    from newsflow.video.ai.settings import find_model
    if not model_ready(find_model(sessions, model_path)):
        raise SelectionError('공식 입력 규격이 확인된 뉴스 영상 모델을 등록하세요. 계정 사용 가능 여부는 미검증입니다.')
    with sessions.begin() as session:
        row = session.get(AppSetting, 'creation_news_video_model')
        if row:
            row.value = model_path
        else:
            session.add(AppSetting(key='creation_news_video_model', value=model_path))
