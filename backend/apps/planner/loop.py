"""The agentic loop: a question in, a cited answer out.

`run_planner` is a **generator**. It yields progress events as tool lanes start
and finish, and finishes by yielding the validated `AskResponse`. That is what
makes the two endpoints one implementation rather than two:

    run_planner(...) ──yields──► mode_start · mode_end · … · done{AskResponse}

    POST /api/ask/        → drain it, return the last event
    POST /api/ask/stream/ → forward each event as SSE

Written by hand rather than with the SDK's tool runner because the runner cannot
resume a `pause_turn`: it hands back the paused turn as if it were finished, with
no error, and the answer is silently truncated.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Iterable, Iterator

from apps.core.serializers import AskResponseSerializer
from apps.tools.registry import Tool, ToolError, modes_for, run_tool, tools_for_session
from django.conf import settings
from django.db import connection
from django.utils import timezone

from . import prompt
from .citations import CitationLedger, validate_markers
from .client import create_message
from .errors import PlannerError

logger = logging.getLogger(__name__)

# The tools are all I/O-bound HTTP, so a small pool is enough to make a parallel
# batch cost about as much as its slowest member.
_MAX_PARALLEL = 4

_NO_ANSWER = "I could not put an answer together for that one. Try rephrasing it?"


def run_planner(
    query: str,
    *,
    session_id: str = "",
    history: Iterable[dict[str, str]] = (),
    now: datetime | None = None,
) -> Iterator[dict[str, Any]]:
    """Answer `query`, yielding progress events and finally the `AskResponse`."""
    deadline = time.monotonic() + settings.PLANNER_DEADLINE_SECONDS
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
        message = create_message(**_request(messages, tools, forced=bool(forced)))
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


def drain(events: Iterator[dict[str, Any]]) -> dict[str, Any]:
    """Run the planner to completion and return the `done` payload."""
    final = None
    for final in events:
        pass

    if final is None or final["type"] != "done":
        raise PlannerError("The planner finished without producing an answer.")
    return final["data"]


# --- The model call -----------------------------------------------------------


def _request(
    messages: list[dict[str, Any]],
    tools: dict[str, Tool],
    *,
    forced: bool,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": settings.PLANNER_MODEL,
        "max_tokens": settings.PLANNER_MAX_TOKENS,
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
    if iterations >= settings.PLANNER_MAX_ITERATIONS:
        return "This took more lookups than expected, so it may be incomplete."
    if pauses > settings.PLANNER_MAX_PAUSE_RESUMES:
        return "A long-running search was cut off, so this may be incomplete."
    return None


def _text(message: Any) -> str:
    return "\n\n".join(
        block.text for block in message.content if block.type == "text"
    ).strip()


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
