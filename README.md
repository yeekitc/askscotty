# AskScotty

Ask Scotty anything about CMU (and *your* CMU) — get a cited, multi-hop answer.

Named for Scotty, CMU's mascot — **not** affiliated with ScottyLabs or other campus "Scotty*" products.

**Product requirements:** see [PRD.md](./docs/PRD.md). Read this before building anything — it defines what we're making and what we're explicitly *not* making.

**Dependencies:** see [dependencies.md](./docs/dependencies.md) — what every package and API key is for, and why it was picked over the alternatives. Add a row there in the same commit that adds a dependency.

Hackathon: [Stellic Pathfinders Challenge](https://www.stellic.com/pathfinders).

---

## Setup

**You need two things installed first:**

1. **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** — runs the database and API for you.
   After installing, **open it** and wait until it says *Running*. Leave it open while you work.
2. **[Node.js LTS](https://nodejs.org/)** — runs the app.
   Download the version labelled **LTS**, not "Current". React Native does not support odd-numbered Node versions.

**Then get the code and run the setup script:**

```bash
git clone <this-repo-url>
cd pathfindersHackathon
./setup.sh
```

> **Tip:** to open a terminal already in a folder on a Mac, right-click the folder in Finder → *Services* → *New Terminal at Folder*.

The first run takes about **3–5 minutes** — it downloads Docker images and installs packages. Long silent pauses are normal. Don't press Ctrl-C.

`./setup.sh` is safe to run again any time. Re-run it after pulling new changes.

### Start the app

```bash
cd frontend/app
npx expo start
```

Then press one key:

| Key | Opens |
|-----|-------|
| `w` | the app in your **web browser** |
| `i` | the **iPhone simulator** (Mac + Xcode required) |
| `a` | the **Android emulator** |

Or install **Expo Go** on your phone and scan the QR code.

| What | Where |
|------|-------|
| App (web) | http://localhost:8081 |
| API health check | http://localhost:8000/api/health/ |
| API test form | http://localhost:8000/api/ask/ |

Stop the database and API when you're done:

```bash
docker compose down
```

---

## How the code is organised

```
.
├── docs/PRD.md            # product requirements — the source of truth
├── tasklist.md            # the build checklist, and where the API contract is agreed
├── docs/dependencies.md  # every dependency and why it's there — read before adding one
├── setup.sh               # one-command setup
├── docker-compose.yml     # database + API containers
├── .env.example           # backend settings (setup.sh copies to .env)
├── backend/               # Django REST API
│   ├── config/settings.py # Django configuration
│   └── apps/
│       ├── core/          # ← the API lives here
│       │   ├── views.py       #   endpoints
│       │   ├── serializers.py #   request/response shapes
│       │   ├── models.py      #   saved chat threads + messages
│       │   └── errors.py      #   the one error shape
│       ├── tools/         # what the planner can do
│       │   ├── registry.py    #   @register_tool + the per-session toolset
│       │   └── sources.py     #   the source registry behind /api/sources/
│       └── personal/      # user-scoped connectors (Canvas, Ed)
│           ├── models.py      #   one encrypted credential per session
│           └── context.py     #   "what has this session connected?"
└── frontend/
    └── app/               # ← the app lives here (iOS + Android + web)
        ├── app/           #   screens (each file = one screen)
        │   ├── _layout.tsx
        │   └── index.tsx  #   the ask screen
        ├── components/    #   reusable pieces
        └── lib/           #   API client, types, theme
            ├── api.ts        #   the only place that calls the backend
            ├── session.ts    #   the anonymous session id (treat as a password)
            └── chatThreads.ts#   saved conversations, loaded from the API
```

### One frontend, three platforms

There is **one** frontend codebase. `frontend/app` runs on iPhone, Android, **and** in the web browser. Editing `app/index.tsx` changes all three at once — there is no separate web version to keep in sync.

This works because the app is written in **React Native**, which uses its own components rather than HTML:

| Instead of HTML | Write |
|-----------------|-------|
| `<div>` | `<View>` |
| `<p>`, `<span>`, `<h1>` | `<Text>` — **all** text must be inside a `<Text>` |
| `<button>` | `<Pressable>` |
| `<input>`, `<textarea>` | `<TextInput>` |
| CSS files / `className` | `StyleSheet.create({...})` and `style={styles.x}` |

`react-native-web` translates those into real HTML for the browser automatically.

**Adding a screen:** create a file in `frontend/app/app/`. `about.tsx` automatically becomes the `/about` route. Navigate with `<Link href="/about">` from `expo-router`.

---

## Daily workflow

| I changed… | I need to… |
|-----------|-----------|
| Anything in `frontend/app/` | Nothing — it reloads instantly |
| A Python file in `backend/` | Nothing — the API reloads itself |
| `backend/requirements.txt` | `docker compose up -d --build`, and add a row to [dependencies.md](./docs/dependencies.md) |
| `frontend/app/package.json` | `cd frontend/app && npm install`, restart Expo |
| Any `models.py` under `backend/apps/` | See *Database changes* below |

### Watching the API logs

```bash
docker compose logs -f backend
```

### Database changes

After editing `models.py`:

```bash
docker compose exec backend python manage.py makemigrations
docker compose exec backend python manage.py migrate
```

---

## The API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health/` | health check — is the API alive? |
| `POST` | `/api/ask/` | the main endpoint (`{"query", "session_id"?, "history"?}`) |
| `POST` | `/api/ask/stream/` | the same answer as SSE progress events — see below |
| `GET` | `/api/sources/` | what AskScotty draws on, and how fresh each source is |
| `GET` | `/api/threads/` | this session's saved conversations |
| `PUT` | `/api/threads/{id}/` | save a conversation (creates it if new) |
| `DELETE` | `/api/threads/{id}/` | delete a conversation and its messages |
| — | `/admin/` | Django admin (needs a superuser, see below) |

The `/api/threads/` endpoints identify the user with an **`X-Session-Id`** header —
an anonymous id the app generates on first run and keeps on the device. There is
no login. Treat that id like a password: anyone who has it can read that
session's conversations, which is why it travels in a header rather than the URL.

Open http://localhost:8000/api/ask/ in a browser for a clickable form to test the endpoint — no code needed.

`/api/ask/` answers:

```json
{
  "answer": "string",
  "citations": [
    {
      "id": "S1",
      "title": "string",
      "url": "string",
      "source": "string",
      "snippet": "string",
      "indexed_at": "ISO-8601 or null",
      "verified_at": "ISO-8601 or null",
      "is_mock": false
    }
  ],
  "modes_used": ["rag", "courses", "dining", "events", "maps", "web_verify", "personal"],
  "note": "string or null"
}
```

Errors — any status — come back as `{"error": {"code": "...", "message": "..."}}`, so the app can show a useful message instead of guessing at the body.

### Watching an answer come together

`POST /api/ask/stream/` takes the same body and streams Server-Sent Events while
the planner works: `mode_start` and `mode_end` as each lane runs, then `done`
carrying **the same validated answer** `/api/ask/` returns. Nothing is lost by
ignoring it — the plain endpoint stays a fallback.

```bash
curl -N -X POST http://localhost:8000/api/ask/stream/ \
  -H 'Content-Type: application/json' \
  -d '{"query": "what is open near Wean right now?"}'
```

**The answer is real, but the sources are not there yet.** The planner runs
(tasklist B4) — it routes, calls tools, cites what they return and degrades when
one fails. What it has to work with is still thin: every registered tool raises
`ToolError` until B1–B3 land, so most answers come back saying they could not
check a live campus source.

The shapes are defined in three places that must stay in sync:
- `tasklist.md` §2 — where the contract is agreed
- `backend/apps/core/serializers.py` (backend)
- `frontend/app/lib/types.ts` (frontend)

To create an admin login:

```bash
docker compose exec backend python manage.py createsuperuser
```

---

## Settings

There are **two** environment files, and they are not interchangeable:

| File | Controls | Notes |
|------|----------|-------|
| `.env` | database + API | copied from `.env.example` |
| `frontend/app/.env` | the app | copied from `frontend/app/.env.example` — **Expo only reads this one**, never the root `.env` |

Both are created by `./setup.sh` and are gitignored — your own settings are never committed.

Common changes:

- `EXPO_PUBLIC_API_URL` (in `frontend/app/.env`) — where the app looks for the API
- `BACKEND_PORT` (in `.env`) — change if port 8000 is taken; update `EXPO_PUBLIC_API_URL` to match
- `DJANGO_SECRET_KEY` — must be changed before any real deployment

### API keys

`.env` also holds keys for the planner, embeddings and web search. The backend
starts fine without them — a feature that needs a missing key fails with a clear
message when you use it, not at startup — so you only need the ones for the lane
you're working on. What each is for, and where to get it:
[dependencies.md § External services](./docs/dependencies.md#external-services).

While `DJANGO_DEBUG=true`, the API accepts requests from any origin, so you won't hit CORS errors during development.

---

## Troubleshooting

**"Could not reach the API" in the app**

The backend isn't running. Start it with `docker compose up -d`, then check `docker compose ps`.

**Testing on a physical phone shows a network error**

On a real phone, `localhost` means *the phone*, not your laptop. Find your laptop's IP:

```bash
ipconfig getifaddr en0        # Mac
```

Then set it in `frontend/app/.env` and restart Expo:

```
EXPO_PUBLIC_API_URL=http://192.168.1.20:8000
```

Your phone and laptop must be on the same Wi-Fi network.

**"address already in use" / "port is already allocated"**

Something else is using that port. Change `BACKEND_PORT` in `.env` (and `EXPO_PUBLIC_API_URL` in `frontend/app/.env` to match), then `docker compose up -d`.

For Expo, run `npx expo start --port 8082`.

**The API keeps restarting, or logs say the database isn't ready**

The database volume can end up half-built if a previous setup was interrupted. Reset it — this deletes local database contents, which is fine while we have no real data:

```bash
docker compose down -v
docker compose up -d
```

**Expo behaves strangely after changing dependencies**

```bash
cd frontend/app
npx expo start --clear
```

**Start completely fresh**

```bash
docker compose down -v
./setup.sh
```

---

## Credits

Uses publicly available CMU web pages and public campus APIs, including open APIs published by ScottyLabs (e.g. Courses). **We are not affiliated with ScottyLabs.**
