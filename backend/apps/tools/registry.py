"""The tool registry — one place that knows every capability the planner has.

A "tool" is a plain Python function (still directly callable and testable) plus
the JSON schema the LLM needs to call it. A registry rather than a hand-kept
list because the toolset is answered per request: personal tools only exist for
sessions that connected the source.

See PRD §3 for the modes and §10 for the rules `mode` / `is_mock` enforce.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

# Name, mode and latency per tool call (tasklist B0), so a slow upstream is
# visible in the logs rather than just felt.
logger = logging.getLogger(__name__)

# Fixed vocabulary for `modes_used`. Part of the API contract — changing one
# means changing tasklist §2 and frontend/app/lib/types.ts too.
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

    Upstream APIs go down mid-demo; we want a partial answer that says so, not a
    500 (tasklist B2: "degrade, don't crash the answer").
    """


@dataclass(frozen=True)
class Tool:
    """One registered capability, plus what the planner needs to use it."""

    name: str
    description: str
    json_schema: dict[str, Any]
    mode: str
    is_mock: bool
    #: Provider slug (e.g. "canvas") whose credential must exist for this tool
    #: to be offered. None means public and always available.
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

        `session_id` is only ever forwarded to connector-gated tools. That is the
        mechanical guarantee behind PRD §3's "never let personal data enter a
        shared-index call": a public tool cannot receive the session, so it
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
        description: written *for the model*, not for us — it is the main thing
            deciding whether the tool gets picked, so say when not to use it too.
        mode: one of MODES. Feeds `modes_used` so the UI can show which lanes ran.
        is_mock: True for fixture-backed tools. Every citation from a mock tool
            must carry `is_mock: true` (PRD §9 — non-negotiable).
        requires_connector: provider slug whose credential this tool needs. Such
            tools are hidden unless the session has connected it.
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
            # The dev server's autoreloader can import a module twice, so
            # re-registering the same function is fine; two different functions
            # fighting over one name is a bug.
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

    Sorted so the list handed to the model is byte-stable across requests; an
    unstable ordering would break prompt caching for no reason.
    """
    return sorted(_TOOLS.values(), key=lambda tool: tool.name)


def disabled_tools() -> frozenset[str]:
    """Tool names switched off by configuration.

    Read per call rather than cached, so switching one off is an env var and a
    restart. The Managed Agents API has no `enabled` flag for a custom tool — the
    built-in toolset has one, ours are on or off by being in the list — so this
    is where a per-tool switch has to live to reach anybody.

    A session's toolset is overridden per request and overrides replace in full,
    so this takes effect for students as soon as the backend restarts. Re-run
    `provision_planner` as well to drop the tool from the agent itself, which is
    what a session opened outside the request path sees.
    """
    from django.conf import settings

    return frozenset(getattr(settings, "PLANNER_DISABLED_TOOLS", ()) or ())


def tools_for_session(session_id: str | None) -> list[Tool]:
    """The tools this particular request is allowed to use.

    Public tools always; a personal tool only once the session has connected
    that provider; neither if it has been switched off. The load-bearing half of
    PRD §7: a tool the planner is never told about is a tool it cannot call.
    """
    off = disabled_tools()
    public = [tool for tool in all_tools() if not tool.is_personal and tool.name not in off]

    if not session_id:
        return public

    # Imported here, not at module scope: apps.personal imports this module to
    # register its tools, so a top-level import is circular.
    from apps.personal.context import get_user_connectors

    connected = {connector.provider for connector in get_user_connectors(session_id)}
    personal = [
        tool
        for tool in all_tools()
        if tool.is_personal and tool.requires_connector in connected and tool.name not in off
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

    `Tool.run` enforces that a public tool never sees the session; this adds the
    other half, refusing a personal tool unless the session really did connect
    that provider — so a model naming a tool it was never offered gets a
    ToolError, not someone else's data.

    Note what the model does *not* supply: it passes arguments, never whose data
    to read. `session_id` comes from the request, which is why cross-session
    leakage is impossible here rather than merely unlikely.
    """
    tool = get_tool(name)

    # Re-checked here and not only where the toolset is built, for the same
    # reason the connector is: a session opened before the switch was flipped is
    # still holding the old offer.
    if name in disabled_tools():
        raise ToolError(f"{name} is switched off.")

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
        # `arguments` is deliberately absent from both log lines: a personal
        # tool's arguments can carry identifying detail, and PRD §9 forbids
        # logging anything credential-shaped. Name plus latency is enough.
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

    Deriving `is_mock` from the producing tool means a mock tool cannot emit a
    citation that looks live — PRD §9 as code rather than as a convention.
    """
    return {"source": tool.name, "is_mock": tool.is_mock}


def modes_for(names: Iterable[str]) -> list[str]:
    """Map the tools that ran onto `modes_used`, de-duplicated.

    Ordered by MODES rather than call order, so two answers drawing on the same
    sources render their chips identically.
    """
    used = {tool.mode for name in names if (tool := _TOOLS.get(name)) is not None}
    return [mode for mode in MODES if mode in used]
