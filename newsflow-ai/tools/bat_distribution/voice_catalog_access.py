"""Same-profile credential use for an explicit voice metadata GET only.

No global DPAPI, key registration, paid synthesis, or background permission is
changed. Existing cached/public samples remain key-free.
"""
from contextvars import ContextVar
from newsflow.intelligence.credentials import CredentialError
from newsflow.video.elevenlabs_tts import ElevenLabsKeys
from newsflow.video.elevenlabs_voices import ElevenLabsVoices
from .character_authoring import _Store,_unlinked

PATH='/video/tts/voices/load'
_REQUEST=ContextVar('newsflow_voice_catalog_request',default=None)
_KEY_USE=ContextVar('newsflow_voice_catalog_key_use',default=None)

def deny():raise CredentialError('인증된 목소리 목록 조회에서만 키를 사용할 수 있습니다.')

class ScopedVoiceCatalog(ElevenLabsVoices):
    def __init__(self,profile,nativefactory,*,transport=None,samples=None):
        self.profile=_unlinked(profile)
        if not self.profile.is_absolute() or not self.profile.is_dir():deny()
        store=_Store(self,'elevenlabs',ElevenLabsKeys,nativefactory())
        super().__init__(self.profile,store,transport=transport,samples=samples)

    def active_key(self,provider):
        context=_REQUEST.get()
        if (provider!='elevenlabs' or not isinstance(context,dict) or context.get('owner') is not self
                or _KEY_USE.get() is not context):deny()

    def load(self,*,more=False,all_voices=False):
        context=_REQUEST.get()
        if (not isinstance(context,dict) or context.get('owner') is not self
                or context.get('started') or type(more) is not bool or type(all_voices) is not bool):deny()
        context['started']=True
        token=_KEY_USE.set(context)
        try:return super().load(more=more,all_voices=all_voices)
        finally:_KEY_USE.reset(token)

    def wrap(self,normal,authenticated):
        owner=self
        class Requests:
            async def __call__(self,scope,receive,send):
                if (scope.get('type')!='http' or scope.get('method')!='POST' or scope.get('path')!=PATH):
                    return await normal(scope,receive,send)
                token=_REQUEST.set({'owner':owner,'started':False})
                try:return await authenticated(scope,receive,send)
                finally:_REQUEST.reset(token)
        return Requests()

def install(app,profile,nativefactory,*,transport=None,samples=None):
    if (_unlinked(app.state.config.data_dir)!=_unlinked(profile)
            or getattr(app.state,'eleven_voice_catalog',None) is not None):deny()
    catalog=ScopedVoiceCatalog(profile,nativefactory,transport=transport,samples=samples)
    app.state.eleven_voice_catalog=catalog
    return catalog
