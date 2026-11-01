"""Current-job, hash-bound local review of a complete saved episode candidate."""
from copy import deepcopy
import json
from .compose import digest
from .schema import CharacterError


def context(job):
    from .service import fingerprint
    return fingerprint({key:job.get(key) for key in (
        'id','script_provider','script_request_sequence','character','topic','duration',
        'studio_selection','episode_limit','reference_sha256')})


def save_candidate(service, job, authoring, attempt):
    if getattr(authoring,'response_received',False) is not True:
        return
    from .story_response import persist_candidate
    try:
        saved=persist_candidate(service.folder(job['id']),attempt,getattr(authoring,'last_candidate',None),
            getattr(authoring,'last_usage',None),provider=job['script_provider'],context_hash=context(job))
        if saved:
            rows=job.setdefault('script_responses',[])
            if not any(row.get('attempt')==attempt for row in rows): rows.append(saved)
    except (ValueError,OSError,TypeError):
        job['script_evidence_error']='write_unavailable'


def read_candidate(service, job):
    if (job.get('automation_version')!=1 or job.get('state')!='script_failed'
            or job.get('response_received') is not True or job.get('script') or job.get('scenes')):
        raise CharacterError('blocked')
    attempt=job.get('script_attempts')
    rows=[row for row in job.get('script_responses',[]) if row.get('attempt')==attempt]
    if len(rows)!=1: raise CharacterError('blocked')
    row=rows[0];folder=service.folder(job['id'])
    if row.get('file')!=f'story-response-attempt-{attempt}.private.json':raise CharacterError('blocked')
    path=folder/row['file']
    if (path.is_symlink() or path.is_junction() or not path.is_file()
            or not 0<path.stat().st_size<=512*1024 or digest(path)!=row.get('sha256')):
        raise CharacterError('blocked')
    record=json.loads(path.read_bytes())
    if (record.get('schemaVersion')!=1 or record.get('attempt')!=attempt
            or record.get('provider')!=job['script_provider'] or record.get('context_hash')!=context(job)
            or not isinstance(record.get('candidate'),dict)
            or digest(folder/'reference.png')!=job.get('reference_sha256')):
        raise CharacterError('blocked')
    return record,row


def preview(service, identifier):
    with service.lock():
        job=service.read(identifier)
        record,row=read_candidate(service,job)
        return {'candidate':deepcopy(record['candidate']),'expected_hash':row['sha256'],
                'additionalProviderCalls':0}


def recover(service, identifier, *, consent=False, script=None, expected_hash=''):
    service.consent(consent)
    from .episode_service import EpisodeFlow, dump, fp, now
    from .episode_story import prompts
    from .kling import check
    with service.lock():
        job=service.read(identifier)
        record,row=read_candidate(service,job)
        if script is not None and expected_hash!=row['sha256']:raise CharacterError('blocked')
        # No truncation, AI repair or parser relaxation. Every local rule still runs.
        story=EpisodeFlow(service).validate(job, record['candidate'] if script is None else script)
        from .episode_policy import job_story_format
        prepared=prompts(story,check(job['studio_selection']),job['character'],job_story_format(job))
        previous=deepcopy(job['script_failure'])
        job.update(script=dump(story),prompts=prepared,state='script_review',response_received=True)
        job['script_hash']=fp(job['script']);job['plan_hash']=service.plan_hash(job)
        job['script_recovery']={'at':now().isoformat(),'attempt':job['script_attempts'],
            'sha256':row['sha256'],'previous_failure':previous,'provider_calls':0,'edited':script is not None}
        job.pop('script_failure',None);job.pop('script_validation_feedback',None)
        (service.folder(identifier)/'script.json').write_text(json.dumps(job['script'],ensure_ascii=False,indent=2),encoding='utf8')
        service.save(job)
