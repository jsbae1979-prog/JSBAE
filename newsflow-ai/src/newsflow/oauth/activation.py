"""Production boundary: a future reviewed code change is required.

No environment variable, configuration field, GUI request, approval object or test
flag is accepted here. Protocol tests use a separate synthetic loopback transport;
they never activate this boundary.
"""

from typing import NoReturn

from .contracts import OAuthBlocked


def require_production_activation() -> NoReturn:
    """Reject production authorization, browser, transport and credential access."""
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
        "production_storage_allowed": False,
        "publishing_allowed": False,
    }
