"""Starlette middleware enforcing Bearer auth for Streamable HTTP."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Reject requests without a matching Authorization: Bearer <token>.

    Public paths (e.g. /healthz) can be exempted for load-balancer probes.
    """

    def __init__(
        self,
        app,
        *,
        token: str,
        public_paths: set[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.token = token
        self.public_paths = public_paths or {"/healthz"}

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path.rstrip("/") or "/"
        public = {p.rstrip("/") or "/" for p in self.public_paths}
        if path in public:
            return await call_next(request)

        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        provided: str | None = None
        if auth and auth.lower().startswith("bearer "):
            provided = auth[7:].strip()
        elif request.headers.get("x-api-key"):
            provided = request.headers.get("x-api-key")

        if not provided or provided != self.token:
            return JSONResponse(
                {"error": "unauthorized", "message": "Valid Bearer token required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)
