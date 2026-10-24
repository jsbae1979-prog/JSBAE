"""Opt-in, non-secret shortform composition policy, frozen into each new draft."""
import json
import math
from dataclasses import asdict, dataclass

from newsflow.db.models import AppSetting

KEY = "shortform_profile_v1"


@dataclass(frozen=True)
class Shortform:
    enabled: bool = False
    hook: bool = True
    captions: bool = True
    motion: bool = True
    source: bool = True
    tight_ending: bool = True
    speed: float = 1.1
    target_seconds: int = 30

    def __post_init__(self):
        if any(type(getattr(self, k)) is not bool for k in (
            "enabled", "hook", "captions", "motion", "source", "tight_ending"
        )):
            raise ValueError("숏폼 옵션을 확인하세요.")
        if (type(self.target_seconds) is not int or not 15 <= self.target_seconds <= 35
                or type(self.speed) not in (int, float) or not math.isfinite(self.speed)
                or not 1 <= self.speed <= 1.2):
            raise ValueError("숏폼 길이(15~35초)·속도(1.0~1.2배)를 확인하세요.")


def read(sessions) -> Shortform:
    with sessions() as session:
        row = session.get(AppSetting, KEY)
        return Shortform(**json.loads(row.value)) if row else Shortform()


def save(sessions, value: Shortform) -> None:
    with sessions.begin() as session:
        session.merge(AppSetting(key=KEY, value=json.dumps(asdict(value))))


def frozen(evidence: dict) -> Shortform:
    return Shortform(**evidence.get("shortform", {}))


def allowed_duration(duration: int, enabled: bool = False) -> bool:
    return type(duration) is int and (duration in (30, 45, 60) or enabled and 15 <= duration <= 35)


def choices(enabled: bool, target: int = 30) -> list[int]:
    return sorted({15, 20, 25, 30, 35, target, 45, 60}) if enabled else [30, 45, 60]


def instruction(profile: Shortform) -> dict:
    return {
        **asdict(profile),
        "structure": "한 이슈만 3~4장면·3~4문장. STANDARD는 도입→배경→핵심→마무리, QUICK은 핵심 위주.",
        "hook_rule": ("첫 내레이션=hook, 15~25자 한 문장, 첫 장면 1~3초. 자료에 있는 결론·수치만 사용. "
                      "새 수치·미래 단정·과장·최신성 주장을 만들지 마세요." if profile.hook else "기존 도입 규칙 유지."),
        "ending_rule": "짧은 핵심 정리로 끝내고 구독 요청·반복 출처 확인 문장은 넣지 마세요.",
        "timing": "합계는 선택한 목표 길이. 음성은 저장된 속도에 추가로 speed배 적용 예정. 최종 길이는 실제 음성 측정.",
        "review": "자동 검사는 사실 검증이 아니며 대본·최종 영상은 사람 검토 필수. 도구·추가 검색 사용 금지.",
    }


def validate_script(content: dict, evidence: dict) -> None:
    profile = frozen(evidence)
    if not profile.enabled:
        return
    scenes = content["scenes"]
    if not 3 <= len(scenes) <= 4 or not 15 <= sum(s["seconds"] for s in scenes) <= 35:
        raise ValueError("숏폼은 한 이슈·3~4장면·15~35초로 구성하세요.")
    if profile.hook and (not 15 <= len(content["hook"].strip()) <= 25
                         or content["hook"].strip() != scenes[0]["narration"].strip()
                         or scenes[0]["seconds"] > 3):
        raise ValueError("첫 장면은 3초 이내, 훅과 같은 15~25자 내레이션으로 검토하세요.")
