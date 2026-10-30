"""Approved episode wrappers, synthetic owned media, and Fake provider IO only."""
from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from bat_distribution import character_manual_execution as m
from bat_distribution import character_quote_only as q
from newsflow.character.episode_service import EpisodeFlow
from newsflow.character.kling import KlingClient, O3, snapshot, check as settings_for
from newsflow.character.schema import CharacterError
from newsflow.character.service import digest
from newsflow.video.ai.contracts import ClipStatus, ProviderAmbiguousSubmit
from newsflow.video.ai.keys import VideoAIKeyStore
from newsflow.video.engine import FFmpegAdapter
from newsflow.video_models.catalog import CATALOG
from test_character_episode_automation import setup_episode
from test_character_episode_schema import image


@pytest.fixture
def episode(tmp_path, monkeypatch):
    monkeypatch.setattr(FFmpegAdapter, 'executable', staticmethod(lambda *a: Path('synthetic-tool.exe')))
    service, _, identifier, _, _ = setup_episode(tmp_path)
    service.write(identifier, consent=True)
    profile = service.root.parent
    (profile / VideoAIKeyStore.FILE).write_bytes(b'owned synthetic cipher')
    state = SimpleNamespace(key='synthetic-only', calls=[], price='0.10', status='completed', failure=None,
                            frame_fault=None, fetch_failed=False)

    class Native:
        def unprotect(self, payload, entropy):
            assert bytes(payload) == b'owned synthetic cipher'
            assert bytes(entropy) == hashlib.sha256(VideoAIKeyStore.ENTROPY).digest()
            return bytearray(state.key.encode())

    class FakeKling(KlingClient):
        def upload_reference(self, path):
            assert self.credential() == state.key
            state.calls.append(('upload', Path(path).name))
            return 'https://example.com/' + Path(path).name
        def estimate(self, payload):
            assert self.credential() == state.key
            state.calls.append(('estimate', deepcopy(payload)))
            return state.price
        def submit_scene(self, payload, key):
            assert self.credential() == state.key
            state.calls.append(('submit', key, deepcopy(payload)))
            if state.failure == 'submit':
                raise ProviderAmbiguousSubmit()
            return {'request_id': key, 'status_url': 'https://api.higgsfield.ai/requests/' + key + '/status'}
        def check(self, handle):
            assert self.credential() == state.key
            state.calls.append(('check', handle['request_id']))
            return ClipStatus(state.status, 'https://example.com/owned-clip.mp4')
        def fetch(self, status, target, cancel):
            state.calls.append(('fetch', target.name))
            if state.failure == 'fetch' and not state.fetch_failed:
                state.fetch_failed = True
                target.write_bytes(b'owned partial')
                raise ConnectionError('synthetic incomplete transfer')
            target.write_bytes(b'owned synthetic clip')

    def last_frame(flow, job, parent):
        folder = flow.owner.folder(job['id'])
        frames = folder / 'frames'
        frames.mkdir(exist_ok=True)
        target = frames / f'scene-{parent["position"]}-t{parent["attempt"]}-last.png'
        target.write_bytes(image())
        parent['last_frame_sha256'] = digest(target)
        flow.owner.save(job)
        if state.frame_fault == 'foreign':
            return folder / 'reference.png'
        if state.frame_fault == 'frame_hash':
            target.write_bytes(image('red'))
        if state.frame_fault == 'clip_hash':
            (folder / parent['file']).write_bytes(b'changed foreign clip')
        return target

    monkeypatch.setattr(q, 'KlingClient', FakeKling)
    monkeypatch.setattr(m, 'KlingClient', FakeKling)
    monkeypatch.setattr(EpisodeFlow, 'last_frame', last_frame)
    monkeypatch.setattr('newsflow.character.episode_service.probe_clip',
                        lambda *a: {'duration': 7, 'width': 144, 'height': 256, 'has_audio': True})
    app = SimpleNamespace(state=SimpleNamespace(character=service, config=SimpleNamespace(data_dir=profile)))
    quote = q.install(app, profile, Native)
    manual = m.install(app, profile, Native)

    def act(action, **kwargs):
        if action == 'prepare':
            token = q._REQUEST.set((quote, identifier))
            try:
                return service.prepare(identifier, consent=True, script_reviewed=True)
            finally:
                q._REQUEST.reset(token)
        token = m._REQUEST.set((manual, identifier, action))
        try:
            if action == 'submit':
                kwargs.setdefault('quote_hash', service.read(identifier)['quote_hash'])
            return getattr(service, action)(identifier, consent=True, **kwargs)
        finally:
            m._REQUEST.reset(token)

    return SimpleNamespace(service=service, identifier=identifier, state=state, act=act,
                           manual=manual, quote=quote, folder=service.folder(identifier))


