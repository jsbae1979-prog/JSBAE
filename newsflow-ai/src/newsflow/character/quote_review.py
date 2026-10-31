"""Local quote freshness/proof checks; never requests a key or a provider."""
from datetime import datetime, timedelta
from .service import fingerprint

QUOTE_LIFETIME = timedelta(minutes=15)

def quote_review(job, at):
    result = {'quoteStatus': 'unavailable', 'quoteExpiresAt': None}
    if job.get('state') != 'quoted':
        return result
    try:
        stamp = datetime.fromisoformat(job['quoted_at'])
        age = at - stamp
        result['quoteExpiresAt'] = (stamp + QUOTE_LIFETIME).isoformat()
        proof = fingerprint([job['plan_hash'], job['scenes'], job['quoted_at'], job['quote_key_id']])
        if proof != job.get('quote_hash') or age < timedelta(0):
            result['quoteStatus'] = 'changed'
        elif age > QUOTE_LIFETIME:
            result['quoteStatus'] = 'expired'
        else:
            result['quoteStatus'] = 'ready'
    except (KeyError, TypeError, ValueError, OverflowError):
        result.update(quoteStatus='changed', quoteExpiresAt=None)
    return result
