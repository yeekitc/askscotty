"""The session driver: a question in, a cited answer out.

Anthropic runs the loop now. We open a session per thread, send the question, and
follow the session's event stream — executing every tool it asks for on our side
and sending the results back. What used to be a `while` loop over `stop_reason`
is a drain loop over events.

`run_planner` is still a **generator** yielding the same events, so both
endpoints stay one implementation:

    run_planner(...) ──yields──► mode_start · mode_end · text_delta · done{AskResponse}

    POST /api/ask/        → drain it, return the last event
    POST /api/ask/stream/ → forward each event as SSE

Four things about this loop are easy to get wrong, and three of them fail
silently:

1. **Open the stream before sending.** The stream carries only what is emitted
   after it opens and there is no replay. Sending first races it.
2. **One idle is not done.** A session goes idle every time it wants a tool
   result. Breaking on `session.status_idle` alone hangs the answer at the first
   tool call; `stop_reason` is what tells the two apart.
3. **A dropped stream loses the gap.** Reconnecting without listing the events
   you missed can strand a pending tool call the session is still waiting on.
4. **Tool execution stays ours.** Every dispatch goes through `run_tool`, which
   is where all five invariants in docs/architecture.md are enforced.

What is *not* here, because the platform owns it now: the `while` loop,
`pause_turn` resume, context compaction, and the wall-clock deadline. The runaway
bound is the session's dollar budget instead.

**Parallel dispatch is still ours**, and the distinction is easy to lose: the
platform batches the model's tool *requests*, but every one of them executes in
this process. Running them one after another would cost the sum of a batch
rather than its slowest member — see `_dispatch`.
"""

from __future__ import annotations

import html
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Iterator

from apps.core.models import Thread
from apps.core.serializers import AskResponseSerializer
from apps.tools.registry import (
    MODES,
    Tool,
    ToolError,
    modes_for,
    run_tool,
    tools_for_session,
)
from django.conf import settings
from django.db import connection
from django.utils import timezone

from . import client, prompt
from .citations import CitationLedger, validate_markers
from .errors import PlannerError

logger = logging.getLogger(__name__)

_NO_ANSWER = "I could not put an answer together for that one. Try rephrasing it?"

# How many times a dropped event stream is re-opened within one turn before we
# give up. A reconnect is cheap and a dropped connection mid-answer is the
# common transient failure; a connection that will not stay up is not.
_MAX_RECONNECTS = 2

# Stream failures worth reconnecting after: the connection died or timed out.
# Anything else (a rejected key, a 400) will fail the same way twice.
_RECONNECTABLE = (502, 504)

# The lanes are all I/O-bound HTTP, so a small pool is enough to make a parallel
# batch cost about as much as its slowest member.
_MAX_PARALLEL = 4


