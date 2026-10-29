"""Normal local Higgsfield key registration, independent of paid execution.

install(app, profile, original_dpapi_factory).wrap(normal_app, authenticated_app)
delegates exactly POST /video-ai-settings/key through the unchanged LocalAccess,
Origin and CSRF layers. Native authority is protect-only, for this profile's
video-ai-key.dpapi and the existing Higgsfield entropy. No API request is sent.
"""
from __future__ import annotations

from contextvars import ContextVar
import hashlib
import hmac
import os
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

from newsflow.intelligence.credentials import CredentialError
from newsflow.video.ai.keys import VideoAIKeyStore

PATH='/video-ai-settings/key'
_CONTEXT=ContextVar('newsflow_higgsfield_key_registration',default=None)
_ENTROPY=hashlib.sha256(VideoAIKeyStore.ENTROPY).digest()


def _private(path):
    from newsflow.distribution.windows_profile import private_directory
    return private_directory(path)


def _unlinked(path):
    from newsflow.distribution.windows_profile import unlinked
    return unlinked(path)


class _ProtectOnly:
    def __init__(self,registration,native):
        self.registration,self.native=registration,native

    def protect(self,payload,entropy):
        self.registration.active()
        if (not isinstance(payload,bytearray) or not 8<=len(payload)<=520
                or not isinstance(entropy,bytearray) or bytes(entropy)!=_ENTROPY):
            raise CredentialError('Higgsfield 키 저장 범위를 확인하세요.')
        try:
            return self.native.protect(payload,entropy)
        except Exception:
            raise CredentialError('Windows 보호 저장소에 키를 저장하지 못했습니다.') from None

    def unprotect(self,payload,entropy):
        raise CredentialError('키 등록 기능에는 비밀값 읽기 권한이 없습니다.')


class _Store(VideoAIKeyStore):
    def __init__(self,registration,cipher):
        super().__init__(registration.profile,cipher)
        self.registration=registration

    def key(self):
        raise CredentialError('키 등록 기능에는 비밀값 읽기 권한이 없습니다.')

    def clear(self):
        raise CredentialError('이번 저장 기능에는 키 삭제 권한이 없습니다.')

    def save(self,key):
        self.registration.active()
        key=self.validate(key)
        plain=bytearray(key.encode('utf8'))
        protected=None
        temporary=None
        created=False
        try:
            with FileLock(str(self.registration.profile/'higgsfield-key-save.lock'),timeout=0):
                _private(self.registration.profile)
                target=_unlinked(self.path)
                if target!=self.registration.profile/VideoAIKeyStore.FILE:
                    raise CredentialError('현재 사용자 키 저장 경로를 확인하세요.')
                if target.exists():
                    if (not target.is_file() or target.stat().st_nlink!=1
                            or not 0<target.stat().st_size<=8192):
                        raise CredentialError('기존 보호 파일을 확인한 뒤 다시 저장하세요.')
                    self.registration.backup(target)
                protected=self._cipher.protect(plain,bytearray(_ENTROPY))
                if not isinstance(protected,(bytearray,bytes)) or not 0<len(protected)<=8192:
                    raise CredentialError('Windows 보호 저장소의 결과를 확인하세요.')
                temporary=_unlinked(self.path.with_name(self.FILE+'.registration-'+uuid4().hex+'.tmp'))
                with temporary.open('xb') as stream:
                    created=True
                    stream.write(protected)
                    stream.flush()
                    os.fsync(stream.fileno())
                # New ciphertext inherits the already protected current-user
                # directory. Replace atomically; never rewrite the old file.
                os.replace(temporary,target)
                created=False
        except CredentialError:
            raise
        except Exception:
            # No key, ciphertext, path, native diagnostic or fingerprint escapes.
            raise CredentialError('키 저장을 완료하지 못했습니다. 기존 보호 파일과 백업은 보존됩니다.') from None
        finally:
            plain[:]=b'\0'*len(plain)
            if isinstance(protected,bytearray):protected[:]=b'\0'*len(protected)
            if created and temporary is not None:
                try:temporary.unlink(missing_ok=True)
                except OSError:pass  # Preserve an unknown cleanup outcome; never claim success.


class Registration:
    def __init__(self,profile):
        self.profile=_unlinked(Path(profile))
        if not self.profile.is_absolute() or not self.profile.is_dir():
            raise CredentialError('현재 Windows 사용자 프로필을 확인하세요.')
        _private(self.profile)

    def active(self):
        if _CONTEXT.get() is not self:
            raise CredentialError('인증된 키 저장 화면에서 직접 저장하세요.')

    def backup(self,target):
        self.active()
        base=_private(self.profile/'credential-backups')
        folder=_private(base/('higgsfield-'+uuid4().hex))
        destination=_unlinked(folder/VideoAIKeyStore.FILE)
        previous=bytearray(target.read_bytes())
        try:
            with destination.open('xb') as stream:
                stream.write(previous)
                stream.flush()
                os.fsync(stream.fileno())
            if not hmac.compare_digest(previous,destination.read_bytes()):
                raise CredentialError('기존 보호 파일의 백업을 확인하지 못했습니다.')
        finally:
            previous[:]=b'\0'*len(previous)

    def wrap(self,normal_app,authenticated_app):
        return _Requests(self,normal_app,authenticated_app)


class _Requests:
    def __init__(self,registration,normal_app,authenticated_app):
        self.registration,self.normal,self.authenticated=registration,normal_app,authenticated_app

    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope['method']!='POST' or scope['path']!=PATH:
            return await self.normal(scope,receive,send)
        token=_CONTEXT.set(self.registration)
        try:
            # The product handler is reached only after the original local
            # authentication, Origin and signed-CSRF middleware succeeds.
            return await self.authenticated(scope,receive,send)
        finally:
            _CONTEXT.reset(token)


def install(app,profile,nativefactory):
    """Keep global NoNativeCipher and character-trial counters entirely untouched."""
    registration=Registration(profile)
    configured=_unlinked(Path(app.state.config.data_dir))
    if configured!=registration.profile:
        raise CredentialError('현재 앱과 동일한 사용자 프로필에만 키를 저장할 수 있습니다.')
    if isinstance(app.state.video_ai.keys,_Store):
        raise CredentialError('키 저장 연결이 이미 적용되어 있습니다.')
    native=nativefactory()  # Construction only: never decrypts or sends a request.
    app.state.video_ai.keys=_Store(registration,_ProtectOnly(registration,native))
    return registration
