"""Registration → generated topics → chosen writer → video → real local MP4.

All provider envelopes are generated in process; only local FFmpeg executes.
"""
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from newsflow.character.authoring import AuthoringAI, CHARACTER_ANALYSIS_INSTRUCTION, TOPIC_INSTRUCTION
from newsflow.character.episode_story import SCRIPT_INSTRUCTION
from newsflow.character.registry import CharacterRegistry
from newsflow.character.topics import TopicStore
from newsflow.character.kling import DEFAULTS, O3
from newsflow.character.service import CharacterService
from newsflow.creation.image_studio import ImageStudio
from newsflow.video.engine import FFmpegAdapter
from test_character_authoring_v3 import Budget, Store, candidate
from test_character_episode_automation import FakeVideo, image, script


class FakeBudget(Budget):
    def reserve(self, **kwargs):
        result = super().reserve(**kwargs)
        result.reserved_usd = '0.01'
        return result


class FakeEnvelope:
    """The real AuthoringAI validates this Fake Claude/OpenAI response envelope."""
    def __init__(self, provider):
        self.provider, self.calls, self.analysis_count = provider, [], 0
        self.last_usage = None

    def _post(self, body, options):
        self.calls.append(deepcopy(body))
        instruction = body.get('system', body.get('instructions'))
        content = body['messages'][0]['content'] if self.provider == 'claude_api' else body['input'][0]['content']
        text = content if isinstance(content, str) else content[0]['text']
        payload = json.loads(text)
        if instruction == CHARACTER_ANALYSIS_INSTRUCTION:
            result = candidate()
            self.analysis_count += 1
            species = 'rabbit' if self.analysis_count == 1 else 'penguin'
            result.update(species=species, appearance=f'Original {species} with a bright orange scarf')
            for item in result['candidates']:
                item['name_ko'] = species + item['name_ko']
        elif instruction == TOPIC_INSTRUCTION:
            name = payload['character']['name_ko']
            result = {'topics': [{'topic': f'{name}의 소동 {i}', 'category': f'장소{i}',
                                  'joke_type': f'반전{i}'} for i in range(payload['count'])]}
        else:
            assert instruction == SCRIPT_INSTRUCTION
            assert 'appearance' not in payload['character']
            assert 'base64' not in json.dumps(content) and 'image_url' not in json.dumps(content)
            result = script(payload['target_seconds'], payload['character']['name_ko'])
        self.last_usage = {'prompt_tokens': 10, 'completion_tokens': 30}
        encoded = json.dumps(result, ensure_ascii=False)
        if self.provider == 'claude_api':
            return {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': encoded}]}
        return {'status': 'completed', 'output': [{'type': 'message',
                'content': [{'type': 'output_text', 'text': encoded}]}]}


@pytest.mark.parametrize('target,selected,provider,model', [
    (15, 0, 'claude_api', 'claude-sonnet-4-6'),
    (35, 1, 'openai', 'gpt-4.1-mini'),
    (60, 0, 'claude_api', 'claude-sonnet-4-6'),
])
def test_registered_characters_and_generated_topics_reach_final_mp4(tmp_path, target, selected, provider, model):
    images = ImageStudio(None, tmp_path, None)
    registry, topics = CharacterRegistry(tmp_path, images), TopicStore(tmp_path)
    transport, budget = FakeEnvelope(provider), FakeBudget()
    authoring = AuthoringAI({provider: Store()}, budget, {provider: transport})
    profiles, topic_rows = [], []
    for index, color in enumerate(('blue', 'green')):
        raw = image(color)
        analysis = authoring.analyze(raw, provider=provider, model=model,
                                    request_id=f'analysis:{index}', consent=True)
        # User chooses a candidate and may edit it before registration.
        chosen = analysis['candidates'][0]
        saved = registry.save({**chosen, 'species': analysis['species'], 'appearance': analysis['appearance'],
                               'style_lock': analysis['style_suggestion']}, images.asset_bytes(raw))
        profiles.append(saved)
        generated = authoring.topics(saved, 5, [], provider=provider, model=model,
                                    request_id=f'topics:{index}', consent=True)
        topic_rows.append(topics.save_generated(saved['id'], generated, 5))
    assert len(registry.list()) == 2
    assert profiles[0]['asset'] != profiles[1]['asset']
    selected_profile, other = profiles[selected], profiles[1-selected]
    topic = topic_rows[selected][0]
    assert other['name_ko'] not in json.dumps(topics.list(selected_profile['id']), ensure_ascii=False)

    ffmpeg = FFmpegAdapter.executable('ffmpeg', None)
    ffprobe = FFmpegAdapter.executable('ffprobe', None)
    settings = {**DEFAULTS, 'video_model': O3, 'native_resolution': 'std', 'duration': target,
                'sound': 'on', 'script_model': model}
    video = FakeVideo(settings, tmp_path, ffmpeg)
    service = CharacterService(tmp_path, None, SimpleNamespace(key=lambda: 'fake'),
                               video=video, ffmpeg=ffmpeg, ffprobe=ffprobe)
    service.authoring = authoring
    identifier, created = service.create_episode(topic['topic'], '5',
        reference=images.asset(selected_profile['asset']).read_bytes(), settings=settings,
        request_id=uuid4().hex, profile=registry.snapshot(selected_profile['id']))
    assert created
    service.write(identifier, consent=True)
    topics.update_status(selected_profile['id'], topic['id'], 'scripted', topic['revision'])
    service.prepare(identifier, consent=True, script_reviewed=True)
    quoted = service.read(identifier)
    service.submit(identifier, consent=True, quote_hash=quoted['quote_hash'])
    for _ in range(len(quoted['scenes'])+1):
        if service.read(identifier)['state'] == 'clips_review': break
        service.check(identifier, consent=True)
    assert service.read(identifier)['state'] == 'clips_review'
    for payload, _ in video.sent:
        assert selected_profile['appearance'] in payload['prompt']
        assert other['appearance'] not in payload['prompt']
        assert 'no dialogue, no voices, no music' in payload['prompt'].lower()
        assert 'lip sync' not in payload['prompt'] and 'Korean' not in payload['prompt']
    output = service.render(identifier, reviewed=True)
    final = service.read(identifier)
    assert output.is_file() and abs(final['output']['media']['duration']-target) <= .1
    assert (final['output']['media']['width'], final['output']['media']['height']) == (1080, 1920)
    assert len(final['scenes']) == {15: 2, 35: 3, 60: 4}[target]
    assert final['character_id'] == selected_profile['id']
    assert final['script']['title'].startswith(selected_profile['name_ko'])
    assert topics.list(other['id'])[0]['status'] == 'new'
    assert len(transport.calls) == 5  # Two analyses, two topic batches, one script.
    assert len(budget.finished) == 5 and all(row[1]['status'] == 'success' for row in budget.finished)