def run_planner(
    query: str,
    *,
    session_id: str = "",
    thread_id: str = "",
    history: Iterable[dict[str, str]] = (),
    disabled_modes: Iterable[str] = (),
    concise: bool = False,
    now: datetime | None = None,
) -> Iterator[dict[str, Any]]:
    """Answer `query`, yielding progress events and finally the `AskResponse`.

    `disabled_modes` are the lanes this reader unchecked in the app. They are
    applied by *not offering* the tools rather than by refusing them later: a
    tool the model is never told about is one it cannot call, which is the same
    mechanism that gates personal tools (PRD §7).
    """
    now = now or timezone.localtime()
    off = set(disabled_modes)
    tools = [tool for tool in tools_for_session(session_id or None) if tool.mode not in off]
    web = "web_verify" not in off
    turn = _Turn(tools={tool.name: tool for tool in tools}, session_id=session_id)

    thread = _thread_for(session_id, thread_id)
    cma_session_id, is_new = _resolve_session(thread, tools, title=query, web=web)

    # A reused session already holds the conversation, so replaying `history`
    # into it would say everything twice. A new one has never seen the thread,
    # so what the app knows is all the continuity there is.
    #
    # There is deliberately no "no lookup tools available" variant, even with an
    # empty registry: the agent's prebuilt toolset always carries web_search and
    # web_fetch, so telling the model nothing can be checked would talk it out of
    # the one lane it still has.
    message = prompt.user_turn(query, now, history=history if is_new else (), concise=concise)

    try:
        yield from _drive(turn, cma_session_id, message)
    except client.SessionGone:
        # The stored id no longer resolves. Nothing has been emitted yet — the
        # 404 comes from opening the stream — so starting over is clean, and it
        # costs the conversation's memory rather than the answer.
        if is_new:
            raise
        logger.info("planner_session gone id=%s; starting a new one", cma_session_id)
        cma_session_id = _reopen_session(thread, tools, title=query, web=web)
        is_new = True
        turn = _Turn(tools=turn.tools, session_id=session_id)
        message = prompt.user_turn(query, now, history=history, concise=concise)
        yield from _drive(turn, cma_session_id, message)

    # Markers off (the default) means an empty issued set, which strips any the
    # model wrote anyway — the app has no renderer for them yet, so a literal
    # "[S1]" would show up in the prose. This branch is what lets citations be
    # turned on by flipping an env var rather than re-provisioning the agent,
    # which is why the agent's prompt carries the marker rules unconditionally.
    issued = turn.ledger.issued_ids if settings.PLANNER_CITATION_MARKERS else set()
    answer, uncited = validate_markers(turn.answer, issued)

    payload = {
        "answer": answer or _NO_ANSWER,
        "citations": turn.ledger.citations,
        # Only tools that actually returned something: a chip claims that lane
        # contributed to the answer, and a failed lane did not.
        "modes_used": _modes_used(turn),
        "note": _note(turn),
    }

    logger.info(
        "planner_answer session=%s new=%s tools=%s failures=%s citations=%s dropped=%s uncited=%s",
        cma_session_id,
        is_new,
        ",".join(turn.ran) or "-",
        len(turn.failures),
        len(turn.ledger.citations),
        turn.web_dropped,
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


# --- Turn state ---------------------------------------------------------------


@dataclass
class _Turn:
    """Everything one question accumulates on its way to an answer."""

    tools: dict[str, Tool]
    #: Our anonymous session id — what scopes personal tools. Not the CMA one.
    session_id: str
    ledger: CitationLedger = field(default_factory=CitationLedger)
    ran: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: The answer so far. Reset whenever a lane starts, because text written
    #: before a lookup is the model narrating itself into it, not the answer.
    answer: str = ""
    #: `agent.custom_tool_use` events waiting for us to run them.
    pending: list[Any] = field(default_factory=list)
    #: Calls we have already sent a result for, so a later `requires_action`
    #: naming them reads as "still catching up" rather than "stuck".
    answered: set[str] = field(default_factory=set)
    #: Built-in tool_use id -> (tool name, its input), so `agent.tool_result` can
    #: close the lane the matching `agent.tool_use` opened — and reach the url it
    #: was asked for, which a result block does not always carry.
    lanes: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)
    #: Whether a built-in web tool actually returned something. `web_verify` is
    #: the one mode `run_tool` cannot report, because Anthropic runs those two.
    web_verified: bool = False
    #: Web sources turned away by `_MAX_WEB_CITATIONS`, so the ceiling shows up
    #: in the logs rather than looking like the search found less than it did.
    web_dropped: int = 0
    #: Event ids already handled, so a reconnect cannot double-count one.
    seen: set[str] = field(default_factory=set)
    finished: bool = False


# --- Resolving the session ----------------------------------------------------


def _thread_for(session_id: str, thread_id: str) -> Thread | None:
    """The thread this question belongs to, or None if the client didn't say.

    `get_or_create` because the app owns thread ids and only saves the thread
    *after* the answer comes back, so the row usually does not exist yet on the
    first question. Without a thread there is nowhere to keep a session id, so
    every question opens its own — correct, just not continuous.
    """
    if not (session_id and thread_id):
        return None
    thread, _created = Thread.objects.get_or_create(
        session_id=session_id, client_id=thread_id
    )
    return thread


