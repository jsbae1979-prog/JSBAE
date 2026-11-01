"""Explicit collection TOP-3 analysis only; no search, scripts or background AI.

The authenticated route checks current collection, provider and user consent,
claims the request durably, and uses the normal per-request budget. Decryption
is scoped to this request's selected provider; environment keys are never used.
"""
from contextvars import ContextVar
from urllib.parse import parse_qs
from newsflow.intelligence.api_settings import APIBudgetService
from newsflow.intelligence.credentials import AIKeyStore, AnthropicKeyStore, CredentialError
from newsflow.intelligence.service import IntelligenceService, IntelligenceError
from newsflow.intelligence.settings import read_studio_settings
from .character_authoring import _Store, _unlinked

PATH = '/news/curation/analyze'
SELECTED_PATH = '/ai/analyze'
_ACTIVE = ContextVar('news_collection_analysis_request', default=None)

class _Service(IntelligenceService):
    def __init__(self, owner, **kwargs):
        self.owner = owner
        super().__init__(owner.app.state.sessions, **kwargs)

    def analyze(self, article_ids, mode, consent, options=None, **kwargs):
        self.owner.active_key(mode)
        if (consent is not True or
                bool(kwargs.get('curate')) != (_ACTIVE.get()[2] == PATH)):
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
        if (_ACTIVE.get() not in {(self, provider, PATH), (self, provider, SELECTED_PATH)} or provider not in self.keys):
            raise CredentialError('현재 승인된 뉴스 분석 요청이 아닙니다.')

    def service(self, request, provider=None):
        selected = provider if provider is not None else read_studio_settings(self.app.state.sessions)['provider']
        self.active_key(selected)
        return _Service(self, key_store=self.keys['openai'], api_key_stores=self.keys,
                        api_providers=self.providers, api_budget=self.budget)

    def wrap(self, normal, authenticated):
        owner = self
        async def call(scope, receive, send):
            if scope.get('type')!='http' or scope.get('method')!='POST' or scope.get('path') not in {PATH, SELECTED_PATH}:
                return await normal(scope,receive,send)
            selected = read_studio_settings(owner.app.state.sessions)['provider']
            path = scope['path']
            if path == SELECTED_PATH:
                # Inspect only bounded form metadata; replay the exact body to the
                # unchanged LocalAccess/Origin/CSRF middleware before any key use.
                headers = {k.lower(): v for k,v in scope.get('headers', [])}
                if headers.get(b'content-type', b'').split(b';')[0] != b'application/x-www-form-urlencoded':
                    await send({'type':'http.response.start','status':415,'headers':[]})
                    return await send({'type':'http.response.body','body':b'Form required.'})
                body = b''
                while True:
                    message = await receive()
                    if message['type'] != 'http.request':
                        return
                    body += message.get('body', b'')
                    if len(body) > 65536:
                        await send({'type':'http.response.start','status':413,'headers':[]})
                        return await send({'type':'http.response.body','body':b'Form too large.'})
                    if not message.get('more_body'):
                        break
                try:
                    fields = parse_qs(body.decode('utf8'), keep_blank_values=True, max_num_fields=100)
                    values = fields.get('provider', ['offline'])
                    if len(values) != 1 or values[0] not in {'claude_api','openai','offline'}:
                        raise ValueError
                    selected = values[0]
                except (ValueError, UnicodeError):
                    await send({'type':'http.response.start','status':422,'headers':[]})
                    return await send({'type':'http.response.body','body':b'Invalid provider.'})
                original_receive, delivered = receive, False
                async def replay():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {'type':'http.request','body':body,'more_body':False}
                    return await original_receive()
                receive = replay
                if selected == 'offline':
                    return await normal(scope, receive, send)
            token = _ACTIVE.set((owner, selected, path))
            try:
                return await authenticated(scope,receive,send)
            finally:
                _ACTIVE.reset(token)
        return call

def install(app, profile, nativefactory):
    return NewsAnalysisAccess(app, profile, nativefactory)
