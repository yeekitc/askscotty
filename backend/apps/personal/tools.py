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

Canvas and Ed go through `apps.core.http.get_json` with an `Authorization`
header. That call is never cached — get_json makes caching structurally
impossible once a header is present — because the cache is keyed on url and
params only, so caching an authenticated response would let two students on the
same endpoint be served each other's data (PRD §9). Stellic is a mock and makes
no request at all.
"""

from __future__ import annotations

import datetime
import logging
import re

import httpx  # for httpx.HTTPError only

from apps.core.http import get_json
from apps.tools.registry import ToolError, register_tool
from django.utils import timezone

from .context import mark_synced, require_connection
from .crypto import DecryptionError
from .models import Provider, UserConnection

logger = logging.getLogger(__name__)

# Passed as `requires_connector` below, which is what hides a tool from sessions
# that have not connected that provider.
CANVAS = Provider.CANVAS.value
ED = Provider.ED.value
PIAZZA = Provider.PIAZZA.value
GRADESCOPE = Provider.GRADESCOPE.value
STELLIC = Provider.STELLIC.value

_CANVAS_BASE = "https://canvas.cmu.edu/api/v1"
_ED_BASE = "https://us.edstem.org/api/"

# Canvas and Ed list endpoints paginate with a Link header get_json never sees
# (docs/b5-canvas-ed-stellic.md Part 0). 100 is the max page and covers a normal
# student's course and thread load; a heavier account is truncated at one page,
# which the tool descriptions say rather than hide.
_PAGE = 100

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


def _credential(connection: UserConnection) -> dict:
    """The decrypted credential, or a ToolError saying to reconnect.

    A stored credential stops decrypting the moment CONNECTOR_ENCRYPTION_KEY
    changes — and while none is set, crypto.py derives one from
    DJANGO_SECRET_KEY, so rotating *that* has the same effect. `DecryptionError`
    is not a ToolError, so without this the planner meets an exception it has no
    degrade path for and the student gets a 500 rather than being told the one
    thing that fixes it.

    Chaining is kept here, unlike the login failures below: this exception is
    ours, and its message is a fixed sentence with no credential in it.
    """
    try:
        return connection.get_credential()
    except (DecryptionError, ValueError, KeyError) as exc:
        raise ToolError(
            f"The stored {connection.provider} credential could not be read — it was "
            f"probably encrypted with a different key. Disconnect and reconnect "
            f"{connection.provider} in settings."
        ) from exc


def _load_cookies(session, cookies: dict) -> None:
    """Load a captured cookie jar into a library's requests session.

    Demo-only (apps/personal/demo_only): the value comes from a browser
    extension that reads an already-signed-in tab's cookies, so whatever names
    that domain uses are set verbatim rather than guessed at here.
    """
    for name, value in cookies.items():
        session.cookies.set(name, str(value))


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
    headers = _bearer(connection)

    courses = _get_json(
        f"{_CANVAS_BASE}/courses",
        params={"enrollment_state": "active", "per_page": _PAGE},
        headers=headers,
        service="Canvas",
    )

    mark_synced(connection)
    results = [
        {
            "id": course.get("id"),
            "name": course.get("name", ""),
            "course_code": course.get("course_code", ""),
        }
        for course in courses
        # A concluded or restricted enrolment comes back without a name; it is
        # not a course the student can act on.
        if isinstance(course, dict) and course.get("name")
    ]
    return {"results": results, "citations": [_course_citation(c) for c in results]}


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
    headers = _bearer(connection)

    # /planner/items aggregates every enrolled course in one call, already
    # ordered by date — which is the "what's due this week" question. Looping
    # /courses/{id}/assignments would be one request per class for the same
    # answer.
    params: dict = {"per_page": _PAGE}
    if due_before:
        params["end_date"] = due_before
    if course_id:
        params["context_codes[]"] = f"course_{course_id}"

    items = _get_json(
        f"{_CANVAS_BASE}/planner/items", params=params, headers=headers, service="Canvas"
    )

    mark_synced(connection)
    results = [
        _planner_item(item) for item in items if isinstance(item, dict)
    ]
    return {"results": results, "citations": [_planner_citation(item) for item in results]}


def _bearer(connection: UserConnection) -> dict:
    """The Authorization header for a token connector (Canvas, Ed).

    Built through _credential so a token that no longer decrypts becomes the
    reconnect ToolError rather than a KeyError, and returned as a fresh dict so
    it never outlives the call.
    """
    return {"Authorization": f"Bearer {_credential(connection).get('token', '')}"}


def _get_json(url: str, *, params: dict, headers: dict, service: str):
    """get_json with the two things every connector call needs: no cache on an
    authenticated request (get_json enforces that structurally once headers are
    present), and every httpx failure translated to a ToolError.

    `service` names the source in the message; the exception text is dropped
    because an httpx error can carry the request URL with its query string, and
    a personal call's params can identify the student.
    """
    try:
        return get_json(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("%s_request_failed error=%s", service.lower(), type(exc).__name__)
        raise ToolError(
            f"{service} could not be reached, or rejected the stored credential. "
            f"If this keeps happening, reconnect {service} in settings."
        ) from None


def _planner_item(item: dict) -> dict:
    """One Canvas planner item, flattened.

    Reads through `.get()` because the `plannable` sub-object's fields vary by
    `plannable_type` (assignment, quiz, discussion_topic, …) and the docs give
    no guarantee every type carries `due_at`; a missing one stays None rather
    than raising. `plannable_date` is the item's own date and backs a due_at the
    sub-object omitted.
    """
    plannable = item.get("plannable") or {}
    return {
        "type": item.get("plannable_type", ""),
        "title": plannable.get("title") or item.get("plannable_type", ""),
        "due_at": plannable.get("due_at") or item.get("plannable_date"),
        "course": item.get("context_name", ""),
        "points_possible": plannable.get("points_possible"),
        # Canvas's own student-facing link, not one hand-built here.
        "html_url": item.get("html_url", ""),
    }


def _course_citation(course: dict) -> dict:
    number = course["course_code"]
    return {
        "title": " — ".join(bit for bit in (number, course["name"]) if bit),
        "url": f"https://canvas.cmu.edu/courses/{course['id']}" if course.get("id") else "",
        "snippet": number,
        "indexed_at": None,
    }


def _planner_citation(item: dict) -> dict:
    bits = [item["course"]]
    if item["due_at"]:
        bits.append(f"due {item['due_at']}")
    return {
        "title": item["title"],
        "url": item["html_url"],
        "snippet": " · ".join(bit for bit in bits if bit),
        "indexed_at": None,
    }


#: How far back canvas_get_announcements looks by default. Canvas's own default
#: is 14 days, which routinely comes back empty; a term-length window keeps the
#: whole semester's announcements in reach, and each result carries `posted_at`
#: so the model can still say what is genuinely recent.
_ANNOUNCEMENT_DAYS = 180


@register_tool(
    name="canvas_get_announcements",
    description=(
        "Get recent Canvas announcements — instructor posts about exams, schedule "
        "changes, policy and logistics — from the student's own courses. Use this for "
        "'did my professor announce anything', 'any updates in <class>', or exam "
        "logistics. Only available when the student has connected Canvas."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "course_id": {
                "type": "string",
                "description": (
                    "Restrict to one course, using an id from canvas_list_courses. "
                    "Omit for announcements across every enrolled course."
                ),
            },
        },
        "required": [],
    },
    mode="personal",
    requires_connector=CANVAS,
)
def canvas_get_announcements(*, session_id: str, course_id: str | None = None) -> dict:
    connection = _connection(session_id, CANVAS)
    headers = _bearer(connection)

    # The announcements endpoint requires context_codes, and the id it stamps on
    # each result is not the course name — so the enrolled list is fetched either
    # way, to build both the contexts and a name map.
    courses = _get_json(
        f"{_CANVAS_BASE}/courses",
        params={"enrollment_state": "active", "per_page": _PAGE},
        headers=headers,
        service="Canvas",
    )
    names = {
        f"course_{course['id']}": course.get("name", "")
        for course in courses
        if isinstance(course, dict) and course.get("id")
    }
    contexts = [f"course_{course_id}"] if course_id else list(names)
    if not contexts:
        mark_synced(connection)
        return {"results": [], "citations": []}

    # Both bounds: with only start_date, Canvas narrows the window and returns
    # nothing (confirmed live). end_date is tomorrow so today is included.
    now = timezone.now()
    since = (now - datetime.timedelta(days=_ANNOUNCEMENT_DAYS)).date().isoformat()
    until = (now + datetime.timedelta(days=1)).date().isoformat()
    items = _get_json(
        f"{_CANVAS_BASE}/announcements",
        params={
            "context_codes[]": contexts,
            "start_date": since,
            "end_date": until,
            "per_page": _PAGE,
        },
        headers=headers,
        service="Canvas",
    )

    mark_synced(connection)
    results = [_announcement(item, names) for item in items if isinstance(item, dict)]
    return {"results": results, "citations": [_announcement_citation(a) for a in results]}


def _strip_html(html: str) -> str:
    """A Canvas announcement body is HTML; a citation snippet wants plain text."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _announcement(item: dict, names: dict) -> dict:
    context = item.get("context_code", "")
    return {
        "title": item.get("title", ""),
        "course": names.get(context, context.replace("course_", "")),
        "posted_at": item.get("posted_at") or item.get("created_at"),
        "author": (item.get("author") or {}).get("display_name", ""),
        "html_url": item.get("html_url", ""),
        "snippet": _strip_html(item.get("message", ""))[:280],
    }


