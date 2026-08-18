"""Demo-only cookie ingestion. Read this folder's README before touching it.

Registered by config/urls.py only when settings.DEBUG is true, so it does not
exist in a judge-facing build. It takes session cookies a browser extension
scraped from a tab we are already signed in to and stores them as the
connection's credential; apps/personal/tools.py injects them instead of calling
the library's login(), which is what gets us past Duo for a live demo.
"""

from __future__ import annotations

from apps.core.views import _session_id
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Provider, UserConnection

# Only the two providers whose libraries authenticate by session cookie. Canvas
# and Ed use a revocable token and have no business on this path (README).
COOKIE_PROVIDERS = frozenset({Provider.PIAZZA.value, Provider.GRADESCOPE.value})

# A cookie jar is bigger than a password but still small. Enough headroom for a
# handful of signed cookies, low enough that this cannot be used as storage.
_MAX_COOKIES = 25
_MAX_COOKIE_LENGTH = 8192


class DemoCookieSerializer(serializers.Serializer):
    """{provider, cookies: {name: value}} — the extension's POST body."""

    provider = serializers.ChoiceField(choices=sorted(COOKIE_PROVIDERS))
    cookies = serializers.JSONField(write_only=True)

    def validate_cookies(self, value):
        if not isinstance(value, dict) or not value:
            raise serializers.ValidationError("Expected a non-empty object of cookies.")
        if len(value) > _MAX_COOKIES:
            raise serializers.ValidationError("Too many cookies.")

        cleaned = {}
        for name, raw in value.items():
            if not isinstance(raw, str) or not raw.strip():
                raise serializers.ValidationError(f"Cookie {name!r} has no value.")
            if len(raw) > _MAX_COOKIE_LENGTH:
                raise serializers.ValidationError(f"Cookie {name!r} is too long.")
            cleaned[str(name)] = raw
        return cleaned


class DemoCookieConnectView(APIView):
    """POST /api/personal/demo/cookies/ — connect via captured session cookies.

    Same session scoping and same write-only credential discipline as the real
    endpoint: the cookies go in, and nothing here ever reads them back out.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request: Request) -> Response:
        session_id = _session_id(request)

        serializer = DemoCookieSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = serializer.validated_data["provider"]
        cookies = serializer.validated_data["cookies"]

        connection = UserConnection.objects.filter(
            session_id=session_id, provider=provider
        ).first() or UserConnection(session_id=session_id, provider=provider)
        connection.set_credential({"cookies": cookies})
        connection.save()

        # The same three-field shape the real connect endpoint returns, and for
        # the same reason: never the credential.
        return Response(
            {
                "provider": connection.provider,
                "connected_at": connection.connected_at,
                "last_sync_at": connection.last_sync_at,
            },
            status=status.HTTP_200_OK,
        )
