"""User-scoped tools, offered only to sessions that connected the source.

A session with no connection to a provider is never told its tools exist (see
`tools_for_session` in apps/tools/registry.py), so the model cannot call them or
mention data it has no business seeing.

Two very different credentials live behind these tools:

  - **Canvas and Ed** issue a scoped personal access token. The student can
    revoke it without touching their account, and it is all we ever hold.
  - **Piazza and Gradescope issue nothing.** Their only login is the student's
    real email and password, so connecting either means we store a password we
    can decrypt. That is a materially worse failure mode and it was accepted
    deliberately after being raised — see docs/b5-piazza-gradescope.md. Treat
    the encryption discipline here as the floor, not as polish.

Because of that, no failure path in this file interpolates a library's own
exception text into a message. Those messages are built from a login response we
do not control, and everything a tool raises travels onward into the planner's
context and can reach an answer.

The Canvas HTTP client is not wired yet (tasklist B5); its definitions are here
because the plumbing — registry, per-session gating, credential handoff — is what
§1 is about. Until then each Canvas function raises `ToolError`, the same path a
real Canvas outage takes, so degrade-don't-crash gets exercised either way.

When it is wired, `apps.core.http.get_json` is the client to use — but never copy
the `ttl=` from a public B2 call into it. That cache is keyed on url and params
only, so two students hitting the same Canvas endpoint with different tokens
would collide and one could be served the other's data (PRD §9). Caching a
personal response needs a key that includes the user.
"""

from __future__ import annotations

import datetime
import logging

from apps.tools.registry import ToolError, register_tool

from .context import mark_synced, require_connection
from .models import Provider, UserConnection

logger = logging.getLogger(__name__)

# Passed as `requires_connector` below, which is what hides a tool from sessions
# that have not connected that provider.
CANVAS = Provider.CANVAS.value
PIAZZA = Provider.PIAZZA.value
GRADESCOPE = Provider.GRADESCOPE.value

_NOT_WIRED = (
    "The Canvas client is not implemented yet (tasklist B5). The connection is "
    "recognised and the token decrypts, but no request is made to Canvas."
)

#: Posts returned per Piazza class. A feed search can match a whole semester of
#: discussion, and the planner pays for every row in context.
_MAX_POSTS_PER_CLASS = 10


def _connection(session_id: str, provider: str) -> UserConnection:
    """This session's connection to `provider`, as a ToolError if missing.

    The registry already gates personal tools on the connector, so finding
    nothing here means it was disconnected mid-request. Re-raising as ToolError
    keeps every tool failure one exception type, which is what lets the planner
    degrade instead of 500ing.
    """
    try:
        return require_connection(session_id, provider)
    except LookupError as exc:
        raise ToolError(str(exc)) from exc


def _iso(value) -> str | None:
    """A library's datetime as a string the tool result can carry."""
    return value.isoformat() if isinstance(value, datetime.datetime) else None


# --- Canvas -------------------------------------------------------------------


@register_tool(
    name="canvas_list_courses",
    description=(
        "List the courses the student is currently enrolled in, according to their own "
        "Canvas account. Use this to resolve a vague reference like 'my systems class' "
        "to a real course before calling any other tool. Only available when the "
        "student has connected Canvas."
    ),
    json_schema={
        "type": "object",
        "properties": {},
        "required": [],
    },
    mode="personal",
    requires_connector=CANVAS,
)
def canvas_list_courses(*, session_id: str) -> dict:
    connection = _connection(session_id, CANVAS)
    _ = connection.get_token()  # proves the credential decrypts; B5 sends it to Canvas
    raise ToolError(_NOT_WIRED)


