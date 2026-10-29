"""Only synthetic persisted jobs and fake provider IO; no app or network startup."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode

import pytest

from bat_distribution import character_manual_execution as m
from bat_distribution import character_quote_only as q
from bat_distribution.lifecycle import Blocked
from newsflow.character.kling import K3, O3, KlingClient
from newsflow.character.schema import CharacterError
from newsflow.character.service import fingerprint, now
from newsflow.intelligence.credentials import CredentialError
from newsflow.video.ai.contracts import ClipStatus, ProviderAmbiguousSubmit
from newsflow.video.ai.keys import VideoAIKeyStore
from test_api_settings import sessions, store
from test_character_kling_studio import studio
from test_character_single_video import seeded

KEY = 'synthetic-only'


@pytest.fixture
def execution(studio, monkeypatch, request):
    service = studio.service
    identifier, _, _ = seeded(studio, duration=30, model=getattr(request, 'param', O3))
    service.prepare(identifier, consent=True, script_reviewed=True)
    quoted = service.read(identifier)
    profile = service.root.parent
    (profile/VideoAIKeyStore.FILE).write_bytes(b'synthetic protected bytes')
    state = SimpleNamespace(calls=[], native=0, normal=[], authenticated=0, fail=None,
                            status='completed', clients=[], inside=None)

    class Native:
        def unprotect(self, payload, entropy):
            assert bytes(payload) == b'synthetic protected bytes'
            assert bytes(entropy) == hashlib.sha256(VideoAIKeyStore.ENTROPY).digest()
            state.native += 1
            return bytearray(KEY.encode())

    class FakeKling(KlingClient):
        def __init__(self, credential, settings):
            super().__init__(credential, settings)
            state.clients.append(self)
        def submit_scene(self, payload, idempotency_key):
            assert self.credential() == KEY
            state.calls.append(('submit', idempotency_key, deepcopy(payload)))
            if state.inside:
                state.inside(manual)
            if state.fail == 'submit':
                raise ProviderAmbiguousSubmit()
            return {'request_id': idempotency_key,
                    'status_url': f'https://api.higgsfield.ai/requests/{idempotency_key}/status'}
        def check(self, handle):
            assert self.credential() == KEY
            state.calls.append(('check', handle['request_id']))
            if state.fail == 'check':
                raise ConnectionError('synthetic status failure')
            return ClipStatus(state.status, 'https://example.com/synthetic.mp4')
        def fetch(self, status, target, cancel):
            state.calls.append(('fetch', target.name))
            if state.fail == 'fetch':
                raise ConnectionError('synthetic download failure')
            target.write_bytes(b'synthetic media only')
        def upload_reference(self, *args):
            pytest.fail('submit/check must not upload the reference again')
        def estimate(self, *args):
            pytest.fail('submit/check must not create a new quote')

    monkeypatch.setattr(m, 'KlingClient', FakeKling)
    monkeypatch.setattr('newsflow.character.service.probe_clip',
                        lambda *args: {'duration': 6, 'width': 720, 'height': 1280, 'has_audio': True})
    app = SimpleNamespace(state=SimpleNamespace(character=service, config=SimpleNamespace(data_dir=profile)))
    quote = q.install(app, profile, Native)
    manual = m.install(app, profile, Native)

    async def normal(environ, receive, send):
        state.normal.append((environ['method'], environ['path']))
        await send({'type': 'http.response.start', 'status': 202, 'headers': []})

    async def authenticated(environ, receive, send):
        state.authenticated += 1
        headers = dict(environ['headers'])
        values = parse_qs((await receive())['body'].decode())
        status = 403
        if (headers.get(b'x-synthetic-auth') == b'yes'
                and headers.get(b'origin') == b'http://127.0.0.1:18768'
                and values.get('csrf_token') == ['synthetic-csrf']):
            try:
                action = environ['path'].rsplit('/', 1)[-1]
                job_id = environ['path'].split('/')[2]
                kwargs = {'consent': values.get('consent') == ['true']}
                if action == 'submit':
                    kwargs['quote_hash'] = values.get('quote_hash', [''])[0]
                if action == 'prepare':
                    kwargs['script_reviewed'] = True
                getattr(service, action)(job_id, **kwargs)
                status = 200
            except (CharacterError, CredentialError, OSError):
                status = 409
        await send({'type': 'http.response.start', 'status': status, 'headers': []})

    def post(action='submit', *, path=None, method='POST', auth=True, csrf=True,
             origin='http://127.0.0.1:18768', consent=True, quote_hash=None, job_id=None):
        values = {'consent': 'true' if consent else 'false',
                  'quote_hash': quoted['quote_hash'] if quote_hash is None else quote_hash,
                  'csrf_token': 'synthetic-csrf' if csrf else 'wrong'}
        body = urlencode(values).encode()
        messages = []
        async def receive():
            return {'type': 'http.request', 'body': body, 'more_body': False}
        async def send(message):
            messages.append(message)
        environ = {'type': 'http', 'method': method,
                   'path': path or f'/character/{job_id or identifier}/{action}',
                   'headers': [(b'x-synthetic-auth', b'yes' if auth else b'no'), (b'origin', origin.encode())]}
        coroutine = manual.wrap(quote.wrap(normal, authenticated), authenticated)(environ, receive, send)
        with pytest.raises(StopIteration):
            coroutine.send(None)
        return messages[0]['status']

    return SimpleNamespace(service=service, studio=studio, profile=profile, identifier=identifier,
                           quoted=quoted, manual=manual, state=state, post=post, app=app, Native=Native)


@pytest.mark.parametrize('execution', [K3, O3], indirect=True)
def test_approved_five_scene_submission_status_download_and_review(execution):
    x = execution
    assert x.service._manual_character_execution_enabled is True
    assert x.service._operating_quote_only is True
    assert x.post() == 200
    assert x.service.read(x.identifier)['state'] == 'generating'
    submits = [row for row in x.state.calls if row[0] == 'submit']
    assert len(submits) == 5 and [row[2]['duration'] for row in submits] == [6]*5
    assert x.post('check') == 200
    job = x.service.read(x.identifier)
    assert job['state'] == 'clips_review' and all(s['state'] == 'downloaded' for s in job['scenes'])
    assert [s['sha256'] for s in job['scenes']] == [hashlib.sha256(b'synthetic media only').hexdigest()]*5
    assert x.studio.writer.calls == 0
    before = list(x.state.calls)
    assert x.post() == x.post('check') == 409
    assert x.state.calls == before
    assert m._REQUEST.get() is None and m._ACTIVE.get() is None


@pytest.mark.parametrize('kwargs', [{'auth': False}, {'csrf': False}, {'origin': 'https://example.com'}])
def test_auth_csrf_origin_rejection_precedes_credentials_and_generation(execution, kwargs):
    assert execution.post(**kwargs) == 403
    assert execution.state.calls == [] and execution.state.native == 0
    assert execution.service.read(execution.identifier) == execution.quoted


@pytest.mark.parametrize('kwargs', [{'consent': False}, {'quote_hash': 'wrong'}])
def test_explicit_consent_and_exact_quote_are_required(execution, kwargs):
    assert execution.post(**kwargs) == 409
    assert execution.state.calls == [] and execution.state.native == 0


@pytest.mark.parametrize('mutation', ['expired', 'budget', 'reference', 'payload'])
def test_quote_integrity_expiry_per_execution_cap_and_reference_are_preserved(execution, mutation):
    x = execution
    job = x.service.read(x.identifier)
    if mutation == 'expired':
        job['quoted_at'] = (now()-timedelta(minutes=16)).isoformat()
    elif mutation == 'budget':
        job['episode_limit'] = '0.49'
        job['plan_hash'] = x.service.plan_hash(job)
    elif mutation == 'reference':
        (x.service.folder(x.identifier)/'reference.png').write_bytes(b'changed synthetic image')
    else:
        job['scenes'][0]['payload']['prompt'] = 'changed'
    if mutation in {'expired', 'budget'}:
        job['quote_hash'] = fingerprint([job['plan_hash'], job['scenes'], job['quoted_at'], job['quote_key_id']])
    x.service.save(job)
    assert x.post(quote_hash=job['quote_hash']) == 409
    assert x.state.calls == []


def test_unknown_submission_is_saved_and_never_replayed(execution):
    x = execution
    x.state.fail = 'submit'
    assert x.post() == 409
    job = x.service.read(x.identifier)
    assert job['state'] == 'submission_unknown' and job['scenes'][0]['state'] == 'unknown'
    assert len(x.state.calls) == 1
    assert x.post() == x.post('check') == 409
    assert len(x.state.calls) == 1


@pytest.mark.parametrize('failure', ['check', 'fetch'])
def test_status_or_download_failure_stops_without_automatic_retry(execution, failure):
    x = execution
    assert x.post() == 200
    x.state.fail = failure
    assert x.post('check') == 409
    assert x.service.read(x.identifier)['state'] == 'status_or_download_failed'
    before = list(x.state.calls)
    assert x.post('check') == 409
    assert x.state.calls == before


def test_pending_status_can_be_checked_again_without_new_submissions(execution):
    x = execution
    assert x.post() == 200
    x.state.status = 'in_progress'
    assert x.post('check') == 200
    assert x.service.read(x.identifier)['state'] == 'generating'
    x.state.status = 'completed'
    assert x.post('check') == 200
    assert sum(call[0] == 'submit' for call in x.state.calls) == 5


@pytest.mark.parametrize('method,suffix', [('GET', 'submit'), ('POST', 'submit/'), ('POST', 'write'),
                                         ('POST', 'retry-scene'), ('POST', 'fetch'), ('POST', 'render')])
def test_only_exact_submit_and_check_routes_bypass_normal_paid_block(execution, method, suffix):
    path = f'/character/{execution.identifier}/{suffix}'
    assert execution.post(path=path, method=method) == 202
    assert execution.state.normal == [(method, path)]
    assert execution.state.authenticated == 0 and execution.state.native == 0


def test_credentials_and_extra_provider_actions_remain_scope_limited(execution):
    x = execution
    with pytest.raises(CharacterError):
        x.manual.keys.key()
    with pytest.raises(CredentialError):
        x.manual.keys.save(KEY)
    def inside(manual):
        wrapped = m._Client(manual, x.state.clients[-1])
        for action in (wrapped.upload_reference, wrapped.estimate):
            with pytest.raises(CharacterError):
                action('synthetic')
        with pytest.raises(CharacterError):
            wrapped.submit_scene({'unapproved': True}, 'external-id')
        with pytest.raises(CharacterError):
            wrapped.check({'request_id': 'external'})
    x.state.inside = inside
    assert x.post() == 200
    with pytest.raises(CharacterError):
        x.state.clients[0].credential()


def test_separate_approved_jobs_are_not_subject_to_one_trial_or_cumulative_cap(execution):
    x = execution
    assert x.post() == 200
    previous = x.service.read(x.identifier)
    second, _, _ = seeded(x.studio, duration=30, model=O3)
    # Prepare through the same fake product provider, without an external quote.
    from newsflow.character.service import CharacterService
    CharacterService.prepare(x.service, second, consent=True, script_reviewed=True)
    quote = x.service.read(second)
    assert x.post(job_id=second, quote_hash=quote['quote_hash']) == 200
    assert x.service.read(x.identifier) == previous
    assert sum(call[0] == 'submit' for call in x.state.calls) == 10


def test_duplicate_or_trial_installation_is_refused(execution):
    with pytest.raises(CharacterError):
        m.install(execution.app, execution.profile, execution.Native)
    execution.service._manual_character_execution = None
    execution.service._approved_character_trial = object()
    with pytest.raises(CharacterError):
        m.install(execution.app, execution.profile, execution.Native)


@pytest.mark.parametrize('kind,value,expected', [('restored-local-operation', None, False),
    ('restored-local-operation', False, False), ('portable-local-operation', True, True),
    ('synthetic-local-work', True, False)])
def test_layout_explicit_opt_in_and_profile_scope(tmp_path, kind, value, expected):
    (tmp_path/'app').mkdir()
    layout = {} if value is None else {'manualCharacterVideoExecutionEnabled': value}
    (tmp_path/'app/layout.json').write_text(json.dumps(layout), encoding='utf8')
    assert m.enabled(SimpleNamespace(program=tmp_path, profile_kind=kind)) is expected


def test_layout_flag_is_not_truthy_coerced(tmp_path):
    (tmp_path/'app').mkdir()
    (tmp_path/'app/layout.json').write_text(json.dumps({'manualCharacterVideoExecutionEnabled': 'true'}), encoding='utf8')
    with pytest.raises(Blocked):
        m.enabled(SimpleNamespace(program=tmp_path, profile_kind='restored-local-operation'))