def _announcement_citation(item: dict) -> dict:
    bits = [item["course"]]
    if item["posted_at"]:
        bits.append(f"posted {item['posted_at']}")
    return {
        "title": item["title"] or "Canvas announcement",
        "url": item["html_url"],
        "snippet": " · ".join(bit for bit in (*bits, item["snippet"]) if bit),
        "indexed_at": None,
    }


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

    credential = _credential(connection)
    gs = GSConnection()

    cookies = credential.get("cookies")
    if cookies:
        # Demo-only path (docs/b5-piazza-gradescope.md, apps/personal/demo_only).
        # A session cookie captured from an already-signed-in browser tab, which
        # skips login() and so is the only path past Duo — an automated password
        # login stops at 2FA. Never populated by the public connect endpoint.
        from gradescopeapi.classes.account import Account

        _load_cookies(gs.session, cookies)
        gs.logged_in = True
        gs.account = Account(gs.session, gs.gradescope_base_url)
        return gs.account

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

    credential = _credential(connection)

    cookies = credential.get("cookies")
    if cookies:
        # Demo-only path — see _gradescope_account. PiazzaRPC._check_authenticated
        # only asserts the cookie jar is non-empty, so a captured session cookie
        # stands in for user_login() and never reaches Duo.
        from piazza_api.rpc import PiazzaRPC

        rpc = PiazzaRPC()
        _load_cookies(rpc.session, cookies)
        return Piazza(piazza_rpc=rpc)

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


