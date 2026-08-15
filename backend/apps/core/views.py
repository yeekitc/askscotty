"""The API endpoints.

Three of them: a health check, the ask endpoint, and the source registry that
powers the credits and freshness UI. Shapes are defined in serializers.py and
agreed in tasklist.md §2.
"""

from __future__ import annotations

from datetime import datetime, timezone

from apps.tools.registry import tools_for_session
from apps.tools.sources import all_sources
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Message, Thread
from .serializers import (
    AskResponseSerializer,
    AskSerializer,
    SourcesResponseSerializer,
    ThreadListResponseSerializer,
    ThreadSerializer,
)


class HealthView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request) -> Response:
        return Response(
            {
                "status": "ok",
                "service": "askscotty-backend",
                "time": datetime.now(timezone.utc).isoformat(),
            }
        )


class AskView(APIView):
    """POST /api/ask/ — the main endpoint.

    Non-streaming, by decision (tasklist §1): one request, one JSON answer. The
    app reports which modes ran from `modes_used` after the fact rather than
    live, which is enough for P0 and avoids agreeing an SSE format before the
    planner exists.

    The planner itself is tasklist B4. What is real here is the contract and the
    per-session toolset: `tools_for_session` returns the public tools plus any
    personal ones this session has connected, and that list is what B4 hands to
    the model.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request: Request) -> Response:
        serializer = AskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        query = serializer.validated_data["query"]
        session_id = serializer.validated_data["session_id"]
        history = serializer.validated_data["history"]

        # The toolset this request is allowed to use. Building it here rather
        # than inside the planner keeps the session-scoping decision in one
        # place — and makes it visible in the stub answer below, so the wiring
        # can be checked before B4 exists.
        tools = tools_for_session(session_id)
        personal_tools = [tool.name for tool in tools if tool.is_personal]

        answer = (
            f'Stub response for: "{query}". The API contract is live but the planner '
            f"is not wired yet (tasklist B4). This request had {len(tools)} tool(s) "
            "available"
        )
        if personal_tools:
            answer += f", including personal: {', '.join(personal_tools)}"
        answer += "."
        if history:
            answer += f" {len(history)} earlier turn(s) received."

        payload = {
            "answer": answer,
            "citations": [
                {
                    "title": "AskScotty build checklist",
                    "url": "",
                    "source": "AskScotty (stub)",
                    "indexed_at": None,
                    "verified_at": datetime.now(timezone.utc),
                    # Not live campus data, so it is badged like anything else
                    # that isn't. PRD §9 applies to our own placeholder too.
                    "is_mock": True,
                }
            ],
            # Nothing ran, so nothing is claimed. Filling this with a plausible
            # mode would make the demo look further along than it is.
            "modes_used": [],
            "note": "Demo stub — the planner is not wired up yet, so this is not live campus data.",
        }

        # Validated on the way out. When B4 replaces the stub, a malformed answer
        # fails here in the backend rather than rendering wrong in the app.
        response = AskResponseSerializer(data=payload)
        response.is_valid(raise_exception=True)
        return Response(response.validated_data, status=status.HTTP_200_OK)


class SourcesView(APIView):
    """GET /api/sources/ — what AskScotty draws on, and how fresh it is.

    Session-independent on purpose: it lists what the product *can* use, not what
    any particular person has connected, so there is nothing here to leak. The
    connectors UI asks a different question and gets its own endpoint (B5).
    """

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request) -> Response:
        payload = {
            "sources": [
                {
                    "name": source.name,
                    "tier": source.tier,
                    "access": source.access,
                    "indexed_at": source.indexed_at(),
                    "implemented": source.implemented,
                    "note": source.note,
                }
                for source in all_sources()
            ]
        }

        response = SourcesResponseSerializer(data=payload)
        response.is_valid(raise_exception=True)
        return Response(response.validated_data, status=status.HTTP_200_OK)


# --- Threads ------------------------------------------------------------------
#
# Chat history lives in our database rather than assistant-ui's hosted Cloud —
# see apps/core/models.py for why. Every endpoint below is scoped to one
# anonymous session (tasklist §1), the same way apps/personal scopes connectors.


def _session_id(request: Request) -> str:
    """The session this request belongs to, or a 400 explaining that it must.

    Read from a header rather than the URL on purpose: a session id is a bearer
    token (see apps/personal/models.py), and query strings end up in server
    logs and browser history. `session_id` in the /api/ask/ body is optional
    because public questions work without one; here it is required, because
    "whose threads?" has no sensible default.
    """
    session_id = request.headers.get("X-Session-Id", "").strip()
    if not session_id:
        raise serializers.ValidationError(
            {"session_id": "Missing X-Session-Id header."}
        )
    if len(session_id) > 128:
        raise serializers.ValidationError({"session_id": "Session id is too long."})
    return session_id


def _serialize_thread(thread: Thread) -> dict:
    """One thread in the shape the app stores it (see ThreadSerializer)."""
    return {
        "id": thread.client_id,
        "messages": [
            {"role": message.role, "content": message.content}
            # `.all()` rather than a fresh query so the prefetch in ThreadListView
            # is actually used — otherwise this is one query per thread.
            for message in thread.messages.all()
        ],
        "updated_at": thread.updated_at,
    }


class ThreadListView(APIView):
    """GET /api/threads/ — every thread for this session, newest first.

    Returns full message lists rather than just titles. The sidebar needs to be
    able to switch threads instantly, and at demo scale (tens of threads) one
    round trip beats a request per thread. If a session ever accumulates enough
    history for that to hurt, this is where pagination goes.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request) -> Response:
        session_id = _session_id(request)

        threads = Thread.objects.filter(session_id=session_id).prefetch_related(
            "messages"
        )

        payload = {"threads": [_serialize_thread(thread) for thread in threads]}
        # Same belt-and-braces as AskView: serialize the response so a shape
        # change here fails in the backend rather than in the app.
        return Response(
            ThreadListResponseSerializer(payload).data, status=status.HTTP_200_OK
        )


