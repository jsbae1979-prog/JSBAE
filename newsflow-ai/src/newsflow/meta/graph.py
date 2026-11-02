"""Fixed Meta Graph host, bounded bodies and one attempt only. Inject HTTP in tests."""

import json
import re
import ssl
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from pydantic import SecretStr

from .contracts import MetaError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class MetaGraph:
    def __init__(self, version="v26.0", transport=None):
        if not re.fullmatch(r"v[1-9][0-9]\.0", version):
            raise MetaError("configuration")
        self.version, self.transport = version, transport or self._http

    def _http(self, method, url, headers, body):
        request = Request(url, headers=headers, data=body if method == "POST" else None, method=method)
        try:
            response = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context())).open(
                request, timeout=120
            )
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.read(262145)

    def call(self, method, path, token, values=None):
        valid = (
            method == "GET"
            and (
                path in {"me/permissions", "me/accounts", "debug_token"}
                or re.fullmatch(r"[1-9][0-9_]{0,80}", path)
            )
        ) or (
            method == "POST"
            and re.fullmatch(r"[1-9][0-9]{0,39}/(?:media|media_publish|photos|videos|feed)", path)
        )
        if not valid or not isinstance(token, SecretStr):
            raise MetaError("invalid")
        values = values or {}
        if (
            set(values) & {"access_token", "client_secret"}
            or ("input_token" in values and path != "debug_token")
            or (path == "debug_token" and set(values) != {"input_token"})
        ):
            raise MetaError("invalid")
        body = urlencode(values).encode("utf8")
        url = f"https://graph.facebook.com/{self.version}/{path}"
        if len(body) > 32768:
            raise MetaError("invalid")
        if method == "GET" and body:
            url += "?" + body.decode("ascii")
        return self.request(
            method,
            url,
            {
                "Authorization": "Bearer " + token.get_secret_value(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body,
        )

    @staticmethod
    def supports_direct(platform, kind):
        return platform == "facebook" or (platform == "instagram" and kind == "video")

    def upload_file(self, target, token, raw, kind, caption):
        from .direct_upload import facebook_file

        return facebook_file(self, target, token, raw, kind, caption)

    def upload_reel(self, container, token, raw):
        from .direct_upload import instagram_file

        return instagram_file(self, container, token, raw)

    def request(self, method, url, headers, body):
        try:
            status, raw = self.transport(method, url, headers, body)
            if len(raw) > 262144:
                raise MetaError("unknown")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise MetaError("unknown")
            if not 200 <= status < 300 or "error" in data:
                detail = data.get("error") if isinstance(data.get("error"), dict) else {}
                code = detail.get("code")
                raise MetaError(
                    "authentication"
                    if code == 190 or status == 401
                    else "permission"
                    if code in {10, 200} or status == 403
                    else "unknown"
                    if status >= 500 or status in {408, 429}
                    else "rejected",
                    diagnostics={"http_status": status, "provider_code": code,
                                 "provider_subcode": detail.get("error_subcode")},
                )
            return data
        except MetaError:
            raise
        except Exception:  # noqa: BLE001 - never expose provider, credential or native exception details
            raise MetaError("unknown") from None