# --- Ed Discussion ------------------------------------------------------------
#
# Confirmed by reading edapi's source, not a README (docs/b5-canvas-ed-stellic.md):
# the same official Bearer token as Canvas, GET /api/user carries the student's
# course enrolments, and there is no server-side thread search — list_threads
# takes only limit/offset/sort. So course resolution mirrors Canvas, and the
# search is an honest client-side filter over one page of recent threads.


@register_tool(
    name="ed_list_courses",
    description=(
        "List the Ed Discussion courses the student is enrolled in, each with the "
        "course_id that ed_search_threads takes. Call this first to turn a course name "
        "or number into a course_id. Only available when the student has connected Ed."
    ),
    json_schema={
        "type": "object",
        "properties": {},
        "required": [],
    },
    mode="personal",
    requires_connector=ED,
)
def ed_list_courses(*, session_id: str) -> dict:
    connection = _connection(session_id, ED)
    headers = _bearer(connection)

    payload = _get_json(f"{_ED_BASE}user", params={}, headers=headers, service="Ed Discussion")

    mark_synced(connection)
    courses = _ed_courses(payload)
    return {"results": courses, "citations": [_ed_course_citation(c) for c in courses]}


@register_tool(
    name="ed_search_threads",
    description=(
        "Search recent threads in one of the student's Ed Discussion courses — "
        "announcements, exam logistics, homework clarifications, staff answers. "
        "Needs a course_id from ed_list_courses.\n\n"
        "This filters the most recent threads by keyword; it does NOT search the "
        "whole course history, so treat a miss as 'not in the recent threads', not "
        "'never discussed'. The threads are a shared class space written by "
        "classmates and staff — summarise what was established, do not repeat other "
        "students' posts verbatim or name them.\n\n"
        "Only available when the student has connected Ed."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "course_id": {
                "type": "string",
                "description": "The Ed course to search, from ed_list_courses.",
            },
            "keywords": {
                "type": "string",
                "description": "Words to match in a thread's title or body. Omit for the most recent.",
            },
        },
        "required": ["course_id"],
    },
    mode="personal",
    requires_connector=ED,
)
def ed_search_threads(
    *, session_id: str, course_id: str, keywords: str | None = None
) -> dict:
    connection = _connection(session_id, ED)
    headers = _bearer(connection)

    payload = _get_json(
        f"{_ED_BASE}courses/{course_id}/threads",
        params={"limit": _PAGE, "offset": 0, "sort": "new"},
        headers=headers,
        service="Ed Discussion",
    )

    mark_synced(connection)
    threads = payload.get("threads", []) if isinstance(payload, dict) else []
    if keywords:
        needle = keywords.lower()
        threads = [
            thread
            for thread in threads
            if isinstance(thread, dict)
            and needle in f"{thread.get('title', '')} {thread.get('document', '')}".lower()
        ]

    results = [_ed_thread(thread) for thread in threads if isinstance(thread, dict)]
    return {"results": results, "citations": [_ed_thread_citation(t) for t in results]}


