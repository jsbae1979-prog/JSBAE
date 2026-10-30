"""Synthetic SSE only; never opens a real socket or reads a credential."""
from io import BytesIO
import json
from types import SimpleNamespace
import urllib.request

import pytest

from newsflow.intelligence.anthropic_stream import read_message
from newsflow.intelligence.api_providers import AnthropicProvider
from newsflow.intelligence.provider import Options, ProviderError
from newsflow.character.story_response import public_failure
from newsflow.character.authoring import request_body
from newsflow.character.episode_story import SCRIPT_INSTRUCTION, EpisodeScript


def events():
    return [
      ('message_start',{'message':{'content':[], 'usage':{'input_tokens':12,'output_tokens':1}}}),
      ('content_block_start',{'index':0,'content_block':{'type':'text','text':''}}),
      ('content_block_delta',{'index':0,'delta':{'type':'text_delta','text':'{"title":"몽실"}'}}),
      ('content_block_stop',{'index':0}),
      ('message_delta',{'delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':8}}),
      ('message_stop',{}),
    ]


def encode(rows):
    return ''.join('event: '+kind+'\ndata: '+json.dumps({'type':kind,**value},ensure_ascii=False)+'\n\n' for kind,value in rows).encode('utf8')


def receive(raw, **kwargs):
    return read_message(BytesIO(raw),limit=100000,deadline=10,cancelled=lambda:None,clock=lambda:0,**kwargs)


def test_complete_message_is_assembled_with_final_cumulative_usage_without_waiting_for_eof():
    class Response(BytesIO):
        def readline(self,n):
            assert self.tell()<len(self.getvalue()),'Must finish at message_stop, not wait for EOF'
            return super().readline(n)
    result=json.loads(read_message(Response(encode(events())),limit=100000,deadline=10,cancelled=lambda:None,clock=lambda:0))
    assert result=={'stop_reason':'end_turn','content':[{'type':'text','text':'{"title":"몽실"}'}],
                    'usage':{'input_tokens':12,'output_tokens':8}}


@pytest.mark.parametrize('change',['missing_stop','missing_start','missing_delta','extra_block','wrong_index','wrong_delta','invalid_usage','mismatch_type','error','bad_json','missing_final_usage','bad_utf8'])
def test_interrupted_or_invalid_stream_never_becomes_a_completed_response(change):
    rows=events()
    if change=='missing_stop':rows.pop()
    elif change=='missing_start':rows.pop(0)
    elif change=='missing_delta':rows.pop(4)
    elif change=='extra_block':rows.insert(4,('content_block_start',{'index':1,'content_block':{'type':'text','text':''}}))
    elif change=='wrong_index':rows[2][1]['index']=1
    elif change=='wrong_delta':rows[2][1]['delta']['type']='input_json_delta'
    elif change=='invalid_usage':rows[4][1]['usage']['output_tokens']='8'
    elif change=='missing_final_usage':rows[4][1]['usage']={}
    elif change=='error':rows.insert(2,('error',{'error':{'message':'PRIVATE DO NOT PROJECT'}}))
    raw=encode(rows)
    if change=='mismatch_type':raw=raw.replace(b'"type": "message_start"',b'"type": "other"',1)
    if change=='bad_utf8':raw=b'event: message_start\ndata: \xff\n\n'
    if change=='bad_json':raw=b'event: message_start\ndata: broken\n\n'
    with pytest.raises(ProviderError) as caught:receive(raw)
    assert 'PRIVATE' not in str(caught.value)


def test_ping_and_unknown_future_events_do_not_fabricate_completion():
    rows=events();rows.insert(2,('ping',{}));rows.insert(2,('future_info',{}))
    assert json.loads(receive(encode(rows)))['stop_reason']=='end_turn'


@pytest.mark.parametrize('kind',['bytes','deadline','cancel'])
def test_stream_remains_size_time_and_cancel_bounded(kind):
    def cancel():raise RuntimeError('cancelled')
    with pytest.raises((ProviderError,TimeoutError,RuntimeError)):
        read_message(BytesIO(encode(events())),limit=5 if kind=='bytes' else 100000,
                     deadline=0 if kind=='deadline' else 10,
                     cancelled=cancel if kind=='cancel' else lambda:None,clock=lambda:1)


def test_existing_transport_uses_one_opener_and_finishes_without_replay(monkeypatch):
    calls=[]
    class Response(BytesIO):
        def __enter__(self):return self
        def __exit__(self,*args):self.close()
    class Opener:
        def open(self,request,timeout):calls.append(1);return Response(encode(events()))
    monkeypatch.setattr(urllib.request,'build_opener',lambda *args:Opener())
    provider=AnthropicProvider(lambda:'synthetic-credential')
    result=provider._post({'stream':True},Options(model='claude-sonnet-4-6'))
    assert len(calls)==1 and provider.last_usage['prompt_tokens']==12 and provider.last_usage['completion_tokens']==8
    assert result['stop_reason']=='end_turn'


def test_only_character_episode_uses_stream_and_budget_tokens_stay_fixed():
    body=request_body(SCRIPT_INSTRUCTION,{},EpisodeScript,Options(model='claude-sonnet-4-6',max_tokens=4000),'claude_api')
    assert body['stream'] is True and body['max_tokens']==4000 and 'tools' not in body
    assert 'image' not in json.dumps(body['messages'])


@pytest.mark.parametrize('reason',['timeout','connection','authentication','request_rejected','response_unavailable'])
def test_request_diagnosis_does_not_claim_schema_failure_or_no_billing(reason):
    result=public_failure({'failure_stage':'request','request_reason':reason,'message':'PRIVATE'})
    assert result['stage']=='request' and result['reason']==reason
    assert 'PRIVATE' not in result['message'] and '형식' not in result['message'] and 'dispatched' not in result


def test_historical_no_response_schema_label_is_corrected_only_in_projection():
    stored={'failure_stage':'schema','message':'old'}
    assert public_failure(stored,False)['reason']=='response_unavailable'
    assert public_failure(stored,True)['stage']=='schema'
    assert stored=={'failure_stage':'schema','message':'old'}
