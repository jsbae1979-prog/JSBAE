"""Explicit offline operator repair for the one byte-pinned legacy key rejector.

No HTTP route, provider, credential read or execution. The operator must verify
the archived running client bytes and back up the stopped profile before use.
"""
from copy import deepcopy
from datetime import datetime
import re
from newsflow.character.service import fingerprint
from newsflow.character.schema import CharacterError

REJECTOR_SHA256 = 'd5037faa1add6f3d2fc8d5b2331058929bab841178fe913bd61b9c8e8dd5310d'

def recover(job, *, expected_job_hash, rejected_client_sha256, consent=False):
    if (consent is not True or rejected_client_sha256.lower()!=REJECTOR_SHA256
            or fingerprint(job)!=expected_job_hash or job.get('automation_version')!=1
            or job.get('state')!='submission_unknown' or not job.get('scenes')
            or job.get('approved_plan_hash')!=job.get('plan_hash')
            or job.get('script_approval',{}).get('sha256')!=fingerprint(job.get('script'))
            or len(job.get('quote_approvals',[]))!=1
            or job['quote_approvals'][0].get('usd')!=job.get('quote_total_usd')):
        raise CharacterError('blocked')
    prepared=[];positions=[]
    for row in job['scenes']:
        key=row.get('idempotency_key')
        expected=f'{job["id"]}-s{row["position"]}-t1'
        if (row.get('attempt')!=1 or key!=expected or re.fullmatch(r'[a-f0-9-]{8,64}',key)
                or row.get('approved_template_hash')!=fingerprint(row.get('payload'))
                or any(k in row for k in ('handle','file','media','submit_diagnostics','dependency','download_expected'))):
            raise CharacterError('blocked')
        cut=row.get('continuity')=='cut'
        if cut:
            if row.get('state')!='unknown' or not row.get('submitted_at'):
                raise CharacterError('blocked')
            submitted=datetime.fromisoformat(row['submitted_at'])
            quoted=datetime.fromisoformat(job['quoted_at'])
            if not 0<=(submitted-quoted).total_seconds()<=900:
                raise CharacterError('blocked')
            positions.append(row['position'])
        elif row.get('continuity')!='continue' or row.get('state')!='waiting_dependency' or row.get('submitted_at'):
            raise CharacterError('blocked')
        original=deepcopy(row)
        original.pop('approved_template_hash');original.pop('submitted_at',None)
        original['state']='not_submitted';prepared.append(original)
    if (not positions or fingerprint([job['plan_hash'],prepared,job['quoted_at'],job['quote_key_id']])!=job['quote_hash']):
        raise CharacterError('blocked')
    result=deepcopy(job)
    fields=('scenes','quote_approvals','approved_plan_hash','quote_hash','quote_total_usd','quoted_at','quote_key_id','script_approval')
    result.setdefault('submission_history',[]).append({
        'previous_state':job['state'],'record':{k:deepcopy(job[k]) for k in fields},
        'proof':{'kind':'byte_pinned_legacy_local_key_rejection','client_sha256':REJECTOR_SHA256,
                 'dispatched':False,'positions':positions},'explicit_operator_recovery':True})
    for key in fields:result.pop(key,None)
    result.update(state='script_review',scenes=[])
    return result