def _ed_courses(payload: dict) -> list[dict]:
    """The student's courses out of GET /api/user's `courses` list.

    Each entry is `{"course": {...}, "role": {...}}`; the model wants the course,
    renamed onto course_id/code/name. An archived course is dropped — a stale
    class the student cannot act on is noise in a "which class?" lookup.
    """
    if not isinstance(payload, dict):
        return []

    courses = []
    for entry in payload.get("courses", []):
        course = entry.get("course", {}) if isinstance(entry, dict) else {}
        if not course.get("id") or course.get("status") == "archived":
            continue
        courses.append(
            {
                "course_id": str(course["id"]),
                "code": course.get("code", ""),
                "name": course.get("name", ""),
                "year": course.get("year", ""),
            }
        )
    return courses


def _ed_thread(thread: dict) -> dict:
    return {
        "course_id": str(thread.get("course_id", "")),
        "number": thread.get("number", ""),
        "title": thread.get("title", ""),
        "type": thread.get("type", ""),
        "category": thread.get("category", ""),
        "is_answered": thread.get("is_answered", False),
        "snippet": (thread.get("document") or "")[:280],
        "created_at": thread.get("created_at", ""),
    }


def _ed_course_citation(course: dict) -> dict:
    return {
        "title": " — ".join(bit for bit in (course["code"], course["name"]) if bit),
        # No confirmed public per-course Ed URL in the response — don't invent one.
        "url": "",
        "snippet": course["year"],
        "indexed_at": None,
    }


def _ed_thread_citation(thread: dict) -> dict:
    """No url: API_Thread carries no link field, and the `discussion/{number}`
    pattern is a guess this project's rules forbid (docs/b5-canvas-ed-stellic.md)."""
    answered = "answered" if thread["is_answered"] else "open"
    return {
        "title": thread["title"] or "Ed thread",
        "url": "",
        "snippet": " · ".join(bit for bit in (thread["category"], answered, thread["snippet"]) if bit),
        "indexed_at": None,
    }


