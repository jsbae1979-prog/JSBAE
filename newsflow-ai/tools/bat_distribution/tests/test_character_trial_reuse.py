"""Saved-story scopes use synthetic files/providers only; no app or native startup."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
from io import BytesIO
import json
from types import SimpleNamespace

from PIL import Image
import pytest

from bat_distribution import character_trial as m
from newsflow.character.schema import CharacterError
from test_character_trial import Service, Client, Cipher, Writer, Inner, denied, ID, OTHER, TOPIC


PRIOR_IDS = ['1' * 32, '2' * 32]


class ReuseClient(Client):
    """Records calls without invoking even the synthetic protected-key wrapper."""
    quote = '1.89'

    def upload_reference(self, path):
        self.calls.append('upload')
        return 'https://example.com/synthetic.png'

    def payload(self, prompt, seconds, url):
        result = super().payload(prompt, seconds, url)
        result['sound'] = self.service.jobs[OTHER]['studio_selection']['sound']
        return result

    def estimate(self, payload):
        self.calls.append('estimate')
        return self.quote

    def submit_scene(self, payload, identifier):
        self.calls.append('submit')
        if self.fail_submit:
            raise ConnectionError('synthetic outcome unknown')
        return {'request_id': identifier}


class ReuseService(Service):
    def prepare(self, identifier, **kwargs):
        super().prepare(identifier, **kwargs)
        self.jobs[identifier]['quote_total_usd'] = str(sum(
            (Decimal(scene['quote_usd']) for scene in self.jobs[identifier]['scenes']), Decimal(0)))


@pytest.fixture
def reuse(tmp_path, monkeypatch, request):
    def private(path):
        assert path.is_relative_to(tmp_path)
        path.mkdir(exist_ok=True)
        return path

    monkeypatch.setattr(m, '_private', private)
    monkeypatch.setattr(m, 'CharacterWriter', Writer)
    service = ReuseService(tmp_path)
    budget = service.budget
    budget.rows['historic-unknown'] = ('unknown', None)
    service.client = ReuseClient(service)
    image = BytesIO()
    Image.new('RGB', (128, 128), '#abcdef').save(image, format='PNG')
    raw = image.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    story = {
        'plan': {'situation': '출근', 'contrast': '태평함', 'punchline': '반전'},
        'title': '저장된 이야기', 'hook_caption': '느긋한 아침', 'end_caption': '다음 이야기',
        'scenes': [{'seconds': 3, 'role': role, 'action': 'A character calmly walks through a room.',
                    'caption': f'기존 자막 {index}', 'sfx': '',
                    'narration': '저장된 대사' if index == 0 else ''}
                   for index, role in enumerate(['setup', 'build', 'contrast', 'build', 'punchline'])],
    }
    for identifier in (ID, OTHER):
        (service.folder(identifier)/'reference.png').write_bytes(raw)
        service.jobs[identifier]['reference_sha256'] = digest
    source = service.jobs[ID]
    source.update(state='submission_unknown', script=deepcopy(story), plan_hash=m._hash({'original': 'plan'}),
                  scenes=[{'state': 'unknown', 'reserved_usd': '1.260'}])
    clone = service.jobs[OTHER]
    clone.update(state='script_review', script=deepcopy(story), episode_limit='2.50')
    clone['studio_selection']['sound'] = 'on'
    for scene in clone['script']['scenes']:
        scene['narration'] = scene['narration'].strip() or scene['caption']
    clone['reused_story'] = {
        'source_job_id': ID, 'source_story_sha256': m._hash(story), 'source_plan_hash': source['plan_hash'],
        'source_reference_sha256': digest, 'dialogue_source': 'saved_dialogue_or_caption',
    }
    policy = {
        'schemaVersion': 1, 'id': 'e' * 32,
        'expires_at': (datetime.now(UTC)+timedelta(hours=1)).isoformat(),
        'topic': TOPIC, 'reference_sha256': digest, 'script_model': m.CLAUDE, 'video_model': m.K3,
        'duration': 15, 'clip_seconds': 3, 'scene_count': 5, 'sound': 'on',
        'script_limit_usd': '0', 'video_limit_usd': '2.50', 'total_limit_usd': '3',
        'reuse_source_job_id': ID, 'reuse_story_sha256': m._hash(story), 'prior_trial_ids': PRIOR_IDS.copy(),
    }
    policy.update(getattr(request, 'param', {}))
    parent = tmp_path/'character-trials'
    parent.mkdir()
    prior = []
    for identifier, script, video in ((PRIOR_IDS[0], '0.25', '0'), (PRIOR_IDS[1], '0.25', '1.260')):
        folder = parent/identifier
        folder.mkdir()
        path = folder/'journal.json'
        path.write_text(json.dumps({
            'schemaVersion': 1, 'policy_sha256': 'f' * 64, 'job_id': ID,
            'calls': {'auto-story': 1}, 'native_calls': {}, 'outcomes': {'auto-story': 'failed_or_unknown'},
            'script': {'state': 'unknown_or_over_limit', 'reserved_usd': script},
            'video': {'state': 'reserved' if video != '0' else 'unspent', 'reserved_usd': video},
        }), encoding='utf8')
        (folder/'journal.lock').write_bytes(b'synthetic old lock: leave unchanged')
        prior.append(path)
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
              for folder in parent.iterdir() for path in folder.iterdir()}
    native = Cipher()
    trial = m.install(SimpleNamespace(state=SimpleNamespace(character=service)), tmp_path, policy, lambda: native)
    inner = Inner(service)
    def post(path):
        messages = []

        async def receive():
            return {'type': 'http.request', 'body': b'', 'more_body': False}

        async def send(message):
            messages.append(message)

        request = trial.wrap(denied, inner)({'type': 'http', 'method': 'POST', 'path': path}, receive, send)
        # These denied paths finish synchronously, without an event loop or OS sockets.
        with pytest.raises(StopIteration):
            request.send(None)
        return messages[0]['status']

    def invoke(action, identifier=OTHER):
        token = m._CONTEXT.set(SimpleNamespace(trial=trial, action=action, job_id=identifier))
        try:
            return getattr(service, {'auto-story': 'write'}.get(action, action))(
                identifier, consent=True, reviewed=True, script_reviewed=True)
        finally:
            m._CONTEXT.reset(token)

    return SimpleNamespace(trial=trial, service=service, policy=policy, root=tmp_path, invoke=invoke,
                           native=native, budget=budget, prior=prior, prior_before=before,
                           source_before=deepcopy(source), post=post, inner=inner)


def row(sample):
    return json.loads(sample.trial.path.read_bytes())


def assert_originals_unchanged(sample):
    assert sample.service.jobs[ID] == sample.source_before
    assert sample.budget.rows == {'historic-unknown': ('unknown', None)}
    assert sample.budget.calls == [] and sample.native.calls == 0
    for path, (contents, modified) in sample.prior_before.items():
        assert path.read_bytes() == contents and path.stat().st_mtime_ns == modified


def test_quote_only_reuse_has_zero_claude_reservation_and_binds_one_new_job(reuse):
    assert row(reuse)['job_id'] is None
    assert row(reuse)['script'] == {'state': 'reused', 'reserved_usd': '0',
                                   'source_job_id': ID, 'source_story_sha256': reuse.policy['reuse_story_sha256']}
    reuse.invoke('prepare')
    journal = row(reuse)
    assert journal['job_id'] == OTHER
    assert journal['calls'] == {'prepare': 1} and journal['outcomes'] == {'prepare': 'success'}
    assert journal['native_calls'] == {'upload': 1, 'estimate': 1}
    assert reuse.service.jobs[OTHER]['scenes'][0]['payload']['sound'] == 'on'
    assert len(reuse.service.jobs[OTHER]['scenes']) == 1
    assert reuse.service.jobs[OTHER]['scenes'][0]['payload']['duration'] == 15
    assert reuse.trial.prior_exposure() == Decimal('1.760')
    with pytest.raises(CharacterError):
        reuse.invoke('prepare')
    assert_originals_unchanged(reuse)


@pytest.mark.parametrize('reuse', [{}, {'allow_submit': False}, {'total_limit_usd': '4.50'}], indirect=True)
def test_quote_only_default_denies_submit_before_counters_or_exposure_are_written(reuse):
    reuse.invoke('prepare')
    before = reuse.trial.path.read_bytes()
    with pytest.raises(CharacterError):
        reuse.invoke('submit')
    assert reuse.trial.path.read_bytes() == before
    assert row(reuse)['video'] == {'state': 'unspent', 'reserved_usd': '0'}
    assert reuse.service.client.calls == ['upload', 'estimate']
    assert_originals_unchanged(reuse)


@pytest.mark.parametrize('reuse', [{'allow_submit': True}], indirect=True)
def test_three_dollar_total_rejects_prior_one_seventy_six_plus_one_eighty_nine(reuse):
    reuse.invoke('prepare')
    before = reuse.trial.path.read_bytes()
    with pytest.raises(CharacterError):
        reuse.invoke('submit')
    assert reuse.trial.path.read_bytes() == before
    assert 'submit' not in reuse.service.client.calls
    assert_originals_unchanged(reuse)


@pytest.mark.parametrize('reuse', [{'allow_submit': True, 'total_limit_usd': '4.50'}], indirect=True)
def test_explicit_future_submit_scope_accepts_maximum_two_fifty_once_in_synthetic_only(reuse):
    reuse.service.client.quote = '2.50'
    reuse.invoke('prepare')
    reuse.invoke('submit')
    assert row(reuse)['video'] == {'state': 'reserved', 'reserved_usd': '2.50'}
    assert row(reuse)['native_calls']['submit_scene'] == 1
    assert reuse.trial.prior_exposure()+Decimal(row(reuse)['video']['reserved_usd']) == Decimal('4.260')
    reuse.service.jobs[OTHER]['state'] = 'quoted'
    with pytest.raises(CharacterError):
        reuse.invoke('submit')
    assert reuse.service.client.calls.count('submit') == 1
    assert_originals_unchanged(reuse)


@pytest.mark.parametrize('reuse', [{'allow_submit': True, 'total_limit_usd': '4.50'}], indirect=True)
def test_unknown_submit_preserves_reservation_and_no_retry(reuse):
    reuse.invoke('prepare')
    reuse.service.client.fail_submit = True
    with pytest.raises(ConnectionError):
        reuse.invoke('submit')
    assert row(reuse)['video']['reserved_usd'] == '1.89'
    assert row(reuse)['outcomes']['submit'] == 'failed_or_unknown'
    reuse.service.jobs[OTHER]['state'] = 'quoted'
    with pytest.raises(CharacterError):
        reuse.invoke('submit')
    assert reuse.service.client.calls.count('submit') == 1
    assert_originals_unchanged(reuse)


@pytest.mark.parametrize('reuse', [{'allow_submit': True, 'total_limit_usd': '4.50'}], indirect=True)
def test_individual_video_limit_remains_two_fifty(reuse):
    reuse.service.client.quote = '2.51'
    reuse.invoke('prepare')
    with pytest.raises(CharacterError):
        reuse.invoke('submit')
    assert row(reuse)['video']['state'] == 'unspent'
    assert 'submit' not in reuse.service.client.calls


def test_reuse_denies_auto_story_authentication_and_claude_credential_before_inner_or_native(reuse):
    for target in ('/api/studio/characters/auto-story', m._AUTHENTICATE):
        assert reuse.post(target) == 403
    assert reuse.inner.calls == 0
    with pytest.raises(CharacterError):
        reuse.invoke('auto-story')
    token = m._CONTEXT.set(SimpleNamespace(trial=reuse.trial, action='authenticate', job_id=None))
    try:
        with pytest.raises(CharacterError):
            reuse.trial.authenticate(consent=True)
        with pytest.raises(CharacterError):
            reuse.service.keys.key()
    finally:
        m._CONTEXT.reset(token)
    assert row(reuse)['calls'] == {}
    assert_originals_unchanged(reuse)


@pytest.mark.parametrize('mutation', ['source_id', 'story_hash', 'plan_hash', 'reference_hash', 'mode',
                                    'extra_marker', 'action', 'caption', 'source_story', 'sound', 'source_model'])
def test_changed_source_proof_or_non_dialogue_fields_are_rejected(reuse, mutation):
    job = reuse.service.jobs[OTHER]
    marker = job['reused_story']
    if mutation in {'source_id', 'story_hash', 'plan_hash', 'reference_hash'}:
        key = {'source_id': 'source_job_id', 'story_hash': 'source_story_sha256',
               'plan_hash': 'source_plan_hash', 'reference_hash': 'source_reference_sha256'}[mutation]
        marker[key] = '0' * (32 if mutation == 'source_id' else 64)
    elif mutation == 'mode':
        marker['dialogue_source'] = 'unapproved'
    elif mutation == 'extra_marker':
        marker['extra'] = True
    elif mutation in {'action', 'caption'}:
        job['script']['scenes'][0][mutation] = 'Changed action' if mutation == 'action' else '바뀐 자막'
    elif mutation == 'source_story':
        reuse.service.jobs[ID]['script']['title'] = '원본 변경'
    elif mutation == 'source_model':
        reuse.service.jobs[ID]['model'] = 'other/model'
    else:
        job['studio_selection']['sound'] = 'off'
    with pytest.raises(CharacterError):
        reuse.invoke('prepare')
    assert row(reuse)['calls'] == {} and reuse.service.client.calls == []


def test_source_itself_cannot_bind_as_new_job_and_only_one_clone_can_bind(reuse):
    with pytest.raises(CharacterError):
        reuse.trial._valid(ID)
    reuse.invoke('prepare')
    duplicate = 'c' * 32
    reuse.service.jobs[duplicate] = {**deepcopy(reuse.service.jobs[OTHER]), 'id': duplicate, 'state': 'script_review'}
    folder = reuse.service.root/duplicate
    folder.mkdir()
    (folder/'reference.png').write_bytes((reuse.service.folder(OTHER)/'reference.png').read_bytes())
    with pytest.raises(CharacterError):
        reuse.invoke('prepare', duplicate)
    assert row(reuse)['job_id'] == OTHER
    assert reuse.service.client.calls == ['upload', 'estimate']


def test_saved_dialogue_uses_existing_narration_then_caption_user_edits_change_narration_only(reuse):
    reuse.trial._valid(OTHER)
    scenes = reuse.service.jobs[OTHER]['script']['scenes']
    assert scenes[0]['narration'] == '저장된 대사' and scenes[1]['narration'] == scenes[1]['caption']
    scenes[0]['narration'] = '사용자 대사'
    with pytest.raises(CharacterError):
        reuse.trial._valid(OTHER)
    reuse.service.jobs[OTHER]['reused_story']['dialogue_source'] = 'user_edited'
    reuse.trial._valid(OTHER)
    scenes[0]['narration'] = 'English only'
    with pytest.raises(CharacterError):
        reuse.trial._valid(OTHER)


@pytest.mark.parametrize('reuse', [{'sound': 'off'}], indirect=True)
def test_off_policy_requires_blank_narration_and_payload_sound_exactly_off(reuse):
    job = reuse.service.jobs[OTHER]
    job['studio_selection']['sound'] = 'off'
    for scene in job['script']['scenes']:
        scene['narration'] = ''
    reuse.invoke('prepare')
    assert job['scenes'][0]['payload']['sound'] == 'off'
    payload = job['scenes'][0]['payload'].copy()
    payload['sound'] = 'on'
    with pytest.raises(CharacterError):
        m._Client(reuse.trial, reuse.service.client, OTHER)._payload(payload)


def test_sound_on_payload_cannot_be_replaced_with_silent_or_multi_shot_payload(reuse):
    reuse.invoke('prepare')
    payload = reuse.service.jobs[OTHER]['scenes'][0]['payload']
    scoped = m._Client(reuse.trial, reuse.service.client, OTHER)
    for changed in ({**payload, 'sound': 'off'}, {**payload, 'duration': 3}, {**payload, 'multi_shots': True}):
        with pytest.raises(CharacterError):
            scoped._payload(changed)


@pytest.mark.parametrize('target', [ID, OTHER])
def test_changed_reference_png_is_rejected_before_prepare(reuse, target):
    (reuse.service.folder(target)/'reference.png').write_bytes(b'not a PNG')
    with pytest.raises(CharacterError):
        reuse.invoke('prepare')
    assert reuse.service.client.calls == []


def test_omitted_nonzero_prior_journal_or_missing_listed_prior_is_rejected(reuse):
    reuse.trial.policy['prior_trial_ids'] = PRIOR_IDS[:1]
    with pytest.raises(CharacterError):
        reuse.trial.prior_exposure()
    reuse.trial.policy['prior_trial_ids'] = PRIOR_IDS+['3' * 32]
    with pytest.raises(CharacterError):
        reuse.trial.prior_exposure()


@pytest.mark.parametrize('malformation', ['invalid_json', 'missing_video', 'nan', 'negative', 'wrong_schema', 'state'])
def test_malformed_prior_journals_fail_closed_without_writing_them(reuse, malformation):
    path = reuse.prior[0]
    prior = json.loads(path.read_bytes())
    if malformation == 'invalid_json':
        path.write_bytes(b'not json')
    else:
        if malformation == 'missing_video':
            prior.pop('video')
        elif malformation in {'nan', 'negative'}:
            prior['script']['reserved_usd'] = 'NaN' if malformation == 'nan' else '-1'
        elif malformation == 'wrong_schema':
            prior['schemaVersion'] = True
        else:
            prior['script']['state'] = 'invented'
        path.write_text(json.dumps(prior), encoding='utf8')
    before = path.read_bytes()
    with pytest.raises(CharacterError):
        reuse.trial.prior_exposure()
    assert path.read_bytes() == before


def test_prior_reparse_path_is_rejected_without_following_or_locking_it(reuse, monkeypatch):
    original = m._unlinked
    calls = []

    def unlinked(path):
        calls.append(path)
        if path == reuse.prior[0].parent:
            raise ValueError('synthetic-reparse-data-path')
        return original(path)

    monkeypatch.setattr(m, '_unlinked', unlinked)
    with pytest.raises(ValueError, match='synthetic-reparse'):
        reuse.trial.prior_exposure()
    assert reuse.prior[0].parent in calls
    assert_originals_unchanged(reuse)


@pytest.mark.parametrize(('key', 'value'), [
    ('script_limit_usd', '.25'), ('video_limit_usd', '2.75'), ('total_limit_usd', '4.51'),
    ('allow_submit', 'true'), ('allow_submit', 1), ('sound', 'unknown'),
    ('prior_trial_ids', [PRIOR_IDS[0], PRIOR_IDS[0]]), ('unapproved_field', True),
])
def test_reuse_policy_accepts_only_exact_fields_and_explicit_boolean_submit(reuse, key, value):
    with pytest.raises(CharacterError):
        m._policy({**reuse.policy, key: value})


def test_legacy_policy_fields_hash_and_existing_journal_are_preserved(reuse):
    legacy = {k: v for k, v in reuse.policy.items() if k in m._FIELDS}
    legacy.update(id='d' * 32, sound='off', script_limit_usd='.25', video_limit_usd='2.75')
    assert set(m._policy(legacy)) == m._FIELDS
    assert m._hash(m._policy(legacy)) == m._hash(legacy)
    with pytest.raises(CharacterError):
        m._policy({**legacy, 'allow_submit': True})
    trial = m.Trial(reuse.service, reuse.root, legacy)
    with trial.journal() as journal:
        journal['calls']['auto-story'] = 1
        journal['job_id'] = ID
        journal['script'].update(state='unknown_or_over_limit', reserved_usd='0.25')
    before = trial.path.read_bytes()
    again = m.Trial(reuse.service, reuse.root, legacy)
    assert again.path.read_bytes() == before and again.reuse is False
    changed = {**legacy, 'topic': '다른 승인'}
    with pytest.raises(CharacterError):
        m.Trial(reuse.service, reuse.root, changed)
    assert trial.path.read_bytes() == before


def test_policy_loader_adds_only_explicit_submit_overlay_without_resetting_base_hash_or_quote(reuse):
    base = deepcopy(reuse.trial.policy)
    base_hash = reuse.trial.policy_hash
    upgraded = {**base, 'allow_submit': True, 'total_limit_usd': '4.50'}
    reloads = []

    def loader():
        reloads.append('explicit-policy-read')
        return deepcopy(upgraded)

    reuse.trial.policy_loader = loader
    reuse.service.client.quote = '2.50'
    reuse.invoke('prepare')
    assert reloads == []
    reuse.invoke('submit')
    journal = row(reuse)
    assert reloads == ['explicit-policy-read']
    assert reuse.trial.policy == base and reuse.trial.policy_hash == base_hash
    assert journal['policy_sha256'] == base_hash
    assert journal['calls'] == {'prepare': 1, 'submit': 1}
    assert journal['native_calls'] == {'upload': 1, 'estimate': 1, 'submit_scene': 1}
    assert journal['video'] == {'state': 'reserved', 'reserved_usd': '2.50'}
    assert journal['submit_approval'] == {
        'from_sha256': base_hash, 'to_sha256': m._hash(upgraded),
        'changes': {'allow_submit': {'from': False, 'to': True},
                    'total_limit_usd': {'from': '3', 'to': '4.50'}},
    }
    assert_originals_unchanged(reuse)


@pytest.mark.parametrize(('key', 'value'), [
    ('id', 'd' * 32), ('topic', '다른 주제'), ('reference_sha256', '0' * 64),
    ('reuse_source_job_id', 'c' * 32), ('reuse_story_sha256', '0' * 64),
    ('prior_trial_ids', PRIOR_IDS[:1]), ('sound', 'off'), ('duration', 30),
    ('video_model', 'other/model'), ('script_model', 'other-script'),
    ('expires_at', (datetime.now(UTC)+timedelta(hours=2)).isoformat()),
])
def test_reload_cannot_change_any_immutable_scope_field(reuse, key, value):
    upgraded = {**reuse.policy, 'allow_submit': True, 'total_limit_usd': '4.50', key: value}
    reuse.trial.policy_loader = lambda: upgraded
    reuse.invoke('prepare')
    before = reuse.trial.path.read_bytes()
    with pytest.raises(CharacterError):
        reuse.invoke('submit')
    assert reuse.trial.path.read_bytes() == before
    assert reuse.service.client.calls == ['upload', 'estimate']
    assert_originals_unchanged(reuse)


@pytest.mark.parametrize(('allowed', 'total'), [(True, '3'), (False, '4.50'), (False, '3')])
def test_reload_invalid_scope_or_unaffordable_total_never_claims_submit(reuse, allowed, total):
    reuse.trial.policy_loader = lambda: {**reuse.policy, 'allow_submit': allowed, 'total_limit_usd': total}
    reuse.invoke('prepare')
    before = reuse.trial.path.read_bytes()
    with pytest.raises(CharacterError):
        reuse.invoke('submit')
    assert reuse.trial.path.read_bytes() == before
    assert 'submit_approval' not in row(reuse)


def test_reload_failure_is_closed_without_claiming_submit_or_recording_diagnostics(reuse):
    def loader():
        raise OSError('private synthetic policy location')

    reuse.trial.policy_loader = loader
    reuse.invoke('prepare')
    before = reuse.trial.path.read_bytes()
    with pytest.raises(CharacterError):
        reuse.invoke('submit')
    assert reuse.trial.path.read_bytes() == before
    assert 'private' not in reuse.trial.path.read_text(encoding='utf8')


def test_unknown_or_prior_submit_blocks_before_loader_and_preserves_overlay(reuse):
    reads = []

    def loader():
        reads.append('read')
        return {**reuse.policy, 'allow_submit': True, 'total_limit_usd': '4.50'}

    reuse.trial.policy_loader = loader
    reuse.invoke('prepare')
    reuse.service.client.fail_submit = True
    with pytest.raises(ConnectionError):
        reuse.invoke('submit')
    assert reads == ['read']
    prior = reuse.trial.path.read_bytes()
    reuse.service.jobs[OTHER]['state'] = 'quoted'
    with pytest.raises(CharacterError):
        reuse.invoke('submit')
    assert reads == ['read'] and reuse.trial.path.read_bytes() == prior
    assert row(reuse)['video']['reserved_usd'] == '1.89'
    assert row(reuse)['submit_approval']['from_sha256'] == reuse.trial.policy_hash
    assert reuse.service.client.calls.count('submit') == 1
    assert_originals_unchanged(reuse)


def test_policy_loader_is_optional_callable_and_is_not_read_on_install_or_restart(reuse):
    reads = []
    again = m.Trial(reuse.service, reuse.root, reuse.policy,
                    policy_loader=lambda: reads.append('unexpected-read'))
    assert reads == [] and again.policy_hash == reuse.trial.policy_hash
    with pytest.raises(CharacterError):
        m.Trial(reuse.service, reuse.root, reuse.policy, policy_loader=True)
