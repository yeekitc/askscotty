"""Loading a session's personal context.

The planner asks one question at the start of every request: "what has this
person connected?" The answer decides which user-scoped tools get added to the
toolset for that request (see apps.tools.registry.tools_for_session).

Every query in this module filters on `session_id`. That is not a convention —
it is the only thing standing between two students' data, so there is
deliberately no function here that returns connections without a session.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from .models import UserConnection

logger = logging.getLogger(__name__)


def get_user_connectors(session_id: str | None) -> list[UserConnection]:
    """Every source this session has connected.

    Returns an empty list for an anonymous request rather than raising, because
    "no connectors" is the normal case: AskScotty answers public questions fine
    before anyone connects anything, and the planner simply gets the public
    toolset.
    """
    if not session_id:
        return []

    return list(UserConnection.objects.filter(session_id=session_id))


def get_connector(session_id: str, provider: str) -> UserConnection | None:
    """One connection, or None. The lookup personal tools use.

    Both arguments are required and both are in the filter, so there is no way
    to call this and accidentally get someone else's row.
    """
    if not session_id:
        return None

    return UserConnection.objects.filter(session_id=session_id, provider=provider).first()


def require_connection(session_id: str, provider: str) -> UserConnection:
    """Fetch a connection, or say clearly why there isn't one.

    Personal tools call this so a missing connector surfaces as one readable
    sentence the planner can act on, rather than an AttributeError on None a few
    frames later. Raises LookupError; tools translate that into a ToolError so
    every tool failure the planner sees is one exception type.
    """
    connection = get_connector(session_id, provider)
    if connection is None:
        raise LookupError(
            f"This session has not connected {provider}. "
            "Ask the user to connect it in settings, then try again."
        )
    return connection


def mark_synced(connection: UserConnection) -> None:
    """Record that we just pulled from this source, for the connectors UI."""
    connection.last_sync_at = timezone.now()
    connection.save(update_fields=["last_sync_at"])


def disconnect(session_id: str, provider: str) -> bool:
    """Disconnect a source and delete everything synced from it.

    PRD §7 requires that disconnecting deletes the data, not just the token.
    Deleting the UserConnection row is the whole implementation: any model
    holding synced data must FK to it with `on_delete=models.CASCADE`, so the
    database enforces this rather than a future maintainer remembering to.

    Returns True if something was disconnected.
    """
    if not session_id:
        return False

    deleted, _ = UserConnection.objects.filter(
        session_id=session_id, provider=provider
    ).delete()

    if deleted:
        # Provider and session only — never the token, and never the row's contents.
        logger.info(
            "connector_disconnected provider=%s session=%s…", provider, session_id[:8]
        )

    return bool(deleted)
