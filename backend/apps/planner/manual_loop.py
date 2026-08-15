"""The hand-written loop — superseded by `loop.py`, kept as the fallback.

This is what ran before the move to Managed Agents, reachable by setting
`PLANNER_MANAGED_AGENTS=false`. It drives the model itself: `while` loop,
`stop_reason` branching, `pause_turn` resume, parallel dispatch, and a wall-clock
deadline that ends in one forced text-only turn.

Every one of those is now the platform's job, which is why none of them appear in
`loop.py`. Keep this working until the migration is proven end to end, then
delete the file rather than growing it. Its brakes are module constants rather
than settings on purpose: they configure *this* file, and shipping them as env
vars would suggest they still steer the planner.

`run_planner` has the same signature and yields the same events as the session
driver, minus `thread_id` — a hand-written loop has no session to reuse.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Iterable, Iterator

import anthropic
from anthropic.types import Message
from apps.core.serializers import AskResponseSerializer
from apps.tools.registry import Tool, ToolError, modes_for, run_tool, tools_for_session
from django.conf import settings
from django.db import connection
from django.utils import timezone
from rest_framework import status

from . import prompt
from .citations import CitationLedger, validate_markers
from .client import get_client
from .errors import PlannerError

logger = logging.getLogger(__name__)

# The tools are all I/O-bound HTTP, so a small pool is enough to make a parallel
# batch cost about as much as its slowest member.
_MAX_PARALLEL = 4

# This loop's brakes. All three end the same way — one last call with tools
# switched off — so a slow lane costs detail rather than the whole answer.
MAX_ITERATIONS = 8
MAX_PAUSE_RESUMES = 3
DEADLINE_SECONDS = 60.0
# Answer length ceiling. Above 16000 the SDK refuses a non-streaming call.
MAX_TOKENS = 8000

_NO_ANSWER = "I could not put an answer together for that one. Try rephrasing it?"


def run_planner(
    query: str,
    *,
    session_id: str = "",
    history: Iterable[dict[str, str]] = (),
    now: datetime | None = None,
) -> Iterator[dict[str, Any]]:
    """Answer `query`, yielding progress events and finally the `AskResponse`."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    now = now or timezone.localtime()

    tools = {tool.name: tool for tool in tools_for_session(session_id or None)}
    messages = _conversation(history, query, now, tools_available=bool(tools))

    ledger = CitationLedger()
    ran: list[str] = []
    failures: list[str] = []
    notes: list[str] = []

    iterations = 0
    pauses = 0
    message = None

    while True:
        forced = _forced_reason(iterations, pauses, deadline)
        message = yield from _turn(_request(messages, tools, forced=bool(forced)))
        iterations += 1

        if forced:
            # This call had tool_choice "none", so it is prose over whatever came
            # back rather than another round of lookups.
            notes.append(forced)
            break

        if message.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": message.content})
            pauses += 1
            continue

        if message.stop_reason != "tool_use":
            break

        # Appended verbatim: server-side tool results carry an `encrypted_content`
        # field, and a reconstructed assistant turn is a 400 on the next call.
        messages.append({"role": "assistant", "content": message.content})
        results = yield from _dispatch(message, tools, session_id, ledger, ran, failures)
        if results:
            # Every result from one assistant turn goes back in ONE user message.
            # Splitting them teaches the model to stop making parallel calls for
            # the rest of the conversation.
            messages.append({"role": "user", "content": results})

    answer = _text(message)
    if message.stop_reason == "max_tokens":
        notes.append("The answer was cut short before it finished.")

    # Markers off (the default) means an empty issued set, which strips any the
    # model wrote anyway — the app has no renderer for them yet, so a literal
    # "[S1]" would show up in the prose.
    issued = ledger.issued_ids if settings.PLANNER_CITATION_MARKERS else set()
    answer, uncited = validate_markers(answer, issued)

    payload = {
        "answer": answer or _NO_ANSWER,
        "citations": ledger.citations,
        # Only tools that actually returned something: a chip claims that lane
        # contributed to the answer, and a failed lane did not.
        "modes_used": modes_for(ran),
        "note": _note(notes, failures, ledger),
    }

    logger.info(
        "planner_answer iterations=%s tools=%s failures=%s citations=%s uncited=%s",
        iterations,
        ",".join(ran) or "-",
        len(failures),
        len(ledger.citations),
        ",".join(sorted(uncited)) or "-",
    )

    response = AskResponseSerializer(data=payload)
    response.is_valid(raise_exception=True)
    yield _event("done", response.data)


# --- The model call -----------------------------------------------------------


