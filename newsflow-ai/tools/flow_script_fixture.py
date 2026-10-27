"""Bounded 30-second synthetic news-review narration, not a production fallback."""
from copy import deepcopy


def valid_script(original):
    result = deepcopy(original)
    result['hook'] = '뉴스를 그대로 믿어도 될까요?'
    result['closing'] = '함께 읽는 분과 공유하세요.'
    texts = [
        '뉴스를 그대로 믿어도 될까요? 합성 자료를 통해 뉴스의 출처와 내용을 검토하는 과정을 알아봅니다.',
        '같은 주제라도 출처마다 표현과 근거가 다를 수 있으므로 서로 어떤 내용을 담았는지 구분해 살펴보세요.',
        '확인되지 않은 내용은 사실로 단정하지 말고 원문과 이용 권한을 직접 검토하세요. 함께 읽는 분과 공유하세요.',
    ]
    assert len(result['scenes']) == 3
    for scene, text, role in zip(result['scenes'], texts, ('fact', 'meaning', 'action'), strict=True):
        scene.update(narration=text, role=role, seconds=10)
    result['scenes'][0]['caption'] = '합성 예시 · 실제 보도 아님'
    return result
