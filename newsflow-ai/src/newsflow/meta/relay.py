"""Separate secret-holding relay; reuse one-use state/verifier, cancellation and HTTP boundary."""

import os
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from pydantic import SecretStr

from newsflow.oauth.instagram import FACEBOOK_SCOPES, InstagramConnectionError
from newsflow.oauth.instagram_relay import InstagramRelayAuthorization
from newsflow.oauth.relay_server import (
    MetaRelayTransport,
    RelayConfig,
    RelayError,
    RelaySessions,
    create_relay_app,
)

from .contracts import SCOPES, TASKS, MetaError, object_id, parse_grant, timestamp
from .graph import MetaGraph


@dataclass(frozen=True)
class MetaServerConfig(RelayConfig):
    graph_version: str = "v26.0"

    def __post_init__(self):
        super().__post_init__()
        if not re.fullmatch(r"v[1-9][0-9]\.0", self.graph_version):
            raise RelayError("configuration_invalid")


class MetaBusinessTransport(MetaRelayTransport):
    def exchange(self, code):
        short = super().exchange(code)
        token = short.get("access_token")
        if not isinstance(token, str) or not token:
            raise RelayError("authentication_failed")
        # A distinct documented exchange, not a retry of the authorization code.
        return self._request(
            "POST",
            "oauth/access_token",
            values={
                "grant_type": "fb_exchange_token",
                "client_id": self.config.app_id,
                "client_secret": self.config.app_secret.get_secret_value(),
                "fb_exchange_token": token,
            },
        )

    def pages(self, token):
        result = []
        after = None
        seen = set()
        for _ in range(20):
            values = {"fields": "id,name,access_token,tasks,instagram_business_account", "limit": "100"}
            if after:
                values["after"] = after
            data = self._request("GET", "me/accounts", values=values, token=token)
            rows = data.get("data")
            if not isinstance(rows, list):
                raise RelayError("outcome_unknown")
            result.extend(rows)
            paging = data.get("paging") or {}
            if not paging.get("next"):
                return {"data": result}
            after = paging.get("cursors", {}).get("after")
            if not isinstance(after, str) or not 1 <= len(after) <= 2048 or after in seen:
                raise RelayError("outcome_unknown")
            seen.add(after)  # Never follow the token-bearing next URL.
        raise RelayError("outcome_unknown")

    def profile(self, identifier, token):
        return MetaGraph(self.config.graph_version).call(
            "GET", object_id(identifier), token, {"fields": "id,username"}
        )


class MetaBusinessSessions(RelaySessions):
    def _exchange(self, code, checkpoint):
        try:
            checkpoint()
            response = self.transport.exchange(code)
            token = SecretStr(response["access_token"])
            if not 1 <= len(token.get_secret_value()) <= 4096:
                raise MetaError("invalid")
            checkpoint()
            data = self.transport.inspect(token)["data"]
            if (
                data.get("is_valid") is not True
                or data.get("type") != "USER"
                or str(data.get("app_id")) != self.config.app_id
            ):
                raise MetaError("identity")
            object_id(data.get("user_id"))
            user_exp = timestamp(data.get("expires_at"))
            data_exp = timestamp(data.get("data_access_expires_at"))
            if min(user_exp, data_exp).timestamp() <= self.clock() + 30:
                raise MetaError("expired")
            checkpoint()
            permissions = self.transport.permissions(token).get("data")
            if not isinstance(permissions, list):
                raise MetaError("invalid")
            granted = {
                x.get("permission")
                for x in permissions
                if isinstance(x, dict) and x.get("status") == "granted"
            }
            granted &= set(data.get("scopes", []))
            if not set(SCOPES[:3]) <= granted:
                raise MetaError("permission")
            checkpoint()
            rows = self.transport.pages(token)["data"]
            choices = []
            private = {}
            if not isinstance(rows, list) or len(rows) > 2000:
                raise MetaError("invalid")
            for row in rows:
                checkpoint()
                if not isinstance(row, dict) or not TASKS.intersection(row.get("tasks", [])):
                    continue
                page = object_id(row.get("id"))
                name = row.get("name")
                if page in private or not isinstance(name, str) or not 1 <= len(name) <= 200:
                    raise MetaError("invalid")
                raw = row.get("access_token")
                if not isinstance(raw, str) or not 1 <= len(raw) <= 4096:
                    raise MetaError("invalid")
                page_token = SecretStr(raw)
                check = self.transport.inspect(page_token)["data"]
                if (
                    check.get("is_valid") is not True
                    or str(check.get("app_id")) != self.config.app_id
                    or check.get("type") != "PAGE"
                    or str(check.get("profile_id")) != page
                ):
                    raise MetaError("identity")
                page_exp = timestamp(check.get("expires_at"), allow_zero=True)
                if page_exp and page_exp.timestamp() <= self.clock() + 30:
                    continue
                page_data = timestamp(check.get("data_access_expires_at"), allow_zero=True)
                if "scopes" in check and not set(SCOPES[:3]) <= set(check["scopes"]):
                    continue
                effective_data = min(data_exp, page_data) if page_data else data_exp
                linked = row.get("instagram_business_account")
                ig = None
                ig_name = None
                if (
                    isinstance(linked, dict)
                    and set(SCOPES) <= granted
                    and set(SCOPES) <= set(check.get("scopes", granted))
                ):
                    ig = object_id(linked.get("id"))
                    profile = self.transport.profile(ig, page_token)
                    if profile.get("id") != ig:
                        raise MetaError("identity")
                    ig_name = profile.get("username")
                    if not isinstance(ig_name, str) or not re.fullmatch(r"[A-Za-z0-9_.]{1,30}", ig_name):
                        raise MetaError("invalid")
                entry = {
                    "page_id": page,
                    "page_name": name,
                    "instagram_id": ig,
                    "instagram_name": ig_name,
                    "page_access_token": raw,
                    "page_expires_at": page_exp.isoformat() if page_exp else None,
                    "data_access_expires_at": effective_data.isoformat(),
                    "tasks": row["tasks"],
                }
                private[page] = entry
                choices.append({"id": page, "name": name, "instagram_id": ig})
            if not choices:
                raise MetaError("permission")
            return {
                "app_id": self.config.app_id,
                "access_token": token.get_secret_value(),
                "expires_at": user_exp.isoformat(),
                "data_access_expires_at": data_exp.isoformat(),
                "scopes": sorted(granted),
                "_selected_grants": private,
            }, choices
        except MetaError as error:
            code = {
                "permission": "permission_denied",
                "expired": "expired",
                "identity": "identity_mismatch",
            }.get(error.code, "authentication_failed")
            raise RelayError(code) from None
        except (KeyError, TypeError, ValueError):
            raise RelayError("authentication_failed") from None

    def redeem(self, identifier, verifier, page_id):
        result = super().redeem(identifier, verifier, page_id)
        grants = result.pop("_selected_grants")
        selected = grants[page_id]
        return {**result, **selected}