def sent(x):
    return [row for row in x.state.calls if row[0] == 'submit']


def test_approved_quote_cut_then_verified_continuation_completes_without_new_ai(episode):
    x = episode
    x.act('prepare')
    assert [c[0] for c in x.state.calls] == ['upload', 'estimate', 'estimate']
    assert not sent(x)
    x.act('submit')
    assert len(sent(x)) == 1
    assert x.service.read(x.identifier)['scenes'][1]['state'] == 'waiting_dependency'
    x.act('check')
    rows = x.service.read(x.identifier)['scenes']
    assert [r['state'] for r in rows] == ['downloaded', 'submitted']
    assert len(sent(x)) == 2
    assert sent(x)[1][1] == x.identifier + '-s2-t1'
    assert sent(x)[1][2]['first_frame_url'].endswith('/scene-1-t1-last.png')
    assert sent(x)[1][2]['image_urls'] == [rows[1]['quoted_reference']]
    assert rows[1]['dependency']['clip_sha256'] == rows[0]['sha256']
    assert rows[1]['dependency']['frame_sha256'] == rows[0]['last_frame_sha256']
    x.act('check')
    assert x.service.read(x.identifier)['state'] == 'clips_review'
    assert len(x.service.authoring.calls) == 1
    before = deepcopy(x.state.calls)
    with pytest.raises(CharacterError):
        x.act('check')
    assert x.state.calls == before
    assert m._ACTIVE.get() is None and q._PAYLOADS.get() is None


def test_continuation_price_increase_requires_new_approval_not_automatic_post(episode):
    x = episode
    x.act('prepare'); x.act('submit')
    x.state.price = '0.11'
    with pytest.raises(CharacterError):
        x.act('check')
    assert x.service.read(x.identifier)['scenes'][1]['state'] == 'dependency_quote_changed'
    before = deepcopy(x.state.calls)
    x.act('check')
    assert len(sent(x)) == 1 and x.state.calls == before


@pytest.mark.parametrize('result', ['unknown', 'failed'])
def test_unknown_or_failed_parent_is_never_reposted_or_used_for_continuation(episode, result):
    x = episode
    x.act('prepare')
    if result == 'unknown':
        x.state.failure = 'submit'
        with pytest.raises(CharacterError):
            x.act('submit')
    else:
        x.act('submit')
        x.state.status = 'failed'
    x.act('check'); x.act('check')
    job = x.service.read(x.identifier)
    assert job['scenes'][0]['state'] == result
    assert job['scenes'][1]['state'] == 'waiting_dependency'
    assert len(sent(x)) == 1
    assert len([r for r in x.state.calls if r[0] == 'upload']) == 1


@pytest.mark.parametrize('fault', ['foreign', 'frame_hash', 'clip_hash'])
def test_continuation_rejects_foreign_or_changed_owned_media_before_upload(episode, fault):
    x = episode
    x.act('prepare'); x.act('submit')
    x.state.frame_fault = fault
    with pytest.raises(CharacterError):
        x.act('check')
    assert len(sent(x)) == 1
    assert len([r for r in x.state.calls if r[0] == 'upload']) == 1
    assert x.service.read(x.identifier)['scenes'][1]['state'] == 'dependency_failed'