@register_tool(
    name="canvas_get_assignments",
    description=(
        "Get the student's upcoming Canvas assignments with their due dates. Use this "
        "for questions about what is due, when something is due, or how busy a "
        "particular week looks. Returns only this student's own coursework. Only "
        "available when the student has connected Canvas."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "due_before": {
                "type": "string",
                "description": (
                    "Only return assignments due before this ISO-8601 timestamp, e.g. "
                    "'2026-08-20T23:59:00-04:00'. Omit for everything upcoming."
                ),
            },
            "course_id": {
                "type": "string",
                "description": (
                    "Restrict to one course, using an id from canvas_list_courses. "
                    "Omit to cover every enrolled course."
                ),
            },
        },
        "required": [],
    },
    mode="personal",
    requires_connector=CANVAS,
)
def canvas_get_assignments(
    *,
    session_id: str,
    due_before: str | None = None,
    course_id: str | None = None,
) -> dict:
    connection = _connection(session_id, CANVAS)
    _ = connection.get_token()
    raise ToolError(_NOT_WIRED)


# --- Gradescope ---------------------------------------------------------------


@register_tool(
    name="gradescope_get_assignments",
    description=(
        "Get the student's Gradescope assignments — name, due date, submission status "
        "and grade — from their own account. Use this for what is due, when something "
        "is due, whether it has been handed in, or what it scored. Covers only courses "
        "the student takes, never one they teach. Only available when the student has "
        "connected Gradescope."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "course_id": {
                "type": "string",
                "description": (
                    "Restrict to one course, using a course_id from an earlier call to "
                    "this tool. Omit to cover every enrolled course."
                ),
            },
        },
        "required": [],
    },
    mode="personal",
    requires_connector=GRADESCOPE,
)
def gradescope_get_assignments(*, session_id: str, course_id: str | None = None) -> dict:
    connection = _connection(session_id, GRADESCOPE)
    account = _gradescope_account(connection)

    try:
        # Instructor courses are dropped rather than filtered later: "the
        # student's assignments" must never include a class they grade.
        courses = account.get_courses().get("student", {})
    except Exception as exc:
        raise ToolError(_upstream_failed("Gradescope", exc)) from None

    if course_id:
        courses = {key: value for key, value in courses.items() if key == course_id}
        if not courses:
            raise ToolError(f"No enrolled Gradescope course with id {course_id!r}.")

    results = []
    for cid, course in courses.items():
        try:
            # Reading the assignments is inside the try as well as fetching
            # them: `_assignment` addresses dataclass fields directly, so a
            # release that renames one raises here rather than at the call, and
            # outside this block it would leave the tool by a route that is not
            # a ToolError.
            results.extend(
                _assignment(assignment, cid, course)
                for assignment in account.get_assignments(cid)
            )
        except Exception as exc:
            # One unreadable course must not cost the student the other five.
            logger.warning(
                "gradescope_course_unreadable course=%s error=%s", cid, type(exc).__name__
            )
            continue

    mark_synced(connection)
    return {
        "results": results,
        "citations": [_assignment_citation(result) for result in results],
    }


def _gradescope_account(connection: UserConnection):
    """Log in and hand back the account, or say so without quoting the library.

    Every call pays a full login: Gradescope issues no token, and neither the
    library nor its docs describe a session cookie that is safe to persist and
    replay, so caching one would be exactly the unverified assumption Phase 0
    exists to prevent.
    """
    from gradescopeapi.classes.connection import GSConnection

    credential = connection.get_credential()
    gs = GSConnection()
    try:
        gs.login(credential["email"], credential["password"])
    except Exception as exc:
        raise ToolError(_login_failed("Gradescope", exc)) from None

    return gs.account


def _assignment(assignment, course_id: str, course) -> dict:
    """One Gradescope assignment, flattened onto its course.

    Field names are the `Assignment` and `Course` dataclasses as installed, read
    off the package rather than its README — which described `get_courses()` as
    returning lists of dicts when it returns dicts of dataclasses keyed by id.
    """
    return {
        "course_id": course_id,
        "course": getattr(course, "full_name", "") or getattr(course, "name", ""),
        "name": assignment.name,
        "assignment_id": assignment.assignment_id,
        "due_date": _iso(assignment.due_date),
        "late_due_date": _iso(assignment.late_due_date),
        "submissions_status": assignment.submissions_status,
        "grade": assignment.grade,
        "max_grade": assignment.max_grade,
    }


