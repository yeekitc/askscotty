"""The API endpoints. Shapes live in serializers.py, agreed in tasklist §2."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Iterator

from apps.planner.errors import PlannerError, as_api_exception
from apps.planner.loop import drain, run_planner
from apps.tools.sources import all_sources
from django.db import transaction
from django.http import StreamingHttpResponse
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .errors import code_for_status
from .models import Message, Thread
from .serializers import (
    AskSerializer,
    SourcesResponseSerializer,
    ThreadListResponseSerializer,
    ThreadSerializer,
)

logger = logging.getLogger(__name__)


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


def _planner_events(request: Request):
    """Validate an ask request and start the planner over it.

    Shared by both endpoints so they cannot drift: same request shape, same
    generator, same validated payload — one drains it, the other forwards it.
    """
    serializer = AskSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    return run_planner(
        serializer.validated_data["query"],
        session_id=serializer.validated_data["session_id"],
        thread_id=serializer.validated_data["thread_id"],
        history=serializer.validated_data["history"],
    )


class AskView(APIView):
    """POST /api/ask/ — the main endpoint.

    One request, one validated JSON answer. `POST /api/ask/stream/` returns the
    identical payload in its `done` event; this stays the fallback for anything
    that cannot read a stream.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request: Request) -> Response:
        try:
            payload = drain(_planner_events(request))
        except PlannerError as exc:
            raise as_api_exception(exc) from exc

        return Response(payload, status=status.HTTP_200_OK)


class AskStreamView(APIView):
    """POST /api/ask/stream/ — the same answer, plus progress events.

    POST rather than GET because the body carries `query` and `history`, and
    because `EventSource` is GET-only and does not exist on React Native anyway
    — the app reads frames off XHR's growing `responseText`.

    Strictly additive (tasklist §2): `mode_start` / `mode_end` drive the mode
    chips, and `done` carries the same validated `AskResponse` /api/ask/ returns.

    Worth knowing before this is deployed anywhere real: a gunicorn sync worker
    is held for the whole life of an open stream. Fine at demo scale.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request: Request) -> StreamingHttpResponse:
        response = StreamingHttpResponse(
            _sse(_planner_events(request)),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        # Proxies buffer by default, which turns progress events into one blob
        # delivered at the end.
        response["X-Accel-Buffering"] = "no"
        return response


def _sse(events) -> Iterator[str]:
    """Planner events as SSE frames.

    Every failure becomes an `error` frame rather than an HTTP status: by the
    time one happens the 200 and its headers are long gone. The body is the same
    `{"code", "message"}` shape every other endpoint returns, so the app has one
    error path. A stream that just stops would leave it waiting instead.
    """
    try:
        for event in events:
            yield _frame(event["type"], event["data"])
    except PlannerError as exc:
        yield _frame("error", {"code": code_for_status(exc.status_code), "message": str(exc)})
    except Exception:
        logger.exception("Unhandled error while streaming an answer")
        yield _frame("error", {"code": "error", "message": "Something went wrong."})


def _frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


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
