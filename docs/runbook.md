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
| `POST` | `/api/ask/stream/` | body `session_id` | Same answer, plus SSE progress events. What the app actually calls. |
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
| `/api/ask/` answers but cites nothing | Expected today. **The planner is built and running** — what it has to call isn't: no campus tool is registered until B1–B3 land. It falls back to the web lane, which earns a `web_verify` chip but no citations until B3 harvests them. |
| Every question fails "The planner is not provisioned" | `PLANNER_AGENT_ID` isn't reaching the container. Run `manage.py provision_planner`, put both ids in the **root** `.env`, then `docker compose up -d backend` — compose passes variables through one by one, and a restart is what picks up a new one. `manage.py check` says so at startup too. |
| Answers are slow, or one takes over a minute | Managed Agents costs a round trip per tool batch — measured at ~2× the old loop end to end and ~4× to first token ([b4-planner.md](./b4-planner.md)). Nothing bounds wall-clock: the session `budget` caps spend, not time, so the app's 120s backstop is what actually cuts a slow answer. |
| An answer hits "The server did not respond within 120s" | The turn is still running and billing on Anthropic's side; we do not reattach to it. Ask again. `PLANNER_MANAGED_AGENTS=false` is faster but **has no web tools until B1–B3 land**, so today it answers from general knowledge with no citations — it is an outage escape hatch, not a speed setting. |
| A follow-up re-searches instead of remembering | The app isn't sending `thread_id`, so each question opens its own planner session. Check the ask request body. |
| SSE stream returns one blob at the end | A proxy is buffering. `X-Accel-Buffering: no` is set; check anything in front of Django. `curl -N` bypasses client-side buffering. |
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