def _assignment_citation(assignment: dict) -> dict:
    """The card behind an inline chip.

    No url: Gradescope's per-assignment page sits behind a course path this
    library never returns, and a guessed link is worse than none (PRD §3).
    The grade is deliberately not in the snippet — it reaches the model through
    `results`, and a citation card is the one part of an answer that gets
    screenshotted.
    """
    bits = [assignment["course"]]
    if assignment["due_date"]:
        bits.append(f"due {assignment['due_date']}")
    if assignment["submissions_status"]:
        bits.append(assignment["submissions_status"])

    return {
        "title": assignment["name"],
        "url": "",
        "snippet": " · ".join(bit for bit in bits if bit),
        "indexed_at": None,
    }


# --- Piazza -------------------------------------------------------------------
#
# Piazza scopes everything to a "network" — one per class — so there is no single
# "the student's Piazza data" the way Canvas has "the student's courses". The
# network id is discovered from the student's own account at query time
# (`get_user_classes`), not asked for when they connect: the model has no way to
# know a network id, and making someone paste one to connect would be a worse
# version of the same lookup.


@register_tool(
    name="piazza_list_classes",
    description=(
        "List the Piazza classes the student is enrolled in, each with the network_id "
        "that piazza_search takes. Call this first to turn a course name or number "
        "into a network_id. Only available when the student has connected Piazza."
    ),
    json_schema={
        "type": "object",
        "properties": {},
        "required": [],
    },
    mode="personal",
    requires_connector=PIAZZA,
)
def piazza_list_classes(*, session_id: str) -> dict:
    connection = _connection(session_id, PIAZZA)
    piazza = _piazza_client(connection)

    classes = _piazza_classes(piazza)

    mark_synced(connection)
    return {
        "results": classes,
        "citations": [_class_citation(klass) for klass in classes],
    }


@register_tool(
    name="piazza_search",
    description=(
        "Search the student's Piazza classes for posts matching a query — instructor "
        "announcements, exam logistics, homework clarifications, policy answers. "
        "Searches every class the student is in unless network_id narrows it.\n\n"
        "This is the student's own view of a *shared* class forum, not their private "
        "data: the posts are written by classmates and course staff. Summarise what a "
        "thread established rather than repeating a post back word for word, and do "
        "not name the students who wrote them.\n\n"
        "Only available when the student has connected Piazza."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keywords to match, e.g. 'midterm regrade policy'.",
            },
            "network_id": {
                "type": "string",
                "description": (
                    "One class's Piazza network id, from piazza_list_classes. Omit to "
                    "search every class the student is enrolled in."
                ),
            },
        },
        "required": ["query"],
    },
    mode="personal",
    requires_connector=PIAZZA,
)
def piazza_search(*, session_id: str, query: str, network_id: str | None = None) -> dict:
    connection = _connection(session_id, PIAZZA)
    piazza = _piazza_client(connection)

    classes = _piazza_classes(piazza)
    if network_id:
        classes = [klass for klass in classes if klass["network_id"] == network_id]
        if not classes:
            raise ToolError(f"The student is not enrolled in Piazza class {network_id!r}.")

    results = []
    for klass in classes:
        try:
            payload = piazza.network(klass["network_id"]).search_feed(query)
            results.extend(
                _post(item, klass) for item in _feed_items(payload)[:_MAX_POSTS_PER_CLASS]
            )
        except Exception as exc:
            # One class refusing a search must not lose the others.
            logger.warning(
                "piazza_class_unreadable network=%s error=%s",
                klass["network_id"],
                type(exc).__name__,
            )
            continue

    mark_synced(connection)
    return {
        "results": results,
        "citations": [_post_citation(post) for post in results],
    }