def _resolve_session(
    thread: Thread | None, tools: list[Tool], *, title: str, web: bool = True
) -> tuple[str, bool]:
    """This thread's session, opened if it has none. Returns (id, is_new).

    Never `agents.create` or `environments.create` — those are configuration,
    created once by `manage.py provision_planner`.
    """
    if thread is not None and thread.cma_session_id:
        # The toolset was fixed when the session opened, and a thread outlives
        # the turn — somebody may have connected or disconnected a source since.
        client.refresh_toolset(thread.cma_session_id, tools, web=web)
        return thread.cma_session_id, False

    cma_session_id = client.create_session(tools, title=title, web=web)
    if thread is not None:
        thread.cma_session_id = cma_session_id
        thread.save(update_fields=["cma_session_id"])
    return cma_session_id, True


def _reopen_session(
    thread: Thread | None, tools: list[Tool], *, title: str, web: bool = True
) -> str:
    """Replace a session id that no longer resolves.

    Ours is not the only store: a session can be archived or deleted on
    Anthropic's side while the thread row still points at it. That should cost
    the conversation's memory, not the answer.
    """
    cma_session_id = client.create_session(tools, title=title, web=web)
    if thread is not None:
        thread.cma_session_id = cma_session_id
        thread.save(update_fields=["cma_session_id"])
    return cma_session_id


# --- Driving the stream -------------------------------------------------------


def _drive(turn: _Turn, cma_session_id: str, message: str) -> Iterator[dict[str, Any]]:
    """Send the question and follow the session until the turn is over.

    Stream first, then send — see the module docstring. On a reconnect the
    session's own event list fills the gap the stream cannot replay, deduped by
    event id so nothing is handled twice.
    """
    since = timezone.now()
    sent = False

    for attempt in range(_MAX_RECONNECTS + 1):
        try:
            with client.stream_events(cma_session_id) as stream:
                if sent:
                    # Reconnecting. Whatever happened while we were away is only
                    # in the event list — and if that included the tool call the
                    # session is now waiting on, skipping it deadlocks the turn.
                    for event in client.events_since(cma_session_id, since):
                        yield from _handle(turn, cma_session_id, event)
                        if turn.finished:
                            return
                else:
                    client.send_events(cma_session_id, [_user_message(message)])
                    sent = True

                for event in client.stream_of(stream):
                    yield from _handle(turn, cma_session_id, event)
                    if turn.finished:
                        return
        except PlannerError as exc:
            if exc.status_code not in _RECONNECTABLE or attempt == _MAX_RECONNECTS:
                raise
            logger.warning(
                "planner_stream dropped session=%s attempt=%s: %s",
                cma_session_id,
                attempt + 1,
                exc,
            )
            continue

        # The stream closed without a terminal event, which is a dropped
        # connection wearing a polite face. Same recovery.
        logger.warning("planner_stream ended early session=%s", cma_session_id)

    raise PlannerError(
        "The planner's connection kept dropping before it finished. Try again.",
        status_code=502,
    )


def _user_message(text: str) -> dict[str, Any]:
    return {"type": "user.message", "content": [{"type": "text", "text": text}]}


