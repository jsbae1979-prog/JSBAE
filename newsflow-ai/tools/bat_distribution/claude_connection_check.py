"""One explicit Claude model-metadata GET in the authenticated operating profile.

This does not grant inference, key mutation, other providers, or a global DPAPI
capability. The existing connection service owns verification and its expiry.
"""
from contextvars import ContextVar

from newsflow.intelligence.api_connection import (
    CHECK_MESSAGES, ConnectionCheckResult, ENDPOINT, MAX_RESPONSE_BYTES, TIMEOUT_SECONDS,
    check_claude_connection,
)
from newsflow.intelligence.api_providers import API_MODELS
from newsflow.intelligence.api_settings import read_api_settings
from newsflow.intelligence.credentials import AnthropicKeyStore, CredentialError
from newsflow.intelligence.provider import OpenAIProvider

from .character_authoring import _Store, _unlinked

PATH = '/api-settings/claude_api/check'
_REQUEST = ContextVar('newsflow_claude_metadata_request', default=None)
_KEY_USE = ContextVar('newsflow_claude_metadata_key_use', default=None)


def _deny():
    raise CredentialError('승인된 Claude 연결 확인 요청만 사용할 수 있습니다.')


class ClaudeConnectionCheck:
    def __init__(self, sessions, profile, nativefactory, *, transport=None):
        self.sessions, self.profile = sessions, _unlinked(profile)
        if not self.profile.is_absolute() or not self.profile.is_dir():
            _deny()
        # Reuse the exact-profile, read-only DPAPI store; no environment fallback.
        self.store = _Store(self, 'claude_api', AnthropicKeyStore, nativefactory())
        self.transport = transport or OpenAIProvider(allow_retry=False)._open

    def _context(self):
        context = _REQUEST.get()
        if not isinstance(context, dict) or context.get('owner') is not self:
            _deny()
        return context

    def active_key(self, provider):
        context = self._context()
        if provider != 'claude_api' or _KEY_USE.get() is not context:
            _deny()

    def _metadata(self, request, timeout, limit):
        context = self._context()
        model = context.get('model')
        headers = {name.lower(): value for name, value in request.header_items()}
        if (_KEY_USE.get() is not context or context.get('sent') is not False
                or model not in API_MODELS['claude_api']
                or request.get_method() != 'GET' or request.full_url != ENDPOINT + model
                or request.data is not None or request.unredirected_hdrs
                or set(headers) != {'accept', 'x-api-key', 'anthropic-version'}
                or headers.get('accept') != 'application/json'
                or headers.get('anthropic-version') != '2023-06-01'
                or timeout != TIMEOUT_SECONDS or limit != MAX_RESPONSE_BYTES):
            _deny()
        # Mark before dispatch: a timeout/redirect/failure cannot be replayed.
        context['sent'] = True
        return self.transport(request, timeout, limit)

    def check(self, *, consent=False):
        try:
            context = self._context()
        except CredentialError:
            return ConnectionCheckResult(False, 'unavailable', CHECK_MESSAGES['unavailable'])
        if consent is not True:
            return ConnectionCheckResult(False, 'consent_required', CHECK_MESSAGES['consent_required'])
        if context.get('started'):
            return ConnectionCheckResult(False, 'busy', CHECK_MESSAGES['busy'])
        context.update(started=True, sent=False,
                       model=read_api_settings(self.sessions, 'claude_api').model)
        token = _KEY_USE.set(context)
        try:
            return check_claude_connection(self.sessions, self.store, consent=True, transport=self._metadata)
        finally:
            _KEY_USE.reset(token)

    def wrap(self, normal_app, authenticated_app):
        return _Requests(self, normal_app, authenticated_app)


class _Requests:
    def __init__(self, owner, normal, authenticated):
        self.owner, self.normal, self.authenticated = owner, normal, authenticated

    async def __call__(self, scope, receive, send):
        if (scope.get('type') != 'http' or scope.get('method') != 'POST' or scope.get('path') != PATH):
            return await self.normal(scope, receive, send)
        token = _REQUEST.set({'owner': self.owner})
        try:
            # Existing LocalAccess, Origin and signed CSRF run before the callback.
            return await self.authenticated(scope, receive, send)
        finally:
            _REQUEST.reset(token)


def install(app, profile, nativefactory, *, transport=None):
    if (getattr(app.state, 'claude_metadata_check', None) is not None
            or _unlinked(app.state.config.data_dir) != _unlinked(profile)):
        _deny()
    checker = ClaudeConnectionCheck(app.state.sessions, profile, nativefactory, transport=transport)
    app.state.claude_metadata_check = checker.check
    return checker
