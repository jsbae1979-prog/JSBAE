"""Finite card failure details; never retain provider text or validation inputs."""
from typing import ClassVar

from newsflow.intelligence.provider import AnalysisResponseError, ProviderResponseError


class CardResponseError(ProviderResponseError):
    MESSAGES: ClassVar[dict[str, str]] = {
        "response_envelope": "Claude 카드 응답의 JSON·보호 검사를 통과하지 못했습니다.",
        "incomplete_response": "Claude 카드 응답이 정상 종료되지 않았습니다.",
        "response_text": "Claude 카드 응답의 텍스트 블록 형식이 맞지 않습니다.",
        "result_json": "Claude 카드 결과를 단일 JSON 객체로 해석하지 못했습니다.",
        "card_schema": "Claude 카드 필드·자료형·길이 조건이 맞지 않습니다.",
        "source_binding": "Claude 카드의 출처 기사 ID가 입력과 일치하지 않습니다.",
        "secret_protection": "Claude 카드 결과가 비밀정보 보호 검사에 의해 차단됐습니다.",
        "language_validation": "Claude 카드 제목·본문에 한국어가 없습니다.",
        "layout_validation": "Claude 카드 내용이 로컬 카드 배치 조건에 맞지 않습니다.",
        "request_rejected": "Claude API가 카드 요청을 거절했습니다.",
        "request_timeout": "Claude 카드 요청 시간이 초과됐습니다.",
        "request_or_response": "Claude 카드 요청·응답 처리 결과를 확인하지 못했습니다.",
    }
    FIELDS = frozenset({"title", "body", "image_prompt", "source_article_ids", "palette", "icon", "design"})
    RULES = frozenset({"string_too_long", "string_too_short", "string_type", "missing", "extra_forbidden",
                       "int_type", "list_type", "too_long", "too_short", "literal_error", "value_error"})

    def __init__(self, stage, *, stop_reason=None, validation=None, http_error=None):
        self.stage = stage if stage in self.MESSAGES else "request_or_response"
        self.details = {"failure_reason": self.stage}
        if stop_reason is not None:
            self.details["stop_reason"] = (
                stop_reason if isinstance(stop_reason, str) and stop_reason in AnalysisResponseError.STOP_REASONS
                else "other")
        if validation is not None:
            # Never include msg/input/ctx or an arbitrary extra-field name.
            issues = set()
            for error in validation.errors(include_input=False, include_context=False, include_url=False):
                field = error["loc"][0] if error["loc"] else ""
                rule = error["type"]
                issues.add((field if field in self.FIELDS else "other",
                            rule if rule in self.RULES else "other"))
            self.details["validation"] = [{"field": f, "rule": r} for f, r in sorted(issues)[:8]]
        if self.stage == "request_rejected" and http_error is not None:
            self.details.update(http_error.diagnostics())
        super().__init__(self.MESSAGES[self.stage] + " 자동 재요청하지 않습니다.")

    def diagnostics(self):
        return self.details.copy()
