# B5, Step 0+1 — the connections contract and endpoint

Hand this to whoever (or whatever) builds it. Written to be pasted whole.

**The one-line version:** nothing in B5 is reachable yet — `POST
/api/connections/` and `DELETE /api/connections/{provider}/` don't exist
anywhere (`apps/core/urls.py` has no route, `apps/core/views.py` has no view
class). `UserConnection`, Fernet encryption, and per-session connector gating
are already built and correct; this is the missing front door to all of it.

---

## Read first, in order

1. This document.
2. `CLAUDE.md` — "Keeping the API contract in sync" (serializers.py ↔ types.ts).
3. `backend/apps/personal/models.py` — `UserConnection`, `Provider`.
4. `backend/apps/personal/crypto.py` — `encrypt`/`decrypt`. Read the
   docstring on `decrypt`: never log the return value, never put it in a
   response.
5. `backend/apps/personal/context.py` — `get_user_connectors`,
   `get_connector`, `require_connection`, `mark_synced`, **`disconnect`**
   (already does exactly what `DELETE` needs — read it before writing a new
   version).
6. `backend/apps/core/views.py` — `ThreadListView`/`ThreadDetailView` and
   `_session_id(request)`. This is the pattern to copy: session id from the
   `X-Session-Id` header, never the body or the URL.
7. `backend/apps/core/serializers.py` — how `MODES`/`ACCESS`/`TIERS` get
   imported from the apps that own them, at module level. Same pattern applies
   to importing `Provider` from `apps.personal.models` here.
8. `frontend/app/lib/api.ts` — `fetchThreads`/`saveThread`/`deleteThread`, for
   the header-setting pattern (`xhr.setRequestHeader('X-Session-Id', ...)`)
   and the `request<T>()` helper to build the new calls on top of.
9. `tasklist.md` B5 (the four boxes this closes) and PRD §7 (personal, the
   rules this enforces).

---

## The credential-shape problem, and the decision

`UserConnection.encrypted_token` is one `TextField`, and today's `set_token`/
`get_token` treat it as one raw string — fine for Canvas and Ed (one token
each), broken for Piazza and Gradescope (email **and** password). No existing
row depends on the current format — nothing in B5 has shipped yet — so this
is free to change now and expensive to change after `personal_search` exists.

**Decision: always store a JSON object, never a bare string.** Extend
`UserConnection` in `models.py`:

```python
import json

def set_credential(self, credential: dict) -> None:
    """Encrypt and store a credential dict. Does not save."""
    self.encrypted_token = encrypt(json.dumps(credential))

def get_credential(self) -> dict:
    """Decrypt and parse the stored credential."""
    return json.loads(decrypt(self.encrypted_token))

def get_token(self) -> str:
    """Convenience for single-token providers (Canvas, Ed)."""
    return self.get_credential()["token"]

def set_token(self, raw_token: str) -> None:
    """Convenience for single-token providers."""
    self.set_credential({"token": raw_token.strip()})
```

`get_token()`/`set_token()` keep working exactly as before for every existing
call site (`apps/personal/tools.py`'s Canvas stubs already call
`connection.get_token()`) — they're now convenience wrappers over the general
path. Piazza/Gradescope code calls `get_credential()` directly.

**Required keys per provider** — add next to `Provider` in `models.py`, one
place that knows the shape so the endpoint and the tools agree:

```python
CREDENTIAL_FIELDS: dict[str, tuple[str, ...]] = {
    Provider.CANVAS: ("token",),
    Provider.ED: ("token",),
    Provider.PIAZZA: ("email", "password"),
    Provider.GRADESCOPE: ("email", "password"),
}
```

Add `PIAZZA = "piazza", "Piazza"` and `GRADESCOPE = "gradescope",
"Gradescope"` to `Provider.choices` here too — this doc doesn't build the
Piazza/Gradescope tools themselves (see `docs/b5-piazza-gradescope.md`), but
the endpoint needs to accept them.

