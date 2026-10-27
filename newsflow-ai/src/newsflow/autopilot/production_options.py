"""Non-secret, immutable choices for one explicitly started production."""

import re
from copy import deepcopy

from .contracts import AutopilotError


def freeze_options(value: dict, voice: str | None) -> dict:
    if (not isinstance(value, dict) or type(value.get("version")) is not int or value.get("version") not in {1, 2}
            or type(value.get("script_review")) is not bool
            or value.get("video_provider") not in {"off", "higgsfield"}
            or not voice):
        raise AutopilotError("이번 제작의 검토·음성·영상 선택을 확인하세요.")
    result = {"version": value["version"], "script_review": value["script_review"],
              "video_provider": value["video_provider"], "voice": voice,
              "external_tts_consent": value.get("external_tts_consent") is True}
    if value["version"] == 2:
        from newsflow.video.tts import SpeechSettings, TTSError

        try:
            speech = SpeechSettings(**value["speech"])
        except (KeyError, TypeError, TTSError):
            raise AutopilotError("이번 제작의 음성 속도·쉼 설정을 확인하세요.") from None
        if value.get("font_size") not in {40, 48, 56} or value.get("subtitle_y") not in {1280, 1420}:
            raise AutopilotError("이번 제작의 자막 설정을 확인하세요.")
        result.update(speech={"rate": speech.rate, "pause_ms": speech.pause_ms},
                      font_size=value["font_size"], subtitle_y=value["subtitle_y"])
    if voice == "elevenlabs":
        from newsflow.video.elevenlabs_tts import MODELS

        config = value.get("elevenlabs", {})
        if (not isinstance(config, dict) or not result["external_tts_consent"] or config.get("enabled") is not True
                or not config.get("voice_id") or config.get("model") not in MODELS):
            raise AutopilotError("ElevenLabs 설정과 이번 음성 제작의 별도 동의가 필요합니다.")
        keys = ("enabled", "voice_id", "model", "job_limit", "monthly_limit", "commercial")
        if any(key not in config for key in keys):
            raise AutopilotError("ElevenLabs 저장 설정을 다시 확인하세요.")
        if (not isinstance(config["voice_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", config["voice_id"])
                or type(config["commercial"]) is not bool or type(config["job_limit"]) is not int
                or type(config["monthly_limit"]) is not int
                or not 1 <= config["job_limit"] <= 10000
                or not config["job_limit"] <= config["monthly_limit"] <= 1000000):
            raise AutopilotError("ElevenLabs 저장 설정을 다시 확인하세요.")
        result["elevenlabs"] = {key: deepcopy(config[key]) for key in keys}
        if value["version"] == 2:
            fingerprint = config.get("credential_fingerprint")
            if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                raise AutopilotError("이번 작업의 음성 계정 설정을 다시 확인하세요.")
            result["elevenlabs"]["credential_fingerprint"] = fingerprint
    return result
