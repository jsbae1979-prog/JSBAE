"""Exact SerpApi registration: protect-only DPAPI, no collection or key reading."""
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4
import hashlib
import hmac
import os
from filelock import FileLock
from newsflow.intelligence.credentials import CredentialError
from newsflow.news.serpapi import SerpApiKeys
from .higgsfield_key_registration import _private, _unlinked

PATH = '/serpapi/settings'
_REQUEST = ContextVar('serpapi_key_registration', default=None)
ENTROPY = hashlib.sha256(SerpApiKeys.ENTROPY).digest()

class Store(SerpApiKeys):
    def __init__(self, owner):
        super().__init__(owner.profile)
        self.owner = owner

    def key(self):
        raise CredentialError('키 등록에는 비밀값 읽기 권한이 없습니다.')

    def clear(self):
        raise CredentialError('키 등록에는 삭제 권한이 없습니다.')

    def save(self, key):
        self.owner.active()
        plain = bytearray(self.validate(key).encode('utf-8'))
        protected = None
        temporary = None
        created = False
        try:
            with FileLock(str(self.owner.profile / 'serpapi-key-save.lock'), timeout=0):
                _private(self.owner.profile)
                target = _unlinked(self.path)
                if target != self.owner.profile / self.FILE:
                    raise CredentialError('현재 사용자 저장 위치를 확인하세요.')
                if target.exists():
                    if not target.is_file() or target.stat().st_nlink != 1 or not 0 < target.stat().st_size <= 8192:
                        raise CredentialError('기존 보호 파일을 확인하세요.')
                    folder = _private(_private(self.owner.profile / 'credential-backups') / ('serpapi-' + uuid4().hex))
                    previous = bytearray(target.read_bytes())
                    try:
                        backup = _unlinked(folder / self.FILE)
                        with backup.open('xb') as out:
                            out.write(previous); out.flush(); os.fsync(out.fileno())
                        if not hmac.compare_digest(previous, backup.read_bytes()):
                            raise CredentialError('기존 키 백업을 확인하지 못했습니다.')
                    finally:
                        previous[:] = b'\0' * len(previous)
                protected = self.owner.native.protect(plain, bytearray(ENTROPY))
                if not isinstance(protected, (bytes, bytearray)) or not 0 < len(protected) <= 8192:
                    raise CredentialError('보호 저장 결과를 확인하세요.')
                temporary = _unlinked(target.with_name(self.FILE + '.registration-' + uuid4().hex + '.tmp'))
                with temporary.open('xb') as out:
                    created = True
                    out.write(protected); out.flush(); os.fsync(out.fileno())
                os.replace(temporary, target)
                created = False
        except Exception:
            raise CredentialError('SerpApi 키 저장을 완료하지 못했습니다. 기존 키와 백업을 보존합니다.') from None
        finally:
            plain[:] = b'\0' * len(plain)
            if isinstance(protected, bytearray): protected[:] = b'\0' * len(protected)
            if created:
                try: temporary.unlink(missing_ok=True)
                except OSError: pass  # Never conceal a failed save with a cleanup error.

class Registration:
    def __init__(self, profile, native):
        self.profile = _unlinked(Path(profile))
        _private(self.profile)
        self.native = native

    def active(self):
        if _REQUEST.get() is not self:
            raise CredentialError('인증된 설정 화면에서 저장하세요.')

    def wrap(self, normal, authenticated):
        owner = self
        class Requests:
            async def __call__(self, scope, receive, send):
                if scope.get('type') != 'http' or scope.get('method') != 'POST' or scope.get('path') != PATH:
                    return await normal(scope, receive, send)
                token = _REQUEST.set(owner)
                try: return await authenticated(scope, receive, send)
                finally: _REQUEST.reset(token)
        return Requests()

def install(app, profile, nativefactory):
    if _unlinked(Path(app.state.config.data_dir)) != _unlinked(Path(profile)):
        raise CredentialError('현재 사용자 프로필에만 저장할 수 있습니다.')
    if getattr(app.state, 'serpapi_registration_available', False):
        raise CredentialError('키 등록 연결이 이미 적용되어 있습니다.')
    owner = Registration(profile, nativefactory())
    app.state.serpapi_keys = Store(owner)
    app.state.serpapi_registration_available = True
    return owner
