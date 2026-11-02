"""Explicit user-token import. No app secret, OAuth exchange, or automatic renewal."""

from time import time
from types import SimpleNamespace

from pydantic import SecretStr

from newsflow.oauth.relay_server import RelayError

from .contracts import MetaError, parse_grant
from .graph import MetaGraph
from .relay import MetaBusinessSessions


class DirectTransport:
    def __init__(self, token, version, graph=None):
        self.token = token
        self.graph = graph or MetaGraph(version)

    def exchange(self, _code):
        # Reuse the verified-grant parser, without exchanging/refreshing a token.
        return {"access_token": self.token.get_secret_value()}

    def inspect(self, token):
        return self.graph.call("GET", "debug_token", self.token, {"input_token": token.get_secret_value()})

    def permissions(self, token):
        return self.graph.call("GET", "me/permissions", token, {})

    def pages(self, token):
        rows, seen, after = [], set(), None
        for _ in range(20):
            values = {"fields": "id,name,access_token,tasks,instagram_business_account", "limit": "100"}
            if after:
                values["after"] = after
            result = self.graph.call("GET", "me/accounts", token, values)
            if not isinstance(result.get("data"), list):
                raise MetaError("invalid")
            rows.extend(result["data"])
            paging = result.get("paging") or {}
            if not paging.get("next"):
                return {"data": rows}
            after = paging.get("cursors", {}).get("after")
            if not isinstance(after, str) or not 1 <= len(after) <= 2048 or after in seen:
                raise MetaError("invalid")
            seen.add(after)  # Never follow a provider URL containing credentials.
        raise MetaError("invalid")

    def profile(self, identifier, token):
        return self.graph.call("GET", identifier, token, {"fields": "id,username"})


def discover(token, config, *, graph=None):
    if not isinstance(token, SecretStr):
        raise MetaError("invalid")
    value = token.get_secret_value()
    if not 1 <= len(value) <= 4096 or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise MetaError("invalid")
    verifier = SimpleNamespace(
        config=SimpleNamespace(app_id=config["appId"]),
        clock=time,
        transport=DirectTransport(token, config["graphVersion"], graph),
    )
    try:
        data, choices = MetaBusinessSessions._exchange(verifier, None, lambda: None)
        private = data.pop("_selected_grants")
        grants = {
            page: parse_grant({**data, **entry}, config["appId"], page) for page, entry in private.items()
        }
        return grants, choices
    except RelayError as error:
        raise MetaError(
            {"permission_denied": "permission", "identity_mismatch": "identity", "expired": "expired"}.get(
                error.code, "invalid"
            )
        ) from None
