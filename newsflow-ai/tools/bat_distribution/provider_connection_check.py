"""Authenticated, exact-GET credential tests; no global native or paid capability."""
from contextvars import ContextVar
import re

from newsflow.intelligence.credentials import AIKeyStore, AnthropicKeyStore, CredentialError
from newsflow.intelligence.provider import OpenAIProvider
from newsflow.intelligence.provider_connections import ProviderConnections, LIMIT, TIMEOUT
from newsflow.video.ai.keys import VideoAIKeyStore
from newsflow.video.elevenlabs_tts import ElevenLabsKeys
from .character_authoring import _Store, _unlinked

PATH = re.compile(r'/api/studio/providers/(claude|openai|elevenlabs|higgsfield)/check\Z')
_REQUEST = ContextVar('newsflow_provider_probe_request',default=None)
_KEY_USE = ContextVar('newsflow_provider_probe_key_use',default=None)


def deny(): raise CredentialError('승인된 공급사 연결 조회만 사용할 수 있습니다.')


class ScopedConnections(ProviderConnections):
    def __init__(self,state,profile,nativefactory,transport=None):
        self.profile=_unlinked(profile)
        if not self.profile.is_absolute() or not self.profile.is_dir(): deny()
        self.native=nativefactory()
        self.network=transport or OpenAIProvider(allow_retry=False)._open
        kinds={'claude':AnthropicKeyStore,'openai':AIKeyStore,'higgsfield':VideoAIKeyStore,'elevenlabs':ElevenLabsKeys}
        stores={provider:_Store(self,provider,kind,self.native) for provider,kind in kinds.items()}
        super().__init__(state,stores,self._metadata_transport)

    def active_key(self,provider):
        context=_REQUEST.get()
        if (not isinstance(context,dict) or context.get('owner') is not self
                or context.get('provider')!=provider or _KEY_USE.get() is not context): deny()

    def _metadata_transport(self,request,timeout,limit):
        context=_REQUEST.get()
        if not isinstance(context,dict) or context.get('owner') is not self or _KEY_USE.get() is not context: deny()
        plan=context['plan'];position=context['sent']
        legacy=plan.provider=='claude' or (plan.provider=='openai' and plan.scope=='text')
        expected_limit=65536 if legacy else LIMIT
        headers={k.lower():v for k,v in request.header_items()}
        auth='x-api-key' if plan.provider=='claude' else 'xi-api-key' if plan.provider=='elevenlabs' else 'authorization'
        expected={'accept',auth}|({'anthropic-version'} if plan.provider=='claude' else set())
        if (type(position) is not int or not 0<=position<len(plan.urls)
                or request.get_method()!='GET' or request.full_url!=plan.urls[position]
                or request.data is not None or request.unredirected_hdrs
                or set(headers)!=expected or headers.get('accept')!='application/json'
                or (plan.provider=='claude' and headers.get('anthropic-version')!='2023-06-01')
                or timeout!=TIMEOUT or limit!=expected_limit): deny()
        context['sent']+=1  # Failure consumes this GET; no implicit replay.
        return self.network(request,timeout,limit)

    def check(self,provider,scope,*,consent=False,plan=None):
        context=_REQUEST.get()
        if (not isinstance(context,dict) or context.get('owner') is not self
                or context.get('provider')!=provider or context.get('started')):
            return {'code':'unavailable','message':'인증된 설정 화면에서 다시 확인하세요.','verified':False}
        if consent is not True:
            return super().check(provider,scope,consent=False)
        context.update(started=True,plan=self.plan(provider,scope),sent=0)
        token=_KEY_USE.set(context)
        try: return super().check(provider,scope,consent=True,plan=context['plan'])
        finally: _KEY_USE.reset(token)

    def wrap(self,normal,authenticated):
        owner=self
        class Requests:
            async def __call__(self,scope,receive,send):
                match=PATH.fullmatch(scope.get('path',''))
                if scope.get('type')!='http' or scope.get('method')!='POST' or not match:
                    return await normal(scope,receive,send)
                token=_REQUEST.set({'owner':owner,'provider':match[1]})
                try: return await authenticated(scope,receive,send)
                finally: _REQUEST.reset(token)
        return Requests()


def install(app,profile,nativefactory,*,transport=None):
    if (_unlinked(app.state.config.data_dir)!=_unlinked(profile)
            or getattr(app.state,'provider_connections',None) is not None): deny()
    checker=ScopedConnections(app.state,profile,nativefactory,transport)
    app.state.provider_connections=checker
    return checker
