"""Reuse the existing single-shot Messages transport; never regenerate on validation failure."""
import json

from pydantic import ValidationError

from newsflow.intelligence.api_providers import AnthropicProvider, _claude_json_object, _output_schema
from newsflow.intelligence.provider import ProviderHTTPResponseError, ProviderResponseError, user_message

from .schema import CHARACTER_SCRIPT_INSTRUCTION, Storyboard


_STUDIO_STAGES = frozenset({'stop_reason','envelope','json','schema','timing'})
_STUDIO_STOPS = frozenset({'end_turn','max_tokens','stop_sequence','tool_use','pause_turn','refusal',
                         'model_context_window_exceeded'})
_STUDIO_FIELDS = frozenset({'plan','situation','contrast','punchline','title','hook_caption','scenes',
                          'end_caption','seconds','role','action','caption','sfx','narration'})
_STUDIO_ERROR_TYPES = frozenset({'missing','extra_forbidden','string_type','string_too_short','string_too_long',
    'int_type','int_parsing','greater_than_equal','less_than_equal','literal_error','list_type','too_short',
    'too_long','model_type','value_error','string_pattern_mismatch','scene_count','clip_seconds','total_duration'})


def _studio_diagnostics(stage, stop_reason=None, errors=()):
    result={'failure_stage':stage if isinstance(stage,str) and stage in _STUDIO_STAGES else 'envelope'}
    if stop_reason is not None:
        result['stop_reason']=stop_reason if isinstance(stop_reason,str) and stop_reason in _STUDIO_STOPS else 'other'
    safe=[]
    for error in list(errors or ())[:20]:
        if not isinstance(error,dict):continue
        loc=error.get('loc',())
        if not isinstance(loc,(list,tuple)):loc=()
        kind=error.get('type')
        safe.append({'loc':[part if type(part) is int and 0<=part<=99 else
                             part if isinstance(part,str) and part in _STUDIO_FIELDS else 'unknown_field'
                             for part in loc[:6]],
                     'type':kind if isinstance(kind,str) and kind in _STUDIO_ERROR_TYPES else 'other'})
    if safe:result['validation_errors']=safe
    return result


class StudioResponseError(ProviderResponseError):
    """Bounded story diagnostics only; response values stay outside exceptions."""
    def __init__(self, stage, *, stop_reason=None, errors=()):
        self.details=_studio_diagnostics(stage,stop_reason,errors)
        super().__init__('스토리 형식 검사 실패 · 자동 재생성하지 않습니다.')

    def diagnostics(self):
        return _studio_diagnostics(self.details.get('failure_stage'),self.details.get('stop_reason'),
                                   self.details.get('validation_errors',()))


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


def studio_output_schema(payload):
    """Keep enums on the wire and enforce English action patterns locally.

    https://platform.claude.com/docs/en/build-with-claude/structured-outputs
    """
    from .studio_story import StudioStoryboard
    schema=_studio_wire_schema(_output_schema(StudioStoryboard))
    scene=schema['$defs']['StudioScene']['properties']
    seconds=payload.get('clip_seconds')
    if type(seconds) is int and 3<=seconds<=15:
        scene['seconds']['enum']=[seconds]
    scene['action']['description'] = (scene['action'].get('description', '') + ' English only. No Korean characters.').strip()
    scene['role']['description']='First scene setup; middle scenes build or contrast; final scene punchline.'
    scene['narration']['enum']=['']
    count=payload.get('scene_count')
    if type(count) is int and 3<=count<=5:
        schema['properties']['scenes']['description']+=(
            f' Exactly {count} scenes, each {seconds} seconds; first setup, last punchline, '
            'middle build or contrast. Never omit or add a beat.')
    return schema


class CharacterWriter(AnthropicProvider):
    def write_studio(self, payload, options, reference=None):
        """Generate from text only; the compatibility reference argument is never read."""
        from .studio_story import INSTRUCTION, StudioStoryboard
        self.last_usage = None
        self.last_failure = None
        self.last_candidate = None
        story_input={key:payload[key] for key in ('topic','duration','clip_seconds','scene_count','sound') if key in payload}
        body={'model':options.model,'max_tokens':options.max_tokens,'temperature':options.temperature,
              'system':INSTRUCTION, 'messages':[{'role':'user','content':user_message(story_input)}],
              'output_config':{'format':{'type':'json_schema',
                                       'schema':studio_output_schema(story_input)}}}
        try:
            document=self._post(body,options)
        except ProviderHTTPResponseError as error:
            # The existing transport already sanitizes these finite diagnostics.
            # Only bounded, redacted error prose is retained; no headers, keys or request/response envelope.
            self.last_failure = error.diagnostics()
            raise
        except ProviderResponseError:
            self._studio_fail('envelope')
        if not isinstance(document,dict):self._studio_fail('envelope')
        stop=document.get('stop_reason')
        blocks=document.get('content')
        if (not isinstance(blocks,list) or len(blocks)!=1 or not isinstance(blocks[0],dict)
                or blocks[0].get('type')!='text' or not isinstance(blocks[0].get('text'),str)):
            self._studio_fail('stop_reason' if stop not in (None,'end_turn') else 'envelope',stop)
        try:
            candidate=_claude_json_object(blocks[0]['text'])
        except ProviderResponseError:
            self._studio_fail('stop_reason' if stop not in (None,'end_turn') else 'json',stop)
        self.last_candidate=candidate  # Separate local-review hook; never included in diagnostics or errors.
        if stop!='end_turn':self._studio_fail('stop_reason' if stop is not None else 'envelope',stop)
        try:
            story=StudioStoryboard.model_validate(candidate)
        except ValidationError as error:
            self._studio_fail('schema',stop,error.errors(include_url=False,include_context=False,include_input=False))
        from .studio_story import timing_errors
        errors=timing_errors(story,story_input)
        if errors:self._studio_fail('timing',stop,errors)
        return story

    def _studio_fail(self,stage,stop_reason=None,errors=()):
        error=StudioResponseError(stage,stop_reason=stop_reason,errors=errors)
        self.last_failure=error.diagnostics()
        raise error from None

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
