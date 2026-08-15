"""User-scoped tools, offered only to sessions that connected the source.

These are the tools that make the difference between "when are CS office hours"
and "what's due this week" — and they are the reason the toolset is built per
request instead of once at startup. A session with no Canvas connection is never
told these exist (see `tools_for_session` in apps/tools/registry.py), so the
model cannot call them and cannot mention data it has no business seeing.

**The Canvas HTTP client is not wired yet — that is tasklist B5.** The tool
definitions live here now because the toolset plumbing is what §1 is about: the
registry, the per-session gating, and the credential handoff. Until the client
lands each function raises `ToolError`, which is the same path a real Canvas
outage takes, so the planner's degrade-don't-crash handling gets exercised
either way.
"""

from __future__ import annotations

from apps.tools.registry import ToolError, register_tool

from .context import require_connection

# Every tool here goes through Canvas, so they share one gate. `requires_connector`
# is what hides them from sessions that have not pasted a token.
CANVAS = "canvas"

_NOT_WIRED = (
    "The Canvas client is not implemented yet (tasklist B5). The connection is "
    "recognised and the token decrypts, but no request is made to Canvas."
)


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
    """The student's active Canvas courses."""
    connection = _canvas_connection(session_id)
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
    """The student's upcoming assignments and due dates."""
    connection = _canvas_connection(session_id)
    _ = connection.get_token()
    raise ToolError(_NOT_WIRED)


def _canvas_connection(session_id: str):
    """Fetch this session's Canvas connection, as a ToolError if it is missing.

    The registry already refuses to run a personal tool for a session that has
    not connected the provider, so reaching this and finding nothing means the
    connection was deleted mid-request. Re-raising as ToolError keeps every tool
    failure one exception type, which is what lets the planner degrade instead of
    500ing.
    """
    try:
        return require_connection(session_id, CANVAS)
    except LookupError as exc:
        raise ToolError(str(exc)) from exc