Leave `STELLIC` alone: its "credential" is an uploaded degree-audit JSON
file, not a login, and doesn't fit this shape. Out of scope for this doc —
don't try to design it here.

---

## The endpoint

`backend/apps/core/views.py`, following `ThreadListView`'s shape exactly
(`_session_id(request)`, no `authentication_classes`/`permission_classes`,
`APIView`):

```python
class ConnectionsView(APIView):
    """GET / POST /api/connections/ — what this session has connected, and
    connecting a new source.

    GET is not in tasklist B5's literal checklist but the settings UI (F4)
    needs it to render connected state on load — same reasoning as
    SourcesView existing at all. Added here rather than as a third doc.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request) -> Response:
        session_id = _session_id(request)
        connections = get_user_connectors(session_id)
        payload = {"connections": [_serialize_connection(c) for c in connections]}
        return Response(
            ConnectionListResponseSerializer(payload).data, status=status.HTTP_200_OK
        )

    def post(self, request: Request) -> Response:
        session_id = _session_id(request)
        serializer = ConnectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = serializer.validated_data["provider"]
        credential = serializer.validated_data["credential"]

        expected = CREDENTIAL_FIELDS[provider]
        missing = [k for k in expected if not credential.get(k)]
        if missing:
            raise serializers.ValidationError(
                {"credential": f"{provider} needs: {', '.join(expected)}. Missing: {', '.join(missing)}."}
            )

        connection, _created = UserConnection.objects.get_or_create(
            session_id=session_id, provider=provider
        )
        connection.set_credential(credential)
        connection.save(update_fields=["encrypted_token"])

        return Response(_serialize_connection(connection), status=status.HTTP_200_OK)


class ConnectionDetailView(APIView):
    """DELETE /api/connections/{provider}/ — disconnect a source.

    All the work is already in apps/personal/context.disconnect(): deletes the
    UserConnection row, which is the whole PRD §7 "disconnect deletes synced
    data" requirement — anything that ever stores synced data must FK to it
    with CASCADE, so there is nothing else to clean up here or in the future.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def delete(self, request: Request, provider: str) -> Response:
        session_id = _session_id(request)
        if not disconnect(session_id, provider):
            raise NotFound(f"No connection for {provider!r}.")
        return Response(status=status.HTTP_204_NO_CONTENT)


def _serialize_connection(connection: UserConnection) -> dict:
    """Never the credential. Not even shaped to accept one — see
    ConnectionSerializer.credential's write_only below."""
    return {
        "provider": connection.provider,
        "connected_at": connection.connected_at,
        "last_sync_at": connection.last_sync_at,
    }
```

Wire into `urls.py`:

```python
path("connections/", ConnectionsView.as_view(), name="connections"),
path("connections/<str:provider>/", ConnectionDetailView.as_view(), name="connection-detail"),
```

## Serializers

`backend/apps/core/serializers.py`, same top-of-file import pattern already
used for `MODES`/`ACCESS`/`TIERS`:

```python
from apps.personal.models import Provider

class ConnectionSerializer(serializers.Serializer):
    """POST /api/connections/ request, and (minus `credential`) the response."""

    provider = serializers.ChoiceField(choices=Provider.choices)
    # write_only: even if something upstream tried to echo this back, DRF
    # would drop it from the serialized output. Defense in depth on top of
    # _serialize_connection() simply never touching it.
    credential = serializers.JSONField(write_only=True)
    connected_at = serializers.DateTimeField(read_only=True, required=False)
    last_sync_at = serializers.DateTimeField(read_only=True, required=False, allow_null=True)


class ConnectionListResponseSerializer(serializers.Serializer):
    connections = ConnectionSerializer(many=True)
```

Response payloads should be validated through
`ConnectionSerializer(_serialize_connection(connection)).data` (or the list
variant) before returning, matching every other view in this file — don't
return a bare dict.

