"""Persisted batch orchestration with Fake job services and synthetic profiles only."""
from copy import deepcopy
from uuid import uuid4

import pytest

from newsflow.character.queue import EpisodeQueue, fingerprint
from newsflow.character.registry import CharacterRegistry
from newsflow.character.topics import TopicStore
from newsflow.character.schema import CharacterError
from newsflow.creation.image_studio import ImageStudio
from test_character_registry_v3 import image,profile


class Service:
    def __init__(self):self.jobs={};self.created={};self.writes=[];self.submits=[];self.checks=[];self.fail_write=False;self.fail_submit=False
    def create_episode(self,topic,episode_limit,**kwargs):
        key=kwargs['request_id']
        if key in self.created:return self.created[key],False
        identifier=uuid4().hex;self.created[key]=identifier
        self.jobs[identifier]={'id':identifier,'state':'needs_script','topic':topic,'script':None,'episode_limit':episode_limit}
        return identifier,True
    def read(self,identifier):return deepcopy(self.jobs[identifier])
    def write(self,identifier,*,consent=False):
        assert consent;self.writes.append(identifier)
        self.jobs[identifier]['state']='writing'
        if self.fail_write:self.jobs[identifier]['state']='script_failed';raise TimeoutError()
        self.jobs[identifier].update(state='script_review',script={'title':'합성 대본'})
    def quote(self,identifier):
        job=self.jobs[identifier]
        job.update(state='quoted',script_approval={'sha256':fingerprint(job['script'])},quote_hash=uuid4().hex,quote_total_usd='0.50')
        return {'job_id':identifier,'quote_hash':job['quote_hash']}
    def submit(self,identifier,*,consent=False,quote_hash=''):
        assert consent and self.jobs[identifier]['quote_hash']==quote_hash
        self.submits.append(identifier)
        if self.fail_submit:self.jobs[identifier]['state']='submission_unknown';raise TimeoutError()
        self.jobs[identifier]['state']='generating'
    def check(self,identifier,*,consent=False):
        assert consent;self.checks.append(identifier)
        self.jobs[identifier]['state']='clips_review'


@pytest.fixture
def setup(tmp_path):
    images=ImageStudio(None,tmp_path,None);asset=images.asset_bytes(image())
    registry=CharacterRegistry(tmp_path,images);character=registry.save(profile(),asset)
    topics=TopicStore(tmp_path);topic_ids=[topics.add(character['id'],f'비 오는 날 {i}')['id'] for i in range(3)]
    service=Service();queue=EpisodeQueue(tmp_path,service,registry,topics)
    created=queue.create(character['id'],topic_ids,{'duration':15},'2',uuid4().hex)
    return queue,service,created,character,topic_ids


def test_batch_drafts_idempotent_then_scripts_once_and_individual_approval(setup):
    queue,service,created,character,topic_ids=setup
    again=queue.create(character['id'],topic_ids,{'duration':15},'2',created['id'])
    assert again==created and len(service.jobs)==3 and not service.writes and not service.submits
    written=queue.run_scripts(created['id'],consent=True)
    assert written['state']=='scripts_ready' and len(service.writes)==3
    queue.run_scripts(created['id'],consent=True)
    assert len(service.writes)==3 and not service.submits
    assert all(row['status']=='scripted' for row in queue.topics.list(character['id']))
    with pytest.raises(CharacterError):queue.approve_videos(created['id'],[{'job_id':created['rows'][0]['job_id'],'quote_hash':'fake'}],'2',consent=True)


def test_video_queue_exact_quotes_and_one_episode_at_a_time(setup):
    queue,service,created,_,_=setup
    queue.run_scripts(created['id'],consent=True)
    approvals=[service.quote(row['job_id']) for row in created['rows']]
    queue.approve_videos(created['id'],approvals,'1.50',consent=True)
    queue.advance_videos(created['id'],consent=True)
    assert service.submits==[approvals[0]['job_id']] and not service.checks
    queue.advance_videos(created['id'],consent=True)
    assert service.submits==[row['job_id'] for row in approvals[:2]]
    queue.advance_videos(created['id'],consent=True)
    assert len(service.submits)==3
    result=queue.advance_videos(created['id'],consent=True)
    assert result['state']=='clips_ready' and all(job['state']=='clips_review' for job in service.jobs.values())
    queue.advance_videos(created['id'],consent=True)
    assert len(service.submits)==3 and len(service.checks)==3


def test_script_failure_stops_batch_and_does_not_repeat_unknown(setup):
    queue,service,created,_,_=setup;service.fail_write=True
    with pytest.raises(CharacterError):queue.run_scripts(created['id'],consent=True)
    assert len(service.writes)==1 and queue.get(created['id'])['state']=='blocked'
    with pytest.raises(CharacterError):queue.run_scripts(created['id'],consent=True)
    assert len(service.writes)==1


def test_unknown_video_submit_stops_queue_without_resubmit(setup):
    queue,service,created,_,_=setup
    queue.run_scripts(created['id'],consent=True)
    approvals=[service.quote(row['job_id']) for row in created['rows']]
    queue.approve_videos(created['id'],approvals,'2',consent=True);service.fail_submit=True
    with pytest.raises(CharacterError):queue.advance_videos(created['id'],consent=True)
    assert len(service.submits)==1 and queue.get(created['id'])['state']=='blocked'
    with pytest.raises(CharacterError):queue.advance_videos(created['id'],consent=True)
    assert len(service.submits)==1


def test_batch_cost_consent_and_changed_quote_are_not_silently_accepted(setup):
    queue,service,created,_,_=setup
    with pytest.raises(CharacterError):queue.run_scripts(created['id'])
    queue.run_scripts(created['id'],consent=True)
    approvals=[service.quote(row['job_id']) for row in created['rows']]
    with pytest.raises(CharacterError):queue.approve_videos(created['id'],approvals,'1.49',consent=True)
    with pytest.raises(CharacterError):queue.approve_videos(created['id'],approvals,'2')
    queue.approve_videos(created['id'],approvals,'2',consent=True)
    service.jobs[approvals[0]['job_id']]['quote_hash']='changed'
    with pytest.raises(CharacterError):queue.advance_videos(created['id'],consent=True)
    assert not service.submits


def test_different_user_queue_and_foreign_jobs_cannot_be_selected(setup,tmp_path):
    queue,service,created,character,topic_ids=setup
    other=EpisodeQueue(tmp_path/'another',service,queue.registry)
    assert other.list()==[]
    with pytest.raises(CharacterError):other.get(created['id'])
    queue.run_scripts(created['id'],consent=True)
    with pytest.raises(CharacterError):queue.approve_videos(created['id'],[{'job_id':uuid4().hex,'quote_hash':'fake'}],'2',consent=True)
    with pytest.raises(CharacterError):queue.create(character['id'],topic_ids,{'duration':30},'2',created['id'])
    assert len(service.jobs)==3