def create_meta_relay_app(config, *, transport=None, clock=None):
    return create_relay_app(
        config,
        transport=transport or MetaBusinessTransport(config),
        clock=clock,
        sessions_factory=MetaBusinessSessions,
    )


def from_environment():
    # Only the separately deployed relay calls this factory. The desktop never does.
    return create_meta_relay_app(
        MetaServerConfig(
            os.environ["NEWSFLOW_META_RELAY_ORIGIN"],
            os.environ["NEWSFLOW_META_APP_ID"],
            os.environ["NEWSFLOW_META_CONFIG_ID"],
            SecretStr(os.environ["NEWSFLOW_META_APP_SECRET"]),
            graph_version=os.environ.get("NEWSFLOW_META_GRAPH_VERSION", "v26.0"),
        )
    )


class MetaDesktopAuthorization(InstagramRelayAuthorization):
    def __init__(self, config, *, config_id, graph_version="v26.0", **kwargs):
        super().__init__(config, **kwargs)
        self.config_id = object_id(config_id)
        self.graph_version = graph_version

    def _authorization_url(self, value):
        try:
            u = urlsplit(value)
            pairs = parse_qsl(u.query, strict_parsing=True)
            q = dict(pairs)
            if (
                u.scheme != "https"
                or u.netloc != "www.facebook.com"
                or u.fragment
                or u.path != f"/{self.graph_version}/dialog/oauth"
                or len(pairs) != len(q)
                or set(q)
                != {
                    "client_id",
                    "config_id",
                    "response_type",
                    "override_default_response_type",
                    "state",
                    "redirect_uri",
                }
                or q["client_id"] != self.config.app_id
                or q["config_id"] != self.config_id
                or q["response_type"] != "code"
                or q["override_default_response_type"] != "true"
                or q["redirect_uri"] != self.config.origin + "/oauth/callback"
                or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", q["state"])
            ):
                raise ValueError
            return value
        except Exception:  # noqa: BLE001 - never expose provider, credential or native exception details
            raise InstagramConnectionError("response_invalid") from None

    @staticmethod
    def _page_choices(value):
        try:
            if not isinstance(value, list) or not 1 <= len(value) <= 2000:
                raise ValueError
            rows = []
            for row in value:
                page = object_id(row["id"])
                ig = object_id(row["instagram_id"]) if row.get("instagram_id") else None
                if not isinstance(row["name"], str) or not 1 <= len(row["name"]) <= 200:
                    raise ValueError
                rows.append({"id": page, "name": row["name"], "instagram_id": ig})
            if len({r["id"] for r in rows}) != len(rows):
                raise ValueError
            return rows
        except Exception:  # noqa: BLE001 - never expose provider, credential or native exception details
            raise InstagramConnectionError("response_invalid") from None

    def authorize(self, *, scopes):
        if tuple(scopes) != SCOPES:
            raise InstagramConnectionError("permission_denied")
        return super().authorize(scopes=FACEBOOK_SCOPES)

    def _grant(self, data, page_id):
        try:
            return parse_grant(data, self.config.app_id, page_id)
        except MetaError:
            raise InstagramConnectionError("response_invalid") from None
