"""Reuse the existing single-shot Messages transport; never regenerate on validation failure."""
import json

from newsflow.intelligence.api_providers import AnthropicProvider, _claude_json_object, _output_schema
from newsflow.intelligence.provider import ProviderHTTPResponseError, ProviderResponseError, user_message

from .schema import CHARACTER_SCRIPT_INSTRUCTION, Storyboard


def _studio_wire_schema(value):
    """Claude supports minItems 0/1; keep larger bounds in local validation only."""
    if isinstance(value, list):
        return [_studio_wire_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    minimum = value.get('minItems')
    unsupported = type(minimum) is int and minimum > 1
    result = {key: _studio_wire_schema(item) for key, item in value.items()
              if not (unsupported and key == 'minItems')}
    if unsupported:
        result['description'] = (result.get('description', '') + ' Local validation: '
                                 + json.dumps({'minItems': minimum})).strip()
    return result


class CharacterWriter(AnthropicProvider):
    def write_studio(self, payload, options, reference=None):
        """Generate from text only; the compatibility reference argument is never read."""
        from .studio_story import INSTRUCTION, StudioStoryboard
        self.last_usage = None
        self.last_failure = None
        story_input={key:payload[key] for key in ('topic','duration','clip_seconds','scene_count','sound') if key in payload}
        body={'model':options.model,'max_tokens':options.max_tokens,'temperature':options.temperature,
              'system':INSTRUCTION, 'messages':[{'role':'user','content':user_message(story_input)}],
              'output_config':{'format':{'type':'json_schema',
                                       'schema':_studio_wire_schema(_output_schema(StudioStoryboard))}}}
        try:
            document=self._post(body,options)
        except ProviderHTTPResponseError as error:
            # The existing transport already sanitizes these finite diagnostics.
            # Never retain supplier prose, headers, keys or the request/response.
            self.last_failure = error.diagnostics()
            raise
        try:
            if document['stop_reason']!='end_turn' or len(document['content'])!=1:
                raise ValueError
            block=document['content'][0]
            if block['type']!='text': raise ValueError
            return StudioStoryboard.model_validate(_claude_json_object(block['text']))
        except (KeyError,TypeError,ValueError):
            raise ProviderResponseError('스토리 형식 검사 실패 · 자동 재생성하지 않습니다.') from None

    def write(self, payload, options):
        body = {'model': options.model, 'max_tokens': options.max_tokens, 'temperature': options.temperature,
                'system': CHARACTER_SCRIPT_INSTRUCTION,
                'messages': [{'role':'user','content':user_message(payload)}],
                'output_config': {'format': {'type': 'json_schema', 'schema': _output_schema(Storyboard)}}}
        document = self._post(body, options)
        try:
            if document['stop_reason'] != 'end_turn':
                raise ValueError
            blocks = document['content']
            if len(blocks) != 1 or blocks[0]['type'] != 'text':
                raise ValueError
            return Storyboard.model_validate(_claude_json_object(blocks[0]['text']))
        except (KeyError, TypeError, ValueError):
            raise ProviderResponseError('캐릭터 대본 형식 검사 실패 · 자동 재생성하지 않습니다.') from None