@register_tool(
    name="ed_get_announcements",
    description=(
        "Get instructor announcements from one of the student's Ed Discussion courses "
        "— exam logistics, schedule changes, policy notices. Needs a course_id from "
        "ed_list_courses. Only available when the student has connected Ed."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "course_id": {
                "type": "string",
                "description": "The Ed course, from ed_list_courses.",
            },
        },
        "required": ["course_id"],
    },
    mode="personal",
    requires_connector=ED,
)
def ed_get_announcements(*, session_id: str, course_id: str) -> dict:
    connection = _connection(session_id, ED)
    headers = _bearer(connection)

    payload = _get_json(
        f"{_ED_BASE}courses/{course_id}/threads",
        params={"limit": _PAGE, "offset": 0, "sort": "new"},
        headers=headers,
        service="Ed Discussion",
    )

    mark_synced(connection)
    threads = payload.get("threads", []) if isinstance(payload, dict) else []
    # Ed marks an announcement with type == "announcement" (confirmed live); it is
    # a field on the same thread shape, so no separate endpoint is needed.
    results = [
        _ed_thread(thread)
        for thread in threads
        if isinstance(thread, dict) and thread.get("type") == "announcement"
    ]
    return {"results": results, "citations": [_ed_thread_citation(t) for t in results]}


# --- Stellic (mock only) ------------------------------------------------------
#
# No real integration, by explicit direction (docs/b5-canvas-ed-stellic.md Part
# C): Stellic offers institutional PAT only, no student credential to build
# against. This is fixture data the same way apps/tools/maps.py's buildings are,
# but still gated through the connections flow so the settings UI has a real
# toggle rather than a special case. Every citation is is_mock via the registry.
#
# What makes this Stellic and not the course catalog: it is keyed to the
# student's *progress* — completed vs required units and what is left — not to
# what courses exist. The programs are CMU's most common majors and minors, with
# real course numbers so the placeholder reads as a real audit; the numbers
# themselves are invented, hence is_mock.
#
# Each entry carries `aliases` and `kind` used only for matching a free-text
# program name; both are stripped before the audit is handed back, so the model
# never sees them.

