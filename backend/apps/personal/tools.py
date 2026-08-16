"""User-scoped tools, offered only to sessions that connected the source.

A session with no Canvas connection is never told these exist (see
`tools_for_session` in apps/tools/registry.py), so the model cannot call them or
mention data it has no business seeing.

The Canvas HTTP client is not wired yet (tasklist B5); the definitions are here
because the plumbing — registry, per-session gating, credential handoff — is
what §1 is about. Until then each function raises `ToolError`, the same path a
real Canvas outage takes, so degrade-don't-crash gets exercised either way.

When it is wired, `apps.core.http.get_json` is the client to use — but never
copy the `ttl=` from a public B2 call into it. That cache is keyed on url and
params only, so two students hitting the same Canvas endpoint with different
tokens would collide and one could be served the other's data (PRD §9). Caching
a personal response needs a key that includes the user.
"""

from __future__ import annotations

from apps.tools.registry import ToolError, register_tool

from .context import require_connection

# Passed as `requires_connector` below, which is what hides these tools from
# sessions that have not pasted a token.
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
    connection = _canvas_connection(session_id)
    _ = connection.get_token()
    raise ToolError(_NOT_WIRED)


def _canvas_connection(session_id: str):
    """Fetch this session's Canvas connection, as a ToolError if it is missing.

    The registry already gates personal tools on the connector, so finding
    nothing here means it was deleted mid-request. Re-raising as ToolError keeps
    every tool failure one exception type, which is what lets the planner
    degrade instead of 500ing.
    """
    try:
        return require_connection(session_id, CANVAS)
    except LookupError as exc:
        raise ToolError(str(exc)) from exc
