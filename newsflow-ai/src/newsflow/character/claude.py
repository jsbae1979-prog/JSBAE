"""Reuse the existing single-shot Messages transport; never regenerate on validation failure."""
from newsflow.intelligence.api_providers import AnthropicProvider, _claude_json_object, _output_schema
from newsflow.intelligence.provider import ProviderResponseError, user_message

from .schema import CHARACTER_SCRIPT_INSTRUCTION, Storyboard


class CharacterWriter(AnthropicProvider):
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