def test_continuation_rejects_payload_changes_beyond_start_frame(episode, monkeypatch):
    x = episode
    x.act('prepare'); x.act('submit')
    original = EpisodeFlow.with_start
    def changed(flow, job, payload, url):
        return {**original(flow, job, payload, url), 'prompt': 'unapproved changed request'}
    monkeypatch.setattr(EpisodeFlow, 'with_start', changed)
    with pytest.raises(CharacterError):
        x.act('check')
    assert len(sent(x)) == 1
    assert len([r for r in x.state.calls if r[0] == 'estimate']) == 2


def test_continuation_respects_current_episode_exposure(episode):
    x = episode
    x.act('prepare'); x.act('submit')
    job = x.service.read(x.identifier)
    job['text_reservations'] = [{'attempt': 'synthetic', 'usd': '4.90'}]
    x.service.save(job)
    with pytest.raises(CharacterError):
        x.act('check')
    assert len(sent(x)) == 1
    assert len([r for r in x.state.calls if r[0] == 'upload']) == 1


def test_explicit_check_recovers_owned_download_without_resubmitting_parent(episode):
    x = episode
    x.act('prepare'); x.act('submit')
    x.state.failure = 'fetch'
    with pytest.raises(CharacterError):
        x.act('check')
    failed = x.service.read(x.identifier)
    assert failed['state'] == 'status_or_download_failed'
    assert failed['scenes'][0]['state'] == 'downloading'
    x.act('check')
    recovered = x.service.read(x.identifier)['scenes'][0]
    assert recovered['state'] == 'downloaded'
    archive = x.folder / recovered['partial_downloads'][0]['file']
    assert archive.read_bytes() == b'owned partial'
    assert [r[1] for r in sent(x)] == [x.identifier + '-s1-t1', x.identifier + '-s2-t1']
    x.act('check')
    assert x.service.read(x.identifier)['state'] == 'clips_review'


def test_registered_catalog_model_not_old_two_model_allowlist(episode, monkeypatch):
    x = episode
    catalog = CATALOG.refresh()
    model = deepcopy(CATALOG.model(O3))
    model['id'] = 'synthetic-video/approved/image-reference'
    model['label'] = 'Synthetic catalog model'
    catalog['models'].append(model)
    monkeypatch.setattr(CATALOG, '_data', catalog)
    job = x.service.read(x.identifier)
    settings = {**settings_for(job['studio_selection']), 'video_model': model['id']}
    job.update(studio_selection=snapshot(settings), model=model['id'])
    job['plan_hash'] = x.service.plan_hash(job)
    x.service.save(job)
    x.act('prepare'); x.act('submit'); x.act('check'); x.act('check')
    assert x.service.read(x.identifier)['state'] == 'clips_review'
    assert len(sent(x)) == 2


def test_initial_quote_cannot_estimate_an_unplanned_payload(episode, monkeypatch):
    x = episode
    original = EpisodeFlow.with_start
    def changed(flow, job, payload, url):
        return {**original(flow, job, payload, url), 'duration': 9}
    monkeypatch.setattr(EpisodeFlow, 'with_start', changed)
    with pytest.raises(CharacterError):
        x.act('prepare')
    assert len([r for r in x.state.calls if r[0] == 'estimate']) == 1
    assert not sent(x)


def test_changed_account_key_cannot_start_a_continuation_from_previous_quote(episode):
    x = episode
    x.act('prepare'); x.act('submit')
    x.state.key = 'synthetic-new-account-key'
    with pytest.raises(CharacterError):
        x.act('check')
    assert len(sent(x)) == 1
    assert len([r for r in x.state.calls if r[0] == 'upload']) == 1
    assert len([r for r in x.state.calls if r[0] == 'estimate']) == 2
    assert x.service.read(x.identifier)['scenes'][1]['state'] == 'dependency_failed'
