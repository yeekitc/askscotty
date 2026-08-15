"""Planner failures, rendered in the one error shape tasklist §2 defines.

Distinct from `ToolError`: a tool failing is normal and degrades into a partial
answer, so it never reaches here. A `PlannerError` means the turn cannot produce
an answer at all — no API key, the model unreachable, rate limited.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException


class PlannerError(Exception):
    """The planner could not answer. Carries the HTTP status to report."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = status.HTTP_502_BAD_GATEWAY,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


def as_api_exception(exc: PlannerError) -> APIException:
    """Hand a PlannerError to DRF so apps/core/errors.py formats it like the rest."""
    api_exception = APIException(str(exc))
    api_exception.status_code = exc.status_code
    return api_exception
