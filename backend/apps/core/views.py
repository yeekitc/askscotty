"""The API endpoints. Shapes live in serializers.py, agreed in tasklist §2."""

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

    Non-streaming by decision (tasklist §1): one request, one JSON answer, so we
    do not have to agree an SSE format before the planner exists. The planner is
    tasklist B4; the contract and the per-session toolset are real already.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request: Request) -> Response:
        serializer = AskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        query = serializer.validated_data["query"]
        session_id = serializer.validated_data["session_id"]
        history = serializer.validated_data["history"]

        # Built here rather than inside the planner so the session-scoping
        # decision lives in one place.
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
                    # PRD §9 applies to our own placeholder too.
                    "is_mock": True,
                }
            ],
            # Nothing ran, so nothing is claimed.
            "modes_used": [],
            "note": "Demo stub — the planner is not wired up yet, so this is not live campus data.",
        }

        # Validated on the way out: a malformed answer fails here rather than
        # rendering wrong in the app.
        response = AskResponseSerializer(data=payload)
        response.is_valid(raise_exception=True)
        return Response(response.validated_data, status=status.HTTP_200_OK)


class SourcesView(APIView):
    """GET /api/sources/ — what AskScotty draws on, and how fresh it is.

    Session-independent on purpose: it lists what the product *can* use, not what
    anyone has connected, so there is nothing here to leak. The connectors UI
    gets its own endpoint (B5).
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
# anonymous session (tasklist §1).


def _session_id(request: Request) -> str:
    """The session this request belongs to, or a 400 explaining that it must.

    Read from a header rather than the URL on purpose: a session id is a bearer
    token (see apps/personal/models.py), and query strings end up in server logs
    and browser history. Required here, unlike in the /api/ask/ body, because
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
    return {
        "id": thread.client_id,
        "messages": [
            {"role": message.role, "content": message.content}
            # `.all()` rather than a fresh query so ThreadListView's prefetch is
            # actually used — otherwise this is one query per thread.
            for message in thread.messages.all()
        ],
        "updated_at": thread.updated_at,
    }


class ThreadListView(APIView):
    """GET /api/threads/ — every thread for this session, newest first.

    Returns full message lists, not just titles, so the sidebar can switch
    threads instantly: at demo scale one round trip beats a request per thread.
    Pagination goes here if a session ever accumulates enough history to hurt.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request) -> Response:
        session_id = _session_id(request)

        threads = Thread.objects.filter(session_id=session_id).prefetch_related(
            "messages"
        )

        payload = {"threads": [_serialize_thread(thread) for thread in threads]}
        return Response(
            ThreadListResponseSerializer(payload).data, status=status.HTTP_200_OK
        )


class ThreadDetailView(APIView):
    """PUT / DELETE /api/threads/{thread_id}/ — save or remove one thread.

    PUT is an upsert: the app owns thread ids and creates them locally the moment
    someone taps "New Chat", so the first save and every later one are the same
    request, mirroring the whole thread rather than appending turn by turn.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def put(self, request: Request, thread_id: str) -> Response:
        session_id = _session_id(request)

        serializer = ThreadSerializer(data={**request.data, "id": thread_id})
        serializer.is_valid(raise_exception=True)
        messages = serializer.validated_data["messages"]

        # Readers see either the old message list or the new one, never a
        # half-written thread.
        with transaction.atomic():
            thread, _created = Thread.objects.get_or_create(
                session_id=session_id, client_id=thread_id
            )

            # Replace rather than diff: the app sends the whole thread every
            # time, and message ids are not stable across an edit or a branch.
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

            # Rewriting messages does not touch the thread row, so auto_now
            # would not fire and the sidebar's ordering would go stale.
            thread.save(update_fields=["updated_at"])

        thread.refresh_from_db()
        return Response(
            ThreadSerializer(_serialize_thread(thread)).data, status=status.HTTP_200_OK
        )

    def delete(self, request: Request, thread_id: str) -> Response:
        session_id = _session_id(request)

        # Filtered by session as well as id, so a guessed thread id deletes
        # nothing rather than someone else's conversation.
        deleted, _ = Thread.objects.filter(
            session_id=session_id, client_id=thread_id
        ).delete()

        if not deleted:
            raise NotFound("No such thread for this session.")

        # Messages go with it via the CASCADE on Message.thread.
        return Response(status=status.HTTP_204_NO_CONTENT)