class ThreadDetailView(APIView):
    """PUT / DELETE /api/threads/{thread_id}/ — save or remove one thread.

    PUT is an upsert: the app owns thread ids and creates them locally the
    moment someone taps "New Chat", so the first save of a thread and every
    later one are the same request. That also matches how the screen already
    works — it mirrors the live thread's messages on every change rather than
    appending turn by turn.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def put(self, request: Request, thread_id: str) -> Response:
        session_id = _session_id(request)

        serializer = ThreadSerializer(data={**request.data, "id": thread_id})
        serializer.is_valid(raise_exception=True)
        messages = serializer.validated_data["messages"]

        # One transaction so a thread is never left half-written: readers see
        # either the old message list or the new one.
        with transaction.atomic():
            thread, _created = Thread.objects.get_or_create(
                session_id=session_id, client_id=thread_id
            )

            # Replace rather than diff. The app sends the whole thread every
            # time, and message ids are not stable across an edit or a branch,
            # so "delete and rewrite" is both simpler and more correct here.
            thread.messages.all().delete()
            Message.objects.bulk_create(
                [
                    Message(
                        thread=thread,
                        role=message["role"],
                        content=message["content"],
                        position=position,
                    )
                    for position, message in enumerate(messages)
                ]
            )

            # get_or_create already set updated_at on insert, but an update to
            # an existing thread has not touched the row itself — save it so the
            # sidebar's ordering reflects the new activity.
            thread.save(update_fields=["updated_at"])

        thread.refresh_from_db()
        return Response(
            ThreadSerializer(_serialize_thread(thread)).data, status=status.HTTP_200_OK
        )

    def delete(self, request: Request, thread_id: str) -> Response:
        session_id = _session_id(request)

        # Filtered by session as well as id, so a guessed thread id from another
        # session deletes nothing rather than someone else's conversation.
        deleted, _ = Thread.objects.filter(
            session_id=session_id, client_id=thread_id
        ).delete()

        if not deleted:
            raise NotFound("No such thread for this session.")

        # Messages go with it via the CASCADE on Message.thread.
        return Response(status=status.HTTP_204_NO_CONTENT)
