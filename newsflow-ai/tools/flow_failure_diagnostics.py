"""Read-only synthetic fixture diagnostics; never dump credentials or request bodies."""
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from newsflow.db.models import AutopilotJob, ContentDraft
from newsflow.intelligence.korean import speech_plan, split_sentences


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != 'call' or 'api_pipeline' not in item.funcargs:
        return
    coordinator, backend, provider, sessions, mode, _ = item.funcargs['api_pipeline']
    with sessions() as session:
        jobs = list(session.scalars(select(AutopilotJob)))
        drafts = list(session.scalars(select(ContentDraft)))
        record = {'test': item.nodeid, 'outcome': report.outcome, 'provider': mode,
                  'fake_calls': provider.calls, 'jobs': [], 'drafts': []}
        for job in jobs:
            snapshot = coordinator.snapshot(job.id)
            record['jobs'].append({k: snapshot.get(k) for k in (
                'status', 'current_stage', 'error_code', 'error_message', 'retryable')})
            record['options'] = job.stage_results.get('request', {}).get('production_options')
        for draft in drafts:
            content, sources = draft.content, draft.sources
            record['drafts'].append({'duration': draft.duration,
                'narration': [s['narration'] for s in content['scenes']],
                'sentence_counts': [len(split_sentences(s['narration'])) for s in content['scenes']],
                'contract': sources.get('news_usage_contract'),
                'source_count': len(sources.get('articles', [])),
                'source_links_present': all(a.get('sources') for a in sources.get('articles', [])),
                'speech_plan': speech_plan(content, draft.duration),
                'notes': backend.intelligence._review_notes(content, sources, draft.duration)})
    output = Path(os.environ['NEWSFLOW_VALIDATION_OUTPUT'])
    output.mkdir(parents=True, exist_ok=True)
    (output / f'diagnostic-{mode}.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