def _turn(request: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """One model turn, forwarding its text as it arrives. Returns the Message.

    Text from a turn that then calls tools is preamble, not answer — the app
    drops it when the next lane starts. Only `done` is authoritative.
    """
    message = None
    for item in stream_message(**request):
        if isinstance(item, Message):
            message = item
        else:
            yield _event("text_delta", {"text": item})
    return message


def _request(
    messages: list[dict[str, Any]],
    tools: dict[str, Tool],
    *,
    forced: bool,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": settings.PLANNER_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": prompt.system_prompt(),
        "messages": messages,
        "output_config": {"effort": settings.PLANNER_EFFORT},
    }

    if tools:
        kwargs["tools"] = [tool.definition() for tool in tools.values()]
        if forced:
            kwargs["tool_choice"] = {"type": "none"}

    return kwargs


def _forced_reason(iterations: int, pauses: int, deadline: float) -> str | None:
    """Why this turn must end in prose, or None to keep going.

    Every limit ends the same way — one more call with tools switched off —
    rather than as a 504, so a slow lane costs detail instead of the answer.
    """
    if time.monotonic() >= deadline:
        return "Some lookups were still running when time ran out, so this covers what had come back."
    if iterations >= MAX_ITERATIONS:
        return "This took more lookups than expected, so it may be incomplete."
    if pauses > MAX_PAUSE_RESUMES:
        return "A long-running search was cut off, so this may be incomplete."
    return None


def _text(message: Any) -> str:
    # Concatenated, not joined with blank lines — see the same note in loop.py.
    # One turn's text blocks are continuous prose split at citation boundaries.
    return "".join(block.text for block in message.content if block.type == "text").strip()


# --- Tool dispatch ------------------------------------------------------------


def _dispatch(
    message: Any,
    tools: dict[str, Tool],
    session_id: str,
    ledger: CitationLedger,
    ran: list[str],
    failures: list[str],
) -> Iterator[dict[str, Any]]:
    """Run every tool the model asked for, yielding lane events as they go.

    Returns the `tool_result` blocks, in the order the model asked for them.
    """
    calls = [block for block in message.content if block.type == "tool_use"]
    if not calls:
        return []

    for block in calls:
        tool = tools.get(block.name)
        if tool is not None:
            yield _event("mode_start", {"mode": tool.mode, "tool": tool.name})

    results: dict[int, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=min(len(calls), _MAX_PARALLEL)) as pool:
        futures = {
            pool.submit(_call_tool, block.name, dict(block.input or {}), session_id): index
            for index, block in enumerate(calls)
        }

        for future in as_completed(futures):
            index = futures[future]
            block = calls[index]
            tool = tools.get(block.name)
            ok, payload = future.result()

            if ok:
                ran.append(block.name)
                content = json.dumps(ledger.record(tool, payload), default=str)
            else:
                failures.append(f"{block.name}: {payload}")
                content = str(payload)

            result: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": content,
            }
            if not ok:
                # A failure is a result, never a dropped block: dropping one
                # breaks tool_use/tool_result pairing and the next call 400s.
                result["is_error"] = True
            results[index] = result

            if tool is not None:
                yield _event("mode_end", {"mode": tool.mode, "tool": tool.name, "ok": ok})

    return [results[index] for index in range(len(calls))]


def _call_tool(name: str, arguments: dict[str, Any], session_id: str) -> tuple[bool, Any]:
    """Run one tool in a pool thread. Never raises — a failure is a value here."""
    try:
        return True, run_tool(name, arguments, session_id=session_id or None)
    except ToolError as exc:
        return False, str(exc)
    except Exception as exc:  # a tool bug must not take the answer down with it
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        # Django only closes the request thread's connection for us, and personal
        # tools hit the database to check the connector.
        connection.close()


# --- Assembling the reply -----------------------------------------------------


def _conversation(
    history: Iterable[dict[str, str]],
    query: str,
    now: datetime,
    *,
    tools_available: bool,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for turn in history:
        _append(messages, turn.get("role", ""), (turn.get("content") or "").strip())
    _append(messages, "user", prompt.user_turn(query, now, tools_available=tools_available))
    return messages


def _append(messages: list[dict[str, Any]], role: str, content: str) -> None:
    """Add one turn, keeping the shape the Messages API insists on.

    Our `history` contract permits things it does not: a blank turn (an empty
    text block is a 400), an assistant turn first, two turns in a row from the
    same role. Each is normalised here rather than 400ing someone's follow-up.
    """
    if not content or role not in ("user", "assistant"):
        return
    if not messages and role != "user":
        return
    if messages and messages[-1]["role"] == role:
        messages[-1]["content"] += f"\n\n{content}"
        return
    messages.append({"role": role, "content": content})


def _note(notes: list[str], failures: list[str], ledger: CitationLedger) -> str | None:
    """The caveats worth putting above the answer, or None if there are none."""
    parts = list(notes)

    if failures:
        parts.append("Some sources did not respond — " + "; ".join(failures))
    elif not ledger.citations:
        parts.append(
            "No campus source backed this answer, so treat it as general knowledge "
            "rather than live CMU data."
        )

    if ledger.has_mock:
        parts.append("Some sources are placeholder data, marked below.")

    return " ".join(parts) or None


def _event(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"type": kind, "data": data}


# --- One call to the model ----------------------------------------------------
#
# This lived in client.py until the migration; it moved here because the session
# driver never calls `messages.stream` at all.


def stream_message(**kwargs: Any) -> Iterator[str | Message]:
    """One turn of the conversation, as it arrives.

    Yields the answer text in chunks and finally yields the finished `Message` —
    the sentinel the caller watches for.

    Three settings this model rejects outright, so they are absent rather than
    defaulted: `temperature`, `top_p` and `top_k` are a 400 at any non-default
    value, and `thinking.budget_tokens` is a 400 — adaptive thinking is already
    the default, and disabling it makes the model *less* willing to call tools,
    which is the opposite of what a routing planner wants.
    """
    client = get_client()

    try:
        with client.messages.stream(**kwargs) as stream:
            # text_stream is only the text blocks, so thinking never leaks into
            # what the user is shown.
            yield from _coalesce(stream.text_stream)
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
    yield message


# Each chunk costs an SSE frame, a re-render, and a full re-serialisation of the
# thread on the app side. Nobody can see the difference between 20 updates a
# second and 60, so the small ones the API sends get batched up.
_CHUNK_CHARS = 24


def _coalesce(deltas: Iterator[str]) -> Iterator[str]:
    buffer = ""
    for delta in deltas:
        buffer += delta
        if len(buffer) >= _CHUNK_CHARS:
            yield buffer
            buffer = ""
    if buffer:
        yield buffer
