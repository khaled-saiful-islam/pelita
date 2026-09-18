"""Application errors and the envelope they are rendered in.

Every error the API returns has the same shape, so the frontend has one code
path for failure rather than one per endpoint.
"""

from __future__ import annotations


class PelitaError(Exception):
    """Base for errors that carry a message safe to show a user."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(PelitaError):
    status_code = 404
    code = "not_found"


class ConflictError(PelitaError):
    status_code = 409
    code = "conflict"


class ValidationError(PelitaError):
    status_code = 422
    code = "validation_error"


class AuthError(PelitaError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(PelitaError):
    status_code = 403
    code = "forbidden"


class RateLimitError(PelitaError):
    """Too many requests. Carries how long to wait, because a 429 without it
    leaves a client guessing — and guessing usually means retrying at once."""

    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str, *, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = max(1, retry_after)


class UpstreamError(PelitaError):
    """A dependency failed in a way the user should be told about."""

    status_code = 502
    code = "upstream_error"
