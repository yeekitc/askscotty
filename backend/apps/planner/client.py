"""The Managed Agents client: sessions, events, and how their failures read.

Everything platform-shaped that is *not* the drain loop lives here — which ids
we point at, how a session is opened or reused, and how an SDK exception becomes
a `PlannerError`.

The lifecycles are the thing to keep straight:

    Agent        model, system prompt, base toolset   created once, versioned
    Environment  the container template                created once
    Session      one conversation                      per thread

The agent and the environment are **configuration**. They are created out of
band by `manage.py provision_planner`, their ids live in `.env`, and nothing in
the request path may create either — a request that provisions its own agent
orphans one per worker boot and quietly defeats the versioning. So an unset
`PLANNER_AGENT_ID` is a loud failure here, never a silent create.

Model settings are absent for the same reason they were absent before: `model`,
`system` and `effort` live on the agent now, and `effort` inside a per-session
override is *ignored rather than rejected*, so setting it here would look like it
worked and do nothing.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Iterable, Iterator

import anthropic
from apps.tools.registry import Tool
from django.conf import settings
from rest_framework import status

from .errors import PlannerError

logger = logging.getLogger(__name__)

# The event stream is long-lived by design: one turn can spend minutes in tool
# calls, and the server sends heartbeats to hold the connection open. The
# per-request timeout that suits a control-plane call would kill it mid-answer,
# so the stream gets its own generous ceiling — a backstop against a wedged
# connection, not a deadline on the answer.
_STREAM_TIMEOUT_SECONDS = 900.0

# The prebuilt toolset (bash/read/write/edit/glob/grep/web_search/web_fetch).
# Kept whole deliberately: only the two web tools are ever used, but the rest
# cost schema tokens rather than config surface, and the web lane arrives by
# enabling this rather than by declaring a tool. See docs/b4-planner.md.
AGENT_TOOLSET = {"type": "agent_toolset_20260401"}

# Built-in tools that count as the web-verify lane. `modes_used` gets `web_verify`
# from these rather than from `run_tool`, because Anthropic executes them.
WEB_TOOLS = frozenset({"web_search", "web_fetch"})

_MISSING_AGENT = (
    "The planner is not provisioned: PLANNER_AGENT_ID is unset. Run\n"
    "  docker compose exec backend python manage.py provision_planner\n"
    "and copy the two ids it prints into the root .env, then restart the backend."
)


@lru_cache(maxsize=1)
def _build_client(api_key: str, timeout: float, max_retries: int) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=max_retries)


def get_client() -> anthropic.Anthropic:
    """The shared Anthropic client. Cached on its arguments, so overriding a
    setting in a test builds a fresh one rather than reusing a stale key.

    The timeout here is for control-plane calls — create a session, send events,
    list events. Streaming passes its own.
    """
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


def agent_reference(tools: Iterable[Tool], *, web: bool = True) -> dict[str, Any]:
    """This request's agent, with its toolset overridden for this session.

    `tools_for_session()` still decides what exists; it is applied here as an
    `agent_with_overrides` reference rather than as a per-request `tools` array.
    **Overrides replace in full**, so the prebuilt toolset has to be listed again
    alongside our custom tools or the web lane silently disappears.
    """
    if not settings.PLANNER_AGENT_ID:
        raise PlannerError(_MISSING_AGENT, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    return {
        "type": "agent_with_overrides",
        "id": settings.PLANNER_AGENT_ID,
        "tools": toolset(tools, web=web),
    }


def toolset(tools: Iterable[Tool], *, web: bool = True) -> list[dict[str, Any]]:
    """The tool list an agent or a session is given: the prebuilt one, then ours.

    One definition rather than three, because the prebuilt toolset has to lead
    every one of them — an override replaces in full, so a list that forgets it
    silently drops the web lane.

    `web=False` is how a reader who unchecked web verification actually gets it.
    Ours can be dropped by leaving them out of the list; the built-in pair cannot,
    because the prebuilt toolset is one opaque entry — so they are switched off
    through its own per-tool config instead.
    """
    prebuilt = AGENT_TOOLSET
    if not web:
        prebuilt = {
            **AGENT_TOOLSET,
            "configs": [{"name": name, "enabled": False} for name in sorted(WEB_TOOLS)],
        }
    return [prebuilt, *(_custom_tool(tool) for tool in tools)]


def _custom_tool(tool: Tool) -> dict[str, Any]:
    """One of our tools, in the shape a session's tool override wants.

    A "custom" tool is one Anthropic never executes: it asks, we run it in
    Django, we send the result back. That is what keeps `run_tool` the only door
    to pgvector, the campus APIs and a Canvas token.
    """
    return {"type": "custom", **tool.definition()}


def _budget() -> dict[str, Any] | None:
    """The session's spend ceiling, or None if it has been switched off.

    This is the replacement for the wall-clock deadline: dollar-denominated,
    which is the shape a runaway tool loop actually has. Note it bounds the whole
    *thread*, not one question — the session outlives the turn.
    """
    cents = settings.PLANNER_SESSION_BUDGET_CENTS
    if cents <= 0:
        return None
    return {"type": "limit", "max_list_cost": {"amount": str(cents), "currency": "USD"}}


def create_session(tools: Iterable[Tool], *, title: str = "", web: bool = True) -> str:
    """Open a session for one conversation and return its id.

    Note what is *not* here: `agents.create` and `environments.create`. Those ran
    once, by hand, in `provision_planner`.
    """
    if not settings.PLANNER_ENVIRONMENT_ID:
        raise PlannerError(_MISSING_AGENT, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    offered = list(tools)
    kwargs: dict[str, Any] = {
        "agent": agent_reference(offered, web=web),
        "environment_id": settings.PLANNER_ENVIRONMENT_ID,
    }
    if title:
        kwargs["title"] = title[:120]

    budget = _budget()
    if budget is not None:
        kwargs["budget"] = budget

    with _translated():
        session = get_client().beta.sessions.create(**kwargs)

    logger.info("planner_session created id=%s tools=%s", session.id, len(offered))
    return session.id


def refresh_toolset(session_id: str, tools: Iterable[Tool], *, web: bool = True) -> None:
    """Re-apply this request's toolset to a session we are reusing.

    A thread's session outlives the turn, so the toolset it was opened with can
    be stale by the next question — somebody connects Canvas, or disconnects it.
    Best effort on purpose: `run_tool` re-checks the connector on every single
    dispatch, so a stale *offer* can never return anyone's data. This only keeps
    what the model is told in step with what it would actually be allowed to run.
    """
    try:
        get_client().beta.sessions.update(session_id, agent={"tools": toolset(tools, web=web)})
    except Exception as exc:  # noqa: BLE001 - never fail an answer over this
        logger.warning("planner_session toolset refresh failed id=%s: %s", session_id, exc)


def send_events(session_id: str, events: list[dict[str, Any]]) -> None:
    with _translated():
        get_client().beta.sessions.events.send(session_id, events=events)


def stream_events(session_id: str) -> Any:
    """Open the session's event stream.

    Open this **before** sending anything. The stream carries only what is
    emitted after it opens and there is no replay, so sending first races it and
    loses the opening events — including, on a fast turn, the whole answer.
    """
    with _translated():
        return get_client().beta.sessions.events.stream(
            session_id,
            # Text as the model writes it rather than only in the buffered
            # `agent.message` at the end of a turn. This is what keeps
            # `text_delta` in the §2 contract alive under Managed Agents.
            event_deltas=["agent.message"],
            timeout=_STREAM_TIMEOUT_SECONDS,
        )


def events_since(session_id: str, since: Any) -> list[Any]:
    """Events this session recorded from `since` onwards, oldest first.

    Only used on reconnect. The stream has no replay, so a dropped connection
    silently loses whatever happened during the gap — and if that gap contained
    the `agent.custom_tool_use` we were meant to answer, the session waits for a
    result that never comes and the turn deadlocks.
    """
    with _translated():
        page = get_client().beta.sessions.events.list(
            session_id, created_at_gte=since, order="asc", limit=1000
        )
        return list(page.data)


class SessionGone(Exception):
    """A stored session id no longer resolves.

    Not a `PlannerError`: the caller's answer is to open a new session, not to
    give up. Raised rather than pre-flighted with a `retrieve` because that
    lookup would cost a round trip on every follow-up to catch a case that
    only happens when a session is archived or deleted out from under us.
    """


class _translated:
    """Turn an SDK exception into the API error shape, with a status that fits.

    Our key, not the caller's — so a rejected credential is us being
    unavailable rather than them being unauthenticated.
    """

    def __enter__(self) -> None:
        return None

    def __exit__(self, kind, exc, tb) -> bool:
        if exc is None:
            return False
        raise _as_planner_error(exc) from exc


def _as_planner_error(exc: BaseException) -> PlannerError:
    if isinstance(exc, PlannerError):
        return exc
    # Pass straight through: these mean "open a new session", not "give up".
    if isinstance(exc, SessionGone):
        raise exc
    if isinstance(exc, anthropic.NotFoundError):
        raise SessionGone(str(exc)) from exc
    if isinstance(exc, anthropic.APITimeoutError):
        return PlannerError(
            "The planner did not respond in time.",
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        )
    if isinstance(exc, anthropic.APIConnectionError):
        return PlannerError("Could not reach the planner.", status_code=status.HTTP_502_BAD_GATEWAY)
    if isinstance(exc, anthropic.RateLimitError):
        return PlannerError(
            "The planner is rate limited. Try again in a moment.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return PlannerError(
            "The planner's API credentials were rejected.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, anthropic.APIStatusError):
        logger.exception("planner_call status=%s", exc.status_code)
        return PlannerError(
            f"The planner returned an error ({exc.status_code}).",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    raise exc


def stream_of(events: Iterable[Any]) -> Iterator[Any]:
    """Iterate a stream, translating a mid-stream SDK failure on the way out."""
    try:
        yield from events
    except Exception as exc:  # noqa: BLE001 - re-raised as a PlannerError
        raise _as_planner_error(exc) from exc
