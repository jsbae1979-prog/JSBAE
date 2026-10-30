"""Claude wire constraints differ from unchanged strict local validation; Fake HTTP only."""
from copy import deepcopy
import io,json
from urllib.error import HTTPError
import pytest
from pydantic import ValidationError
from newsflow.character.claude import studio_output_schema
from newsflow.character.studio_story import StudioStoryboard, ENGLISH_ACTION_PATTERN
from newsflow.character.episode_story import EpisodeScript
from newsflow.character.authoring import wire_schema, AnalysisResult, TopicResponse
from newsflow.publishing.claude_cards import FullImagePlan, DesignedCardPlan
from newsflow.intelligence.api_providers import _output_schema, _analysis_output_schema, _script_output_schema
from newsflow.intelligence.provider import ProviderHTTPResponseError, bounded_error_message
from test_character_studio_response import candidate
from test_character_episode_schema import script


def check(value):
    if isinstance(value,dict):
        assert not set(value)&{'pattern','minLength','maxLength','minimum','maximum','maxItems'}
        assert 'minItems' not in value or value['minItems'] in (0,1)
        for child in value.values(): check(child)
    elif isinstance(value,list):
        for child in value: check(child)


@pytest.mark.parametrize('schema',[
 lambda:studio_output_schema({'duration':30,'clip_seconds':6,'scene_count':5}),
 lambda:wire_schema(EpisodeScript,'claude_api'),lambda:wire_schema(AnalysisResult,'claude_api'),
 lambda:wire_schema(TopicResponse,'claude_api'),lambda:_output_schema(FullImagePlan),
 lambda:_output_schema(DesignedCardPlan),lambda:_analysis_output_schema('v1'),
 lambda:_analysis_output_schema('v2'),lambda:_script_output_schema('v1'),lambda:_script_output_schema('v2')])
def test_all_claude_wire_schemas_recursively_exclude_local_only_constraints(schema):check(schema())


def test_english_instruction_and_local_constraint_remain_and_original_schema_is_unchanged():
    before=deepcopy(StudioStoryboard.model_json_schema())
    node=studio_output_schema({'clip_seconds':6})['$defs']['StudioScene']['properties']['action']
    assert 'English only. No Korean characters.' in node['description']
    assert 'Local validation:' in node['description'] and 'pattern' in node['description']
    assert StudioStoryboard.model_json_schema()==before
    assert before['$defs']['StudioScene']['properties']['action']['pattern']==ENGLISH_ACTION_PATTERN
    StudioStoryboard.model_validate(candidate())
    for value in ('토끼 waters a garden.','12345',''):
        bad=candidate();bad['scenes'][0]['action']=value
        with pytest.raises(ValidationError):StudioStoryboard.model_validate(bad)


def test_new_episode_and_openai_local_contracts_are_preserved():
    value=script();value['scenes'][0]['action']='토끼 moves.'
    with pytest.raises(ValidationError):EpisodeScript.model_validate(value)
    assert 'pattern' in wire_schema(EpisodeScript,'openai')['$defs']['EpisodeScene']['properties']['action']


def error(message, **kwargs):
    raw=json.dumps({'error':{'type':'invalid_request_error','message':message},'headers':{'x-api-key':'ENVELOPE_PRIVATE'},'request':'BODY_PRIVATE'}).encode()
    return ProviderHTTPResponseError.from_http_error(HTTPError('https://api.anthropic.com/v1/messages',400,'',{},io.BytesIO(raw)),**kwargs)


def test_http_error_keeps_type_and_bounded_message_not_response_or_request_envelope():
    message='schema action pattern is not supported. '+'긴'*400
    value=error(message).diagnostics()
    assert value['error_type']=='invalid_request_error' and value['error_message']==message[:300]
    assert 'ENVELOPE_PRIVATE' not in json.dumps(value) and 'BODY_PRIVATE' not in json.dumps(value)
    assert len(value['error_message'])==300


@pytest.mark.parametrize('message',[
 'schema rejected SECRET_LITERAL', 'schema rejected sk-ant-private-key',
 'schema rejected\nAuthorization: Bearer PRIVATE_AUTH',
 'schema rejected x-api-key: PRIVATE_HEADER',
 'schema rejected headers: {"secret":"PRIVATE_HEADER"}',
 'schema rejected messages: [{"content":"PRIVATE_PROMPT"}]',
 'schema rejected PRIVATE_SYSTEM_INSTRUCTION',
])
def test_error_message_redacts_credentials_headers_and_echoed_inputs(message):
    value=error(message,secret='SECRET_LITERAL',request_body={'system':'PRIVATE_SYSTEM_INSTRUCTION','messages':[{'content':'PRIVATE_PROMPT'}]}).diagnostics()
    text=value['error_message']
    for private in ('SECRET_LITERAL','sk-ant-private-key','PRIVATE_AUTH','PRIVATE_HEADER','PRIVATE_PROMPT','PRIVATE_SYSTEM_INSTRUCTION'):
        assert private not in text
    assert len(text)<=300


def test_redaction_happens_before_truncation_and_never_appears_in_exception_text():
    key='arbitrary-key-without-prefix'
    value=error('x'*295+key,secret=key)
    assert key[:8] not in value.diagnostics()['error_message']
    assert 'error_message' not in str(value) and key not in str(value)
    assert bounded_error_message(None) is None


def test_new_episode_private_job_retains_bounded_rejection_without_revealing_it_publicly(tmp_path, monkeypatch):
    from test_character_story_preflight import episode
    from test_character_authoring_v3 import Budget
    from newsflow.intelligence.api_providers import AnthropicProvider
    from newsflow.character.schema import CharacterError
    from newsflow.character.story_response import public_failure
    budget=Budget(); original=budget.reserve
    def reserve(**kwargs):
        item=original(**kwargs);item.reserved_usd='0.252';return item
    budget.reserve=reserve
    service,authoring,adapter,identifier=episode(tmp_path,None,budget)
    adapter=AnthropicProvider(lambda:'sk-ant-synthetic-private')
    authoring.providers['claude_api']=adapter
    calls=[]
    def reject(*args):
        calls.append(1)
        raw=json.dumps({'error':{'type':'invalid_request_error','message':'schema pattern unsupported sk-ant-synthetic-private'}}).encode()
        raise HTTPError('https://api.anthropic.com/v1/messages',400,'',{},io.BytesIO(raw))
    monkeypatch.setattr(adapter,'_open',reject)
    with pytest.raises(CharacterError):service.write(identifier,consent=True)
    failure=service.read(identifier)['script_failure']
    assert failure['error_type']=='invalid_request_error' and failure['http_status']==400
    assert failure['error_message']=='schema pattern unsupported [REDACTED]'
    assert 'error_message' not in public_failure(failure)
    assert 'sk-ant-synthetic-private' not in json.dumps(failure)
    assert len(calls)==1 and budget.finished[0][1]['status']=='unknown'
    with pytest.raises(CharacterError):service.write(identifier,consent=True)
    assert len(calls)==1