_MOCK_AUDITS: dict[str, dict] = {
    "cs_major": {
        "program": "Computer Science (SCS)",
        "kind": "major",
        "required": 360,
        "completed": 315,
        "remaining": ["15-451 Algorithm Design and Analysis", "one 300+ CS elective"],
        "aliases": (" cs ", "computer science", "comp sci"),
    },
    "ece_major": {
        "program": "Electrical & Computer Engineering (CIT)",
        "kind": "major",
        "required": 380,
        "completed": 300,
        "remaining": ["18-290 Signals and Systems", "one capstone", "two technical electives"],
        "aliases": ("ece", "electrical", "computer engineering"),
    },
    "business_major": {
        "program": "Business Administration (Tepper)",
        "kind": "major",
        "required": 360,
        "completed": 279,
        "remaining": ["70-371 Operations Management", "70-391 Finance", "one 70-3xx elective"],
        "aliases": ("business", "tepper"),
    },
    "meche_major": {
        "program": "Mechanical Engineering (CIT)",
        "kind": "major",
        "required": 385,
        "completed": 301,
        "remaining": ["24-231 Fluid Mechanics", "24-351 Dynamics", "one ME elective"],
        "aliases": ("mechanical", "mech e", "meche"),
    },
    "statistics_major": {
        "program": "Statistics & Data Science (Dietrich)",
        "kind": "major",
        "required": 360,
        "completed": 288,
        "remaining": ["36-401 Modern Regression", "36-402 Advanced Methods for Data Analysis"],
        "aliases": ("statistics", "stats", "statistics and data science"),
    },
    "ai_major": {
        "program": "Artificial Intelligence (SCS)",
        "kind": "major",
        "required": 380,
        "completed": 305,
        "remaining": ["10-301 Introduction to Machine Learning", "15-281 AI: Representation & Problem Solving"],
        "aliases": ("artificial intelligence", " ai ", "bsai"),
    },
    "infosys_major": {
        "program": "Information Systems (Dietrich)",
        "kind": "major",
        "required": 360,
        "completed": 327,
        "remaining": [
            "67-272 Application Design & Development",
            "67-373 Information Systems Practicum",
            "one Statistics elective (36-202)",
        ],
        "aliases": ("information system", "info sys", "info systems", " is "),
    },
    "economics_major": {
        "program": "Economics (Dietrich)",
        "kind": "major",
        "required": 360,
        "completed": 270,
        "remaining": ["73-240 Intermediate Macroeconomics", "73-274 Econometrics I", "one economics elective"],
        "aliases": ("economics", "econ"),
    },
    "math_major": {
        "program": "Mathematical Sciences (MCS)",
        "kind": "major",
        "required": 360,
        "completed": 279,
        "remaining": ["21-355 Principles of Real Analysis I", "21-373 Algebraic Structures", "one math elective"],
        "aliases": ("mathematical sciences", "mathematics", "math"),
    },
    "psychology_major": {
        "program": "Psychology (Dietrich)",
        "kind": "major",
        "required": 360,
        "completed": 288,
        "remaining": ["85-300 Introduction to Research Methods", "85-241 Social Psychology", "one psychology elective"],
        "aliases": ("psychology", "psych"),
    },
    "cs_minor": {
        "program": "CS Minor (SCS)",
        "kind": "minor",
        "required": 63,
        "completed": 45,
        "remaining": ["15-210 Parallel & Sequential Data Structures", "one 300+ CS elective"],
        "aliases": (" cs ", "computer science", "comp sci"),
    },
    "business_minor": {
        "program": "Business Administration Minor (Tepper)",
        "kind": "minor",
        "required": 54,
        "completed": 36,
        "remaining": ["70-122 Introduction to Accounting", "18 units of 70-3xx electives"],
        "aliases": ("business", "tepper"),
    },
    "statistics_minor": {
        "program": "Statistics Minor (Dietrich)",
        "kind": "minor",
        "required": 54,
        "completed": 36,
        "remaining": ["36-225 Introduction to Probability Theory", "two statistics electives"],
        "aliases": ("statistics", "stats"),
    },
    "ml_minor": {
        "program": "Machine Learning Minor (SCS)",
        "kind": "minor",
        "required": 63,
        "completed": 42,
        "remaining": ["one advanced ML course (10-417 / 10-418)", "two ML electives"],
        "aliases": ("machine learning", " ml "),
    },
    "hci_minor": {
        "program": "Human-Computer Interaction Minor (SCS)",
        "kind": "minor",
        "required": 54,
        "completed": 36,
        "remaining": ["05-410 User-Centered Research & Evaluation", "two HCI electives", "a project course"],
        "aliases": ("human-computer interaction", "human computer interaction", "hci"),
    },
    "design_minor": {
        "program": "Design Minor (CFA)",
        "kind": "minor",
        "required": 54,
        "completed": 36,
        "remaining": ["51-262 Communication & Digital Design Fundamentals", "three studio electives"],
        "aliases": ("design",),
    },
}

_DEFAULT_AUDIT = "cs_major"


def _resolve_audit(program: str) -> dict:
    """Match a free-text program name onto a mock audit, forgivingly.

    The model passes whatever the student typed ('information systems', 'IS
    major', 'stats minor'), so matching is on each entry's aliases rather than an
    exact key. When the text says "major" or "minor", that wins the tie between
    two programs sharing a name (CS, Business, Statistics all exist as both);
    otherwise majors are listed first, so a bare "CS" resolves to the major.
    """
    query = f" {program.strip().lower()} "
    wants_minor, wants_major = "minor" in query, "major" in query

    def matches(audit: dict) -> bool:
        return any(alias in query for alias in audit["aliases"])

    for audit in _MOCK_AUDITS.values():
        if not matches(audit):
            continue
        if wants_minor and audit["kind"] != "minor":
            continue
        if wants_major and audit["kind"] != "major":
            continue
        return audit

    # A kind was named but nothing of that kind matched — fall back to the
    # program regardless of kind before giving up entirely.
    for audit in _MOCK_AUDITS.values():
        if matches(audit):
            return audit

    return _MOCK_AUDITS[_DEFAULT_AUDIT]


