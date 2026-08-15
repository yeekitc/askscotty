"""The tool registry — one place that knows every capability the planner has.

A "tool" is a plain Python function plus the JSON schema the LLM needs in order
to call it. Decorating a function with @register_tool does two things at once:

1. it stays an ordinary function you can call and unit-test directly, and
2. it becomes something the planner can hand to the model as a tool definition.

Why a registry rather than a hand-maintained list: the planner has to answer
"what can I do for *this* request?" on every call, because personal tools
(Canvas, Ed, …) only exist when that session has connected the source. Keeping
the answer in one place means nobody has to remember to update a second list.

See PRD §3 for the four modes and §10 for the rules the `mode` / `is_mock`
fields exist to enforce.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

# Every tool call is logged with name, mode and latency (tasklist B0) so the
# demo can show which lanes actually ran, and so a slow upstream API is obvious
# in `docker compose logs -f backend` rather than just feeling slow.
logger = logging.getLogger(__name__)

# The fixed vocabulary for `modes_used` in the /api/ask/ response. The frontend
# renders one chip per mode, so these strings are part of the API contract —
# changing one means changing tasklist.md §2 and frontend/app/lib/types.ts too.
MODES: tuple[str, ...] = (
    "rag",
    "courses",
    "dining",
    "events",
    "maps",
    "web_verify",
    "personal",
)


class ToolError(Exception):
    """A tool failed in a way the planner should report, not crash on.

    Upstream APIs go down mid-demo. When they do we want a partial answer that
    says so, not a 500 (tasklist B2: "degrade, don't crash the answer").
    """


@dataclass(frozen=True)
class Tool:
    """One registered capability, plus everything the planner needs to use it."""

    name: str
    description: str
    json_schema: dict[str, Any]
    mode: str
    is_mock: bool
    #: Provider slug (e.g. "canvas") whose credential must exist for this tool
    #: to be offered. None means the tool is public and always available.
    requires_connector: str | None
    func: Callable[..., Any] = field(compare=False, repr=False)

    @property
    def is_personal(self) -> bool:
        return self.requires_connector is not None

    def definition(self) -> dict[str, Any]:
        """The shape Anthropic's tool-use API expects."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.json_schema,
        }

    def run(self, arguments: dict[str, Any], *, session_id: str | None = None) -> Any:
        """Call the underlying function with the model's arguments.

        `session_id` is only ever forwarded to connector-gated tools. That is
        the mechanical guarantee behind PRD §3's "never let personal data enter
        a shared-index call": a public tool cannot receive the session, so it
        cannot look up anything user-scoped even by accident.
        """
        if self.requires_connector is None:
            return self.func(**arguments)

        if not session_id:
            raise ToolError(
                f"{self.name} is user-scoped and needs a session_id, but none was given."
            )
        return self.func(session_id=session_id, **arguments)


# name -> Tool. Populated at import time by the decorator below.
_TOOLS: dict[str, Tool] = {}


