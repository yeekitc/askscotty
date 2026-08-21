# B5, Step 0+1 — the connections contract and endpoint

The front door to every personal source: `GET`/`POST /api/connections/` and
`DELETE /api/connections/{provider}/`, on top of `UserConnection`, Fernet
encryption at rest, and per-session connector gating.

The tools that spend these credentials live in
[b5-canvas-ed-stellic.md](./b5-canvas-ed-stellic.md) (Canvas, Ed, Stellic) and
[b5-piazza-gradescope.md](./b5-piazza-gradescope.md) (Piazza, Gradescope —
read that one for the password trade-off those two carry).

---

## The rules this enforces — PRD §7 and §9

- **Credentials are encrypted at rest, never logged, never returned by any
  endpoint.**
- **Everything is scoped to one `session_id`.** One session can neither read
  nor disconnect another's sources.
- **Disconnecting deletes that source's synced data** along with the
  credential.
- **Personal data never enters the shared vector index.** Nothing here is
  crawled, embedded, or shared; personal sources are read live, per session,
  per request.

---

## Read first

1. `backend/apps/personal/models.py` — `UserConnection`, `Provider`,
   `CREDENTIAL_FIELDS`.
2. `backend/apps/personal/crypto.py` — `encrypt`/`decrypt`, and the docstring
   on `decrypt`: never log the return value, never put it in a response.
3. `backend/apps/personal/context.py` — `get_user_connectors`, `get_connector`,
   `require_connection`, `mark_synced`, **`disconnect`** (already does exactly
   what `DELETE` needs; don't write a second version).
4. `backend/apps/core/views.py` — `ThreadListView` and `_session_id(request)`:
   session id comes from the `X-Session-Id` header, never the body or the URL.
5. `CLAUDE.md` — "Keeping the API contract in sync" (`serializers.py` ↔
   `types.ts`).

---

## Credential shape

`UserConnection.encrypted_token` is one `TextField` holding Fernet ciphertext
of a JSON object — **always an object, never a bare string.** Canvas and Ed
hand over a single token; Piazza and Gradescope need an email *and* a
password, and one stored shape means the endpoint and the tools never have to
ask which kind of provider they are holding.

`set_credential()`/`get_credential()` are the general path;
`set_token()`/`get_token()` are convenience wrappers for the single-token
providers. A decrypted credential stays local to the function that read it:
never logged, never attached to an exception, never returned.

`CREDENTIAL_FIELDS` is the one place that knows what each provider needs, so
the endpoint and the tools cannot disagree. **A provider absent from that map
cannot be connected at all.**

| provider | required keys |
|---|---|
| `canvas` | `token` |
| `ed` | `token` |
| `piazza` | `email`, `password` |
| `gradescope` | `email`, `password` |
| `stellic` | *(none)* |

Stellic maps to no required keys: it is a mock with nothing to authenticate
([b5-canvas-ed-stellic.md](./b5-canvas-ed-stellic.md) Part C), but it still
connects — with an empty credential — so the settings UI can toggle it like
any other source instead of special-casing it.

## When a source is not connected

A session that has not connected a provider is never told its tools exist
(`tools_for_session` in `backend/apps/tools/registry.py`), so the model can
neither call them nor mention data it has no business seeing. Each provider
also has a demo stand-in — `canvas_sample`, `ed_sample`, `piazza_sample`,
`gradescope_sample` — offered *only* while the real provider is disconnected
(`shadows=`). They take no `session_id`, so no personal data reaches them, and
every citation they produce carries `is_mock=True`. Note that the app does not
yet render a badge for it — see PRD §9 in [architecture.md](./architecture.md).

---

## The endpoint

`ConnectionsView` and `ConnectionDetailView` in `backend/apps/core/views.py`,
following `ThreadListView`'s shape: `APIView`, no
`authentication_classes`/`permission_classes`, session id from
`_session_id(request)`.

- **`GET`** lists this session's connections. Not in tasklist B5's literal
  checklist, but the settings UI needs it to render connected state on load —
  the same reason `SourcesView` exists.
- **`POST`** validates, then encrypts *before* the row is written: inserting
  first would leave a row holding an empty credential if encryption raised,
  and every later `get_credential()` on it would fail with no way to tell why.
  Reconnecting rewrites the existing row rather than leaving a stale
  credential behind, which the model's
  `unique_connection_per_session_provider` constraint requires anyway.
- **`DELETE`** delegates entirely to `context.disconnect()`. That function
  deletes the `UserConnection` row, which is the whole of PRD §7's
  "disconnecting deletes the synced data" — anything that ever stores synced
  data must FK to that row with `CASCADE`, so there is nothing else to clean
  up here, now or later. A provider with no connection is a 404.

## Serializers

`ConnectionSerializer` in `backend/apps/core/serializers.py` carries the
request and — minus `credential` — the response:

- `credential` is `write_only`. Even if something upstream tried to echo it
  back, DRF drops it from the serialized output. That is defence in depth on
  top of `_serialize_connection()` simply never touching it (PRD §9). **Keep
  both; neither is redundant.**
- `validate_credential` rejects a non-object, so a bare string or list is a
  400 rather than an `AttributeError` 500 in the per-provider key check.
- `validate()` holds the `CREDENTIAL_FIELDS` check. It is cross-field —
  `credential` is only meaningful against a `provider` — so it belongs on the
  serializer, not in the view.

## Frontend

`frontend/app/lib/types.ts` mirrors the response shape (`Connection`,
`ConnectionListResponse`); `frontend/app/lib/api.ts` has `fetchConnections`,
`connect` and `disconnect` built on the same `request<T>()` helper and
`X-Session-Id` header as `fetchThreads`/`saveThread`/`deleteThread`;
`frontend/app/components/ConnectionsModal.tsx` renders it. Per-provider copy
— including the warning Piazza and Gradescope must carry — is specified in
[b5-piazza-gradescope.md](./b5-piazza-gradescope.md).

---

## Non-negotiables

- **Never return a credential.** `_serialize_connection` never touches it;
  `ConnectionSerializer.credential` is `write_only`. Both independently
  enforce PRD §9's "never returned by any endpoint".
- **`X-Session-Id` header, never the body.** A session id is a bearer token
  (see `backend/apps/personal/models.py`'s docstring) — it does not belong in
  a query string, or in a body that ends up in a log line.
- **Disconnect only ever calls `context.disconnect()`.** Don't hand-roll a
  second delete path: the CASCADE guarantee lives in that function being the
  only one, not in this view remembering to replicate it.
- **`get_token()`/`set_token()` keep their exact signatures.** The Canvas and
  Ed tools call `get_token()`; changing its return type breaks code you
  didn't touch.

---

## What the tests hold

`backend/apps/core/tests.py`:

- Connecting Canvas stores an *encrypted* credential, and the response carries
  no credential or token key anywhere.
- A Piazza credential missing `password` is a 400 — not a 500, and not a
  silently-accepted partial credential.
- Stellic connects with an empty credential.
- Reconnecting replaces the credential in place rather than creating a second
  row.
- Listing never includes a credential field, and one session can see neither
  another session's connections nor disconnect its sources.
- `DELETE` on a real connection returns 204 and the row is gone; on a
  nonexistent one, 404.

```
docker compose exec backend python manage.py test apps.core
```
