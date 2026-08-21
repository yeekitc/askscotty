# AskScotty

Ask Scotty anything about CMU — and about *your* CMU — and get an answer with
citations you can check.

Named for Scotty, CMU's mascot. **Not** affiliated with ScottyLabs or other
campus "Scotty*" products.

Hackathon: [Stellic Pathfinders Challenge](https://www.stellic.com/pathfinders).

---

## What it is

A campus question-answering agent. One question goes in; the model decides which
campus sources to consult, calls them, and writes an answer that cites each one
with a timestamp.

Two kinds of question, one interface:

- **Public** — "what's open near Wean right now?", "how do I get a housing
  exemption?", "is 15-213 hard?" Answered from a crawl of CMU's public web plus
  live campus APIs.
- **Personal** — "what's due this week?", "what did my TA say about the
  midterm?" Answered from sources *you* connect (Canvas, Ed, Piazza,
  Gradescope, Stellic), scoped to your session and deleted when you disconnect.

## How it works

```
Expo / React Native 0.86        one codebase → iOS, Android, web
        │  SSE
Django 5.2 REST API             streams progress events while the agent works
        │
Claude Sonnet 5                 Anthropic Managed Agents; agentic tool-calling loop
        │
24 tools ──┬── 10 public        campus index, dining, courses, FCE, events,
           │                    Handshake, maps, rooms
           └── 14 personal      Canvas · Ed · Piazza · Gradescope · Stellic
                                (10 live + 4 labelled demo stand-ins)
        │
Postgres 16 + pgvector          HNSW index over 1536-dim embeddings
```

The planner is not a router with hardcoded branches. It reads the tool registry
at request time and chooses; adding a tool is a two-line change and the planner
is never told about it explicitly (see [CLAUDE.md](./CLAUDE.md) § Registering a
tool).

**Retrieval is hybrid.** `campus_search` runs vector similarity *and* Postgres
full-text search over the same chunks, then fuses the two rankings with
Reciprocal Rank Fusion — which needs no weight tuning and survives one half
returning nothing useful. Embeddings are OpenAI `text-embedding-3-small`
(1536-dim); everything else is Claude.

### What's actually in the index

174 documents, 1,439 chunks, all from `www.cmu.edu` — weighted toward housing,
the HUB, dining, student affairs, health services, news and academics. It ships
as a data dump (`backend/fixtures/rag_index.sql.gz`) that `./setup.sh` restores,
so a fresh clone can answer public questions without waiting on a crawl.

Volatile data is never indexed. Dining hours, course listings and events are
fetched live at query time, because an answer about what is open right now must
not come from a crawl taken last week.

### Honesty guarantees

Enforced in code, not policy — with one gap called out below:

- **Mock data is flagged.** Any citation not from a live source carries
  `is_mock`. The model cannot relabel a mock as live — the
  only thing it writes about a citation is the marker id (`S1`); every other
  field comes from the tool that produced it. The demo stand-in tools, which let
  you see what a connected Canvas or Ed looks like without connecting one, are
  the main users of this and disappear the moment you connect the real thing.
- **Freshness is visible.** Every citation carries `indexed_at` / `verified_at`.
- **Nothing behind a login is scraped.** No SIO, Stellic scraping, Canvas
  scraping, Autolab, 25Live, or Handshake SSO. Personal sources are reached
  through APIs you authorise.
- **Personal data is user-scoped** and never mixed into shared storage.
  Disconnecting a source deletes it.
- **"I don't know" is a real answer.** When no campus source backs a claim, the
  response says so rather than filling the gap from the open web unmarked.

Also: the crawler respects robots.txt, rate-limits itself, and identifies itself
by user-agent.

**Product requirements:** [PRD.md](./docs/PRD.md) — the source of truth for what
we are and aren't building.
**Dependencies:** [dependencies.md](./docs/dependencies.md) — what every package
and API key is for, and why it beat the alternatives. Add a row in the same
commit that adds a dependency.

---

## Setup

**Install two things first:**

1. **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** — runs
   the database and API. Open it and wait until it says *Running*.
