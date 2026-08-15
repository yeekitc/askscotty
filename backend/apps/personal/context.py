"""What has this session connected? — the answer that decides which user-scoped
tools join the toolset (see apps.tools.registry.tools_for_session).

Every query here filters on `session_id`. That filter is the only thing standing
between two students' data, so there is deliberately no function in this module
that returns connections without a session.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from .models import UserConnection

logger = logging.getLogger(__name__)


def get_user_connectors(session_id: str | None) -> list[UserConnection]:
    """Every source this session has connected.

    Empty list rather than an error for an anonymous request: "no connectors" is
    the normal case, and the planner just gets the public toolset.
    """
    if not session_id:
        return []

    return list(UserConnection.objects.filter(session_id=session_id))


def get_connector(session_id: str, provider: str) -> UserConnection | None:
    """One connection, or None.

    Both arguments are required and both are in the filter, so there is no way
    to call this and accidentally get someone else's row.
    """
    if not session_id:
        return None

    return UserConnection.objects.filter(session_id=session_id, provider=provider).first()


def require_connection(session_id: str, provider: str) -> UserConnection:
    """Fetch a connection, or say clearly why there isn't one.

    A missing connector surfaces as one sentence the planner can act on, rather
    than an AttributeError on None a few frames later. Tools translate the
    LookupError into a ToolError.
    """
    connection = get_connector(session_id, provider)
    if connection is None:
        raise LookupError(
            f"This session has not connected {provider}. "
            "Ask the user to connect it in settings, then try again."
        )
    return connection


def mark_synced(connection: UserConnection) -> None:
    connection.last_sync_at = timezone.now()
    connection.save(update_fields=["last_sync_at"])


def disconnect(session_id: str, provider: str) -> bool:
    """Disconnect a source and delete everything synced from it.

    PRD §7: disconnecting deletes the data, not just the token. Deleting the
    UserConnection row is the whole implementation — any model holding synced
    data must FK to it with `on_delete=models.CASCADE`, so the database enforces
    this rather than a future maintainer remembering to.
    """
    if not session_id:
        return False

    deleted, _ = UserConnection.objects.filter(
        session_id=session_id, provider=provider
    ).delete()

    if deleted:
        # Provider and truncated session only — never the token.
        logger.info(
            "connector_disconnected provider=%s session=%s…", provider, session_id[:8]
        )

    return bool(deleted)
