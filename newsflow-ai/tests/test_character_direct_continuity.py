"""One 30-second incident, offline Fake provider and synthetic decoded frames."""
from copy import deepcopy
from uuid import uuid4

from PIL import Image
import pytest

from newsflow.character.compose import run, digest
from newsflow.character.direct_video import make_plan, prompts
from newsflow.character.kling import O3, K3, check, KlingClient
from newsflow.character.schema import CharacterError
from newsflow.video_models.catalog import CATALOG
from test_character_episode_automation import setup_episode
from test_character_episode_schema import image


def ready(tmp_path):
    s, v, old, registry, profile = setup_episode(tmp_path)
    settings = {**check(s.read(old)['studio_selection']), 'duration': 30}
    i, _ = s.create_episode('바람에 날린 모자를 되찾는 캐릭터', '5', reference=image(),
        settings=settings, profile=profile, request_id=uuid4().hex,
        direct_video=True, direct_extension=True)
    s.prepare(i, consent=True, script_reviewed=True)
    return s, v, i


@pytest.mark.parametrize('model_id', [O3, K3])
def test_30_seconds_has_setup_and_continuing_ending_without_a_writer(tmp_path, model_id):
    s, v, old, registry, profile = setup_episode(tmp_path)
    settings = {**check(s.read(old)['studio_selection']), 'video_model': model_id}
    plan = make_plan('같은 사건을 끝까지 이어가는 주제', 30, CATALOG.model(model_id), allow_continuation=True)
    rows = prompts(plan, settings, profile)
    assert [r['seconds'] for r in rows] == [15, 15]
    assert 'do not end or reset' in rows[0]['prompt']
    assert 'clear visual ending' in rows[1]['prompt']
    assert rows[1]['continuation_context']['previous_direction'] == rows[0]['continuation_context']['direction']
    assert rows[1]['continuation_context']['elapsed_seconds'] == 15
    assert 'timeline 15-30s' in rows[1]['prompt'] and 'not observed result' in rows[1]['prompt']
    assert 'visible pose, props, location and unfinished action' in rows[1]['prompt']
    for row in rows:
        assert plan.topic in row['prompt']
        assert 'No dialogue, no voices, no music' in row['prompt']
    native = CATALOG.model(model_id)
    client = KlingClient(lambda: 'synthetic-only', {**settings, 'native_resolution': native['default_resolution']})
    original = 'https://example.com/original.png'
    last = 'https://example.com/verified-last.png'
    payload = client.payload(rows[1]['prompt'], 15, original)
    from newsflow.character.episode_service import EpisodeFlow
    mapped = EpisodeFlow(s).with_start({'model': model_id}, payload, last)
    assert mapped[native['continuation_param']] == last
    if model_id == O3:
        assert mapped['image_urls'] == [original]
    else:
        assert mapped['image_url'] == last and 'first_frame_url' not in mapped
    assert not s.authoring.calls and not v.sent


def test_second_segment_receives_true_final_frame_and_frozen_context(tmp_path):
    s, v, i = ready(tmp_path)
    def fetch(status, path, cancel):
        # A different final frame exposes the historical -0.1s extraction error.
        run([str(v.ffmpeg), '-nostdin', '-n', '-v', 'error', '-f', 'lavfi', '-i',
             "color=c=blue:s=144x256:r=30:d=15,drawbox=color=red:t=fill:enable='eq(n,449)'",
             '-c:v', 'libx264', '-crf', '0', '-pix_fmt', 'yuv420p', str(path)], path.parent)
    v.fetch = fetch
    before = deepcopy(s.read(i)['scenes'][1]['payload'])
    s.submit(i, consent=True, quote_hash=s.read(i)['quote_hash'])
    assert len(v.sent) == 1 and s.read(i)['scenes'][1]['state'] == 'waiting_dependency'
    s.check(i, consent=True)
    job = s.read(i); first, second = job['scenes']
    assert len(v.sent) == 2 and not s.authoring.calls
    frame = s.folder(i)/'frames/scene-1-t1-last.png'
    with Image.open(frame) as picture:
        red, green, blue = picture.convert('RGB').getpixel((72, 128))
    assert red > 200 and blue < 30  # Actual last frame, not a blue near-end frame.
    assert second['dependency']['frame_sha256'] == digest(frame)
    assert second['dependency']['clip_sha256'] == first['sha256']
    assert len(second['dependency']['context_sha256']) == 64
    assert second['payload']['image_urls'] == before['image_urls']  # Original identity reference retained.
    assert {k: x for k, x in second['payload'].items() if k != 'first_frame_url'} == {
        k: x for k, x in before.items() if k != 'first_frame_url'}
    assert v.sent[1][0] == second['payload']


@pytest.mark.parametrize('field', ['context', 'parent_prompt'])
def test_changed_context_never_submits_the_continuation(tmp_path, field):
    s, v, i = ready(tmp_path)
    s.submit(i, consent=True, quote_hash=s.read(i)['quote_hash'])
    job = s.read(i)
    if field == 'context': job['scenes'][1]['continuation_context']['topic'] = '다른 주제'
    else: job['scenes'][0]['prompt'] = 'unrelated instructions'
    with s.lock(): s.save(job)
    with pytest.raises(CharacterError): s.check(i, consent=True)
    assert len(v.sent) == 1 and not s.authoring.calls


@pytest.mark.parametrize('failure', ['failed', 'unknown'])
def test_failed_or_unknown_parent_does_not_start_or_retry_next_segment(tmp_path, failure):
    s, v, i = ready(tmp_path)
    v.unknown = failure == 'unknown'
    v.fail = failure == 'failed'
    if v.unknown:
        with pytest.raises(CharacterError): s.submit(i, consent=True, quote_hash=s.read(i)['quote_hash'])
    else: s.submit(i, consent=True, quote_hash=s.read(i)['quote_hash'])
    s.check(i, consent=True)
    assert len(v.sent) == 1 and s.read(i)['scenes'][1]['state'] == 'waiting_dependency'
    assert not s.authoring.calls


def test_continuation_price_increase_stops_before_second_submit(tmp_path):
    s, v, i = ready(tmp_path)
    s.submit(i, consent=True, quote_hash=s.read(i)['quote_hash'])
    v.estimate = lambda payload: '0.20'
    with pytest.raises(CharacterError): s.check(i, consent=True)
    assert s.read(i)['scenes'][1]['state'] == 'dependency_quote_changed'
    assert len(v.sent) == 1 and not s.authoring.calls