---

## Frontend: `frontend/app/lib/types.ts` + `frontend/app/lib/api.ts`

New types, matching the response shape above:

```typescript
export type Connection = {
  provider: 'canvas' | 'ed' | 'stellic' | 'piazza' | 'gradescope'
  connected_at: string
  last_sync_at: string | null
}

export type ConnectionListResponse = {
  connections: Connection[]
}
```

New calls in `api.ts`, alongside `fetchThreads`/`saveThread`/`deleteThread` —
same `request<T>()` helper, same `X-Session-Id` header:

```typescript
export function fetchConnections(): Promise<Connection[]> {
  return request<ConnectionListResponse>('/api/connections/').then(r => r.connections)
}

export function connect(provider: string, credential: Record<string, string>): Promise<Connection> {
  return request<Connection>('/api/connections/', {
    method: 'POST',
    body: JSON.stringify({ provider, credential }),
  })
}

export function disconnect(provider: string): Promise<void> {
  return request<void>(`/api/connections/${encodeURIComponent(provider)}/`, { method: 'DELETE' })
}
```

This doc doesn't build the settings screen itself (F4) — that's a separate
piece of work that can start the moment this contract is frozen, in parallel
with the Piazza/Gradescope tools (`docs/b5-piazza-gradescope.md`), since
neither depends on the other once this endpoint exists.

---

## Non-negotiables

- **Never return a credential.** `_serialize_connection` never touches it;
  `ConnectionSerializer.credential` is `write_only`. Both independently
  enforce PRD §9's "never returned by any endpoint" — keep both, don't treat
  one as redundant.
- **`X-Session-Id` header, never the body.** Matches every other
  session-scoped endpoint in this file. A session id is a bearer token
  (`apps/personal/models.py`'s own docstring) — it doesn't belong in a query
  string or a body that ends up in a log line.
- **Disconnect only ever calls `context.disconnect()`.** Don't hand-roll a
  second delete path — the CASCADE guarantee lives in that function's
  docstring being true, not in this view remembering to replicate it.
- **`get_token()`/`set_token()` keep their exact current signatures.** Canvas
  tool stubs already call `get_token()` — changing its return type or
  argument shape breaks code you didn't touch.

---

## How to verify

New tests in `backend/apps/core/tests.py` (or wherever `apps.core`'s test
file lives once one exists — check first, don't assume `apps/core/tests.py`
is empty).

- [ ] `POST /api/connections/` with a valid Canvas token creates a
      `UserConnection`; the response contains no `credential`/`token` key
      anywhere
- [ ] `POST /api/connections/` with a Piazza credential missing `password`
      is a 400, not a 500 or a silently-accepted partial credential
- [ ] Reconnecting the same provider updates the existing row rather than
      creating a second one (the model's `unique_connection_per_session_provider`
      constraint should make a duplicate impossible either way — test that
      too)
- [ ] `GET /api/connections/` never includes a credential field
- [ ] `DELETE /api/connections/{provider}/` on a real connection returns 204
      and the row is gone; on a nonexistent one returns 404
- [ ] Missing `X-Session-Id` header is a 400 on all three, same as
      `ThreadListView`
- [ ] `UserConnection.get_token()` still works against a row written with the
      old `set_token()` call shape — or confirm there's no data to migrate and
      skip this

```
docker compose exec backend python manage.py test apps.core
```

---

## Done when

- [ ] `GET`/`POST /api/connections/` and `DELETE /api/connections/{provider}/`
      all exist and are tested
- [ ] `Provider` includes `PIAZZA` and `GRADESCOPE`
- [ ] No response, ever, contains a credential
- [ ] `frontend/app/lib/types.ts` and `api.ts` have the matching client calls
- [ ] Boxes ticked in `tasklist.md` B5, same commit

## Style

Follow `CLAUDE.md`. Comments explain *why*, never what. If a comment could be
deleted without losing information, delete it.