def _handle(turn: _Turn, cma_session_id: str, event: Any) -> Iterator[dict[str, Any]]:
    """One event from the session, turned into whatever it means for us."""
    kind = event.type

    # Live text previews are stream-only and never replayed, so they have no id
    # to dedupe on — and nothing downstream depends on them, because the
    # buffered `agent.message` is what the answer is actually built from.
    if kind == "event_delta":
        text = getattr(getattr(event.delta, "content", None), "text", "")
        if text:
            yield _event("text_delta", {"text": text})
        return
    if kind == "event_start":
        return

    event_id = getattr(event, "id", "")
    if event_id:
        if event_id in turn.seen:
            return
        turn.seen.add(event_id)

    if kind == "agent.message":
        # Concatenated, *not* joined with blank lines. One message's text blocks
        # are one continuous piece of prose: the model splits them at citation
        # boundaries, so a quoted span arrives as its own block with the sentence
        # around it in the blocks either side. Joining with "\n\n" turns every
        # quote into a free-standing paragraph and leaves a stray blank one
        # wherever a block was empty — the answer comes out shredded.
        turn.answer = "".join(
            block.text for block in event.content if block.type == "text"
        ).strip()

    elif kind == "agent.custom_tool_use":
        # Ours to run. The session is about to go idle waiting for the result.
        turn.answer = ""
        turn.pending.append(event)
        tool = turn.tools.get(event.name)
        if tool is not None:
            yield _event("mode_start", {"mode": tool.mode, "tool": tool.name})

    elif kind == "agent.tool_use":
        # Anthropic's to run. Only the web pair earns a chip; bash and the file
        # tools are in the toolset because removing them is config surface, not
        # because the planner has any use for them.
        turn.answer = ""
        if event.name in client.WEB_TOOLS:
            turn.lanes[event.id] = (event.name, dict(event.input or {}))
            yield _event("mode_start", {"mode": "web_verify", "tool": event.name})

    elif kind == "agent.tool_result":
        lane = turn.lanes.pop(event.tool_use_id, None)
        if lane is not None:
            name, arguments = lane
            ok = not event.is_error
            turn.web_verified = turn.web_verified or ok
            if ok:
                _harvest_web(turn, name, arguments, event)
            else:
                turn.failures.append(f"{name}: {_result_text(event) or 'the lookup failed'}")
            yield _event("mode_end", {"mode": "web_verify", "tool": name, "ok": ok})

    elif kind == "session.error":
        # Not fatal by itself: the session reschedules after a retryable error,
        # and says so with a terminal event if it cannot.
        detail = getattr(event.error, "message", None) or event.error.type
        logger.warning("planner_session error session=%s: %s", cma_session_id, detail)

    elif kind == "session.status_idle":
        yield from _on_idle(turn, cma_session_id, event)

    elif kind == "session.status_terminated":
        turn.finished = True


def _on_idle(turn: _Turn, cma_session_id: str, event: Any) -> Iterator[dict[str, Any]]:
    """Idle means one of two very different things — read the stop reason.

    `requires_action` is the session waiting on us; anything else is the turn
    being over. Treating them the same is what makes an answer hang at its first
    tool call.
    """
    reason = event.stop_reason.type

    if reason == "requires_action":
        if turn.pending:
            yield from _dispatch(turn, cma_session_id)
            return

        # Nothing of ours is outstanding. That is normally the session catching
        # up — it idles again while it works through the results we just sent —
        # so keep draining. Treating it as the end of the turn truncates the
        # answer right after the last lookup, which is exactly what it looks
        # like: tools ran, citations collected, no prose.
        outstanding = set(getattr(event.stop_reason, "event_ids", None) or [])
        blocked = outstanding - turn.answered
        if blocked:
            # It is waiting on something we never saw asked and cannot answer —
            # a tool confirmation, say. We set no permission policy, so this
            # should not happen; stopping beats hanging until the app gives up.
            logger.warning(
                "planner_session waiting on events we cannot answer: %s %s",
                cma_session_id,
                ",".join(sorted(blocked)),
            )
            turn.finished = True
        return

    if reason == "budget_reached":
        turn.notes.append(
            "This conversation reached its lookup budget, so the answer may be incomplete."
        )
    elif reason == "retries_exhausted":
        turn.notes.append("The planner gave up after repeated errors, so this may be incomplete.")

    turn.finished = True


# --- Web verify ---------------------------------------------------------------

# A citation snippet is a preview on a card, so a fetched page is trimmed to fit
# one. Deliberately unlike a RAG hit, where the snippet *is* the model's
# grounding: here the model already has the full content in its own context,
# because Anthropic ran the tool.
_WEB_SNIPPET_CHARS = 400

# How many citations one turn's web lane may issue. A search returns about ten
# results and the model searches several times over a broad question — one live
# question came back with 96, which is not a source list, it is a wall. They
# arrive in the search's own relevance order, so a ceiling keeps the best of
# them; what it turned away is logged rather than silently dropped.
_MAX_WEB_CITATIONS = 10

# A fetched page arrives as markdown behind a block of CMS metadata, then nav
# chrome, before any prose — confirmed live on www.cmu.edu/news, whose first 400
# characters are Drupal `meta-` keys. Taking the head of the page verbatim puts
# that on the citation card.
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")

