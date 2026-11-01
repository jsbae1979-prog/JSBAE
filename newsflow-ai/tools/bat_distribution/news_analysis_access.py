"""Explicit collection TOP-3 analysis only; no search, scripts or background AI.

The authenticated route checks current collection, provider and user consent,
claims the request durably, and uses the normal per-request budget. Decryption
is scoped to this request's selected provider; environment keys are never used.
"""
from contextvars import ContextVar
from newsflow.intelligence.api_settings import APIBudgetService
from newsflow.intelligence.credentials import AIKeyStore, AnthropicKeyStore, CredentialError
from newsflow.intelligence.service import IntelligenceService, IntelligenceError
from newsflow.intelligence.settings import read_studio_settings
from .character_authoring import _Store, _unlinked

PATH = '/news/curation/analyze'
_ACTIVE = ContextVar('news_collection_analysis_request', default=None)

class _Service(IntelligenceService):
    def __init__(self, owner, **kwargs):
        self.owner = owner
        super().__init__(owner.app.state.sessions, **kwargs)

    def analyze(self, article_ids, mode, consent, options=None, **kwargs):
        self.owner.active_key(mode)
        if consent is not True or kwargs.get('curate') is not True:
            raise IntelligenceError('수집 회차 분석 범위를 확인하세요.', 'ai_consent', False)
        return super().analyze(article_ids, mode, consent, options, **kwargs)

class NewsAnalysisAccess:
    def __init__(self, app, profile, nativefactory, *, providers=None, budget=None):
        self.app = app
        self.profile = _unlinked(profile)
        if self.profile != _unlinked(app.state.config.data_dir):
            raise CredentialError('사용자 데이터 경로를 확인하세요.')
        native = nativefactory()
        self.keys = {name:_Store(self,name,kind,native) for name,kind in
                     (('claude_api',AnthropicKeyStore),('openai',AIKeyStore))}
        self.providers, self.budget = providers, budget or APIBudgetService(app.state.sessions)
        app.state.news_analysis_access = self

    def active_key(self, provider):
        if (_ACTIVE.get() != (self, provider) or provider not in self.keys):
            raise CredentialError('현재 승인된 뉴스 분석 요청이 아닙니다.')

    def service(self, request):
        selected = read_studio_settings(self.app.state.sessions)['provider']
        self.active_key(selected)
        return _Service(self, key_store=self.keys['openai'], api_key_stores=self.keys,
                        api_providers=self.providers, api_budget=self.budget)

    def wrap(self, normal, authenticated):
        owner = self
        async def call(scope, receive, send):
            if scope.get('type')!='http' or scope.get('method')!='POST' or scope.get('path')!=PATH:
                return await normal(scope,receive,send)
            selected = read_studio_settings(owner.app.state.sessions)['provider']
            token = _ACTIVE.set((owner, selected))
            try:
                return await authenticated(scope,receive,send)
            finally:
                _ACTIVE.reset(token)
        return call

def install(app, profile, nativefactory):
    return NewsAnalysisAccess(app, profile, nativefactory)
