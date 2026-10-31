"""Explicit metadata-only provider tests; no inference, upload, retry or billing claims."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import re
import urllib.error
import urllib.request
from uuid import uuid4

from newsflow.db.models import utcnow
from .api_connection import check_api_connection
from .api_settings import api_readiness, read_api_settings
from .credentials import CredentialError
from .provider import OpenAIProvider, ProviderResponseError
from .settings import _set, _value

TIMEOUT = 15
LIMIT = 256 * 1024
SCOPES = {'claude': ('text',), 'openai': ('text', 'image'), 'elevenlabs': ('voice',), 'higgsfield': ('video',)}
MESSAGES = {
 'not_checked': '연결 미확인', 'checking': '연결 확인 중', 'key_missing': 'API 키를 먼저 등록하세요.',
 'key_error': '보호 저장소에서 키를 읽지 못했습니다.', 'consent_required': '연결 테스트 실행 동의가 필요합니다.',
 'auth_error': '키 인증 실패 · 키 상태를 확인하세요.', 'permission': '조회 권한이 부족합니다.',
 'model_unavailable': '선택 모델을 조회할 수 없습니다.', 'request_unavailable': '기존 요청 조회 불가 · 키 오류로 단정할 수 없습니다.',
 'unsupported': '무료 인증 확인에 사용할 기존 요청이 없습니다. 생성은 실행하지 않았습니다.',
 'rate_limit': '공급사 조회 한도에 도달했습니다. 자동 재시도하지 않습니다.',
 'timeout': '조회 시간이 초과됐습니다. 자동 재시도하지 않습니다.', 'network': '공급사 연결 상태를 확인하세요.',
 'unavailable': '공급사 조회를 완료하지 못했습니다.', 'invalid_response': '조회 응답 형식을 확인하지 못했습니다.',
 'stale': '키 또는 모델 설정이 변경됐습니다. 현재 설정으로 다시 확인하세요.',
 'busy': '이미 연결 확인 중입니다.', 'success': '키 인증·모델 조회 확인',
 'voice_success': '키 인증·모델 목록 확인 · 실제 음성·상업 이용 권한은 별도입니다.',
 'video_success': '키 인증·기존 요청 조회 확인 · 새 모델 생성 권한은 별도입니다.',
}

@dataclass(frozen=True)
class Plan:
    provider: str
    scope: str
    model: str
    urls: tuple[str, ...]
    reference: str = ''


def revision(store):
    """Bind cached results to ciphertext only. Never decrypt during a status GET."""
    try:
        path = getattr(store, 'path', None)
        if (path is None or path.is_symlink() or path.is_junction() or not path.is_file()
                or path.stat().st_nlink != 1 or not 0 < path.stat().st_size <= 8192):
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def public(row):
    code = row.get('code', 'not_checked')
    if code not in MESSAGES: code='invalid_response'
    return {'code': code, 'message': MESSAGES.get(code, MESSAGES['not_checked']),
            'verified': row.get('authenticated') is True, 'modelVerified': row.get('modelVerified') is True,
            'modelListed': row.get('modelListed') is True, 'model': row.get('model', ''),
            'checkedAt': row.get('checkedAt'), 'scope': row.get('scope', '')}


class MissingStore:
    def status(self): return {'configured':False}
    def key(self): raise CredentialError('API 키를 먼저 등록하세요.')


class ProviderConnections:
    def __init__(self, state, stores=None, transport=None):
        from newsflow.video.elevenlabs_tts import ElevenLabsKeys
        self.state, self.sessions = state, state.sessions
        self.stores = stores if stores is not None else {
            'claude': getattr(state,'api_keys',{}).get('claude_api'), 'openai': getattr(state,'ai_keys',None),
            'higgsfield': getattr(getattr(state,'video_ai',None),'keys',None), 'elevenlabs': ElevenLabsKeys(state.config.data_dir)}
        self.stores={provider:store if store is not None else MissingStore() for provider,store in self.stores.items()}
        self.transport = transport or OpenAIProvider(allow_retry=False)._open

    def plan(self, provider, scope):
        if provider not in SCOPES or scope not in SCOPES[provider]:
            raise ValueError('지원하는 공급사와 항목을 선택하세요.')
        if provider == 'claude' or (provider == 'openai' and scope == 'text'):
            alias = 'claude_api' if provider == 'claude' else 'openai'
            model = read_api_settings(self.sessions, alias).model
            if not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', model): raise ValueError('모델 설정을 확인하세요.')
            base = 'https://api.anthropic.com' if provider == 'claude' else 'https://api.openai.com'
            return Plan(provider, scope, model, (base + '/v1/models/' + model,))
        if provider == 'openai':
            from newsflow.creation.catalog import read_defaults
            model = read_defaults(self.sessions, 'image')['model']
            return Plan(provider, scope, model, ('https://api.openai.com/v1/models/' + model,))
        if provider == 'elevenlabs':
            from newsflow.video.elevenlabs_tts import settings
            model = settings(self.sessions)['model']
            return Plan(provider, scope, model, ('https://api.elevenlabs.io/v1/user', 'https://api.elevenlabs.io/v1/models'))
        # The official public catalog is not an authentication test. Only inspect
        # an owned, previously terminal request; never invent a request or submit.
        character=getattr(self.state,'character',None)
        for job in character.listing() if character is not None else []:
            for scene in reversed(job.get('scenes', [])):
                handle = scene.get('handle', {})
                identifier = handle.get('request_id', '')
                url = handle.get('status_url', '')
                if (scene.get('state') in {'downloaded', 'failed', 'nsfw', 'canceled'}
                        and isinstance(identifier,str) and re.fullmatch(r'[a-fA-F0-9-]{32,36}', identifier)
                        and url == 'https://api.higgsfield.ai/requests/' + identifier + '/status'):
                    return Plan(provider, scope, job['model'], (url,), identifier)
        return Plan(provider, scope, '', ())

    def status(self, provider, scope):
        store = self.stores[provider]
        configured = bool(store.status().get('configured'))
        try: plan = self.plan(provider, scope)
        except (ValueError,KeyError):
            return {**public({'code':'model_unavailable','scope':scope}), 'configured':configured}
        with self.sessions() as session:
            raw = _value(session, 'provider_probe:' + provider + ':' + scope)
        try: row = json.loads(raw) if raw else None
        except (ValueError, TypeError): row = None
        if raw and not isinstance(row,dict):
            return {**public({'code':'invalid_response','scope':scope}), 'configured':configured}
        if row:
            try: age = utcnow() - datetime.fromisoformat(row.get('checkedAt') or row['startedAt'])
            except (KeyError,TypeError,ValueError):
                return {**public({'code':'invalid_response','scope':scope}), 'configured':configured}
            if (row.get('revision') == revision(store) and row.get('model') == plan.model
                    and timedelta(0) <= age < timedelta(days=1)):
                result = public(row)
                if result['code'] == 'checking' and age > timedelta(seconds=60):
                    result = public({'code':'stale','scope':scope,'model':plan.model})
                return {**result, 'configured': configured}
            return {**public({'code':'stale','scope':scope,'model':plan.model}), 'configured':configured}
        if configured and provider in {'claude','openai'} and scope == 'text':
            alias = 'claude_api' if provider == 'claude' else 'openai'
            if api_readiness(self.sessions, alias, store, 'analysis')['authentication_verified']:
                return {**public({'code':'success','authenticated':True,'modelVerified':True,'model':plan.model,'scope':scope}), 'configured': True}
        return {**public({'code':'not_checked' if configured else 'key_missing','scope':scope,'model':plan.model}), 'configured':configured}

    def _metadata(self, plan, store):
        if not plan.urls: return {'code':'unsupported'}
        key = store.key()
        if not key: return {'code':'key_missing'}
        if any(ord(c)<33 or ord(c)>126 for c in key): return {'code':'key_error'}
        headers = {'Accept':'application/json'}
        if plan.provider == 'elevenlabs': headers['xi-api-key'] = key
        else: headers['Authorization'] = ('Key ' if plan.provider == 'higgsfield' else 'Bearer ') + key
        authenticated = False
        try:
            for index, url in enumerate(plan.urls):
                request = urllib.request.Request(url, method='GET', headers=headers)
                raw = self.transport(request, TIMEOUT, LIMIT)
                if not isinstance(raw, bytes) or len(raw)>LIMIT: return {'code':'invalid_response','authenticated':authenticated}
                doc = json.loads(raw)
                if plan.provider == 'openai':
                    valid = isinstance(doc,dict) and doc.get('object')=='model' and doc.get('id')==plan.model
                    return {'code':'success' if valid else 'invalid_response','authenticated':valid,'modelVerified':valid}
                if plan.provider == 'higgsfield':
                    valid = (isinstance(doc,dict) and doc.get('request_id',plan.reference)==plan.reference
                             and doc.get('status') in {'queued','in_progress','completed','failed','nsfw','canceled'})
                    return {'code':'video_success' if valid else 'invalid_response','authenticated':valid}
                if index == 0:
                    if not isinstance(doc,dict) or not isinstance(doc.get('user_id'),str) or not doc['user_id']:
                        return {'code':'invalid_response'}
                    authenticated = True
                else:
                    found = isinstance(doc,list) and any(isinstance(m,dict) and m.get('model_id')==plan.model for m in doc)
                    return {'code':'voice_success' if found else 'model_unavailable','authenticated':True,'modelListed':found}
        except urllib.error.HTTPError as error:
            code = {401:'auth_error',403:'permission',404:'request_unavailable' if plan.provider=='higgsfield' else 'model_unavailable',
                    429:'rate_limit',408:'timeout',504:'timeout'}.get(error.code,'unavailable')
            error.close()
            return {'code':code,'authenticated':False if code=='auth_error' else authenticated}
        except (TimeoutError, urllib.error.URLError) as error:
            return {'code':'timeout' if isinstance(error,TimeoutError) or isinstance(getattr(error,'reason',None),TimeoutError) else 'network', 'authenticated':authenticated}
        except (OSError, ValueError, TypeError, ProviderResponseError):
            return {'code':'invalid_response','authenticated':authenticated}
        except Exception:  # Secret-bearing supplier objects must never reach logs/UI.
            return {'code':'unavailable','authenticated':authenticated}

    def check(self, provider, scope, *, consent=False, plan=None):
        plan = plan or self.plan(provider, scope)
        if consent is not True: return public({'code':'consent_required'})
        store = self.stores[provider]
        if not store.status().get('configured'): return public({'code':'key_missing','scope':scope,'model':plan.model})
        rev = revision(store)
        if rev is None: return public({'code':'key_error'})
        name = 'provider_probe:' + provider + ':' + scope
        token = uuid4().hex
        with self.sessions.begin() as session:
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
            raw = _value(session, name)
            try: previous = json.loads(raw) if raw else {}
            except (ValueError, TypeError): previous = {}
            if not isinstance(previous,dict): previous={}
            if previous.get('code')=='checking':
                try: started=datetime.fromisoformat(previous['startedAt'])
                except (KeyError,TypeError,ValueError): started=utcnow()-timedelta(seconds=61)
                if started.tzinfo is not None and timedelta(0)<=utcnow()-started<timedelta(seconds=60): return public({'code':'busy'})
            row={'code':'checking','token':token,'scope':scope,'model':plan.model,'revision':rev,'startedAt':utcnow().isoformat()}
            _set(session,name,json.dumps(row))
        try:
            if provider=='claude' or (provider=='openai' and scope=='text'):
                alias='claude_api' if provider=='claude' else 'openai'
                result=check_api_connection(self.sessions,store,provider=alias,consent=True,transport=self.transport)
                outcome={'code':'model_unavailable' if result.code=='unsupported_model' else result.code,'authenticated':result.ok,'modelVerified':result.ok}
            else: outcome=self._metadata(plan,store)
        except Exception:
            outcome={'code':'key_error'}
        if revision(store)!=rev or self.plan(provider,scope)!=plan:
            outcome={'code':'stale'}
        with self.sessions.begin() as session:
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
            current=json.loads(_value(session,name) or '{}')
            if current.get('token')!=token: return public({'code':'stale'})
            row.update(outcome,checkedAt=utcnow().isoformat());row.pop('token',None)
            _set(session,name,json.dumps(row))
        return public(row)


def connections(state):
    checker=getattr(state,'provider_connections',None)
    return checker if checker is not None else ProviderConnections(state)
