"""Exact posting-copy review scope; preserves auth, budget and current-user keys."""
from contextvars import ContextVar
from newsflow.character.authoring import AuthoringAI
from newsflow.intelligence.api_settings import APIBudgetService
from newsflow.intelligence.credentials import AnthropicKeyStore,AIKeyStore,CredentialError
from newsflow.publishing.posting_copy import PostingCopy,_Budget,INSTRUCTION,Suggestion
from .character_authoring import _Store,_unlinked

PATH='/api/studio/publishing/copy/review'
_ACTIVE=ContextVar('posting_copy_request',default=None)

class _AI(AuthoringAI):
    def __init__(self,owner,keys,budget,providers=None):
        self.owner=owner
        super().__init__(keys,_Budget(budget),providers)
    def generate(self,instruction,payload,schema,options,**kwargs):
        if (_ACTIVE.get() is not self.owner or instruction!=INSTRUCTION or schema is not Suggestion
            or kwargs.get('consent') is not True or kwargs.get('image_bytes') is not None
            or kwargs.get('kind')!='script' or not kwargs.get('request_id','').startswith('posting-review:')):
            raise CredentialError('게시 문구 검토 요청을 확인하세요.')
        return super().generate(instruction,payload,schema,options,**kwargs)

class PostingCopyAccess:
    def __init__(self,app,profile,nativefactory,*,budget=None,providers=None):
        self.profile=_unlinked(profile)
        if self.profile!=_unlinked(app.state.config.data_dir):raise CredentialError('사용자 데이터 경로를 확인하세요.')
        native=nativefactory()
        keys={name:_Store(self,name,kind,native) for name,kind in (('claude_api',AnthropicKeyStore),('openai',AIKeyStore))}
        ai=_AI(self,keys,budget or APIBudgetService(app.state.sessions),providers)
        app.state.posting_copy=PostingCopy(app.state,ai=ai)
    def active_key(self,provider):
        if _ACTIVE.get() is not self or provider not in {'claude_api','openai'}:
            raise CredentialError('현재 게시 문구 검토 요청이 아닙니다.')
    def wrap(self,normal,authenticated):
        owner=self
        async def call(scope,receive,send):
            if scope.get('type')!='http' or scope.get('method')!='POST' or scope.get('path')!=PATH:
                return await normal(scope,receive,send)
            token=_ACTIVE.set(owner)
            try:return await authenticated(scope,receive,send)
            finally:_ACTIVE.reset(token)
        return call

def install(app,profile,nativefactory):
    return PostingCopyAccess(app,profile,nativefactory)
