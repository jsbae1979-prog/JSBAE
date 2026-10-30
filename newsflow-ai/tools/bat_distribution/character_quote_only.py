"""Authenticated reference upload + planned quotes only; never a video/story execution grant."""
from __future__ import annotations
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from filelock import FileLock
from newsflow.character.service import CharacterService,generation_rows,fingerprint,digest
from newsflow.character.kling import KlingClient,check
from newsflow.character.schema import CharacterError
from newsflow.intelligence.credentials import CredentialError
from newsflow.video.ai.keys import VideoAIKeyStore

PATH=re.compile(r'/character/([a-f0-9]{32})/prepare\Z')
_REQUEST=ContextVar('newsflow_quote_request',default=None)
_ACTIVE=ContextVar('newsflow_quote_active',default=None)
_PAYLOADS=ContextVar('newsflow_quote_payloads',default=None)
_ENTROPY=hashlib.sha256(VideoAIKeyStore.ENTROPY).digest()


def _unlinked(path):
    from newsflow.distribution.windows_profile import unlinked
    return unlinked(Path(path))


def _deny():
    raise CharacterError('blocked')


class _ReadOnlyCipher:
    def __init__(self,scope,native):self.scope,self.native=scope,native
    def protect(self,*args):raise CredentialError('견적 기능에는 키 저장 권한이 없습니다.')
    def unprotect(self,payload,entropy):
        self.scope.active()
        if (not isinstance(entropy,bytearray) or bytes(entropy)!=_ENTROPY
                or not isinstance(payload,bytearray) or not 0<len(payload)<=8192):
            raise CredentialError('현재 프로필의 영상 키만 견적에 사용할 수 있습니다.')
        try:return self.native.unprotect(payload,entropy)
        except Exception:raise CredentialError('Windows 보호 저장소의 영상 키를 확인하세요.') from None


class _Store(VideoAIKeyStore):
    def __init__(self,scope,cipher):super().__init__(scope.profile,cipher);self.scope=scope
    def key(self):
        self.scope.active()
        path=_unlinked(self.path)
        if (path!=self.scope.profile/VideoAIKeyStore.FILE or not path.is_file()
                or path.stat().st_nlink!=1 or not 0<path.stat().st_size<=8192):
            raise CredentialError('현재 Windows 프로필에 영상 API 키를 등록하세요.')
        return super().key()  # Stored exact file only; environment fallback is unreachable.
    def save(self,*args):raise CredentialError('견적 기능에는 키 저장 권한이 없습니다.')
    def clear(self):raise CredentialError('견적 기능에는 키 삭제 권한이 없습니다.')


class _Client:
    def __init__(self,scope,original):self.scope,self.original=scope,original
    def credential(self):self.scope.active();return self.original.credential()
    def payload(self,prompt,seconds,reference):
        identifier=self.scope.active(); context=_PAYLOADS.get()
        if not isinstance(context,dict) or context.get('job_id')!=identifier:_deny()
        index=len(context['payloads'])
        if index>=len(context['planned']) or reference!=context.get('reference'):_deny()
        planned=context['planned'][index]
        if prompt!=planned['prompt'] or seconds!=planned['seconds']:_deny()
        result=self.original.payload(prompt,seconds,reference)
        expected=result
        if planned.get('continuity')=='continue':
            from newsflow.video_models.catalog import CATALOG
            job=self.scope.local.read(identifier)
            field=CATALOG.model(job['model']).get('continuation_param')
            if not field:_deny()
            expected={**result,field:reference}
        context['payloads'].append(fingerprint(expected))
        return result
    def upload_reference(self,path):
        folder=self.scope.local.folder(self.scope.active())
        if _unlinked(path) not in {folder/'reference.png',folder/'generation-reference.png'}:_deny()
        job=self.scope.local.read(self.scope.active())
        if digest(_unlinked(folder/'reference.png'))!=job['reference_sha256']:_deny()
        context=_PAYLOADS.get()
        if not isinstance(context,dict) or context.get('job_id')!=job['id']:_deny()
        self.scope.claim('upload')
        from newsflow.video.ai.download import safe_url
        public=safe_url(self.original.upload_reference(path))
        context['reference']=public
        return public
    def estimate(self,payload):
        identifier=self.scope.active(); context=_PAYLOADS.get()
        if not isinstance(context,dict) or context.get('job_id')!=identifier:_deny()
        index=context['estimated']
        if index>=len(context['payloads']) or fingerprint(payload)!=context['payloads'][index]:_deny()
        context['estimated']+=1
        self.scope.claim('estimate');return self.original.estimate(payload)
    def submit_scene(self,*args,**kwargs):_deny()
    def check(self,*args,**kwargs):_deny()
    def fetch(self,*args,**kwargs):_deny()


