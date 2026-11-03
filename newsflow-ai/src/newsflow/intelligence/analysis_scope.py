"""Bind the news-analysis exception to a server-created running analysis."""
import re
from newsflow.db.models import IntelligenceRun


def is_news_analysis(session, settings, request_id, kind, search_calls):
    match = re.fullmatch(r"intelligence:([1-9][0-9]*)", request_id)
    if not match or kind != "analysis" or search_calls != 0:
        return False
    run = session.get(IntelligenceRun, int(match[1]))
    return bool(run and run.kind == "analysis" and run.status == "running"
                and run.provider == settings.provider and isinstance(run.options, dict)
                and run.options.get("model") == settings.model
                and isinstance(run.evidence, dict) and run.evidence)