def _piazza_client(connection: UserConnection):
    """Log in to Piazza, or say so without quoting the library.

    `user_login` prompts on stdin for anything it is not given, which a web
    request can never answer — so both keyword arguments are always passed, and
    a blank one is rejected at the connections endpoint rather than here.
    """
    from piazza_api import Piazza

    credential = connection.get_credential()
    piazza = Piazza()
    try:
        piazza.user_login(email=credential["email"], password=credential["password"])
    except Exception as exc:
        raise ToolError(_login_failed("Piazza", exc)) from None

    return piazza


def _piazza_classes(piazza) -> list[dict]:
    """The student's classes, renamed onto our own keys.

    `nid` is Piazza's name for it and means nothing to the model; the tool
    schema calls it network_id, so the result should too.
    """
    try:
        raw = piazza.get_user_classes()
    except Exception as exc:
        raise ToolError(_upstream_failed("Piazza", exc)) from None

    return [
        {
            "network_id": klass.get("nid", ""),
            "name": klass.get("name", ""),
            "course_number": klass.get("num", ""),
            "term": klass.get("term", ""),
        }
        for klass in raw or []
        if klass.get("nid")
    ]


def _feed_items(payload) -> list[dict]:
    """A search response as a list of posts.

    Phase 0 confirmed the *call* by reading the installed package, but not the
    response body — that needs a real class. So this accepts either shape the
    endpoint is described as returning and yields nothing on a third, because a
    search that finds nothing degrades and a raise does not.
    """
    if isinstance(payload, dict):
        payload = payload.get("feed")
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _post(item: dict, klass: dict) -> dict:
    # `content_snipet` is Piazza's own spelling; the corrected one is accepted
    # too rather than betting the snippet on which reaches us.
    snippet = item.get("content_snipet") or item.get("content_snippet") or ""
    return {
        "network_id": klass["network_id"],
        "class": klass["name"],
        "number": item.get("nr", ""),
        "subject": item.get("subject", ""),
        "snippet": snippet,
        "type": item.get("type", ""),
        "created": item.get("created", ""),
    }


def _class_citation(klass: dict) -> dict:
    return {
        "title": " — ".join(bit for bit in (klass["course_number"], klass["name"]) if bit),
        "url": _class_url(klass["network_id"]),
        "snippet": klass["term"],
        "indexed_at": None,
    }


def _post_citation(post: dict) -> dict:
    """Links to the class feed rather than the post.

    The class URL is the one piazza-api documents. A per-post anchor is widely
    assumed to be `?cid=`, which is exactly the sort of thing Phase 0 refuses to
    take on faith — verify it against a real class before adding it.
    """
    number = f"@{post['number']}" if post["number"] else ""
    return {
        "title": post["subject"] or f"Piazza {number}".strip() or "Piazza post",
        "url": _class_url(post["network_id"]),
        "snippet": " · ".join(bit for bit in (post["class"], number, post["snippet"]) if bit),
        "indexed_at": None,
    }


def _class_url(network_id: str) -> str:
    return f"https://piazza.com/class/{network_id}" if network_id else ""


# --- Failure messages ---------------------------------------------------------
#
# Both of these drop the caught exception's text, and every `raise` that uses
# them says `from None`. That is not tidiness, and it should not be "fixed" back
# to `from exc`:
#
#   - piazza-api raises `AuthenticationError(f"...\n{response.text}")` — an
#     exception message assembled out of a login page we do not control.
#   - A ToolError's message travels into the planner's context and can reach an
#     answer, and `run_tool` logs a failure with `logger.exception`, which walks
#     the `__cause__` chain. `from exc` would put that same page in both places.
#
# The exception *type* is logged instead, which is what actually tells you
# whether a call failed on credentials, the network, or a parse.


def _login_failed(service: str, exc: Exception) -> str:
    logger.warning("%s_login_failed error=%s", service.lower(), type(exc).__name__)
    return (
        f"Could not sign in to {service}. The stored email or password may be wrong "
        f"or out of date — reconnect {service} in settings and try again."
    )


def _upstream_failed(service: str, exc: Exception) -> str:
    logger.warning("%s_request_failed error=%s", service.lower(), type(exc).__name__)
    return f"Signed in to {service}, but it did not return the student's courses."