class QuoteOnly:
    def __init__(self,service,profile,nativefactory):
        self.profile=_unlinked(profile)
        if not self.profile.is_absolute() or not self.profile.is_dir():_deny()
        if _unlinked(service.root)!=self.profile/'character':_deny()
        # No constructor, writer, budget, provider, scheduler or startup work.
        self.local=CharacterService.__new__(CharacterService)
        self.local.root=service.root
        self.local.ffmpeg=getattr(service,'ffmpeg',None)
        self.local.ffprobe=getattr(service,'ffprobe',None)
        self.local.video_for=self.video_for
        self.keys=_Store(self,_ReadOnlyCipher(self,nativefactory()))

    def active(self):
        requested=_REQUEST.get();active=_ACTIVE.get()
        if (not isinstance(requested,tuple) or requested[0] is not self
                or not isinstance(active,tuple) or len(active)!=3 or active[:2]!=requested):_deny()
        return active[1]

    def receipt(self,identifier,attempt=None):
        if attempt is None:
            active=_ACTIVE.get()
            if not isinstance(active,tuple) or len(active)!=3 or active[:2]!=(self,identifier):_deny()
            attempt=active[2]
        if not isinstance(attempt,str) or not re.fullmatch(r'[a-f0-9]{32}',attempt):_deny()
        return _unlinked(self.local.folder(identifier)/'quote-attempts'/f'{attempt}.json')

    def _read(self,identifier,attempt=None):
        path=self.receipt(identifier,attempt)
        if not path.is_file() or not 0<path.stat().st_size<=4096:_deny()
        value=json.loads(path.read_bytes())
        if (value.get('schemaVersion')!=1 or value.get('job_id')!=identifier
                or value.get('state') not in {'started_or_unknown','quoted','failed_or_unknown'}):_deny()
        return value

    def _write(self,identifier,value,attempt=None):
        path=self.receipt(identifier,attempt);temporary=_unlinked(path.with_suffix('.new'))
        with temporary.open('x',encoding='utf8') as stream:
            json.dump(value,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)

    def claim(self,action):
        identifier=self.active()
        if action not in {'upload','estimate'}:_deny()
        with FileLock(str(self.local.folder(identifier)/'quote-only.lock'),timeout=0):
            row=self._read(identifier)
            maximum=1 if action=='upload' else row['planned_estimates']
            if type(maximum) is not int or maximum<1:_deny()
            if row['state']!='started_or_unknown' or row['calls'].get(action,0)>=maximum:_deny()
            row['calls'][action]=row['calls'].get(action,0)+1
            self._write(identifier,row)  # Claim persists before this request's external contact; no automatic replay.

    def video_for(self,job):
        identifier=self.active()
        if job.get('id')!=identifier:_deny()
        row=self._read(identifier)
        if (row['state']!='started_or_unknown' or job.get('plan_hash')!=row['plan_sha256']
                or job.get('reference_sha256')!=row['reference_sha256']
                or fingerprint(job.get('script'))!=row['story_sha256']):_deny()
        settings=check(job['studio_selection'])
        return _Client(self,KlingClient(self.keys.key,settings))

    def prepare(self,identifier,*,consent=False,script_reviewed=False):
        if _REQUEST.get()!=(self,identifier):_deny()
        self.local.consent(consent);self.local.consent(script_reviewed)
        with self.local.lock():
            job=self.local.read(identifier)
            if (job.get('state')!='script_review' or not job.get('script') or job.get('scenes')
                    or not job.get('studio_selection')):_deny()
            settings=check(job['studio_selection'])
            if job['plan_hash']!=self.local.plan_hash(job):_deny()
            rows=generation_rows(job)
            if not rows:_deny()
            attempt=uuid4().hex
            directory=_unlinked(self.local.folder(identifier)/'quote-attempts')
            directory.mkdir(exist_ok=True)
            path=self.receipt(identifier,attempt)
            row={'schemaVersion':1,'job_id':identifier,'state':'started_or_unknown','calls':{},
                 'attempt_id':attempt,'plan_sha256':job['plan_hash'],'reference_sha256':job['reference_sha256'],
                 'story_sha256':fingerprint(job['script']),'planned_estimates':len(rows),'generation_requests':0}
            with path.open('x',encoding='utf8') as stream:
                json.dump(row,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        token=_ACTIVE.set((self,identifier,attempt))
        payload_token=_PAYLOADS.set({'job_id':identifier,'planned':rows,'payloads':[],'estimated':0})
        try:
            CharacterService.prepare(self.local,identifier,consent=True,script_reviewed=True)
            job=self.local.read(identifier)
            if (job['state']!='quoted' or len(job.get('scenes',[]))!=row['planned_estimates']
                    or job['plan_hash']!=row['plan_sha256']):_deny()
        except BaseException:
            with FileLock(str(self.local.folder(identifier)/'quote-only.lock'),timeout=0):
                failed=self._read(identifier,attempt);failed['state']='failed_or_unknown';self._write(identifier,failed,attempt)
            raise
        finally:
            _PAYLOADS.reset(payload_token)
            _ACTIVE.reset(token)
        with FileLock(str(self.local.folder(identifier)/'quote-only.lock'),timeout=0):
            final=self._read(identifier,attempt);final['state']='quoted';self._write(identifier,final,attempt)

    def wrap(self,normal_app,authenticated_app):return _Requests(self,normal_app,authenticated_app)


class _Requests:
    def __init__(self,scope,normal,authenticated):self.scope,self.normal,self.authenticated=scope,normal,authenticated
    async def __call__(self,scope,receive,send):
        matched=PATH.fullmatch(scope.get('path','')) if scope.get('type')=='http' and scope.get('method')=='POST' else None
        if not matched:return await self.normal(scope,receive,send)
        token=_REQUEST.set((self.scope,matched.group(1)))
        try:return await self.authenticated(scope,receive,send)
        finally:_REQUEST.reset(token)


def install(app,profile,nativefactory):
    service=app.state.character
    if getattr(service,'_character_quote_only',None) is not None:_deny()
    if _unlinked(app.state.config.data_dir)!=_unlinked(profile):_deny()
    quote=QuoteOnly(service,Path(profile),nativefactory)
    original=service.prepare
    def prepare(identifier,*args,**kwargs):
        if _REQUEST.get()==(quote,identifier):return quote.prepare(identifier,*args,**kwargs)
        return original(identifier,*args,**kwargs)
    service.prepare=prepare
    service._character_quote_only=quote
    service._operating_quote_only=True  # Presentation flag only; old trial policy/journals remain intact.
    return quote
