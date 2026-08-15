"""One error shape for the whole API (tasklist §2):

    {"error": {"code": "validation_error", "message": "query: This field is required."}}

DRF's default body varies by exception — a `{"query": [...]}` field dict here, a
`{"detail": "..."}` string there — so without this handler the frontend would
have to guess which it got.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)

# HTTP status -> the stable `code` the frontend switches on. Codes are part of
# the contract; statuses get reused, so the app keys off these strings.
_CODES = {
    status.HTTP_400_BAD_REQUEST: "validation_error",
    status.HTTP_401_UNAUTHORIZED: "unauthenticated",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
    status.HTTP_502_BAD_GATEWAY: "upstream_error",
    status.HTTP_503_SERVICE_UNAVAILABLE: "unavailable",
    status.HTTP_504_GATEWAY_TIMEOUT: "timeout",
}


def _flatten(detail, path: str = "") -> str:
    """Turn DRF's nested error detail into one human sentence.

    DRF hands back a string, a list, or a dict-of-lists depending on what failed.
    The app shows one message, so this flattens to `field.path: problem` — e.g.
    `history.0.role: "system" is not a valid choice.`
    """
    if isinstance(detail, dict):
        parts = []
        for field, value in detail.items():
            # "detail" is DRF's key for errors that aren't about a field (404s,
            # 405s, throttling). Dropped rather than prefixed, because
            # "detail: ..." puts framework jargon in front of a student.
            label = path if field == "detail" else f"{path}.{field}" if path else str(field)
            parts.append(_flatten(value, path=label))
        return " ".join(p for p in parts if p)

    if isinstance(detail, (list, tuple)):
        return " ".join(_flatten(item, path=path) for item in detail if item)

    text = str(detail).strip()
    if not text:
        return ""
    return f"{path}: {text}" if path else text


def api_exception_handler(exc, context):
    """DRF exception handler. Wired up in settings.REST_FRAMEWORK."""
    response = drf_exception_handler(exc, context)

    if response is None:
        # Not a DRF exception — an unhandled bug. Returning None hands the 500
        # back to Django (DEBUG still shows the traceback page); log the view
        # name first so it is findable in the container logs.
        logger.exception(
            "Unhandled error in %s", context.get("view").__class__.__name__ if context.get("view") else "?"
        )
        return None

    code = _CODES.get(response.status_code, "error")
    message = _flatten(response.data) or "Something went wrong."

    return Response({"error": {"code": code, "message": message}}, status=response.status_code)
