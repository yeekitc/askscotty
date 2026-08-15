# Runbook

Everything you need mid-demo, on one page. Base URL is `http://localhost:8000`.

## Start / stop

```bash
docker compose up -d          # database + API
cd frontend/app && npx expo start   # the app (press w for browser)
docker compose logs -f backend      # API logs
docker compose down                 # stop
```

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/health/` | — | Is the API alive? |
| `POST` | `/api/ask/` | body `session_id` | **The main endpoint.** Ask a question. |
| `GET` | `/api/sources/` | — | Source registry + freshness (credits UI) |
| `GET` | `/api/threads/` | `X-Session-Id` | This session's saved conversations |
| `PUT` | `/api/threads/{id}/` | `X-Session-Id` | Save a conversation (creates if new) |
| `DELETE` | `/api/threads/{id}/` | `X-Session-Id` | Delete a conversation |
| — | `/admin/` | superuser | Django admin |

Two different places carry the session id, on purpose: `/api/ask/` reads it from
the **body** (`session_id`), the thread endpoints from the **`X-Session-Id`
header** — a GET has no body, and a bearer token must not sit in a URL where
server logs will keep it.

## Copy-paste checks

```bash
# alive?
curl -s localhost:8000/api/health/

# ask (browser form also works: http://localhost:8000/api/ask/)
curl -s -X POST localhost:8000/api/ask/ \
  -H 'Content-Type: application/json' \
  -d '{"query":"where can I eat near Wean?","session_id":"demo"}'

# what sources do we claim, and how fresh?
curl -s localhost:8000/api/sources/

# saved threads for a session
curl -s localhost:8000/api/threads/ -H 'X-Session-Id: demo'
```

## Shapes

`POST /api/ask/` takes `{query, session_id?, history?}` and returns:

```json
{ "answer": "…", "citations": [ … ], "modes_used": ["rag"], "note": null }
```

A citation is `{title, url, source, indexed_at, verified_at, is_mock}`.
`modes_used` is drawn from a fixed list: `rag` · `courses` · `dining` ·
`events` · `maps` · `web_verify` · `personal`.

**Every** failure, any status, comes back as:

```json
{ "error": { "code": "validation_error", "message": "query: This field is required." } }
```

Codes: `validation_error` · `unauthenticated` · `forbidden` · `not_found` ·
`method_not_allowed` · `unsupported_media_type` · `rate_limited` ·
`upstream_error` · `unavailable` · `timeout` · `error`.

The contract lives in three places that must agree — `backend/apps/core/serializers.py`,
`frontend/app/lib/types.ts`, and [tasklist.md §2](../tasklist.md).

## When it breaks

| Symptom | Cause / fix |
|---|---|
| App says "Could not reach the API" | `docker compose up -d`. On a **physical phone**, `localhost` is the phone — set `EXPO_PUBLIC_API_URL` in `frontend/app/.env` to your laptop's LAN IP and restart Expo. |
| `/api/ask/` answers but says "0 tool(s) available" | Expected today — the tools are tasklist B2 and the planner is B4. The contract is real; the answer is a stub. |
| Threads return `validation_error` about `X-Session-Id` | The header is missing. The app sends it automatically; `curl` needs it by hand. |
| Thread request fails in the browser only | CORS preflight. `X-Session-Id` must be in `CORS_ALLOW_HEADERS` (`backend/config/settings.py`). |
| Changed `models.py`, now errors | `docker compose exec backend python manage.py makemigrations && … migrate` |
| Changed `requirements.txt`, import errors | `docker compose up -d --build` — a plain restart won't reinstall. |
| Python command fails on your machine | Run it **inside** the container: `docker compose exec backend …`. The host has no database connection. |

## Demo reset

```bash
# wipe saved threads only
docker compose exec backend python manage.py shell -c \
  "from apps.core.models import Thread; Thread.objects.all().delete()"

# nuke everything and rebuild from scratch
docker compose down -v && ./setup.sh
```
