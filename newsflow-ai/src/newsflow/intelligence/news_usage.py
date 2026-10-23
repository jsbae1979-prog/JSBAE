"""News-use policy, without networking or inferred factual verification.

URL shape can prioritize a candidate; it cannot prove an article's contents or
publication date. The application currently has no independent source verifier,
so VERIFIED is deliberately blocked. Legacy local explainers retain their
strict template gate. Explicit API drafts use a separate, review-required contract.
"""

from __future__ import annotations

import re
from math import ceil, floor
from urllib.parse import parse_qs, urlsplit

from newsflow.intelligence.schema import Script

from .korean import CHARS_PER_SECOND, SENTENCE_PAUSE_SECONDS, narration_budget, rate_factor, split_sentences

NEWS_USAGE_LABELS = {"QUICK": "빠른 제작", "STANDARD": "균형 제작", "VERIFIED": "검증 우선"}
API_SCRIPT_METHOD = "api_grounded_v1"
API_SCRIPT_METHODS = frozenset({API_SCRIPT_METHOD, 'api_grounded_v2'})


def api_news_contract(evidence: dict, mode: str, duration: int | None = None, *, speech: dict | None = None,
                      version: str | None = None) -> dict:
    """Server-owned instructions, never a model-selected validation exemption."""
    assessment = assess_news_usage(evidence, mode)
    if assessment["approach"] == "blocked":
        raise ValueError(assessment["message"])
    contract = {
        "mode": assessment["mode"],
        "structure": (
            "핵심 주제 → 시청자가 알아둘 점 → 마무리. 배경은 꼭 필요한 만큼만 간결하게."
            if assessment["mode"] == "QUICK" else
            "도입 → 배경 → 핵심 쟁점 → 마무리. 각 장면에 내레이션·짧은 자막·소재 제안을 작성."
        ),
        "grounding": (
            "입력 제목·요약·검색 근거의 구체적 주제로 구성하고 고정 분야 설명으로 대체하지 마세요. "
            "목록·검색 요약은 주제 참고 자료이며 개별 사건의 사실 검증이 아닙니다. "
            "개별 기사 내용이 부족하면 같은 주제의 설명형 대본을 생성하고 미확인 사항을 밝히세요. "
            "자료에 없는 사건·발언·수치·발행일·인물을 만들지 마세요. 검색 시각은 기사 발행일이 아닙니다. "
            "확인된 입력 내용과 해설·추정을 구분하고, 사실 검증 완료라고 주장하지 마세요."
        ),
        "verification_status": "NOT VERIFIED",
        "human_review_required": True,
        "selected_article_ids": [article["id"] for article in _articles(evidence) if type(article.get("id")) is int],
        "tools": "추가 검색·외부 명령·Provider 전환 없이 제공된 자료만 사용하세요.",
    }
    from .provider import prompt_version

    selected = prompt_version(evidence, selected=version)
    if selected == 'v2':
        contract.update(
            prompt_version='v2',
            structure=(
                '장면 3개, role 순서: fact(무슨 일인지 최대 2문장) → meaning(시청자에게 왜 중요한지, 흔한 오해 바로잡기) '
                '→ action(시청자가 지금 확인할 일 1가지).'
                if assessment['mode'] == 'QUICK' else
                '장면 4개. 자료에 후속 일정·이슈가 있으면 fact → meaning → action → next, '
                '없으면 fact → meaning(왜 중요한지) → meaning(시청자 관점의 배경·핵심 쟁점) → action. '
                'fact는 모두 합쳐 최대 2문장.'
            ) + ' meaning과 action의 초 합계가 fact보다 길어야 합니다. hook은 질문 또는 흔한 오해, '
                'closing은 공유·다음 일정 기억·후속 확인. 각 장면은 role·내레이션·짧은 자막·소재 제안을 포함합니다.',
            role_orders=([['fact', 'meaning', 'action']] if assessment['mode'] == 'QUICK' else
                         [['fact', 'meaning', 'meaning', 'action'], ['fact', 'meaning', 'action', 'next']]),
            grounding=contract['grounding'] + ' 자료가 부족하면 fact는 최소화하고 같은 주제의 해석·일반적인 확인 방법으로 구성하세요. '
                      '시청자 관점의 해석은 허용하지만 새 사건 사실이 아니며, 자료에 없는 통계·수치·법령·가격·날짜는 넣지 마세요. '
                      '자료에 없는 향후 전망·원인·결과를 가능성이라는 표현으로 추가하지 마세요. '
                      '합성·가상 자료는 사실 장면의 내레이션과 자막에도 합성·가상 예시임을 표시하고 실제 보도로 소개하지 마세요. '
                      '후속 일정은 자료에 있을 때만 사용하고, 투자·상품·구매 권유 대신 확인할 일로 표현하세요.',
        )
    if duration is not None:
        from newsflow.shortform import allowed_duration, frozen

        profile = frozen(evidence)
        if not allowed_duration(duration, profile.enabled):
            raise ValueError("영상 길이를 확인하세요.")
        # This is an estimate, not an audio measurement. Existing TTS checks the
        # actual WAV and returns a review action instead of another paid request.
        speech = {"rate": 0, "pause_ms": 250, **(speech or {})}
        scene_count = 3 if assessment["mode"] == "QUICK" else 4
        sentence_limits = ([1] * scene_count if profile.enabled else
                           [2, *([1] * (scene_count - 2)), 2])
        sentences = (sum(sentence_limits) if selected == 'v2' else
                     scene_count if profile.enabled else scene_count * 2)
        pause_seconds = (SENTENCE_PAUSE_SECONDS * sentences
                         + speech["pause_ms"] / 1000 * (sentences - scene_count))
        speed = CHARS_PER_SECOND * rate_factor(speech["rate"]) * (profile.speed if profile.enabled else 1)
        contract["duration_seconds"] = duration
        contract["narration_spoken_units_target"] = {
            "minimum": max(1, ceil((duration * .90 - pause_seconds) * speed)),
            "maximum": max(1, floor((duration * .97 - pause_seconds) * speed)),
            "unit": "공백·문장부호를 제외한 한글 음절 수. 영문·숫자 묶음은 기존 발화 추정 단위 적용.",
        }
        contract["speech_estimate"] = {
            "rate": speech["rate"], "pause_ms": speech["pause_ms"],
            "scene_count_hint": scene_count, "sentence_count_hint": sentences,
            "target_seconds_minimum": round(duration * .90, 2),
            "target_seconds_maximum": round(duration * .97, 2),
            "estimated_pauses_seconds": round(pause_seconds, 2),
            "basis": "기존 한국어 음성 길이 추정식. 실제 엔진의 WAV 측정이나 품질 검증 결과가 아님.",
        }
        contract["audio_fit"] = (
            "전체 장면 내레이션은 목표 분량에 맞게 작성하고 장면별 음성 시간을 고려하세요. "
            "긴 무음·정지 화면으로 길이를 채우거나 과도한 속도를 요구하지 마세요. "
            "근거가 부족하면 그 한계를 설명하되 사실을 만들어 분량을 채우지 마세요."
        )
        if selected == 'v2':
            # Concrete scene budgets use the unchanged estimator, not WAV measurement.
            seconds = [min(3, max(1, duration // 5)) if profile.enabled and profile.hook
                       else max(1, duration // 5)]
            remaining = duration - seconds[0]
            seconds.extend([remaining // (scene_count - 1)] * (scene_count - 1))
            seconds[-1] += duration - sum(seconds)
            contract['scene_narration_budgets'] = [
                {'scene': i, **narration_budget(sec, limit, **speech,
                                              speed=profile.speed if profile.enabled else 1)}
                for i, (sec, limit) in enumerate(zip(seconds, sentence_limits), 1)
            ]
            contract['narration_limits_version'] = 'scene-characters-v1'
            contract['narration_characters_maximum'] = sum(
                budget['maximum_characters'] for budget in contract['scene_narration_budgets'])
            contract['narration_length_rule'] = (
                'maximum_characters는 내레이션의 공백·문장부호를 포함한 글자 수 상한입니다. '
                '각 장면의 글자 수·문장 수·발화 단위·총 분량을 모두 지키세요. '
                '중간 의미 장면은 짧은 문장 하나로 서로 다른 핵심만 말하고 해설을 반복하지 마세요. '
                '긴 문장을 쉼표로 이어 붙이지 마세요. 도입·마무리도 같은 예산에 포함합니다. '
                '검토 메모에 분량 준수라고 쓰는 것은 내레이션 검사 통과를 대신하지 않습니다.'
            )
            contract['spoken_boundaries'] = (
                'hook은 첫 장면 내레이션의 맨 앞, closing은 마지막 장면의 맨 끝에 같은 문장으로 각각 한 번 포함하세요. '
                '두 문장도 분량 예산에 포함합니다. 장면별 초와 발화 단위 예산을 사용하고, '
                '초 배정을 바꾸면 같은 추정식으로 예산을 다시 계산하세요. 의미 장면끼리 설명을 반복하지 마세요.'
            )
    return contract


def validate_api_news_script(output: dict, evidence: dict) -> None:
    """Bounded edit/output checks; these do not establish factual correctness."""
    assessment = assess_news_usage(evidence, evidence.get("news_usage"))
    if assessment["approach"] == "blocked":
        raise ValueError(assessment["message"])
    script = Script.model_validate(output)
    articles = _articles(evidence)
    if any(not article.get("sources") for article in articles):
        raise ValueError("대본에 연결된 출처 자료가 필요합니다.")
    # Figures and quotations absent from the input cannot be added by the model
    # or editor. Event/name accuracy still needs human review; do not label PASS.
    source_text = " ".join(
        str(article.get(field) or "") for article in articles for field in ("title", "summary")
    )
    text = " ".join([
        script.title, script.hook, script.summary, script.closing,
        *(getattr(scene, field) for scene in script.scenes for field in ("narration", "caption")),
    ])
    # Check the original bounded-planning strings too, before optional-field truncation can hide a claim.
    if isinstance(output.get('analysis'), dict):
        text += ' ' + ' '.join(value for key, value in output['analysis'].items()
                              if key in {'misconception', 'viewer_relevance', 'viewer_action', 'next_event'}
                              and isinstance(value, str))
    def numbers(value: str) -> set[str]:
        return {number.replace(",", "") for number in re.findall(r"\d+(?:[,.]\d+)*", value)}

    if numbers(text) - numbers(source_text):
        raise ValueError("자료에 없는 수치·날짜는 추가할 수 없습니다.")
    for quoted in re.findall(r'[“\"]([^”\"]{4,})[”\"]', text):
        if quoted not in source_text:
            raise ValueError("자료에 없는 직접 발언은 추가할 수 없습니다.")


def explainer_findings(content: dict, evidence: dict, *, speech: dict | None = None) -> list[dict]:
    """Composition warnings never approve facts or reject otherwise valid legacy output."""
    if evidence.get('script_prompt_version') != 'v2' and evidence.get('script_method') != 'api_grounded_v2':
        return []
    analysis = content.get('analysis') or {}
    roles = [scene.get('role') for scene in content['scenes']]
    expected = (['fact', 'meaning', 'action'] if evidence.get('news_usage') == 'QUICK' else
                ['fact', 'meaning', 'action', 'next'] if analysis.get('next_event') else
                ['fact', 'meaning', 'meaning', 'action'])
    result = []

    def note(code, message):
        import logging

        logging.getLogger(__name__).warning('explainer_review_warning=%s', code)
        # Informational review items keep these editorial checks soft, including when review is skipped.
        result.append({'code': code, 'level': 'info', 'kind': 'composition_warning', 'message': message})

    if roles != expected:
        note('explainer_roles', '해석형 장면 역할·순서가 권장 구성과 다릅니다. 사실·의미·확인할 일을 검토하세요.')
    fact = sum(scene['seconds'] for scene in content['scenes'] if scene.get('role') == 'fact')
    interpretation = sum(scene['seconds'] for scene in content['scenes'] if scene.get('role') in {'meaning', 'action'})
    if fact >= interpretation:
        note('explainer_balance', '사실 소개보다 시청자 관점의 의미·확인할 일에 충분한 시간을 배정하세요.')
    if any(word in content.get('closing', '') for word in ('원문', '출처를 확인')):
        note('explainer_closing', '마무리는 원문 이동 안내보다 공유·후속 일정 기억 등 시청자 참여로 정리하세요.')
    if analysis.get('ad_risk') == 'high':
        result.append({'code': 'explainer_ad_risk', 'level': 'warning',
                       'message': '폭력·위험·광고 민감 주제입니다. 비선정적 표현과 실루엣·아이콘·텍스트 소재를 검토하세요.'})
    result.extend(_explainer_broadcast_findings(content, evidence))
    result.extend(_narration_length_findings(content, evidence, speech=speech))
    return result


def _narration_length_findings(content: dict, evidence: dict, *, speech: dict | None = None) -> list[dict]:
    """Only newly frozen contracts opt in; old drafts and their text stay intact."""
    contract = evidence.get('news_usage_contract') or {}
    if contract.get('narration_limits_version') != 'scene-characters-v1':
        return []
    from newsflow.shortform import frozen

    profile = frozen(evidence)
    speech = {**(contract.get('speech_estimate') or {}), **(speech or {})}
    scenes, findings, seen = content['scenes'], [], set()
    for i, scene in enumerate(scenes):
        # Editing scene seconds recalculates the ceiling without changing voice,
        # stored narration or the old contract's original planning suggestion.
        sentences = 1 if profile.enabled or 0 < i < len(scenes) - 1 else 2
        budget = narration_budget(scene['seconds'], sentences, rate=speech.get('rate', 0),
                                  pause_ms=speech.get('pause_ms', 250), speed=profile.speed if profile.enabled else 1)
        text = scene['narration']
        if len(text) > budget['maximum_characters']:
            findings.append({'code': 'narration_character_limit', 'level': 'warning',
                             'message': f"장면 {i+1} 내레이션 {len(text)}자가 분량 안내 {budget['maximum_characters']}자를 넘습니다. 핵심 문장만 남겨 수정하세요."})
        parts = split_sentences(text)
        if len(parts) > sentences:
            findings.append({'code': 'narration_sentence_limit', 'level': 'warning',
                             'message': f'장면 {i+1}은 최대 {sentences}문장으로 정리하세요. 글자 수와 음성 길이도 함께 확인합니다.'})
        for part in parts:
            normalized = re.sub(r'\W+', '', part)
            if len(normalized) >= 10 and normalized in seen:
                findings.append({'code': 'narration_repeated_sentence', 'level': 'info', 'kind': 'composition_warning',
                                 'message': '내레이션에 같은 문장이 반복됩니다. 장면별 핵심을 나눠 수정하세요.'})
                break
            seen.add(normalized)
    return findings


_SYNTHETIC_MARKER = re.compile(r'합성|가상|\bsynthetic\b|\bfictional\b', re.IGNORECASE)
_SYNTHETIC_SOURCE = re.compile(
    r'^\s*(?:\[(?:합성|가상|synthetic|fictional)[^\]]*\]|'
    r'(?:합성|가상)\s*(?:자료|예시|사례)입니다|'
    r'(?:this is |these are )?(?:synthetic|fictional)\s+(?:data|source|example|fixture|scenario)\b)',
    re.IGNORECASE,
)
# Deliberately narrow Korean outlook signals, not a semantic fact verifier.
_OUTLOOK = re.compile(r'(?:향후|앞으로|조만간).{0,90}?(?:전망|예상|가능성|예정)|'
                      r'(?:인하|인상|급등|폭락|증가|감소).{0,24}?(?:전망|예상|가능성)')
_UNCONFIRMED = re.compile(r'미확인|미확정|알 수 없|확인되지 않|확인되지 않았')


def _explainer_broadcast_findings(content: dict, evidence: dict) -> list[dict]:
    """Flag observable speech/source mismatches without rewriting or approving facts."""
    import logging

    findings = []

    def warn(code, message):
        logging.getLogger(__name__).warning('explainer_review_warning=%s', code)
        findings.append({'code': code, 'level': 'warning', 'message': message})

    normalize = lambda value: ' '.join(str(value).split())
    scenes = content['scenes']
    hook, closing = normalize(content.get('hook', '')), normalize(content.get('closing', ''))
    narration = normalize(' '.join(scene['narration'] for scene in scenes))
    if hook and (not normalize(scenes[0]['narration']).startswith(hook) or narration.count(hook) != 1):
        warn('explainer_spoken_hook', '도입 문장을 첫 장면 내레이션 맨 앞에 한 번 포함하도록 수정하세요.')
    if closing and (not normalize(scenes[-1]['narration']).endswith(closing) or narration.count(closing) != 1):
        warn('explainer_spoken_closing', '마무리 문장을 마지막 장면 내레이션 맨 끝에 한 번 포함하도록 수정하세요.')
    source_text = ' '.join(str(article.get(key) or '') for article in evidence.get('articles', [])
                           for key in ('title', 'summary'))
    fact_scenes = [scene for scene in scenes if scene.get('role') == 'fact']
    # A topic about synthetic media is not itself a synthetic event. Only
    # explicit source labels/declarations trigger the broadcast disclosure check.
    synthetic = any(_SYNTHETIC_SOURCE.search(str(article.get(field) or ''))
                    for article in evidence.get('articles', []) for field in ('title', 'summary'))
    if synthetic and (
        not fact_scenes or any(not _SYNTHETIC_MARKER.search(scene[field])
                              for scene in fact_scenes for field in ('narration', 'caption'))
    ):
        warn('explainer_synthetic_context', '합성·가상 자료입니다. 사실 장면의 내레이션과 자막에 예시임을 표시하세요.')
    # Include planning and display fields, but never producer-only review notes.
    visible = [content['title'], content['hook'], content['summary'], content.get('closing', ''),
                        *(scene[field] for scene in scenes for field in ('narration', 'caption')),
                        *(str(value) for key, value in (content.get('analysis') or {}).items() if key != 'ad_risk')]
    # A supplied outlook still needs human review; absence is only a warning signal.
    if not _OUTLOOK.search(source_text) and any(
        _OUTLOOK.search(sentence) and not _UNCONFIRMED.search(sentence)
        for value in visible for sentence in split_sentences(value)
    ):
        warn('explainer_outlook_without_source', '자료에서 확인되지 않은 전망 표현이 있습니다. 근거를 확인하거나 해당 표현을 수정하세요.')
    return findings


def validate_explainer_analysis(output: dict, evidence: dict) -> None:
    """New editorial fields cannot smuggle numerical facts/quotes from another candidate."""
    articles = {article['id']: article for article in _articles(evidence)}

    def check(values, ids):
        source = ' '.join(str(articles[i].get(k) or '') for i in ids if i in articles
                          for k in ('title', 'summary'))
        text = ' '.join(value for value in values if isinstance(value, str))
        numbers = lambda value: {n.replace(',', '') for n in re.findall(r'\d+(?:[,.]\d+)*', value)}
        if numbers(text)-numbers(source):
            raise ValueError('해석에 자료에 없는 수치·날짜가 있습니다.')
        if any(quote not in source for quote in re.findall(r'[“"]([^”"]{4,})[”"]', text)):
            raise ValueError('해석에 자료에 없는 직접 발언이 있습니다.')

    for comparison in output.get('comparisons', []):
        check([comparison.get('viewer_angle')], comparison.get('article_ids', []))
    chosen = output.get('recommended_article_id')
    ids = next((comparison.get('article_ids', []) for comparison in output.get('comparisons', [])
                if chosen in comparison.get('article_ids', [])), [chosen])
    check([output.get('recommended_angle')], ids)
_CATEGORIES = {
    "all": ("뉴스", "뉴스는 사건과 주장을 전합니다. 보도 내용과 의미를 풀이하는 해설은 구분해야 합니다."),
    "politics": ("정치", "정책은 문제에 대응하는 방안입니다. 제안과 확정, 시행은 서로 다른 단계입니다."),
    "economy": ("경제", "물가는 가격 수준을 뜻합니다. 구매력은 같은 돈으로 살 수 있는 정도입니다."),
    "society": ("사회", "사회 문제에는 개인의 경험과 제도가 얽힙니다. 같은 대응도 대상별 영향이 다를 수 있습니다."),
    "it": ("기술", "기술의 가치는 기능뿐 아니라 사용 목적과 실제 필요에 따라 달라집니다."),
    "world": ("국제", "국제 관계에는 외교와 무역, 안보가 얽힙니다. 당사자별 이해도 다를 수 있습니다."),
    "culture": ("문화", "문화 작품은 창작자의 표현과 관객의 해석이 만납니다. 취향과 평가도 다를 수 있습니다."),
    "sports": ("스포츠", "스포츠 기록은 경기 규칙과 조건 안에서 나옵니다. 결과와 경기 내용은 구분해 볼 수 있습니다."),
}
_CONSIDERATIONS = {
    "all": "배경과 근거를 비교해 보세요. 단편적인 제목만으로 전체 의미를 판단하기는 어렵습니다.",
    "politics": "정책의 대상과 재원, 시행 조건을 함께 살펴보세요. 목표와 실행 방법도 나누어 볼 수 있습니다.",
    "economy": "가격의 변화와 가계 부담을 구분해 보세요. 소득과 소비 품목에 따라 체감은 다를 수 있습니다.",
    "society": "문제의 원인과 영향을 나누어 보세요. 해결 방안의 접근성과 부담도 함께 살펴야 합니다.",
    "it": "도입 전 비용과 개인정보 처리 방식, 이용 조건을 함께 비교해 보세요.",
    "world": "공식 입장과 실제 조치를 나누어 보세요. 다른 지역에 미칠 영향도 맥락 속에서 살펴야 합니다.",
    "culture": "작품의 배경과 표현 방식을 살펴보세요. 인기도와 작품에 대한 평가는 같은 뜻이 아닙니다.",
    "sports": "기록을 비교할 때는 종목과 경기 조건을 살펴보세요. 한 경기만으로 장기 성과를 단정하기 어렵습니다.",
}
_CATEGORY_ALIASES = {
    "전체": "all", "미분류": "all", "기타": "all", "정치": "politics", "경제": "economy", "사회": "society",
    "IT·과학": "it", "IT/과학": "it", "IT": "it", "기술": "it", "과학": "it", "국제": "world",
    "문화": "culture", "스포츠": "sports",
}
_URL_TOPIC_LABELS = {
    "technology": "it", "tech": "it", "science": "it", "politics": "politics",
    "economy": "economy", "business": "economy", "finance": "economy", "markets": "economy",
    "society": "society", "world": "world", "international": "world", "culture": "culture", "sports": "sports",
}
_TOPIC_CAPTIONS = {
    "all": ("보도와 해설", "배경 · 근거 · 맥락"),
    "politics": ("제안 · 확정 · 시행", "대상 · 재원 · 실행 조건"),
    "economy": ("물가와 구매력", "소득 · 소비 · 체감 부담"),
    "society": ("개인과 제도", "원인 · 영향 · 접근성"),
    "it": ("활용 목적과 필요", "비용 · 개인정보 · 이용 조건"),
    "world": ("외교 · 무역 · 안보", "입장 · 조치 · 지역 영향"),
    "culture": ("표현과 해석", "배경 · 인기도 · 평가"),
    "sports": ("결과와 경기 내용", "규칙 · 조건 · 장기 성과"),
}
_LISTING_PARTS = {
    "technology", "tech", "politics", "economy", "business", "world", "news", "latest",
    "science", "society", "search", "category", "categories", "section", "sections", "topics",
    "tag", "tags", "index", "index.html", "index.htm",
}


def validate_news_usage(value: str | None) -> str:
    """Missing selections default to STANDARD; never replace an invalid selection."""
    if value is None:
        return "STANDARD"
    if not isinstance(value, str) or value.strip().upper() not in NEWS_USAGE_LABELS:
        raise ValueError("뉴스 활용 수준을 확인하세요.")
    return value.strip().upper()


def _articles(evidence: dict) -> list[dict]:
    if not isinstance(evidence, dict):
        raise ValueError("뉴스 참고 자료가 없습니다.")  # noqa: TRY004 - one public validation error contract
    articles = evidence.get("articles", [evidence])
    if not isinstance(articles, list) or not articles or any(not isinstance(a, dict) for a in articles):
        raise ValueError("뉴스 참고 자료가 없습니다.")
    if any(not any(a.get(key) for key in ("title", "url", "sources")) for a in articles):
        raise ValueError("뉴스 참고 자료가 없습니다.")
    return articles


def _source_kind(article: dict) -> str:
    url = article.get("url")
    if not url:
        sources = article.get("sources", [])
        url = sources[0].get("url") if isinstance(sources, list) and sources and isinstance(sources[0], dict) else ""
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return "unknown"
        path = [part.lower() for part in parts.path.split("/") if part]
        query = parse_qs(parts.query)
    except (TypeError, ValueError, AttributeError):
        return "unknown"
    if (not path or path[-1] in _LISTING_PARTS or "search" in path
            or any(key in query for key in ("q", "query", "search"))):
        return "listing"
    if ("articles" in path or "article" in path or path[-1].endswith((".html", ".htm"))
            or re.search(r"/\d{4}/\d{2}/\d{2}/", parts.path)
            or any(key in query for key in ("article_id", "articleId", "aid"))):
        return "article_candidate"
    # No attempt to guess that an unknown slug is an independently read article.
    return "unknown"


def assess_news_usage(evidence: dict, mode: str = "STANDARD") -> dict:
    mode = validate_news_usage(mode)
    articles = _articles(evidence)
    kinds = [_source_kind(article) for article in articles]
    ordered = list(zip(articles, kinds, strict=True))
    if mode == "STANDARD":
        ordered.sort(key=lambda entry: entry[1] != "article_candidate")
    blocked = mode == "VERIFIED"
    return {
        "mode": mode,
        "label": NEWS_USAGE_LABELS[mode],
        "approach": "blocked" if blocked else "topic",
        "source_kind": kinds[0] if len(set(kinds)) == 1 else "mixed",
        "verification_status": "NOT VERIFIED",
        "message": (
            "개별 기사·발행일·핵심 사실의 독립 확인 근거가 없어 제작을 중단합니다."
            if blocked else
            "주제 설명형으로 제작합니다. 개별 사건·수치·발언·발행일은 미검증입니다."
        ),
        "preferred_article_ids": [article["id"] for article, _ in ordered if type(article.get("id")) is int],
    }


def _category_script(evidence: dict, duration: int) -> dict:
    """Use only allowlisted category text; never turn a model/title claim into narration.

    The source URL/title/unknown date remain in the caller's evidence, not copied
    into spoken text. This is a transparent local fallback, not an AI fact check.
    """
    if type(duration) is not int or duration not in (30, 45, 60):
        raise ValueError("영상 길이를 확인하세요.")
    article = _articles(evidence)[0]
    category = article.get("category", "all")
    if isinstance(category, str):
        category = _CATEGORY_ALIASES.get(category, category)
    category = category if isinstance(category, str) and category in _CATEGORIES else "all"
    if category == "all":
        # A category path can choose a topic label only, never prove page type,
        # an event, publication date, or any other fact about the source.
        sources = article.get("sources", [])
        urls = [article.get("url")]
        if isinstance(sources, list):
            urls.extend(source.get("url") for source in sources if isinstance(source, dict))
        for url in urls:
            if not isinstance(url, str):
                continue
            try:
                parts = urlsplit(url)
            except ValueError:
                continue
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                continue
            matches = [_URL_TOPIC_LABELS[part] for part in parts.path.lower().split("/") if part in _URL_TOPIC_LABELS]
            if matches:
                category = matches[-1]
                break
    topic, explanation = _CATEGORIES[category]
    narrations = [
        f"{topic} 뉴스의 배경을 풀어봅니다. 개별 사건은 미검증입니다.",
        explanation,
        _CONSIDERATIONS[category],
    ]
    if duration >= 45:
        narrations[0] += " 참고 자료에서 출발해 기본 개념과 판단 기준을 소개합니다."
        narrations[1] += " 무엇을 비교하는지 먼저 정하면 의미를 이해하기 쉽습니다."
        narrations[2] += " 자신의 상황에 어떤 의미가 있는지도 생각해 보세요."
    if duration == 60:
        narrations[0] += " 결론을 내리기보다 쟁점을 나누어 살펴보겠습니다."
        narrations[1] += " 같은 단어라도 쓰이는 맥락에 따라 뜻이 달라질 수 있습니다."
        narrations[2] += " 서로 다른 관점의 근거를 함께 읽으면 시야를 넓힐 수 있습니다."
    return {
        "title": f"{topic} 뉴스의 배경과 핵심 쟁점",
        "hook": f"{topic} 뉴스의 기본 개념과 판단 기준을 소개합니다.",
        "summary": "참고 자료에서 출발한 주제 설명입니다. 개별 사건과 원문 사실은 미검증입니다.",
        "scenes": [
            {"seconds": duration // 3, "narration": narration, "caption": caption,
             "material": "직접 제작한 주제 설명 텍스트 카드"}
            for narration, caption in zip(narrations, (
                "주제 참고 · 개별 기사 미확인", *_TOPIC_CAPTIONS[category],
            ), strict=True)
        ],
        "closing": "원문과 이용 권한을 확인한 뒤 게시해 주세요.",
    }


# Source text selects concepts only. No source sentence, name, number, date or
# purported quote is copied into narration. Matching is not fact verification.
_TOPICS = (
    ("반도체", ("반도체", "semiconductor", "semiconductors", "칩셋", "chipset", "chipsets",
             "microchip", "microchips", "computer chip", "computer chips", "ai chip", "ai chips"),
     "반도체는 전자 기기의 연산과 저장에 쓰이는 부품입니다.",
     "성능과 전력 소비, 공급 조건을 함께 비교해야 합니다.",
     "기기에 필요한 성능과 가격을 기준으로 살펴보세요."),
    ("생성형 AI", ("생성형", "생성형ai", "chatgpt", "챗gpt", "llm", "llms", "generative ai",
                "generative artificial intelligence"),
     "생성형 인공지능은 입력을 바탕으로 글이나 이미지 같은 결과를 만듭니다.",
     "결과의 정확성과 개인정보 처리, 저작권이 주요 판단 기준입니다.",
     "중요한 답변은 별도 자료로 확인하고 민감한 정보 입력에 주의하세요."),
    ("인공지능", ("인공지능", "artificial intelligence", "ai"),
     "인공지능은 데이터를 바탕으로 분류와 예측 등 여러 작업을 수행하는 기술입니다.",
     "용도와 학습 자료, 오류의 영향을 함께 살펴야 합니다.",
     "어떤 작업을 지원하는지 확인하고 중요한 판단은 결과의 근거도 살펴보세요."),
    ("스마트폰", ("스마트폰", "smartphone", "smartphones", "아이폰", "iphone", "iphones", "갤럭시"),
     "스마트폰은 통신과 촬영, 앱 사용을 한 기기에서 지원합니다.",
     "새 기능의 필요성과 배터리, 지원 기간을 함께 비교해야 합니다.",
     "자주 쓰는 기능과 수리 비용을 기준으로 선택을 검토하세요."),
    ("개인정보 보호", ("개인정보", "privacy", "데이터 유출", "해킹", "hacking"),
     "개인정보 보호는 정보의 수집과 이용, 보관 범위를 다루는 문제입니다.",
     "서비스 편의성과 정보 제공 범위, 이용자의 통제권을 함께 살펴야 합니다.",
     "앱 권한과 보관 기간, 삭제 방법을 확인하세요."),
    ("로봇", ("로봇", "robot", "robots", "휴머노이드"),
     "로봇은 센서와 제어 장치를 이용해 물리적인 작업을 수행합니다.",
     "시연 조건과 실제 작업 환경, 안전 관리가 중요한 비교 기준입니다.",
     "가능한 작업의 범위와 유지 비용을 확인하세요."),
    ("전기차 배터리", ("전기차", "electric vehicle", "electric vehicles", "ev battery", "ev batteries"),
     "전기차 배터리는 이동에 필요한 전기 에너지를 저장합니다.",
     "주행 조건과 충전 편의, 안전 및 수명을 함께 살펴야 합니다.",
     "자신의 이동 거리와 충전 환경을 기준으로 비교하세요."),
    ("배터리", ("배터리", "battery", "batteries"),
     "배터리는 전기 에너지를 저장하고 필요한 기기에 공급합니다.",
     "용도와 사용 조건에 따라 필요한 용량과 성능이 달라질 수 있습니다.",
     "사용 기기에 맞는 규격과 안전 안내, 교체 및 폐기 방법을 확인하세요."),
    ("금리", ("금리", "interest rate"),
     "금리는 돈을 빌리거나 맡길 때 적용되는 비율입니다.",
     "대출 부담과 예금 수익은 계약 조건에 따라 다를 수 있습니다.",
     "고정 금리와 변동 금리, 계약 기간을 함께 확인하세요."),
    ("물가", ("물가", "inflation"),
     "물가는 여러 상품과 서비스의 가격 수준을 나타냅니다.",
     "전체 지표와 개인의 소비 품목에 따른 체감은 다를 수 있습니다.",
     "비교 기간과 품목, 소득의 변화를 함께 살펴보세요."),
    ("기후", ("기후", "climate", "탄소"),
     "기후 문제는 장기간의 환경 변화와 사회의 대응을 함께 다룹니다.",
     "관측 자료와 예측, 정책 목표를 구분해 살펴야 합니다.",
     "자료의 관측 기간과 지역, 불확실성 표시를 확인하세요."),
)


def _topic(article: dict) -> tuple | None:
    # Priority: headline, then search summary. Raw tool payloads cannot override
    # the selected article and are never serialized into a script.
    provenance = article.get("search_provenance", {})
    sources = article.get("sources", [])
    urls = {source.get("url") for source in sources if isinstance(source, dict)}
    urls.add(article.get("url"))
    candidates = provenance.get("topic_candidates", []) if isinstance(provenance, dict) else []
    titles = [candidate.get("title") for candidate in candidates
              if isinstance(candidate, dict) and candidate.get("url") in urls]
    for value in (article.get("title"), *titles, article.get("summary")):
        if not isinstance(value, str):
            continue
        text = value[:800].casefold()
        for topic in _TOPICS:
            if any(re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", text)
                   for word in topic[1]):
                return topic
    return None


def safe_topic_script(evidence: dict, duration: int) -> dict:
    """Select local concept prose from search evidence, never assert its claims."""
    legacy = _category_script(evidence, duration)
    mode = validate_news_usage(evidence.get("news_usage"))
    if mode == "VERIFIED":
        raise ValueError(assess_news_usage(evidence, mode)["message"])
    selected = _topic(_articles(evidence)[0])
    if selected:
        topic, _, background, issue, takeaway = selected
    else:
        topic = legacy["title"].split(" 뉴스")[0]
        background = legacy["scenes"][1]["narration"]
        issue = legacy["scenes"][2]["narration"]
        takeaway = "제목과 검색 요약은 주제 참고 자료입니다. 개별 사실은 원문에서 확인하세요."
    quick = mode == "QUICK"
    title = f"{topic} · {'빠르게 알아보기' if quick else '배경과 핵심 쟁점'}"
    introduction = f"{topic}, 무엇을 알아두면 좋을까요? 주제 소개이며 개별 사건은 미검증입니다."
    captions = [f"{topic} · 주제 참고 · 개별 기사 미확인", f"{topic} · 기본 개념", f"{topic} · 알아둘 점"]
    narrations = [introduction, background, takeaway]
    if not quick:
        narrations = [introduction + " 검색 자료의 주장과 일반적인 설명을 구분해 살펴봅니다.",
                      background, issue, takeaway]
        captions = [captions[0], f"{topic} · 배경", f"{topic} · 핵심 쟁점", captions[2]]
    # QUICK retains short prose even in a longer canvas; STANDARD adds useful
    # context without inventing events to fill the requested running time.
    if not quick and duration >= 45:
        narrations[2] += " 비교 기준이 다르면 평가도 달라질 수 있습니다."
    if not quick and duration == 60:
        narrations[3] += " 검색 요약만으로 결론을 내리지 말고 근거의 범위도 살펴보세요."
    seconds, remainder = divmod(duration, len(narrations))
    return {
        "title": title,
        "hook": f"{topic}의 {'기본 개념과 확인할 점' if quick else '배경, 쟁점과 판단 기준'}을 살펴봅니다.",
        "summary": "검색 자료에서 고른 주제의 일반 설명입니다. 확인된 개별 사실 없음 · 사건·발언·수치·발행일 미검증.",
        "scenes": [
            {"seconds": seconds + (index < remainder), "narration": narration, "caption": caption,
             "material": f"직접 제작한 {topic} 주제 설명 텍스트 카드"}
            for index, (narration, caption) in enumerate(zip(narrations, captions, strict=True))
        ],
        "closing": legacy["closing"],
    }


def validate_news_usage_script(output: dict, evidence: dict, assessment: dict) -> None:
    """Reject unsupported claims without claiming a heuristic can verify prose.

    No independent verifier exists yet. Topic mode therefore accepts only the
    known local template, including its uncertainty captions. VERIFIED cannot
    be enabled by booleans supplied in model output or by a modified assessment.
    """
    if not isinstance(assessment, dict):
        raise ValueError("뉴스 활용 수준을 확인하세요.")  # noqa: TRY004 - callers handle policy validation uniformly
    actual = assess_news_usage(evidence, assessment.get("mode"))
    if actual["approach"] == "blocked":
        raise ValueError(actual["message"])
    try:
        script = Script.model_validate(output).model_dump()
        duration = sum(scene["seconds"] for scene in script["scenes"])
        expected = safe_topic_script(evidence, duration)
    except (ValueError, TypeError):
        raise ValueError("미확인 자료의 주제 설명 대본 형식을 확인하세요.") from None
    # Older accepted drafts stay renderable without rewriting stored content.
    if script == _category_script(evidence, duration):
        return
    # Reviewers may reorder/retime scenes and choose shorter captions or known
    # narration variants for each role. Arbitrary prose cannot bypass gates.
    candidates = [safe_topic_script(evidence, value) for value in (30, 45, 60)]
    top_fields = ("title", "hook", "summary", "closing")
    valid = all(script[field] == expected[field] for field in top_fields)
    valid = valid and len(script["scenes"]) == len(expected["scenes"])
    valid = valid and any("개별 기사 미확인" in scene["caption"] for scene in script["scenes"])
    matched_roles = []
    for scene in script["scenes"]:
        roles = {
            index for candidate in candidates for index, allowed in enumerate(candidate["scenes"])
            if scene["narration"] == allowed["narration"] and scene["material"] == allowed["material"]
            and scene["caption"] in {allowed["caption"], expected["title"].split(" · ")[0]}
        }
        # Keep each scene's purpose exactly once even when variants are mixed.
        # A duplicate background cannot replace the uncertainty or takeaway.
        valid = valid and len(roles) == 1
        matched_roles.extend(roles)
    valid = valid and sorted(matched_roles) == list(range(len(expected["scenes"])))
    if not valid:
        raise ValueError("미확인 사실이 포함될 수 있어 대본을 차단했습니다. 주제 설명형을 사용하세요.")