# Short lines are usually nav ("Skip to main content"), so a line long enough to
# be a sentence is preferred — but only preferred. A page whose whole answer is
# one short line still deserves a snippet.
_PROSE_CHARS = 40


def _page_snippet(text: str) -> str:
    """The first line of a fetched page that reads like prose rather than chrome."""
    fallback = ""
    for raw in _FRONT_MATTER.sub("", text).splitlines():
        line = " ".join(_MD_LINK.sub(r"\1", raw).split())
        # A bullet or heading marker is a nav list, not the page's own prose.
        if not line or line.startswith(("http://", "https://", "*", "-", "#", "|")):
            continue
        if len(line) >= _PROSE_CHARS:
            return line[:_WEB_SNIPPET_CHARS]
        fallback = fallback or line
    return fallback[:_WEB_SNIPPET_CHARS]


def _harvest_web(turn: _Turn, name: str, arguments: dict[str, Any], event: Any) -> None:
    """Turn a built-in web tool's result into citations.

    `agent.tool_result.content` is a list of blocks. `search_result` carries
    `source` (the url), `title` and a `content` list of text blocks; `document`
    carries `source.url` plus an optional `title`; a bare `text` block carries no
    url at all, so it falls back to the one the matching `agent.tool_use` asked
    for. Field names are the SDK's `BetaManagedAgentsAgentToolResultEvent`.

    Nothing here reads `agent.message`. On the raw Messages API its text blocks
    carry per-sentence `web_search_result_location` citations, which would be the
    better source; under Managed Agents they carry only `text`.
    """
    verified_at = timezone.now()
    requested_url = str(arguments.get("url") or "")

    for block in getattr(event, "content", None) or []:
        kind = getattr(block, "type", "")

        if kind == "search_result":
            url = str(getattr(block, "source", "") or "")
            title = str(getattr(block, "title", "") or "")
            snippet = " ".join(
                getattr(part, "text", "")
                for part in getattr(block, "content", None) or []
                if getattr(part, "type", "") == "text"
            )
        elif kind == "document":
            source = getattr(block, "source", None)
            # web_fetch comes back as a *plain-text* document — no url on the
            # block at all — so the one the tool_use asked for is the only one
            # there is. Confirmed live; the `url` source variant is untested.
            url = str(getattr(source, "url", "") or requested_url)
            title = str(getattr(block, "title", "") or "")
            snippet = _page_snippet(
                str(getattr(source, "data", "") or getattr(block, "context", "") or "")
            )
        elif kind == "text":
            url, title = requested_url, ""
            snippet = str(getattr(block, "text", "") or "")
        else:
            continue

        # A source with no url is one nobody can check, which is most of what a
        # citation is for.
        if not url:
            continue

        if turn.ledger.web_count >= _MAX_WEB_CITATIONS and not turn.ledger.cites(url):
            turn.web_dropped += 1
            continue

        turn.ledger.record_web(
            title=title or url,
            url=url,
            # Search excerpts arrive HTML-escaped — "Carnegie Mellon&#x27;s"
            # renders as exactly that on a citation card.
            snippet=" ".join(html.unescape(snippet).split())[:_WEB_SNIPPET_CHARS],
            verified_at=verified_at,
            source=name,
        )


def _result_text(event: Any) -> str:
    """The text blocks of a tool result, joined — what a failed one says."""
    return " ".join(
        getattr(block, "text", "")
        for block in getattr(event, "content", None) or []
        if getattr(block, "type", "") == "text"
    ).strip()


# --- Tool dispatch ------------------------------------------------------------


