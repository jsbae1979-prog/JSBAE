"""Manual SerpApi collection only, behind LocalAccess, CSRF and saved usage approval."""
from contextvars import ContextVar
from pathlib import Path
import hashlib
from newsflow.intelligence.credentials import CredentialError
from newsflow.news.serpapi import SerpApiKeys
from .higgsfield_key_registration import _unlinked

PATH = '/news/curation/serpapi'
_REQUEST = ContextVar('manual_serpapi_collection', default=None)

class CollectionStore:
    def __init__(self, owner, registration):
        self.owner, self.registration = owner, registration
    def status(self): return self.registration.status()
    def validate(self, key): return self.registration.validate(key)
    def save(self, key): return self.registration.save(key)
    def clear(self): return self.registration.clear()
    def key(self):
        if _REQUEST.get() is not self.owner:
            raise CredentialError('수집 시작과 사용 승인을 확인하세요.')
        protected = plain = None
        try:
            path = _unlinked(self.owner.profile / SerpApiKeys.FILE)
            if not path.is_file() or path.stat().st_nlink != 1 or not 0 < path.stat().st_size <= 8192:
                raise ValueError()
            protected = bytearray(path.read_bytes())
            plain = self.owner.native.unprotect(protected, bytearray(hashlib.sha256(SerpApiKeys.ENTROPY).digest()))
            if not isinstance(plain, (bytes, bytearray)) or not 0 < len(plain) <= 1024: raise ValueError()
            return SerpApiKeys.validate(bytes(plain).decode('utf8'))
        except Exception:
            raise CredentialError('현재 사용자 SerpApi 키를 확인하세요.') from None
        finally:
            if isinstance(plain, bytearray): plain[:] = b'\0' * len(plain)
            if isinstance(protected, bytearray): protected[:] = b'\0' * len(protected)

class Collection:
    def __init__(self, profile, native):
        self.profile, self.native = _unlinked(Path(profile)), native
    def wrap(self, normal, authenticated):
        owner = self
        class Boundary:
            async def __call__(self, scope, receive, send):
                if scope.get('type') != 'http' or scope.get('method') != 'POST' or scope.get('path') != PATH:
                    return await normal(scope, receive, send)
                token = _REQUEST.set(owner)
                try: return await authenticated(scope, receive, send)
                finally: _REQUEST.reset(token)
        return Boundary()

def install(app, profile, nativefactory):
    if _unlinked(Path(app.state.config.data_dir)) != _unlinked(Path(profile)):
        raise CredentialError('현재 사용자 데이터 경로를 확인하세요.')
    owner = Collection(profile, nativefactory())
    app.state.serpapi_keys = CollectionStore(owner, app.state.serpapi_keys)
    return owner
