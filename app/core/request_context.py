"""
Request-scoped context variable for correlation ID propagation.

Usage:
    # Reading the current request ID from anywhere in the call stack:
    from app.core.request_context import get_request_id

    headers = {"X-Request-ID": get_request_id()}

The ContextVar is set by the request_id_middleware in app/main.py at the
start of every request and automatically reverts to the default after the
response is returned (Python's contextvars semantics ensure isolation between
concurrent requests without any manual cleanup).
"""
from contextvars import ContextVar

_REQUEST_ID_VAR: ContextVar[str] = ContextVar("request_id", default="")


def set_request_id(request_id: str) -> None:
    """Store the correlation ID for the current request context."""
    _REQUEST_ID_VAR.set(request_id)


def get_request_id() -> str:
    """Return the correlation ID for the current request, or an empty string."""
    return _REQUEST_ID_VAR.get()