@register_tool(
    name="stellic_degree_audit",
    description=(
        "Check progress toward a degree or minor requirement, using a MOCK degree "
        "audit. This is placeholder data, not the student's real Stellic record — say "
        "so in the answer. Combine with search_courses/get_course for live course "
        "data; this tool only covers what's 'required', not what's offered. Only "
        "available when the student has connected Stellic."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "program": {
                "type": "string",
                "description": "e.g. 'CS minor', 'ECE major', 'Information Systems'.",
            },
        },
        "required": ["program"],
    },
    mode="personal",
    requires_connector=STELLIC,
    is_mock=True,
)
def stellic_degree_audit(*, session_id: str, program: str) -> dict:
    # Confirms the connector is connected (and translates a mid-request
    # disconnect to a ToolError); nothing is read from it — there is no
    # credential to read.
    _connection(session_id, STELLIC)

    audit = _resolve_audit(program)
    # `aliases` is only for matching; `kind` is folded into the program label
    # already. Neither belongs in what the model reads back.
    result = {key: value for key, value in audit.items() if key not in ("aliases", "kind")}
    return {
        "results": [result],
        "citations": [
            {
                "title": f"{audit['program']} — mock degree audit",
                "url": "",
                "snippet": f"{audit['completed']}/{audit['required']} units completed (mock data)",
                "indexed_at": None,
            }
        ],
    }


# --- Demo stand-ins -----------------------------------------------------------
#
# Each of these appears in tools_for_session only when its real provider is not
# connected (shadows= gates it). requires_connector=None means run() calls the
# function directly, with no session_id forwarded, which keeps personal data out
# of the call (same guarantee as any public tool). is_mock=True is stamped on
# every citation so the MOCK badge always appears.


@register_tool(
    name="canvas_sample",
    description=(
        "Returns example Canvas courses and assignments for a CMU student. "
        "Only use this tool when the user has NOT connected Canvas. "
        "Always tell the user this is example data and that they can connect "
        "Canvas via their profile to see their real courses and assignments."
    ),
    json_schema={"type": "object", "properties": {}},
    mode="personal",
    is_mock=True,
    shadows=CANVAS,
)
def canvas_sample() -> dict:
    return {
        "results": [
            {
                "courses": [
                    {"id": 101, "name": "15-213 Introduction to Computer Systems", "term": "Fall 2024"},
                    {"id": 102, "name": "15-251 Great Theoretical Ideas in CS", "term": "Fall 2024"},
                    {"id": 103, "name": "21-127 Concepts of Mathematics", "term": "Fall 2024"},
                ],
                "upcoming_assignments": [
                    {
                        "course": "15-213",
                        "name": "Data Lab",
                        "due": "2024-09-20T23:59:00",
                        "points": 100,
                    },
                    {
                        "course": "15-251",
                        "name": "Problem Set 2",
                        "due": "2024-09-22T23:59:00",
                        "points": 50,
                    },
                ],
                "announcements": [
                    {
                        "course": "15-213",
                        "title": "Office hours this week",
                        "posted": "2024-09-15",
                    }
                ],
            }
        ],
        "citations": [
            {
                "title": "Canvas — example courses (not your real data)",
                "url": "",
                "snippet": "Example data — connect Canvas in your profile to see your real courses and assignments.",
                "indexed_at": None,
                "is_mock": True,
                "source": "canvas_sample",
            }
        ],
    }


@register_tool(
    name="ed_sample",
    description=(
        "Returns example Ed Discussion threads for a CMU student. "
        "Only use this tool when the user has NOT connected Ed. "
        "Always tell the user this is example data and that they can connect "
        "Ed via their profile to see their real discussion threads."
    ),
    json_schema={"type": "object", "properties": {}},
    mode="personal",
    is_mock=True,
    shadows=ED,
)
def ed_sample() -> dict:
    return {
        "results": [
            {
                "courses": [
                    {"id": 201, "name": "15-213 Introduction to Computer Systems"},
                    {"id": 202, "name": "15-251 Great Theoretical Ideas in CS"},
                ],
                "recent_threads": [
                    {
                        "course": "15-213",
                        "title": "Lab 1 submission — do we need a Makefile?",
                        "type": "question",
                        "answered": True,
                        "created": "2024-09-14",
                    },
                    {
                        "course": "15-213",
                        "title": "Logistics: midterm location confirmed",
                        "type": "announcement",
                        "answered": False,
                        "created": "2024-09-13",
                    },
                    {
                        "course": "15-251",
                        "title": "PS2 Q3 — hint request",
                        "type": "question",
                        "answered": False,
                        "created": "2024-09-15",
                    },
                ],
            }
        ],
        "citations": [
            {
                "title": "Ed Discussion — example threads (not your real data)",
                "url": "",
                "snippet": "Example data — connect Ed in your profile to see your real discussion threads.",
                "indexed_at": None,
                "is_mock": True,
                "source": "ed_sample",
            }
        ],
    }


