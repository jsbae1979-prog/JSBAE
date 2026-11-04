"""User-initiated YouTube connection only; no upload, global cipher or background grant."""
from contextvars import ContextVar
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from pydantic import SecretStr
from newsflow.oauth.activation import require_production_activation, production_activation_status
from newsflow.oauth.contracts import OAuthBlocked
from newsflow.oauth.production import BrowserLaunchError, ProtocolError
from newsflow.oauth.youtube import YouTubeClientStore
from newsflow.oauth.production_dpapi import (
    ProductionWindowsCredentialVault, ProductionVaultError, _ProductionDPAPIFileKernel, _owner_sid,
)
from newsflow.distribution.windows_profile import unlinked

_REQUEST = ContextVar('youtube_connection_request', default=None)
_ACTIONS = re.compile(r'/youtube/(?:client|connect(?:/[1-9][0-9]*/(?:cancel|reopen))?)\Z')

class _Client(YouTubeClientStore):
    def __init__(self, owner):
        super().__init__(owner.profile)
        self.owner = owner
    def _get_cipher(self):
        if _REQUEST.get() is not self.owner:
            raise OAuthBlocked()
        # Never replace the global DPAPI prohibition for other services.
        return self.owner.native_factory()
    def key(self):
        if _REQUEST.get() is not self.owner:
            raise OAuthBlocked()
        unlinked(self.path)
        return super().key()
    def save(self, value):
        if _REQUEST.get() is not self.owner:
            raise OAuthBlocked()
        unlinked(self.path)
        return super().save(value)
    def clear(self):
        raise OAuthBlocked()

class _Vault(ProductionWindowsCredentialVault):
    def __init__(self, owner):
        super().__init__(owner.profile / 'youtube-oauth')
        self.owner = owner
    def _backend(self):
        require_production_activation()
        if production_activation_status()['production_storage_allowed'] is not True:
            raise OAuthBlocked()
        try:
            if self._kernel is None:
                self._kernel = _ProductionDPAPIFileKernel(
                    self._root, self.owner.native_factory(), _owner_sid(),
                    native=True, synthetic_only=False)
            return self._kernel
        except Exception:
            raise ProductionVaultError() from None

class ChromeOAuthBrowser:
    def open(self, authorization_url):
        require_production_activation()
        if not isinstance(authorization_url, SecretStr):
            raise ProtocolError('transport_invalid')
        value = authorization_url.get_secret_value()
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.netloc != 'accounts.google.com'
                or parsed.path != '/o/oauth2/v2/auth' or parsed.fragment):
            raise ProtocolError('transport_invalid')
        try:
            for path in (Path('C:/Program Files/Google/Chrome/Application/chrome.exe'),
                         Path('C:/Program Files (x86)/Google/Chrome/Application/chrome.exe'),
                         Path.home() / 'AppData/Local/Google/Chrome/Application/chrome.exe'):
                path = unlinked(path)
                if path.is_file():
                    process = subprocess.Popen([str(path), '--new-window', value], shell=False,
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        close_fds=True)
                    if process.poll() in (None, 0):
                        return
                    break
        except Exception:
            pass
        raise BrowserLaunchError()

class YouTubeConnectionAccess:
    def __init__(self, app, profile, native_factory):
        self.profile = unlinked(Path(profile))
        if self.profile != unlinked(Path(app.state.config.data_dir)):
            raise OAuthBlocked()
        self.native_factory = native_factory
        # Keep the original service/lifespan and its callback, PKCE, ownership and ledger.
        app.state.youtube.client_store = _Client(self)
        app.state.youtube.vault = _Vault(self)
        app.state.youtube.browser = ChromeOAuthBrowser()
    def wrap(self, normal, authenticated):
        owner = self
        async def call(scope, receive, send):
            if (scope.get('type') != 'http' or scope.get('method') != 'POST'
                    or not _ACTIONS.fullmatch(scope.get('path', ''))):
                return await normal(scope, receive, send)
            token = _REQUEST.set(owner)
            try:
                # Windows session, Origin, CSRF and endpoint consent run unchanged.
                return await authenticated(scope, receive, send)
            finally:
                _REQUEST.reset(token)
        return call

def install(app, profile, native_factory):
    return YouTubeConnectionAccess(app, profile, native_factory)
