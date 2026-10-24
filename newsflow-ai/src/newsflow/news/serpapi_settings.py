"""Separate secret/approval state. Saving or viewing settings never calls SerpApi."""
import json
import uuid

from sqlalchemy import select

from newsflow.db.models import AppSetting, IntelligenceRun, utcnow


def settings(sessions) -> dict:
    with sessions() as session:
        def value(key):
            row = session.get(AppSetting, "serpapi_" + key)
            return row.value if row else None

        return {"approved_at": value("approved_at"), "generation": value("generation") or "initial"}


def context(sessions, keys) -> dict:
    from .global_collection import plan_context

    state = settings(sessions)
    with sessions() as session:
        run = session.scalar(select(IntelligenceRun).where(IntelligenceRun.provider == "serpapi",
                                                           IntelligenceRun.kind == "news_search")
                             .order_by(IntelligenceRun.id.desc()).limit(1))
        last = None
        if run and run.options.get("generation") == state["generation"]:
            last = {"id": run.id, "status": run.status, "code": run.result.get("error_code"),
                    "message": run.message, "test_only": run.options.get("test_only", False)}
    key = keys.status()
    return {**state, "key": key, "last": last,
            "collection_plan": plan_context(),
            "can_request": bool(key["configured"] and state["approved_at"]),
            "request_token": uuid.uuid4().hex}


def save(sessions, keys, *, key: str = "", approved: bool = False) -> None:
    if key:
        keys.validate(key)  # Invalid input does not alter existing files or approvals.
    generation = uuid.uuid4().hex
    with sessions.begin() as session:
        # Revoke the prior approval before a possible credential change; failures stay closed.
        row = session.get(AppSetting, "serpapi_approved_at")
        if row:
            row.value = ""
    if key:
        keys.save(key)
    if approved and not keys.status()["configured"]:
        raise ValueError("SerpApi 키를 먼저 등록해 주세요.")
    with sessions.begin() as session:
        for name, value in {"serpapi_generation": generation,
                            "serpapi_approved_at": utcnow().isoformat() if approved else ""}.items():
            row = session.get(AppSetting, name)
            if row:
                row.value = value
            else:
                session.add(AppSetting(key=name, value=value))


def claim(session, token: str, run_id: int) -> None:
    session.add(AppSetting(key="serpapi_request:" + token, value=json.dumps({"run_id": run_id})))
