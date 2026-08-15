"""One call to the model, and the client that makes it.

Everything model-shaped that is *not* the loop lives here: which knobs we are
allowed to set, and how an SDK exception becomes a `PlannerError`.

Three settings this model rejects outright, so they are absent rather than
defaulted: `temperature`, `top_p`, `top_k` are a 400 at any non-default value,
and `thinking.budget_tokens` is a 400 — adaptive thinking is already the default
and disabling it makes the model *less* willing to call tools, which is the
opposite of what a routing planner wants.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import anthropic
from anthropic.types import Message
from django.conf import settings
from rest_framework import status

from .errors import PlannerError

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _build_client(api_key: str, timeout: float, max_retries: int) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=max_retries)


def get_client() -> anthropic.Anthropic:
    """The shared Anthropic client. Cached on its arguments, so overriding a
    setting in a test builds a fresh one rather than reusing a stale key."""
    if not settings.ANTHROPIC_API_KEY:
        raise PlannerError(
            "ANTHROPIC_API_KEY is not set, so the planner cannot answer. "
            "Add it to the root .env and restart the backend.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return _build_client(
        settings.ANTHROPIC_API_KEY,
        settings.PLANNER_REQUEST_TIMEOUT,
        settings.PLANNER_MAX_RETRIES,
    )


def create_message(**kwargs: Any) -> Message:
    """One turn of the conversation with the model.

    Streamed internally and reassembled: a long tool-using turn can outlive an
    HTTP idle timeout on the non-streaming path, and the SDK refuses large
    `max_tokens` without it. Nothing about our own API contract changes — this
    still returns one finished `Message`.
    """
    client = get_client()

    try:
        with client.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()
    except anthropic.APITimeoutError as exc:
        raise PlannerError(
            "The model did not respond in time.",
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        ) from exc
    except anthropic.APIConnectionError as exc:
        raise PlannerError(
            "Could not reach the model.", status_code=status.HTTP_502_BAD_GATEWAY
        ) from exc
    except anthropic.RateLimitError as exc:
        raise PlannerError(
            "The model is rate limited. Try again in a moment.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        ) from exc
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        # Our key, not the caller's, so this is us being unavailable rather than
        # them being unauthenticated.
        raise PlannerError(
            "The planner's API credentials were rejected.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    except anthropic.APIStatusError as exc:
        logger.exception("planner_call status=%s", exc.status_code)
        raise PlannerError(
            f"The model returned an error ({exc.status_code}).",
            status_code=status.HTTP_502_BAD_GATEWAY,
        ) from exc

    usage = message.usage
    # cache_read_input_tokens is the only way to tell prompt caching is actually
    # working — a mis-placed cache_control breakpoint fails silently, it just
    # costs full price for ever.
    logger.info(
        "planner_call stop_reason=%s input=%s output=%s cache_read=%s cache_write=%s",
        message.stop_reason,
        usage.input_tokens,
        usage.output_tokens,
        getattr(usage, "cache_read_input_tokens", None),
        getattr(usage, "cache_creation_input_tokens", None),
    )
    return message
