"""A new posting-copy operation must not replay or rewrite old character requests."""
import re
from newsflow.db.models import AppSetting, IntelligenceRun
from newsflow.intelligence.api_settings import APISettingsError
from newsflow.character.request_scope import EPISODE, previously_reviewed_ids, validate_operation
from newsflow.character.schema import CharacterError


def reviewed_character_unknowns(session, settings, rows):
    """Reuse an exact prior user review, never infer consent from provider settings.

    In-flight, unreviewed, changed, unclassifiable and posting-copy unknowns remain
    blockers. Historical reservation amounts/statuses are never changed.
    """
    reviewed = previously_reviewed_ids(session, settings, rows)
    result = set()
    for row in rows:
        if (row.provider != settings.provider or row.status != "unknown"
                or row.finished_at is None or row.id not in reviewed
                or row.request_id.startswith("posting-review:")):
            continue
        operation = (row.bounds or {}).get("character_operation")
        if operation is not None:
            try:
                validate_operation(operation, row.kind, row.request_id)
            except CharacterError:
                continue
            result.add(row.id)
        elif row.kind == "script" and EPISODE.fullmatch(row.request_id):
            result.add(row.id)
    return result


def validate_posting_request(session, settings, request_id, kind, search_calls):
    """Scope is server-created, bound to the durable explicitly approved request."""
    if not re.fullmatch(r"posting-review:[a-f0-9]{32}", request_id) or kind != "script" or search_calls != 0:
        raise APISettingsError("게시 문구 검토 요청 범위를 확인하세요.")
    claim = session.get(AppSetting, request_id)
    try:
        run = session.get(IntelligenceRun, int(claim.value)) if claim else None
    except (ValueError, TypeError):
        run = None
    if (not run or run.kind != "posting_copy_review" or run.status != "running"
            or run.provider != settings.provider or not isinstance(run.options, dict)
            or run.options.get("model") != settings.model
            or not re.fullmatch(r"(?:news|image|post):[1-9][0-9]*|character:[a-f0-9]{32}", str(run.options.get("project_id", "")))
            or not re.fullmatch(r"[a-f0-9]{64}", str(run.options.get("fingerprint", "")))):
        raise APISettingsError("현재 게시 문구 검토 요청이 아닙니다.")
