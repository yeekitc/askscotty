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
| `GET` | `/api/connections/` | `X-Session-Id` | Personal sources this session has connected |
| `POST` | `/api/connections/` | `X-Session-Id` | Connect one (`{provider, credential}`) |
| `DELETE` | `/api/connections/{provider}/` | `X-Session-Id` | Disconnect, deleting its data |
| — | `/admin/` | superuser | Django admin |

Two different places carry the session id, on purpose: `/api/ask/` reads it from
the **body** (`session_id`), the thread and connection endpoints from the
**`X-Session-Id` header** — a GET has no body, and a bearer token must not sit in
a URL where server logs will keep it.

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

# what personal sources has this session connected?
curl -s localhost:8000/api/connections/ -H 'X-Session-Id: demo'
```

## What's registered

The planner is never told which tools exist — it reads the registry at request
time. So when an answer comes back entirely off the open web, check the toolset
before suspecting the model:

```bash
docker compose exec backend python manage.py shell -c \
  "from apps.tools.registry import tools_for_session; print([t.name for t in tools_for_session(None)])"
```

Expect 10 public tools (`campus_search`, `find_dining`, `search_courses`,
`get_course`, `get_fce_ratings`, `find_events`, `find_handshake_events`,
`nearby`, `walk_time`, `find_available_rooms`). Pass a real session id and it
also gets that session's personal tools — 14 are registered: 10 live ones across
Canvas, Ed, Piazza, Gradescope and Stellic, plus 4 demo stand-ins that appear
*only* while their provider is unconnected, and whose citations are `is_mock`.
An empty list means a tool module never imported — see CLAUDE.md § Registering a
tool.

```bash
# is the campus index loaded? (~174 documents, ~1,439 chunks)
docker compose exec db psql -U askscotty -d askscotty \
  -c "select count(*) from rag_document; select count(*) from rag_chunk;"
```

## Shapes

`POST /api/ask/` takes `{query, session_id?, thread_id?, history?,
disabled_modes?, concise?}` and returns:

```json
{ "answer": "…", "citations": [ … ], "modes_used": ["rag"], "note": null }
```

A citation is `{id, title, url, source, snippet, indexed_at, verified_at,
is_mock}`. `modes_used` is drawn from a fixed list: `rag` · `courses` ·
`dining` · `events` · `maps` · `rooms` · `handshake` · `fce` · `web_verify` ·
`personal`. `disabled_modes` uses the same vocabulary and is a *deny* list, so a
lane added after the app cached the picker is on by default.

**Every** failure, any status, comes back as:

```json
{ "error": { "code": "validation_error", "message": "query: This field is required." } }
```

Codes: `validation_error` · `unauthenticated` · `forbidden` · `not_found` ·
`method_not_allowed` · `unsupported_media_type` · `rate_limited` ·
`upstream_error` · `unavailable` · `timeout` · `error`.

The contract lives in three places that must agree — `backend/apps/core/serializers.py`,
`frontend/app/lib/types.ts`, and [tasklist.md §2](../tasklist.md), where it was
agreed.

## When it breaks

| Symptom | Cause / fix |
|---|---|
| App says "Could not reach the API" | `docker compose up -d`. On a **physical phone**, `localhost` is the phone — set `EXPO_PUBLIC_API_URL` in `frontend/app/.env` to your laptop's LAN IP and restart Expo. |
| `/api/ask/` answers but cites nothing, or answers everything off the open web | Check what is actually registered (below). An empty toolset means a tool module never imported, so every question is handed nothing to call and falls back to the `web_verify` lane. |
| Public questions find nothing in the index | The index is empty. `SELECT count(*) FROM rag_chunk;` should be ~1,439. `./setup.sh` restores the dump; to rebuild live, `manage.py crawl && manage.py reindex`. |
| Every question fails "The planner is not provisioned" | `PLANNER_AGENT_ID` isn't reaching the container. Run `manage.py provision_planner`, put both ids in the **root** `.env`, then `docker compose up -d backend` — compose passes variables through one by one, and a restart is what picks up a new one. `manage.py check` says so at startup too. |
| Answers are slow, or one takes over a minute | Expected, not broken. Managed Agents costs a round trip per tool batch — measured at ~2× the old loop end to end and ~4× to first token ([b4-planner.md](./b4-planner.md)). There is deliberately no server-side deadline: a slow turn is allowed to finish. The session `budget` caps spend, not time. |
| An answer hits "The server did not respond within 120s" | The app's own backstop, not the planner. The turn is still running (and billing) on Anthropic's side, and we do not reattach to it yet, so ask again. There is no second loop to fall back to ([b4-planner.md](./b4-planner.md)). |
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
