"""One fake Claude response per case: no credentials, network or operating writes."""
from copy import deepcopy
import json
import re

import pytest

from newsflow.character.claude import CharacterWriter, StudioResponseError, studio_output_schema
from newsflow.character.studio_story import StudioStoryboard
from newsflow.intelligence.provider import Options, ProviderHTTPResponseError, ProviderTimeoutError


PAYLOAD={'topic':'토끼가 정원을 가꾸는 새로운 이야기','duration':30,'clip_seconds':6,'scene_count':5,'sound':'on'}
OPTIONS=Options(model='claude-sonnet-4-6',max_tokens=3000)


def candidate():
    return {'plan':{'situation':'정원 돌보기','contrast':'작은 씨앗과 큰 수확','punchline':'이웃과 나눔'},
            'title':'토끼의 정원','hook_caption':'오늘의 작은 정원','end_caption':'다음 정원 이야기',
            'scenes':[{'seconds':6,'role':'setup' if index==0 else 'punchline' if index==4 else 'build',
                       'action':'The original rabbit carefully waters a vegetable bed in a quiet garden.',
                       'caption':f'정원 장면 {index+1}','sfx':'water droplets','narration':''}
                      for index in range(5)]}


def envelope(story=None,**changes):
    return {'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(story or candidate())}],
            'usage':{'input_tokens':100,'output_tokens':300},**changes}


def writer_for(monkeypatch,document):
    writer=CharacterWriter(lambda:'synthetic-claude-only')
    requests=[]
    def reply(request,timeout,limit):
        requests.append(json.loads(request.data))
        return json.dumps(document).encode('utf8')
    monkeypatch.setattr(writer,'_open',reply)
    return writer,requests


def test_wire_uses_supported_dynamic_seconds_and_english_action_without_unsupported_array_bounds():
    schema=studio_output_schema(PAYLOAD)
    scene=schema['$defs']['StudioScene']['properties']
    assert scene['seconds']['enum']==[6] and scene['narration']['enum']==['']
    assert re.fullmatch(scene['action']['pattern'],'A rabbit waters a garden.')
    assert not re.fullmatch(scene['action']['pattern'],'토끼 waters a garden.')
    assert not re.fullmatch(scene['action']['pattern'],'12345')
    assert 'Exactly 5 scenes, each 6 seconds' in schema['properties']['scenes']['description']
    assert 'first setup, last punchline' in schema['properties']['scenes']['description']
    assert 'First scene setup' in scene['role']['description']
    def inspect(value):
        if isinstance(value,dict):
            assert not set(value)&{'minimum','maximum','minLength','maxLength','maxItems','prefixItems'}
            assert 'minItems' not in value or value['minItems'] in (0,1)
            for child in value.values():inspect(child)
        elif isinstance(value,list):
            for child in value:inspect(child)
    inspect(schema)
    assert StudioStoryboard.model_json_schema()['properties']['scenes']['minItems']==3


def test_successful_five_by_six_story_sends_topic_text_only_once_and_keeps_review_candidate(monkeypatch):
    writer,requests=writer_for(monkeypatch,envelope())
    class UnreadReference:
        def __bytes__(self):raise AssertionError('PNG must not be inspected')
        def __repr__(self):raise AssertionError('PNG must not be serialized')
    result=writer.write_studio({**PAYLOAD,'character':{'private':'omitted'},'recent_topics':['omitted']},OPTIONS,UnreadReference())
    assert [scene.seconds for scene in result.scenes]==[6]*5 and len(requests)==1
    assert json.loads(requests[0]['messages'][0]['content'])==PAYLOAD
    assert 'Do not author dialogue' in requests[0]['system']
    assert not {'image','source','base64','audio','tools'}&set(requests[0])
    assert writer.last_candidate==candidate() and writer.last_failure is None and not writer.last_retried
    assert writer.last_usage['completion_tokens']==300


@pytest.mark.parametrize('stop',['max_tokens','refusal','tool_use','pause_turn','model_context_window_exceeded','private-stop-text',None])
def test_stop_reason_is_finite_candidate_remains_separate_and_no_retry_occurs(monkeypatch,stop):
    writer,requests=writer_for(monkeypatch,envelope(stop_reason=stop))
    with pytest.raises(StudioResponseError) as caught:writer.write_studio(PAYLOAD,OPTIONS)
    details=caught.value.diagnostics()
    assert details['failure_stage']==('envelope' if stop is None else 'stop_reason')
    if stop is not None:assert details['stop_reason']==('other' if stop=='private-stop-text' else stop)
    assert writer.last_candidate==candidate() and writer.last_failure==details and len(requests)==1
    assert 'private-stop-text' not in json.dumps(details) and '정원' not in str(caught.value)


@pytest.mark.parametrize('document',[
    None, [], {}, {'stop_reason':'end_turn','content':None},
    {'stop_reason':'end_turn','content':[{'type':'tool_use','input':'private-value'}]},
    {'stop_reason':'end_turn','content':[{'type':'text','text':'{}'},{'type':'text','text':'private-prose'}]},
])
def test_invalid_envelope_is_classified_without_storing_remote_prose(monkeypatch,document):
    writer,requests=writer_for(monkeypatch,document)
    with pytest.raises(StudioResponseError) as caught:writer.write_studio(PAYLOAD,OPTIONS)
    assert caught.value.diagnostics()['failure_stage']=='envelope'
    assert writer.last_candidate is None and len(requests)==1
    assert 'private' not in json.dumps(writer.last_failure)


