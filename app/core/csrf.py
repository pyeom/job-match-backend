"""
CSRF protection middleware for the web interface.

Uses itsdangerous to issue and verify signed CSRF tokens.

Strategy:
- A CSRF token is issued via GET /api/v1/csrf-token as a signed cookie (non-HttpOnly)
  so the JavaScript frontend can read it.
- State-changing requests (POST, PUT, PATCH, DELETE) must include the token in the
  X-CSRF-Token header.
- Requests that already carry an Authorization: Bearer token are exempt — bearer-token
  auth is inherently CSRF-safe because cross-origin requests cannot forge the header.
- WebSocket upgrades and safe methods (GET, HEAD, OPTIONS) are always exempt.
"""

import secrets

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request
from fastapi.responses import JSONResponse

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"
CSRF_TOKEN_MAX_AGE = 3600  # 1 hour

_STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_EXEMPT_PATHS = {
    "/api/v1/csrf-token",  # the endpoint that issues tokens
    "/healthz",
    "/healthz/live",
    "/healthz/ready",
    # Auth endpoints are unauthenticated by definition; Bearer-token CSRF exemption
    # cannot apply, and mobile clients don't use cookies/CSRF tokens.
    "/api/v1/auth/register",
    "/api/v1/auth/register-company",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/workos/callback",
    "/api/v1/auth/workos/verify-email",
}


def _get_serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="csrf")


def generate_csrf_token(secret: str) -> str:
    """Generate a signed CSRF token containing a random nonce."""
    nonce = secrets.token_hex(32)
    s = _get_serializer(secret)
    return s.dumps(nonce)


def verify_csrf_token(token: str, secret: str) -> bool:
    """Return True if the token is valid and not expired."""
    s = _get_serializer(secret)
    try:
        s.loads(token, max_age=CSRF_TOKEN_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


class CSRFMiddleware:
    """ASGI middleware that enforces CSRF token validation on state-changing requests."""

    def __init__(self, app, secret: str, is_production: bool = False):
        self.app = app
        self.secret = secret
        self.is_production = is_production

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            # Pass through WebSocket and other non-HTTP scopes untouched
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        method = request.method.upper()

        # Safe methods and WebSocket upgrades are always exempt
        if method not in _STATE_CHANGING_METHODS:
            await self.app(scope, receive, send)
            return

        # Skip CSRF check for exempt paths (token issuance, health)
        if request.url.path in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        # Requests carrying a Bearer token are inherently CSRF-safe
        # (cross-origin JS cannot forge the Authorization header)
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            await self.app(scope, receive, send)
            return

        # Validate CSRF token from header
        client_token = request.headers.get(CSRF_HEADER_NAME)
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME)

        if not client_token or not cookie_token:
            response = JSONResponse(
                {"detail": "CSRF token missing. Include X-CSRF-Token header."},
                status_code=403,
            )
            await response(scope, receive, send)
            return

        # Both tokens must match and be valid
        if client_token != cookie_token or not verify_csrf_token(client_token, self.secret):
            response = JSONResponse(
                {"detail": "CSRF token invalid or expired."},
                status_code=403,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
