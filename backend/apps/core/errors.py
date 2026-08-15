"""One error shape for the whole API (tasklist §2).

Every failure the app can see comes back as:

    {"error": {"code": "validation_error", "message": "query: This field is required."}}

with a real HTTP status alongside it. The frontend switches on `code` and shows
`message`, so it never has to guess whether a 400 body is DRF's `{"query": [...]}`
field-error dict, a `{"detail": "..."}` string, or something else — which is what
you get without this handler, because DRF's default shape varies by exception.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)

# HTTP status -> the stable `code` the frontend switches on. Codes are part of
# the contract; statuses can be reused, so the app keys off these strings.
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

    DRF hands back a string, a list, or a dict-of-lists depending on what failed,
    and nests them for nested serializers. The app shows one message, so this
    flattens to `field.path: problem` — e.g. `history.0.role: "system" is not a
    valid choice.` — which is specific enough to fix without opening the
    browsable API.
    """
    if isinstance(detail, dict):
        parts = []
        for field, value in detail.items():
            # "detail" is DRF's key for errors that aren't about a field
            # (404s, 405s, throttling). Prefixing those with "detail:" would
            # put a word from our framework in front of a sentence meant for a
            # student, so it is dropped.
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
        # Not a DRF exception — an unhandled bug. Django's own handler deals with
        # the 500 (and DEBUG still shows the traceback page); log it with the
        # view name so it is findable in `docker compose logs -f backend`.
        logger.exception(
            "Unhandled error in %s", context.get("view").__class__.__name__ if context.get("view") else "?"
        )
        return None

    code = _CODES.get(response.status_code, "error")
    message = _flatten(response.data) or "Something went wrong."

    return Response({"error": {"code": code, "message": message}}, status=response.status_code)
