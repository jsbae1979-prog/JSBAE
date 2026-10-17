"""Default-closed boundary with an explicit, context-local YouTube operation.

Legacy entry points remain closed without this service-owned context. Configuration
and environment variables cannot activate network, browser or credential access.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from .contracts import OAuthBlocked

_YOUTUBE_OPERATION: ContextVar[bool] = ContextVar("newsflow_youtube_operation", default=False)


@contextmanager
def youtube_operation(*, consent: bool) -> Iterator[None]:
    """Scope an explicitly approved YouTube service operation to the current context.

    This is not a global configuration switch. Browser, transport and storage calls
    outside the service's short-lived operation remain blocked, including other threads.
    """
    if consent is not True:
        raise OAuthBlocked()
    token = _YOUTUBE_OPERATION.set(True)
    try:
        yield
    finally:
        _YOUTUBE_OPERATION.reset(token)


def require_production_activation() -> None:
    """Permit only a service operation carrying explicit user consent."""
    if not _YOUTUBE_OPERATION.get():
        raise OAuthBlocked()


def production_activation_status() -> dict[str, str | bool]:
    """Public readiness metadata only; no credential or client configuration."""
    return {
        "phase": "4B-2B",
        "production_activation": False,
        "environment_can_activate": False,
        "gui_can_activate": False,
        "browser_login_allowed": False,
        "token_exchange_allowed": False,
        "production_storage_allowed": _YOUTUBE_OPERATION.get(),
        "publishing_allowed": False,
    }
