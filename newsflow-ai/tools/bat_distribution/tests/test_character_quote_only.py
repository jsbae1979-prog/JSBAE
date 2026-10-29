"""One saved-story quote through synthetic ASGI, cipher and Kling adapters only."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode

import pytest
from sqlalchemy import select

from bat_distribution import character_quote_only as m
from newsflow.character.kling import K3, O3, KlingClient
from newsflow.character.schema import CharacterError
from newsflow.db.models import APIRequestReservation
from newsflow.intelligence.credentials import CredentialError
from newsflow.video.ai.keys import VideoAIKeyStore
from test_api_settings import sessions, store
from test_character_kling_studio import studio
from test_character_single_video import seeded


KEY = 'synthetic-quote-only-key-0123456789'


def receipts(value):
    return sorted((value.service.folder(value.identifier)/'quote-attempts').glob('*.json'),key=lambda p:(p.stat().st_mtime_ns,p.name))

def latest_receipt(value):
    return json.loads(receipts(value)[-1].read_bytes())


def ledger(sessions):
    with sessions() as session:
        return deepcopy(list(session.execute(select(APIRequestReservation.__table__)).mappings()))


@pytest.fixture
def quoted(studio, monkeypatch, request):
    service = studio.service
    identifier, _, _ = seeded(studio, model=getattr(request, 'param', K3))
    source_id, _, _ = seeded(studio)
    source = service.read(source_id)
    source.update(state='submission_unknown', scenes=[{'state': 'unknown', 'quote_usd': '1.26'}])
    service.save(source)
    profile = service.root.parent
    (profile/VideoAIKeyStore.FILE).write_bytes(b'synthetic opaque protected bytes')
    trial = profile/'character-trials'/('e' * 32)
    trial.mkdir(parents=True)
    journal = trial/'journal.json'
    journal.write_text(json.dumps({'schemaVersion': 1, 'job_id': source_id,
                                   'script': {'state': 'unknown', 'reserved_usd': '.25'},
                                   'video': {'state': 'reserved', 'reserved_usd': '1.26'}}), encoding='utf8')
    with service.sessions.begin() as session:
        session.add(APIRequestReservation(id='a' * 32, request_id='legacy:unknown',
            provider='claude_api', kind='script', model='claude-sonnet-4-6', status='unknown',
            reserved_usd='0.25', bounds={}, prices={}, usage={}, test_only=True))
    state = SimpleNamespace(calls=[], native=0, fail=None, clients=[], inside=None,
                            normal=[], authenticated=0, original=[], payloads=[])

    class Native:
        def unprotect(self, payload, entropy):
            state.native += 1
            assert bytes(payload) == b'synthetic opaque protected bytes'
            assert bytes(entropy) == hashlib.sha256(VideoAIKeyStore.ENTROPY).digest()
            return bytearray(KEY.encode())

    class FakeKling(KlingClient):
        def __init__(self, credential, settings):
            super().__init__(credential, settings)
            state.clients.append(self)

        def payload(self, *args, **kwargs):
            value = super().payload(*args, **kwargs)
            state.payloads.append(deepcopy(value))
            return value

        def upload_reference(self, path):
            assert scope._read(identifier)['calls']['upload'] == 1
            assert self.credential() == KEY
            state.calls.append('upload')
            if state.fail == 'upload':
                raise ConnectionError('synthetic unknown upload')
            return 'https://example.com/synthetic-reference.png'

        def estimate(self, payload):
            assert scope._read(identifier)['calls']['estimate'] == state.calls.count('estimate') - getattr(state,'previous_estimates',0) + 1
            assert self.credential() == KEY
            state.calls.append('estimate')
            if state.inside:
                state.inside(scope)
            if state.fail == 'estimate':
                raise ConnectionError('synthetic unknown estimate')
            return '0.10'

        def submit_scene(self, *args, **kwargs):
            pytest.fail('quote-only adapter must never submit')

        def check(self, *args, **kwargs):
            pytest.fail('quote-only adapter must never poll')

        def fetch(self, *args, **kwargs):
            pytest.fail('quote-only adapter must never fetch')

    monkeypatch.setattr(m, 'KlingClient', FakeKling)
    service.prepare = lambda *args, **kwargs: state.original.append((args, kwargs))
    app = SimpleNamespace(state=SimpleNamespace(character=service, config=SimpleNamespace(data_dir=profile)))
    scope = m.install(app, profile, Native)

    async def normal(environ, receive, send):
        state.normal.append((environ['method'], environ['path']))
        await send({'type': 'http.response.start', 'status': 202, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'existing normal boundary'})

    async def authenticated(environ, receive, send):
        state.authenticated += 1
        headers = dict(environ['headers'])
        values = parse_qs((await receive())['body'].decode())
        status = 403
        if (headers.get(b'x-synthetic-auth') == b'yes'
                and headers.get(b'origin') == b'http://127.0.0.1:18768'
                and values.get('csrf_token') == ['synthetic-csrf']):
            try:
                service.prepare(identifier, consent=values.get('consent') == ['true'],
                                script_reviewed=values.get('script_reviewed') == ['true'])
                status = 200
            except (CharacterError, CredentialError, OSError):
                status = 409
        await send({'type': 'http.response.start', 'status': status, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'synthetic response'})

    def post(*, path=None, method='POST', auth=True, csrf=True, origin='http://127.0.0.1:18768',
             consent=True, reviewed=True):
        values = {'consent': 'true' if consent else 'false', 'script_reviewed': 'true' if reviewed else 'false',
                  'csrf_token': 'synthetic-csrf' if csrf else 'wrong'}
        body = urlencode(values).encode()
        messages = []

        async def receive():
            return {'type': 'http.request', 'body': body, 'more_body': False}

        async def send(message):
            messages.append(message)

        environ = {'type': 'http', 'method': method, 'path': path or f'/character/{identifier}/prepare',
                   'headers': [(b'x-synthetic-auth', b'yes' if auth else b'no'), (b'origin', origin.encode())]}
        coroutine = scope.wrap(normal, authenticated)(environ, receive, send)
        # All adapters above are synchronous; no event loop, socket or app startup.
        with pytest.raises(StopIteration):
            coroutine.send(None)
        return messages[0]['status']

    return SimpleNamespace(scope=scope, service=service, studio=studio, identifier=identifier, profile=profile,
        state=state, post=post, journal=journal, journal_before=journal.read_bytes(), ledger_before=ledger(service.sessions),
        source_path=service.folder(source_id)/'jobs.json', source_before=(service.folder(source_id)/'jobs.json').read_bytes(),
        original=service.read(identifier))


def assert_old_state_unchanged(value):
    assert value.source_path.read_bytes() == value.source_before
    assert value.journal.read_bytes() == value.journal_before
    assert ledger(value.service.sessions) == value.ledger_before
    assert value.studio.writer.calls == 0


@pytest.mark.parametrize('quoted', [K3, O3], indirect=True)
def test_saved_story_gets_one_15_second_quote_without_script_or_generation_or_ledger_changes(quoted):
    assert quoted.post() == 200
    job = quoted.service.read(quoted.identifier)
    receipt = latest_receipt(quoted)
    assert job['state'] == receipt['state'] == 'quoted'
    assert job['script'] == quoted.original['script'] and job['prompts'] == quoted.original['prompts']
    assert job['plan_hash'] == quoted.original['plan_hash']
    assert len(job['scenes']) == len(quoted.state.payloads) == 5
    assert [scene['payload']['duration'] for scene in job['scenes']] == [3]*5
    assert job['scenes'][0]['payload']['sound'] == 'off'
    assert [scene['position'] for scene in job['scenes']] == [1,2,3,4,5]
    assert receipt['calls'] == {'upload': 1, 'estimate': 5} and receipt['generation_requests'] == 0
    assert receipt['story_sha256'] == m.fingerprint(quoted.original['script'])
    assert quoted.state.calls == ['upload']+['estimate']*5 and quoted.state.native > 0
    assert quoted.state.original == []
    assert_old_state_unchanged(quoted)


@pytest.mark.parametrize('consent,reviewed', [(False, True), (True, False), (False, False)])
def test_missing_paid_upload_or_story_review_consent_does_no_io(quoted, consent, reviewed):
    assert quoted.post(consent=consent, reviewed=reviewed) == 409
    assert quoted.state.calls == [] and quoted.state.native == 0
    assert not receipts(quoted)
    assert quoted.service.read(quoted.identifier) == quoted.original


@pytest.mark.parametrize('arguments', [{'auth': False}, {'csrf': False}, {'origin': 'https://example.com'}])
def test_existing_auth_origin_and_csrf_boundary_runs_before_prepare(quoted, arguments):
    assert quoted.post(**arguments) == 403
    assert quoted.state.authenticated == 1 and quoted.state.calls == [] and quoted.state.native == 0
    assert not receipts(quoted)
    assert quoted.service.read(quoted.identifier) == quoted.original


@pytest.mark.parametrize('blocked', ['quoted', 'submission_unknown', 'existing_scenes'])
def test_previously_bound_quoted_or_unknown_work_is_never_replayed(quoted, blocked):
    job = quoted.service.read(quoted.identifier)
    if blocked == 'old_trial':
        prior = json.loads(quoted.journal.read_bytes())
        prior['job_id'] = quoted.identifier
        quoted.journal.write_text(json.dumps(prior), encoding='utf8')
    elif blocked == 'started_receipt':
        quoted.scope.receipt(quoted.identifier).write_text(json.dumps({
            'schemaVersion': 1, 'job_id': quoted.identifier, 'state': 'started_or_unknown',
            'calls': {'upload': 1}, 'generation_requests': 0}), encoding='utf8')
    elif blocked == 'existing_scenes':
        job['scenes'] = [{'state': 'not_submitted'}]
        quoted.service.save(job)
    else:
        job['state'] = blocked
        quoted.service.save(job)
    assert quoted.post() == 409
    assert quoted.state.calls == [] and quoted.state.native == 0


@pytest.mark.parametrize('failure', ['upload', 'estimate'])
def test_failed_or_unknown_call_is_claimed_before_io_and_cannot_be_retried(quoted, failure):
    quoted.state.fail = failure
    assert quoted.post() == 409
    receipt = latest_receipt(quoted)
    assert receipt['state'] == 'failed_or_unknown' and receipt['calls'][failure] == 1
    assert receipt['generation_requests'] == 0
    calls = list(quoted.state.calls)
    native = quoted.state.native
    assert calls == (['upload'] if failure == 'upload' else ['upload', 'estimate'])
    # A repeat without an explicit user settings reset cannot contact the supplier.
    assert quoted.post() == 409
    assert quoted.state.calls == calls and quoted.state.native == native
    assert latest_receipt(quoted) == receipt
    assert_old_state_unchanged(quoted)


@pytest.mark.parametrize('method,suffix', [('GET', 'prepare'), ('POST', 'prepare/'),
                                         ('POST', 'submit'), ('POST', 'check'), ('POST', 'retry-quote')])
def test_only_exact_post_prepare_is_intercepted_and_normal_boundary_remains(quoted, method, suffix):
    path = f'/character/{quoted.identifier}/{suffix}'
    assert quoted.post(path=path, method=method) == 202
    assert quoted.state.normal == [(method, path)] and quoted.state.authenticated == 0
    assert quoted.state.calls == [] and quoted.state.native == 0
    quoted.service.prepare(quoted.identifier, consent=True, script_reviewed=True)
    assert len(quoted.state.original) == 1
    assert not receipts(quoted)


def test_key_access_requires_exact_prepare_context_profile_and_entropy_and_is_read_only(quoted):
    with pytest.raises(CharacterError):
        quoted.scope.keys.key()
    with pytest.raises(CredentialError):
        quoted.scope.keys.save(KEY)
    with pytest.raises(CredentialError):
        quoted.scope.keys.clear()
    with pytest.raises(CredentialError):
        quoted.scope.keys._cipher.protect(bytearray(b'synthetic'), bytearray())
    assert quoted.state.native == 0

    def inside(scope):
        count = quoted.state.native
        with pytest.raises(CredentialError):
            scope.keys._cipher.unprotect(bytearray(b'synthetic'), bytearray(b'foreign entropy'))
        original = scope.keys.path
        scope.keys.path = quoted.profile.parent/'foreign-video-ai-key.dpapi'
        try:
            with pytest.raises(CredentialError):
                scope.keys.key()
        finally:
            scope.keys.path = original
        assert quoted.state.native == count

    quoted.state.inside = inside
    assert quoted.post() == 200
    with pytest.raises(CharacterError):
        quoted.state.clients[0].credential()
    assert m._REQUEST.get() is None and m._ACTIVE.get() is None


def test_quote_adapter_blocks_submit_status_and_fetch_even_inside_authorized_prepare(quoted):
    def inside(scope):
        wrapped = m._Client(scope, quoted.state.clients[0])
        for action in (wrapped.submit_scene, wrapped.check, wrapped.fetch):
            with pytest.raises(CharacterError):
                action('synthetic-unused')

    quoted.state.inside = inside
    assert quoted.post() == 200
    assert quoted.state.calls == ['upload', 'estimate']
    assert quoted.scope._read(quoted.identifier)['generation_requests'] == 0
    assert_old_state_unchanged(quoted)
