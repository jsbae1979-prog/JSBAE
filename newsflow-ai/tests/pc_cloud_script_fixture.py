"""Grounded synthetic V2 fixture for media orchestration, not editorial quality evidence."""
from newsflow.intelligence.korean import speech_plan


def healthy_three_scene(result, seconds):
    assert seconds == 30
    result["hook"] = "합성 예시로 뉴스 검토 과정을 살펴볼까요?"
    result["closing"] = "함께 확인할 분에게 이 내용을 공유해 주세요."
    narrations = [
        result["hook"] + " 합성 자료에 담긴 내용과 출처를 구분하는 과정입니다.",
        "기사의 표현만으로 사실을 단정하기보다 제공된 자료에서 확인할 수 있는 내용과 한계를 함께 읽는 관점이 필요합니다.",
        "자료를 볼 때는 출처와 확인할 내용을 구분해 보세요. " + result["closing"],
    ]
    assert len(result["scenes"]) == 3
    for scene, role, narration in zip(result["scenes"], ("fact", "meaning", "action"), narrations):
        scene.update(role=role, narration=narration, caption="합성 예시 · 자료와 출처 확인")
    timing = speech_plan(result, seconds)
    assert timing["fits"] and timing["estimated_total_seconds"] >= seconds * .90
    return result