def _dispatch(turn: _Turn, cma_session_id: str) -> Iterator[dict[str, Any]]:
    """Run every tool the session asked for and send the results back.

    **In parallel.** The platform batches the model's *requests* — several
    `agent.custom_tool_use` events arrive together and resolve into one idle —
    but it never runs our tools, so executing them one after another costs the
    sum of the batch rather than its slowest member. The lanes are all I/O-bound
    HTTP, so a small pool makes a four-tool batch cost about what one tool does.

    Two ordering details, both deliberate:

    - `mode_end` fires as each lane finishes, so a fast lane's chip clears while
      a slow one is still spinning.
    - Citations are harvested afterwards, **in the order the model asked**, not
      in completion order. `S1` is then the same source on every run, which a
      non-deterministic ledger would not give us.
    """
    calls = turn.pending
    turn.pending = []
    outcomes: dict[int, tuple[bool, Any]] = {}

    # max(1, …): a pool of zero workers is a ValueError, and an empty batch is
    # only unreachable because the one caller guards it.
    with ThreadPoolExecutor(max_workers=max(1, min(len(calls), _MAX_PARALLEL))) as pool:
        futures = {
            pool.submit(
                _call_tool, call.name, dict(call.input or {}), turn.session_id, set(turn.tools)
            ): index
            for index, call in enumerate(calls)
        }

        for future in as_completed(futures):
            index = futures[future]
            call = calls[index]
            outcomes[index] = future.result()

            tool = turn.tools.get(call.name)
            if tool is not None:
                yield _event(
                    "mode_end", {"mode": tool.mode, "tool": tool.name, "ok": outcomes[index][0]}
                )

    results: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        ok, payload = outcomes[index]

        if ok:
            turn.ran.append(call.name)
            content = json.dumps(
                turn.ledger.record(turn.tools.get(call.name), payload), default=str
            )
        else:
            turn.failures.append(f"{call.name}: {payload}")
            content = str(payload)

        results.append(
            {
                "type": "user.custom_tool_result",
                "custom_tool_use_id": call.id,
                "content": [{"type": "text", "text": content}],
                # A failure is a result, never a dropped block: a call left
                # unanswered leaves the session idle for ever.
                "is_error": not ok,
            }
        )
        turn.answered.add(call.id)

    client.send_events(cma_session_id, results)


def _call_tool(
    name: str, arguments: dict[str, Any], session_id: str, offered: set[str]
) -> tuple[bool, Any]:
    """Run one tool in a pool thread. Never raises — a failure is a value here.

    A failure has to come back as a value rather than an exception: the model
    reads it and routes around a dead upstream, which is what makes "degrade,
    don't crash" real.

    `offered` is what this turn was told about. A thread's session outlives the
    turn, so one opened before a lane was unchecked is still holding the old
    offer — refusing here is the same belt-and-braces as re-checking a connector.
    """
    if name not in offered:
        return False, f"{name} is not available for this question."

    try:
        return True, run_tool(name, arguments, session_id=session_id or None)
    except ToolError as exc:
        return False, str(exc)
    except Exception as exc:  # a tool bug must not take the answer down with it
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        # Django only closes the request thread's connection for us, and personal
        # tools hit the database to check the connector. Without this each pool
        # thread leaks one connection per dispatch.
        connection.close()


# --- Assembling the reply -----------------------------------------------------


def _modes_used(turn: _Turn) -> list[str]:
    """The lanes that contributed, in MODES order.

    `web_verify` is unioned in separately because Anthropic executes the web
    tools: they never reach `run_tool`, so `modes_for` has no way to see them.
    """
    modes = set(modes_for(turn.ran))
    if turn.web_verified:
        modes.add("web_verify")
    return [mode for mode in MODES if mode in modes]


def _note(turn: _Turn) -> str | None:
    """The caveats worth putting above the answer, or None if there are none."""
    parts = list(turn.notes)

    if turn.failures:
        parts.append("Some sources did not respond — " + "; ".join(turn.failures))
    elif not (turn.ledger.citations or turn.ran or turn.web_verified):
        # Only when nothing ran at all. A lookup that succeeded and found
        # nothing — no dining open at 4am — is still a live campus check, and
        # calling that "general knowledge" tells the reader the opposite of
        # what happened.
        parts.append(
            "No campus source backed this answer, so treat it as general knowledge "
            "rather than live CMU data."
        )

    if turn.ledger.has_mock:
        parts.append("Some sources are placeholder data, marked below.")

    return " ".join(parts) or None


def _event(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"type": kind, "data": data}
