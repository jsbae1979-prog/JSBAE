"""Exact Meta routes only; inner Windows authentication and CSRF remain mandatory.

External requests require explicit installation provisioning. This flag neither
substitutes account permissions nor grants publication consent. No other API is
forwarded; existing global provider/scheduler boundaries remain unchanged.
"""

import re

from starlette.responses import JSONResponse

LOCAL = re.compile(
    r"/api/meta/(?:config|media-config|automatic-storage|accounts/[a-f0-9]{32}/(?:rename|disconnect)|publications/prepare|publications/[a-f0-9]{32}/storage)\Z"
)
EXTERNAL = re.compile(
    r"/api/meta/(?:import-token|connect|select-page|cancel|publications/[a-f0-9]{32}/(?:send|check|publish))\Z"
)


class MetaRequests:
    def __init__(self, normal, authenticated, *, enabled=False):
        self.normal, self.authenticated, self.enabled = normal, authenticated, enabled is True

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            method, path = scope.get("method"), scope.get("path", "")
            if (method == "GET" and path == "/api/meta/status") or (
                method == "POST" and LOCAL.fullmatch(path)
            ):
                return await self.authenticated(scope, receive, send)
            if method == "POST" and EXTERNAL.fullmatch(path):
                if self.enabled:
                    return await self.authenticated(scope, receive, send)
                return await JSONResponse(
                    {
                        "detail": {
                            "code": "unavailable",
                            "message": "Meta 실행 연결이 아직 적용되지 않았습니다.",
                        }
                    },
                    status_code=403,
                )(scope, receive, send)
        return await self.normal(scope, receive, send)
