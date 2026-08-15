"""The API contract, in code.

This file and `frontend/app/lib/types.ts` describe the same JSON. Change one,
change the other — and update tasklist.md §2, which is where the contract is
agreed. Frontend and backend both code against §2, so it moves only on purpose.

The response serializers are not decoration. `AskView` runs its payload through
`AskResponseSerializer` before returning it, so a planner that forgets
`indexed_at` or invents a mode fails here, in the backend, rather than showing up
as a blank chip on someone's phone during the demo.
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

    # The anonymous session this question belongs to. Optional: public questions
    # work without one. When present it is what scopes personal connectors — see
    # apps/personal/models.py for what that does and does not guarantee.
    session_id = serializers.CharField(
        max_length=128,
        required=False,
        allow_blank=True,
        default="",
    )

    # Prior turns, oldest first. Capped so a runaway client cannot push an
    # unbounded transcript through the planner's context window.
    history = serializers.ListField(
        child=HistoryMessageSerializer(),
        required=False,
        default=list,
        max_length=40,
    )


# --- Response -----------------------------------------------------------------


class CitationSerializer(serializers.Serializer):
    """Where one piece of the answer came from, and how fresh it is.

    PRD §3 and §9: every answer shows its sources with `indexed_at` /
    `verified_at`, and anything from a fixture is visibly marked. `is_mock` is
    what the UI badges, so it is required rather than defaulted — a citation that
    forgot it would silently claim to be real data.
    """

    title = serializers.CharField()

    # Not URLField: mock sources legitimately have no link, and a deep link is
    # not always http(s). Empty string means "no link", which the app renders as
    # plain text instead of a tappable card.
    url = serializers.CharField(allow_blank=True, default="")

    # Human-readable, e.g. "CMU Eats" or "Campus maps (mock)" — this is what
    # shows on the citation card, so it is not the internal tool name.
    source = serializers.CharField()

    # DateTimeField renders a datetime as ISO-8601 and passes an existing string
    # through untouched, so a tool can return either and the wire format still
    # matches what the app parses.
    indexed_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    verified_at = serializers.DateTimeField(required=False, allow_null=True, default=None)

    is_mock = serializers.BooleanField()


class AskResponseSerializer(serializers.Serializer):
    """POST /api/ask/ response body."""

    answer = serializers.CharField(allow_blank=True, trim_whitespace=False)
    citations = CitationSerializer(many=True)

    # Fixed vocabulary, defined once in apps/tools/registry.py. ChoiceField means
    # a typo'd mode is a backend error, not a chip that silently never renders.
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

    # Beyond the §2 contract, and additive on purpose: the app can ignore both,
    # but the credits page reads much better when it can say what a source gives
    # us and which lanes are still placeholders.
    implemented = serializers.BooleanField(default=False)
    note = serializers.CharField(allow_blank=True, default="")


class SourcesResponseSerializer(serializers.Serializer):
    """GET /api/sources/ response body."""

    sources = SourceSerializer(many=True)


# --- Threads ------------------------------------------------------------------


class MessageSerializer(serializers.Serializer):
    """One stored turn, in the shape assistant-ui hands us.

    `content` is a list of message *parts*, not a string — an assistant turn is
    its answer text plus one part per citation. See apps/core/models.Message.
    """

    role = serializers.ChoiceField(choices=["user", "assistant"])
    content = serializers.JSONField()

    def validate_content(self, value):
        # JSONField accepts any JSON, but the app always sends a parts array and
        # the renderer will crash on anything else. Rejecting it here means a
        # malformed thread fails at save time with a clear message, rather than
        # blanking someone's sidebar the next time they open the app.
        if not isinstance(value, list):
            raise serializers.ValidationError("Expected a list of message parts.")
        return value


class ThreadSerializer(serializers.Serializer):
    """One thread, with its full message list.

    Used for both directions: the app PUTs this shape to save a thread, and
    reads it back on load. `id` is the app's own thread id (`client_id` in the
    model) so the sidebar's ids survive a reload.
    """

    id = serializers.CharField(max_length=64)
    messages = MessageSerializer(many=True)
    updated_at = serializers.DateTimeField(read_only=True)


class ThreadListResponseSerializer(serializers.Serializer):
    """GET /api/threads/ response body."""

    threads = ThreadSerializer(many=True)
