"""The API contract, in code.

This file and `frontend/app/lib/types.ts` describe the same JSON. Change one,
change the other, and update tasklist §2 where the contract is agreed.

The response serializers are not decoration: views validate outgoing payloads
through them, so a planner that forgets `indexed_at` or invents a mode fails
here rather than as a blank chip on someone's phone.
"""

from __future__ import annotations

from apps.tools.registry import MODES
from apps.tools.sources import ACCESS, TIERS
from rest_framework import serializers

# --- Request ------------------------------------------------------------------


class HistoryMessageSerializer(serializers.Serializer):
    """One earlier turn, so follow-up questions ("what about Friday?") work."""

    role = serializers.ChoiceField(choices=["user", "assistant"])
    content = serializers.CharField(allow_blank=True, trim_whitespace=False)


class AskSerializer(serializers.Serializer):
    """POST /api/ask/ request body."""

    query = serializers.CharField(max_length=2000)

    # Optional: public questions work without one. When present it is what
    # scopes personal connectors (see apps/personal/models.py).
    session_id = serializers.CharField(
        max_length=128,
        required=False,
        allow_blank=True,
        default="",
    )

    # Oldest first. Capped so a runaway client cannot push an unbounded
    # transcript through the planner's context window.
    history = serializers.ListField(
        child=HistoryMessageSerializer(),
        required=False,
        default=list,
        max_length=40,
    )


# --- Response -----------------------------------------------------------------


class CitationSerializer(serializers.Serializer):
    """Where one piece of the answer came from, and how fresh it is.

    PRD §3 and §9: sources carry `indexed_at` / `verified_at`, and fixtures are
    visibly marked. `is_mock` is what the UI badges, so it is required rather
    than defaulted — a citation that forgot it would claim to be real data.
    """

    # The planner's stable handle for this source ("S1"), and the only thing the
    # model ever writes about it — so it can neither invent a source nor relabel
    # a mock as live. Explicit rather than positional, so filtering the list
    # later cannot silently rebind every marker.
    id = serializers.CharField(allow_blank=True, default="")

    title = serializers.CharField()

    # Not URLField: mock sources legitimately have no link, and a deep link is
    # not always http(s). Empty string means "no link".
    url = serializers.CharField(allow_blank=True, default="")

    # The supporting excerpt, for a tap-to-open preview. "" when the tool has
    # nothing to quote — a preview showing only the title is pointless.
    snippet = serializers.CharField(allow_blank=True, default="")

    # Human-readable ("CMU Eats"), not the internal tool name — it goes on the
    # citation card.
    source = serializers.CharField()

    # DateTimeField renders a datetime as ISO-8601 and passes an existing string
    # through untouched, so a tool can return either.
    indexed_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    verified_at = serializers.DateTimeField(required=False, allow_null=True, default=None)

    is_mock = serializers.BooleanField()


class AskResponseSerializer(serializers.Serializer):
    """POST /api/ask/ response body."""

    answer = serializers.CharField(allow_blank=True, trim_whitespace=False)
    citations = CitationSerializer(many=True)

    # ChoiceField so a typo'd mode is a backend error, not a chip that silently
    # never renders.
    modes_used = serializers.ListField(child=serializers.ChoiceField(choices=MODES))

    # Caveats worth surfacing above the answer: a tool that timed out, mock data
    # in play, a stale index. null when there is nothing to flag.
    note = serializers.CharField(required=False, allow_null=True, allow_blank=True, default=None)


class SourceSerializer(serializers.Serializer):
    """One entry in GET /api/sources/ — powers the credits and freshness UI."""

    name = serializers.CharField()
    tier = serializers.ChoiceField(choices=TIERS)
    access = serializers.ChoiceField(choices=ACCESS)
    indexed_at = serializers.DateTimeField(required=False, allow_null=True, default=None)

    # Beyond the §2 contract and additive on purpose: the app can ignore both,
    # but the credits page uses them to say which lanes are still placeholders.
    implemented = serializers.BooleanField(default=False)
    note = serializers.CharField(allow_blank=True, default="")


class SourcesResponseSerializer(serializers.Serializer):
    """GET /api/sources/ response body."""

    sources = SourceSerializer(many=True)


# --- Threads ------------------------------------------------------------------


class MessageSerializer(serializers.Serializer):
    """One stored turn, in the shape assistant-ui hands us.

    `content` is a list of message *parts*, not a string — answer text plus one
    part per citation. See apps/core/models.Message.
    """

    role = serializers.ChoiceField(choices=["user", "assistant"])
    content = serializers.JSONField()

    def validate_content(self, value):
        # JSONField accepts any JSON, but the renderer crashes on anything that
        # is not a parts array. Failing at save time beats blanking someone's
        # sidebar the next time they open the app.
        if not isinstance(value, list):
            raise serializers.ValidationError("Expected a list of message parts.")
        return value


class ThreadSerializer(serializers.Serializer):
    """One thread, with its full message list. Used in both directions.

    `id` is the app's own thread id (`client_id` in the model), so the sidebar's
    ids survive a reload.
    """

    id = serializers.CharField(max_length=64)
    messages = MessageSerializer(many=True)
    updated_at = serializers.DateTimeField(read_only=True)


class ThreadListResponseSerializer(serializers.Serializer):
    """GET /api/threads/ response body."""

    threads = ThreadSerializer(many=True)
