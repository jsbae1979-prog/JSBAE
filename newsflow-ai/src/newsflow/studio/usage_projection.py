"""Read-only token projection across legacy usage and durable request ledgers.

Deduplicate only by a proven request/run relationship, never by time or amounts.
No historical ledger is rewritten and absent usage is not treated as zero.
"""
import re
from sqlalchemy import select
from newsflow.db.models import APIRequestReservation

def combined_usage(session, legacy):
    result = []
    covered = set()
    for row in session.scalars(select(APIRequestReservation).order_by(
            APIRequestReservation.created_at.desc(), APIRequestReservation.id.desc())):
        usage = row.usage or {}
        counts = [usage.get(k) for k in ('prompt_tokens', 'completion_tokens')]
        if not all(type(n) is int and n >= 0 for n in counts): continue
        match = re.fullmatch(r'(?:intelligence|feed-card):([1-9][0-9]*)', row.request_id)
        if match: covered.add((int(match[1]), row.provider, row.model))
        result.append({'id':'request:'+row.id, 'provider':row.provider, 'model':row.model,
            'kind':row.kind, 'status':row.status, 'prompt_tokens':counts[0],
            'completion_tokens':counts[1], 'total_tokens':sum(counts),
            'created_at':row.created_at.isoformat(), 'source':'request_ledger'})
    # The UI projection intentionally does not expose run ids. Resolve exact IDs locally.
    from newsflow.db.models import AIUsage
    duplicates = set()
    for row in session.scalars(select(AIUsage)):
        if (row.run_id, row.provider, row.model) in covered: duplicates.add(row.id)
    result.extend({**row, 'id':'usage:'+str(row['id']), 'source':'legacy_usage'}
                  for row in legacy if row['id'] not in duplicates)
    return sorted(result, key=lambda row:(str(row['created_at']),str(row['id'])), reverse=True)