def register_tool(
    name: str,
    description: str,
    json_schema: dict[str, Any],
    mode: str,
    is_mock: bool = False,
    *,
    requires_connector: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a function as a tool the planner can call.

    Args:
        name: what the model calls it. Snake case, matches the function name.
        description: written *for the model*, not for us — this is the main
            thing that decides whether the tool gets picked, so say when to use
            it and when not to.
        json_schema: JSON Schema object describing the arguments.
        mode: one of MODES. Feeds `modes_used` in the response so the UI can
            show which lanes actually ran.
        is_mock: True for fixture-backed tools. Every citation produced by a
            mock tool must carry `is_mock: true` (PRD §9 — non-negotiable).
        requires_connector: provider slug whose credential this tool needs.
            Tools with this set are hidden unless the session has connected it.

    Usage::

        @register_tool(
            name="find_dining",
            description="Find campus dining locations open at a given time.",
            json_schema={
                "type": "object",
                "properties": {"open_at": {"type": "string"}},
                "required": [],
            },
            mode="dining",
        )
        def find_dining(open_at: str | None = None) -> dict:
            ...
    """
    if mode not in MODES:
        raise ValueError(f"Unknown mode {mode!r} for tool {name!r}. Expected one of {MODES}.")
    if not isinstance(json_schema, dict) or json_schema.get("type") != "object":
        raise ValueError(
            f"Tool {name!r} needs a JSON Schema object "
            '(e.g. {"type": "object", "properties": {...}}).'
        )

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        existing = _TOOLS.get(name)
        origin = f"{func.__module__}.{func.__qualname__}"
        if existing is not None:
            existing_origin = f"{existing.func.__module__}.{existing.func.__qualname__}"
            # Django can import a module twice under the dev server's autoreloader.
            # Re-registering the same function is fine; two different functions
            # fighting over one name is a bug we want to hear about immediately.
            if existing_origin != origin:
                raise ValueError(
                    f"Tool {name!r} is already registered by {existing_origin}; "
                    f"{origin} tried to take the same name."
                )

        _TOOLS[name] = Tool(
            name=name,
            description=description,
            json_schema=json_schema,
            mode=mode,
            is_mock=is_mock,
            requires_connector=requires_connector,
            func=func,
        )
        return func

    return decorator


def get_tool(name: str) -> Tool:
    """Look up one tool by name. Raises ToolError if the model invents a name."""
    try:
        return _TOOLS[name]
    except KeyError:
        raise ToolError(f"No tool named {name!r} is registered.") from None


def all_tools() -> list[Tool]:
    """Every registered tool, public and personal, sorted by name.

    Sorted so the tool list handed to the model is byte-stable across requests —
    an unstable ordering would break prompt caching for no reason.
    """
    return sorted(_TOOLS.values(), key=lambda tool: tool.name)


def tools_for_session(session_id: str | None) -> list[Tool]:
    """The tools this particular request is allowed to use.

    Public tools always; a personal tool only once the session has actually
    connected that provider. An anonymous request (no session_id) gets the
    public set, which is why the app is useful before anyone connects anything.

    This is the load-bearing half of PRD §7: a tool the planner is never told
    about is a tool it cannot call.
    """
    public = [tool for tool in all_tools() if not tool.is_personal]

    if not session_id:
        return public

    # Imported inside the function, not at module scope: apps.personal imports
    # this module to register its tools, so a top-level import is circular.
    from apps.personal.context import get_user_connectors

    connected = {connector.provider for connector in get_user_connectors(session_id)}
    personal = [
        tool
        for tool in all_tools()
        if tool.is_personal and tool.requires_connector in connected
    ]

    return public + personal


def tool_definitions(session_id: str | None = None) -> list[dict[str, Any]]:
    """The `tools` array to hand the planner, scoped to this session."""
    return [tool.definition() for tool in tools_for_session(session_id)]


def run_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    session_id: str | None = None,
) -> Any:
    """Execute a tool on the planner's behalf. The only sanctioned entry point.

    `Tool.run` enforces that a public tool never sees the session. This adds the
    other half: a *personal* tool is refused unless this session has genuinely
    connected that provider — so even if the model names a tool it was never
    offered, it gets a ToolError rather than someone else's data.

    Note what is *not* passed in: the model supplies the tool's arguments, but
    never says whose data to read. `session_id` comes from the request, and
    `Tool.run` injects it. That is the mechanical reason cross-session leakage
    is not possible here, rather than merely unlikely.
    """
    tool = get_tool(name)

    if tool.is_personal:
        if not session_id:
            raise ToolError(f"{name} is user-scoped and needs a session_id, but none was given.")

        from apps.personal.context import get_user_connectors

        connected = {connector.provider for connector in get_user_connectors(session_id)}
        if tool.requires_connector not in connected:
            raise ToolError(
                f"{name} needs the {tool.requires_connector} connector, "
                "which this session has not connected."
            )

    started = time.monotonic()
    try:
        result = tool.run(arguments, session_id=session_id)
    except Exception:
        # Note the absence of `arguments` in both log lines. A personal tool's
        # arguments can carry identifying detail, and PRD §9 forbids logging
        # anything credential-shaped. Name plus latency is enough to debug.
        logger.exception(
            "tool_call name=%s mode=%s outcome=error latency_ms=%.0f",
            name,
            tool.mode,
            (time.monotonic() - started) * 1000,
        )
        raise

    logger.info(
        "tool_call name=%s mode=%s personal=%s is_mock=%s outcome=ok latency_ms=%.0f",
        name,
        tool.mode,
        tool.is_personal,
        tool.is_mock,
        (time.monotonic() - started) * 1000,
    )
    return result


def citation_defaults(tool: Tool) -> dict[str, Any]:
    """Citation fields a tool shouldn't have to remember to set itself.

    Deriving `is_mock` from the tool that produced the result means a mock tool
    physically cannot emit a citation that looks live — which is what PRD §9
    asks for, expressed as code rather than as a convention people follow.
    """
    return {"source": tool.name, "is_mock": tool.is_mock}


def modes_for(names: Iterable[str]) -> list[str]:
    """Map the tools that ran onto `modes_used`, de-duplicated.

    Ordered by MODES rather than by call order, so two answers drawing on the
    same sources render their chips in the same order.
    """
    used = {tool.mode for name in names if (tool := _TOOLS.get(name)) is not None}
    return [mode for mode in MODES if mode in used]