@register_tool(
    name="piazza_sample",
    description=(
        "Returns example Piazza posts for a CMU student. "
        "Only use this tool when the user has NOT connected Piazza. "
        "Always tell the user this is example data and that they can connect "
        "Piazza via their profile to see their real posts."
    ),
    json_schema={"type": "object", "properties": {}},
    mode="personal",
    is_mock=True,
    shadows=PIAZZA,
)
def piazza_sample() -> dict:
    return {
        "results": [
            {
                "classes": [
                    {"id": "cs213fall24", "name": "15-213 Fall 2024"},
                    {"id": "cs251fall24", "name": "15-251 Fall 2024"},
                ],
                "recent_posts": [
                    {
                        "class": "15-213",
                        "title": "Cache lab — is blocking required?",
                        "type": "question",
                        "resolved": True,
                        "created": "2024-09-12",
                    },
                    {
                        "class": "15-213",
                        "title": "Regrades for Exam 1 open until Friday",
                        "type": "instructor-note",
                        "resolved": False,
                        "created": "2024-09-11",
                    },
                    {
                        "class": "15-251",
                        "title": "Study group forming for PS3",
                        "type": "note",
                        "resolved": False,
                        "created": "2024-09-14",
                    },
                ],
            }
        ],
        "citations": [
            {
                "title": "Piazza — example posts (not your real data)",
                "url": "",
                "snippet": "Example data — connect Piazza in your profile to see your real posts.",
                "indexed_at": None,
                "is_mock": True,
                "source": "piazza_sample",
            }
        ],
    }


@register_tool(
    name="gradescope_sample",
    description=(
        "Returns example Gradescope assignments and grades for a CMU student. "
        "Only use this tool when the user has NOT connected Gradescope. "
        "Always tell the user this is example data and that they can connect "
        "Gradescope via their profile to see their real grades."
    ),
    json_schema={"type": "object", "properties": {}},
    mode="personal",
    is_mock=True,
    shadows=GRADESCOPE,
)
def gradescope_sample() -> dict:
    return {
        "results": [
            {
                "courses": [
                    {"id": 301, "name": "15-213 Introduction to Computer Systems"},
                    {"id": 302, "name": "15-251 Great Theoretical Ideas in CS"},
                ],
                "assignments": [
                    {
                        "course": "15-213",
                        "name": "Bomb Lab",
                        "score": 70,
                        "max_score": 70,
                        "status": "graded",
                        "due": "2024-09-10",
                    },
                    {
                        "course": "15-213",
                        "name": "Data Lab",
                        "score": None,
                        "max_score": 100,
                        "status": "upcoming",
                        "due": "2024-09-20",
                    },
                    {
                        "course": "15-251",
                        "name": "Problem Set 1",
                        "score": 45,
                        "max_score": 50,
                        "status": "graded",
                        "due": "2024-09-08",
                    },
                    {
                        "course": "15-251",
                        "name": "Problem Set 2",
                        "score": None,
                        "max_score": 50,
                        "status": "upcoming",
                        "due": "2024-09-22",
                    },
                ],
            }
        ],
        "citations": [
            {
                "title": "Gradescope — example assignments (not your real data)",
                "url": "",
                "snippet": "Example data — connect Gradescope in your profile to see your real grades.",
                "indexed_at": None,
                "is_mock": True,
                "source": "gradescope_sample",
            }
        ],
    }


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
