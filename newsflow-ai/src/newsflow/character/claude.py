"""Reuse the existing single-shot Messages transport; never regenerate on validation failure."""
from newsflow.intelligence.api_providers import AnthropicProvider, _claude_json_object, _output_schema
from newsflow.intelligence.provider import ProviderResponseError, user_message

from .schema import CHARACTER_SCRIPT_INSTRUCTION, Storyboard


class CharacterWriter(AnthropicProvider):
    def write_studio(self, payload, options, reference=None):
        """Generate from text only; the compatibility reference argument is never read."""
        from .studio_story import INSTRUCTION, StudioStoryboard
        self.last_usage = None
        story_input={key:payload[key] for key in ('topic','duration','clip_seconds','scene_count','sound') if key in payload}
        body={'model':options.model,'max_tokens':options.max_tokens,'temperature':options.temperature,
              'system':INSTRUCTION, 'messages':[{'role':'user','content':user_message(story_input)}],
              'output_config':{'format':{'type':'json_schema','schema':_output_schema(StudioStoryboard)}}}
        document=self._post(body,options)
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