@pytest.mark.parametrize('text',['private-prose', '[1,2]', '{"broken":', '{"title":"one","title":"private-value"}'])
def test_invalid_or_duplicate_json_does_not_produce_a_review_candidate(monkeypatch,text):
    writer,requests=writer_for(monkeypatch,envelope(content=[{'type':'text','text':text}]))
    with pytest.raises(StudioResponseError) as caught:writer.write_studio(PAYLOAD,OPTIONS)
    assert caught.value.diagnostics()=={'failure_stage':'json','stop_reason':'end_turn'}
    assert writer.last_candidate is None and len(requests)==1


@pytest.mark.parametrize('change,location,kind',[
    ('long_caption',['scenes',0,'caption'],'string_too_long'),
    ('korean_action',['scenes',0,'action'],'string_pattern_mismatch'),
    ('unknown_field',['unknown_field'],'extra_forbidden'),
    ('role_order',[],'value_error'),
])
def test_schema_failure_captures_only_safe_location_and_type_while_preserving_candidate(monkeypatch,change,location,kind):
    story=candidate()
    if change=='long_caption':story['scenes'][0]['caption']='private-caption-'*5
    elif change=='korean_action':story['scenes'][0]['action']='The 토끼 waters a private garden.'
    elif change=='unknown_field':story['private-secret-field']='private-value'
    else:story['scenes'][0]['role']='build'
    writer,requests=writer_for(monkeypatch,envelope(story))
    with pytest.raises(StudioResponseError) as caught:writer.write_studio(PAYLOAD,OPTIONS)
    details=caught.value.diagnostics()
    assert details['failure_stage']=='schema'
    assert {'loc':location,'type':kind} in details['validation_errors']
    assert writer.last_candidate==story and len(requests)==1
    serialized=json.dumps(details)
    assert not any(text in serialized for text in ('private','input','ctx','msg','https://'))


@pytest.mark.parametrize('change',['wrong_seconds','three_beats'])
def test_generic_schema_valid_story_with_wrong_requested_timing_fails_without_fabricating_beats(monkeypatch,change):
    story=candidate()
    if change=='wrong_seconds':
        for scene in story['scenes']:scene['seconds']=7
    else:
        story['scenes']=[story['scenes'][index] for index in (0,2,4)]
        for scene in story['scenes']:scene['seconds']=10
    assert StudioStoryboard.model_validate(story)
    writer,requests=writer_for(monkeypatch,envelope(story))
    with pytest.raises(StudioResponseError) as caught:writer.write_studio(PAYLOAD,OPTIONS)
    details=caught.value.diagnostics()
    assert details['failure_stage']=='timing'
    assert any(error['type']=='clip_seconds' for error in details['validation_errors'])
    assert any(error['type']==('total_duration' if change=='wrong_seconds' else 'scene_count')
               for error in details['validation_errors'])
    assert writer.last_candidate==story and len(requests)==1 and not writer.last_retried


def test_diagnostic_allowlists_exclude_unknown_fields_context_values_and_unbounded_indexes():
    error=StudioResponseError('private-stage',stop_reason='private-stop',errors=[{
        'loc':['private-field',999999,True,{'private':'data'}], 'type':['private-type'],
        'input':'private-input','ctx':{'error':'private-message'},'msg':'private-prose'}]*30)
    details=error.diagnostics()
    assert details['failure_stage']=='envelope' and details['stop_reason']=='other'
    assert len(details['validation_errors'])==20
    assert details['validation_errors'][0]=={'loc':['unknown_field']*4,'type':'other'}
    assert 'private' not in json.dumps(details)


def test_next_attempt_clears_previous_candidate_and_failure_before_transport(monkeypatch):
    writer,requests=writer_for(monkeypatch,envelope(candidate(),stop_reason='max_tokens'))
    with pytest.raises(StudioResponseError):writer.write_studio(PAYLOAD,OPTIONS)
    assert writer.last_candidate
    def timeout(request,timeout,limit):raise TimeoutError
    monkeypatch.setattr(writer,'_open',timeout)
    with pytest.raises(ProviderTimeoutError):writer.write_studio(PAYLOAD,OPTIONS)
    assert writer.last_candidate is None and writer.last_failure is None and writer.last_usage is None
    assert len(requests)==1


def test_http_rejection_keeps_existing_finite_http_diagnostics_and_no_candidate(monkeypatch):
    writer=CharacterWriter(lambda:'synthetic-only')
    calls=[]
    def reject(body,options):
        calls.append(body)
        raise ProviderHTTPResponseError(400,'invalid_request_error','schema_invalid',['schema'])
    monkeypatch.setattr(writer,'_post',reject)
    with pytest.raises(ProviderHTTPResponseError):writer.write_studio(PAYLOAD,OPTIONS)
    assert writer.last_failure=={'http_status':400,'error_type':'invalid_request_error',
                                 'request_issue':'schema_invalid','request_fields':['schema']}
    assert writer.last_candidate is None and len(calls)==1