2. **[Node.js LTS](https://nodejs.org/)** — runs the app. Take the version
   labelled **LTS**, not "Current": React Native does not support odd-numbered
   Node versions.

**Then:**

```bash
git clone <this-repo-url>
cd pathfindersHackathon
./setup.sh
```

The first run takes about **3–5 minutes** — it pulls Docker images, installs
packages, and restores the campus index. Long silent pauses are normal; don't
press Ctrl-C. Re-run `./setup.sh` any time, including after pulling changes.

### Start the app

```bash
cd frontend/app
npx expo start
```

Then press one key:

| Key | Opens |
|-----|-------|
| `w` | the app in your **web browser** |
| `i` | the **iOS simulator** (Mac + Xcode required) |
| `a` | the **Android emulator** |

Or install **Expo Go** on your phone and scan the QR code.

| What | Where |
|------|-------|
| App (web) | http://localhost:8081 |
| API health check | http://localhost:8000/api/health/ |
| API test form | http://localhost:8000/api/ask/ |

`docker compose down` stops the database and API when you're done.

---

## How the code is organised

```
.
├── docs/                   # PRD.md · runbook.md · dependencies.md
├── setup.sh                # one-command setup
├── docker-compose.yml      # database + API containers
├── backend/                # Django REST API
│   ├── fixtures/           #   the prebuilt campus index
│   └── apps/
│       ├── core/           # ← the HTTP API: views, serializers, threads
│       ├── planner/        #   the agentic loop over the registry
│       ├── rag/            #   crawler, chunker, embedder, hybrid search
│       ├── tools/          #   public tools
│       │   ├── registry.py     #   @register_tool + the per-session toolset
│       │   └── sources.py      #   the source registry behind /api/sources/
│       └── personal/       #   user-scoped connectors
│           ├── models.py       #   one encrypted credential per session
│           └── context.py      #   "what has this session connected?"
└── frontend/
    └── app/                # ← the app (iOS + Android + web)
        ├── app/            #   screens (each file = one route)
        └── lib/
            ├── api.ts         #   the only place that calls the backend
            ├── types.ts       #   API response shapes
            └── session.ts     #   the anonymous session id (treat as a password)
```

### One frontend, three platforms

There is **one** frontend codebase. `frontend/app` runs on iPhone, Android
**and** in the browser; editing `app/index.tsx` changes all three at once. There
is no separate web version and there must never be one.

That works because it is React Native, not HTML: `<View>` not `<div>`,
`<Text>` not `<p>` (**all** text must sit inside a `<Text>` or native crashes),
`<Pressable>` not `<button>`, `StyleSheet.create({...})` not CSS.
`react-native-web` translates those to real HTML for the browser. Full rules in
[CLAUDE.md](./CLAUDE.md).

**Adding a screen:** create a file in `frontend/app/app/` — `about.tsx` becomes
the `/about` route. Navigate with `<Link href="/about">` from `expo-router`.

---

## Daily workflow

| I changed… | I need to… |
|-----------|-----------|
| Anything in `frontend/app/` | Nothing — it reloads instantly |
| A Python file in `backend/` | Nothing — the API reloads itself |
| `backend/requirements.txt` | `docker compose up -d --build`, and add a row to [dependencies.md](./docs/dependencies.md) |
| `frontend/app/package.json` | `cd frontend/app && npm install`, restart Expo |
| Any `models.py` | `docker compose exec backend python manage.py makemigrations` then `… migrate` |

Run Python commands **inside** the container (`docker compose exec backend …`) —
the host has no database connection. API logs: `docker compose logs -f backend`.

---

## The API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health/` | health check |
| `POST` | `/api/ask/` | the main endpoint |
| `POST` | `/api/ask/stream/` | the same answer as SSE progress events — what the app calls |
| `GET` | `/api/sources/` | what AskScotty draws on, and how fresh each source is |
| `GET` `PUT` `DELETE` | `/api/threads/[{id}/]` | this session's saved conversations |
| `GET` `POST` | `/api/connections/` | connected personal sources; connect one |
| `DELETE` | `/api/connections/{provider}/` | disconnect, deleting its data |
| — | `/admin/` | Django admin (`manage.py createsuperuser`) |

Threads and connections identify the user with an **`X-Session-Id`** header — an
anonymous id the app generates on first run and keeps on the device. There is no
login. Treat that id like a password, which is why it travels in a header rather
than a URL where server logs would keep it.

`/api/ask/` takes `{query, session_id?, thread_id?, history?, disabled_modes?,
concise?}` and answers:

```json
{
  "answer": "string",
  "citations": [
    {
      "id": "S1", "title": "string", "url": "string", "source": "string",
      "snippet": "string",
      "indexed_at": "ISO-8601 or null", "verified_at": "ISO-8601 or null",
      "is_mock": false
    }
  ],
  "modes_used": ["rag", "dining"],
  "note": "string or null"
}
```

`modes_used` comes from a fixed vocabulary — `rag` · `courses` · `dining` ·
`events` · `maps` · `rooms` · `handshake` · `fce` · `web_verify` · `personal` —
so the app can light up a chip per lane. `note` carries caveats worth showing
above the answer: a tool that timed out, mock data in play, a stale index.

Errors — any status — come back as `{"error": {"code": "…", "message": "…"}}`,
so the app can show something useful instead of guessing at the body.

Open http://localhost:8000/api/ask/ in a browser for a clickable test form.

### Watching an answer come together

`POST /api/ask/stream/` takes the same body and streams Server-Sent Events:

| Event | Data | Means |
|---|---|---|
| `mode_start` | `{mode, tool}` | a lane started — light up its chip |
| `mode_end` | `{mode, tool, ok}` | it finished, or failed |
| `text_delta` | `{text}` | answer text as the model writes it |
| `done` | the full `AskResponse` | the validated answer |
| `error` | `{code, message}` | it failed after the response had started |

`done` carries **the same validated answer** `/api/ask/` returns, so a client can
ignore everything else and the plain endpoint stays a fallback.

Two things about `text_delta`. It is **provisional**: text written before a
`mode_start` was the model talking itself into a lookup, so drop what you have
when a lane starts and let `done` replace it at the end (deltas are raw; markers
are only validated by then). And it is **chunky, not a typewriter** — the API
batches its own output.

```bash
curl -N -X POST http://localhost:8000/api/ask/stream/ \
  -H 'Content-Type: application/json' \
  -d '{"query": "what is open near Wean right now?"}'
```

The response shapes are defined in two places that must stay in sync:
`backend/apps/core/serializers.py` and `frontend/app/lib/types.ts`.

---

## Settings

There are **two** environment files, and they are not interchangeable:

| File | Controls | Notes |
|------|----------|-------|
| `.env` | database + API | copied from `.env.example` |
| `frontend/app/.env` | the app | **Expo reads only this one**, never the root `.env` |

Both are created by `./setup.sh` and are gitignored. Expo bakes its variables
into the bundle, so nothing secret may go in the frontend one — that is what the
`EXPO_PUBLIC_` prefix is warning you about.

Common changes:

- `EXPO_PUBLIC_API_URL` (frontend) — where the app looks for the API
- `BACKEND_PORT` (root) — change if 8000 is taken, and update `EXPO_PUBLIC_API_URL`
- `DJANGO_SECRET_KEY` — must be changed before any real deployment

`.env` also holds `ANTHROPIC_API_KEY` (planner *and* the server-side web search
lane) and `OPENAI_API_KEY` (embeddings only). The backend starts fine without
them: a feature whose key is missing fails with a clear message when you use it,
not at boot, so you only need the keys for the lane you're working on. Details:
[dependencies.md § External services](./docs/dependencies.md#external-services).

While `DJANGO_DEBUG=true` the API accepts requests from any origin, so you won't
hit CORS errors in development.

---

## Troubleshooting

[docs/runbook.md](./docs/runbook.md) has the full symptom → fix table. The four
that bite most often:

**"Could not reach the API"** — the backend isn't running. `docker compose up -d`,
then check `docker compose ps`.

**Network error on a physical phone** — `localhost` means *the phone*. Get your
laptop's IP with `ipconfig getifaddr en0`, put it in `frontend/app/.env` as
`EXPO_PUBLIC_API_URL=http://192.168.1.20:8000`, restart Expo. Same Wi-Fi network.

**"address already in use"** — change `BACKEND_PORT` in `.env` (and
`EXPO_PUBLIC_API_URL` to match). For Expo: `npx expo start --port 8082`.

**Expo behaving strangely after a dependency change** — `npx expo start --clear`.

Start completely over — this wipes the local database, index included, and
`setup.sh` restores it:

```bash
docker compose down -v && ./setup.sh
```

---

## Credits

Built on publicly available CMU web pages and public campus APIs, including open
APIs published by ScottyLabs (e.g. Courses). **We are not affiliated with
ScottyLabs.**
