"""Private bounded story candidates and finite public validation summaries only."""
import hashlib
import json
import os
from pathlib import Path
from .claude import StudioResponseError

MESSAGES={
    'stop_reason':'스토리 응답이 끝까지 완료되지 않았습니다.',
    'envelope':'AI 응답의 스토리 형식을 확인하지 못했습니다.',
    'json':'AI 응답을 스토리 자료로 읽지 못했습니다.',
    'schema':'스토리의 장면 정보나 글자 길이가 형식에 맞지 않습니다.',
    'timing':'스토리 장면 수나 길이가 선택한 영상 설정과 맞지 않습니다.',
}

PREFLIGHT_MESSAGES={
    'authentication_required':'설정에서 선택한 AI의 연결 상태를 다시 확인하세요.',
    'episode_limit':'이번 영상의 남은 사용 한도를 확인하세요.',
    'settings':'스토리 요청 전 설정 확인에서 중단됐습니다.',
    'unresolved_requests':'이전 AI 요청의 처리·과금이 미확정입니다. 기록을 보존하고 새 스토리 사용 승인을 확인하세요.',
    'credential_unavailable':'보호된 API 키를 읽지 못했습니다. 연결 설정을 확인하세요.',
    'request_invalid':'스토리 요청 형식 또는 입력 크기를 확인하세요.',
    'request_cancelled':'전송 전에 스토리 요청이 취소됐습니다.',
}


def bounded_preflight_reason(value):
    return value if isinstance(value,str) and value in PREFLIGHT_MESSAGES else 'settings'

REQUEST_MESSAGES={
    'timeout':'스토리 응답 대기 시간이 초과됐습니다. 처리·과금 여부를 확인하세요. 자동 재요청하지 않습니다.',
    'connection':'스토리 응답 연결이 중단됐습니다. 처리·과금 여부를 확인하세요. 자동 재요청하지 않습니다.',
    'authentication':'스토리 API 인증이 거절됐습니다. 연결 설정을 확인하세요.',
    'request_rejected':'스토리 API가 요청을 거절했습니다. 자동 재요청하지 않습니다.',
    'response_unavailable':'스토리 응답을 확인하지 못했습니다. 처리·과금 여부를 확인하세요. 자동 재요청하지 않습니다.',
}


def bounded_request_reason(value):
    return value if isinstance(value,str) and value in REQUEST_MESSAGES else 'response_unavailable'


def public_failure(value, response_received=None):
    if not isinstance(value,dict):return None
    if value.get('failure_stage') == 'request' or (
            value.get('failure_stage') == 'schema' and response_received is False):
        reason=bounded_request_reason(value.get('request_reason'))
        return {'stage':'request','reason':reason,'message':REQUEST_MESSAGES[reason]}
    if value.get('failure_stage')=='preflight':
        if value.get('dispatched') is not False:return None
        reason=bounded_preflight_reason(value.get('preflight_reason'))
        return {'stage':'preflight','reason':reason,'dispatched':False,
                'message':PREFLIGHT_MESSAGES[reason]+' 유료 요청은 전송되지 않았습니다.'}
    if value.get('failure_stage') not in MESSAGES:
        return {'stage':'request','message':'스토리 API 요청이 완료되지 않았습니다.'} if 'http_status' in value else None
    errors=value.get('validation_errors',())
    if not isinstance(errors,(list,tuple)):errors=()
    safe=StudioResponseError(value['failure_stage'],stop_reason=value.get('stop_reason'),
                             errors=errors).diagnostics()
    stage=safe['failure_stage']
    return {'stage':stage,'message':MESSAGES[stage],**safe}

def persist_candidate(folder,attempt,candidate,usage=None):
    if not isinstance(candidate,dict):return None
    if type(attempt) is not int or not 1<=attempt<=1000:raise ValueError('attempt')
    folder=Path(folder)
    if not folder.is_dir() or any(p.is_symlink() or p.is_junction() for p in [folder,*folder.parents]):
        raise ValueError('folder')
    safe_usage={k:v for k,v in (usage or {}).items()
                if k in {'prompt_tokens','completion_tokens','search_calls'} and type(v) is int and 0<=v<=10_000_000}
    record={'schemaVersion':1,'provider':'claude_api','attempt':attempt,'candidate':candidate,'usage':safe_usage}
    raw=json.dumps(record,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf8')
    if len(raw)>512*1024:raise ValueError('candidate-size')
    target=folder/f'story-response-attempt-{attempt}.private.json'
    temporary=target.with_suffix('.pending')
    if target.exists():
        if target.is_symlink() or target.is_junction() or target.read_bytes()!=raw:raise ValueError('candidate-exists')
    else:
        with temporary.open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        # Windows rename refuses an existing destination; never replace evidence.
        if os.name=='nt':os.rename(temporary,target)
        else:
            os.link(temporary,target)
            temporary.unlink()
    return {'file':target.name,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'attempt':attempt}
