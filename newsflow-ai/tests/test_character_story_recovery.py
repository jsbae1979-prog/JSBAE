"""Local recovery has no provider calls, refunds, or implicit replays."""
from copy import deepcopy
from types import SimpleNamespace
import json
import pytest
from test_api_settings import sessions, store
from test_character_kling_studio import studio, create, story
from newsflow.character.schema import CharacterError
from newsflow.character.story_response import persist_candidate

def failed(studio):
    service=studio.service
    identifier=create(studio,duration=30,clip_seconds=6,sound='off')
    candidate=story(30,'off')
    candidate['plan']['situation']='x'*180
    candidate['scenes'][0]['sfx']='x'*85
    for scene in candidate['scenes']:scene['narration']=''
    job=service.read(identifier)
    job.update(state='script_failed',response_received=True,script_attempts=2,
               script_failure={'failure_stage':'schema','stop_reason':'end_turn',
                  'validation_errors':[{'loc':['plan','situation'],'type':'string_too_long'}]})
    saved=persist_candidate(service.folder(identifier),2,candidate,{'prompt_tokens':100,'completion_tokens':200})
    job['script_responses']=[saved]
    service.save(job)
    def forbidden(*a,**kw):raise AssertionError('No provider or budget access during local recovery')
    service.writer=SimpleNamespace(write_studio=forbidden)
    service.budget=SimpleNamespace(reserve=forbidden,finish=forbidden)
    return identifier,candidate,saved

def test_complete_saved_response_is_recovered_without_call_or_truncation(studio):
    identifier,candidate,saved=failed(studio);service=studio.service
    before=service.read(identifier);path=service.folder(identifier)/saved['file'];raw=path.read_bytes()
    service.recover_story_response(identifier,consent=True)
    after=service.read(identifier)
    assert after['state']=='script_review' and after['script']==candidate
    assert after['script_attempts']==2 and after['events']==before['events']
    assert after['script_recovery']['previous_failure']==before['script_failure']
    assert after['script_recovery']['provider_calls']==0 and path.read_bytes()==raw
    assert json.loads((service.folder(identifier)/'script.json').read_bytes())==candidate
    with pytest.raises(CharacterError):service.recover_story_response(identifier,consent=True)

@pytest.mark.parametrize('change',['consent','unknown','incomplete','already_success','tampered','bad_path','bad_timing','spoken'])
def test_recovery_rejects_untrusted_or_incomplete_candidates(studio,change):
    identifier,candidate,saved=failed(studio);service=studio.service;job=service.read(identifier)
    if change=='unknown':job['response_received']=False
    if change=='incomplete':job['script_failure']['stop_reason']='max_tokens'
    if change=='already_success':job['state']='script_review'
    if change=='bad_path':job['script_responses'][0]['file']='../../other.json'
    if change=='tampered':(service.folder(identifier)/saved['file']).write_text('{}')
    if change in {'bad_timing','spoken'}:
        import hashlib
        path=service.folder(identifier)/saved['file'];record=json.loads(path.read_bytes())
        record['candidate']['scenes'][0]['seconds' if change=='bad_timing' else 'narration']=7 if change=='bad_timing' else 'not empty'
        path.write_text(json.dumps(record))
        job['script_responses'][0]['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    service.save(job);before=service.read(identifier)
    with pytest.raises((CharacterError,ValueError)):
        service.recover_story_response(identifier,consent=change!='consent')
    assert service.read(identifier)==before
    assert not (service.folder(identifier)/'script.json').exists()
