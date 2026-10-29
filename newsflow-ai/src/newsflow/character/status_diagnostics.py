"""Bounded display-only provider errors; never a retry or billing decision."""
import re
from urllib.parse import quote, quote_plus

STATES = frozenset({'queued', 'in_progress', 'completed', 'failed', 'nsfw', 'canceled'})
TERMINAL = frozenset({'failed', 'nsfw', 'canceled'})
LIMIT = 1000


def private_inputs(job):
    values = []
    def strings(value):
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, dict):
            for part in value.values():
                strings(part)
        elif isinstance(value, list):
            for part in value:
                strings(part)
    for field in ('topic', 'character', 'script', 'prompts'):
        strings(job.get(field))
    for scene in job.get('scenes', []):
        strings(scene.get('handle'))
        strings(scene.get('idempotency_key'))
        payload = scene.get('payload', {})
        for field in ('prompt', 'image_url', 'image_urls'):
            strings(payload.get(field))
    return tuple(values)


def safe_error(value, protected=()):
    if not isinstance(value, str) or not value.strip():
        return ''
    text = value[:16384]
    hidden = set()
    for raw in protected:
        if not isinstance(raw, str) or not raw:
            continue
        hidden.update((raw, quote(raw, safe=''), quote_plus(raw)))
        # Keep generic English error terms (prompt/duration/reference) readable.
        # Reflected multi-word input phrases and named Korean input remain hidden.
        words = list(re.finditer(r"[^\W_]+(?:['’-][^\W_]+)*", raw, re.UNICODE))
        for match in words:
            word = match.group()
            if len(word) >= 2 and not word.isascii():
                hidden.add(word)
        for index in range(len(words) - 2):
            phrase = raw[words[index].start():words[index + 2].end()]
            if len(phrase) >= 16:
                hidden.add(phrase)
    for raw in sorted(hidden, key=len, reverse=True):
        if len(raw) >= 2:
            text = re.sub(re.escape(raw), '[보호 정보]', text, flags=re.IGNORECASE)
    text = re.sub(r'https?://[^\s<>"\']+', '[URL 생략]', text, flags=re.IGNORECASE)
    text = re.sub(r'(?i)\b(?:Bearer|Basic|Key)\s+[A-Za-z0-9._~+:/=-]{6,}', '[인증 정보]', text)
    text = re.sub(r'(?i)(?:\b[A-Z]:[\\/]|\\\\)[^\r\n<>"|]*', '[경로 생략]', text)
    text = re.sub(r'(?<!\w)/(?:Users|home|tmp|var|private|mnt)/[^\s<>"\']+', '[경로 생략]', text)
    text = re.sub(r'\b[A-Za-z0-9_-]{24,}\b', '[식별자 생략]', text)
    text = re.sub(r'<[^>]{0,200}>', '', text)
    text = re.sub(r'[\x00-\x1f\x7f]', ' ', text)
    return ' '.join(text.split())[:LIMIT]


def facts(error, protected=()):
    message = safe_error(error, protected)
    return {'error_message': message, 'detail_available': bool(message)}


def diagnostic(status, old_state, checked_at, protected=()):
    if status.state not in STATES:
        raise ValueError('unknown-provider-state')
    values = status.facts if isinstance(status.facts, dict) else {}
    return {'observed_state': status.state, **facts(values.get('error_message'), protected),
            'state_mismatch': status.state != old_state, 'checked_at': checked_at}


def public_diagnostic(value, protected=()):
    if (not isinstance(value, dict) or value.get('observed_state') not in STATES
            or type(value.get('state_mismatch')) is not bool
            or not isinstance(value.get('checked_at'), str)
            or not re.fullmatch(r'[0-9T:.+Z-]{19,40}', value['checked_at'])):
        return None
    return {'observed_state': value['observed_state'],
            **facts(value.get('error_message'), protected),
            'state_mismatch': value['state_mismatch'], 'checked_at': value['checked_at']}
