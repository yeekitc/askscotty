# Working in this repo

Guidance for AI assistants (and humans) making changes to AskScotty.
Read [PRD.md](./docs/PRD.md) before implementing features — it is the source of truth.

## Layout

- `backend/` — Django REST API. Endpoints live in `backend/apps/core/`; the
  planner's toolset in `backend/apps/tools/`; user-scoped connectors in
  `backend/apps/personal/`.
- `frontend/app/` — **one** Expo/React Native codebase that runs on iOS, Android, and web.
- `PRD.md` — product requirements.
- `dependencies.md` — every dependency and why it's there. Adding a package to
  `requirements.txt` or `package.json` means adding a row here in the same
  commit, with the reasoning — not just the version.

## The frontend is React Native, not HTML

`frontend/app` renders to all three platforms from the same source. Never create a
separate web version, and never introduce a second frontend project.

Use React Native components, not HTML elements:

- `<View>` not `<div>`, `<Text>` not `<p>`/`<span>`, `<Pressable>` not `<button>`,
  `<TextInput>` not `<input>`
- **All text must be wrapped in `<Text>`.** Bare strings inside `<View>` crash on native.
- Styles go in `StyleSheet.create({...})`. There are no CSS files and no `className`.
- Do not use `window`, `document`, or other browser-only APIs — they don't exist on
  a phone. If something is genuinely web-only, guard it with `Platform.OS === 'web'`.
- Screens are files in `frontend/app/app/` (expo-router). `about.tsx` → `/about`.

Shared code lives in `frontend/app/lib/`:
- `api.ts` — the only place that calls the backend. Add new endpoints here rather
  than calling `fetch` from a screen.
- `types.ts` — API response shapes.
- `theme.ts` — colours and spacing. Prefer adding a token over a hardcoded hex.

## Environment variables

Two separate files, frequently confused:

- Root `.env` — backend and Docker only.
- `frontend/app/.env` — the app. **Expo only reads this one.** Variables must be
  prefixed `EXPO_PUBLIC_` to reach the app, and they are baked into the bundle,
  so never put a secret there.

## Running things

The database and API run in Docker; the frontend runs on the host.

- `docker compose up -d` — start database + API
- `docker compose logs -f backend` — API logs
- `cd frontend/app && npx expo start` — start the app
- Backend and frontend both hot-reload. No rebuild needed for ordinary edits.
- After changing `requirements.txt`: `docker compose up -d --build`
- After changing `models.py`: `docker compose exec backend python manage.py makemigrations && ... migrate`
- Run Python commands inside the container (`docker compose exec backend ...`),
  not on the host — the host has no database connection.

## Keeping the API contract in sync

`backend/apps/core/serializers.py` and `frontend/app/lib/types.ts` describe the same
data. Change one, change the other.

## Registering a tool

The planner needs no change — it reads the registry rather than naming tools,
which is why the lanes can be built in any order.

**Tools in a new app** (B1's `apps.rag`, B5's `apps.personal`) — two lines:

1. `backend/config/settings.py` — list the app **before** `apps.tools` in
   `INSTALLED_APPS`. App configs load in order, and `ToolsConfig.ready()` imports
   your tool module, so your models must be ready by then.
2. `backend/apps/tools/apps.py` — import that module inside `ready()`, so the
   `@register_tool` decorators actually run.

**Tools inside `apps.tools`** (B2's live tools, B3's web verify) — only step 2,
written `from . import <module>`. There is no new app to create; `apps.tools` is
scoped to hold these.

Miss the import and the tool silently never registers. The planner is never told
it exists, so it looks like the model chose not to use it.

**No re-provisioning, ever, for a tool.** `provision_planner` declares only the
prebuilt toolset; every session gets ours from the registry at request time. That
is what keeps a new tool a two-line change.

If a question comes back answered entirely off the open web, the agent is not the
cause. Check what is actually registered first:

```
docker compose exec backend python manage.py shell -c \
  "from apps.tools.registry import tools_for_session; print([t.name for t in tools_for_session(None)])"
```

An empty list there means a tool module never imported, and every question is
being handed a toolset of nothing.

## Hard rules from the PRD

These are non-negotiable; see PRD.md §9 and §10.

- **Public pages only in the shared index.** Never put live structured API results
  (Courses, Eats, TartanConnect) or any personal/authenticated data into the vector
  index. Volatile data is fetched live at query time.
- **Personal data is user-scoped.** Never mix it into shared storage. Disconnecting
  a source must delete its synced data.
- **Label mock data.** Anything not from a live source must be visibly marked as a
  mock in the UI (`is_mock` on a citation).
- **Show freshness.** Citations must surface `indexed_at` / `verified_at`.
- **Respect robots.txt**, rate-limit crawls, and identify the crawler user-agent.
- **Do not scrape behind logins** — no SIO, Stellic, Canvas-scraping, Autolab, 25Live,
  or Handshake SSO.

## Style

Match the surrounding code. **Keep comments lean.**

Comment only when the reason isn't visible from the code — a constraint, a
trade-off, a bug being avoided, a rule from the PRD. Never restate what a line
does, and don't write tutorial prose.

If a comment could be deleted without losing information, delete it.

**Write the current state, not the edit history.** Comments and docs describe how
things are and why; git describes how they got that way. No "removed X", "used to
be Y", "superseded — see below", "N tests, down from M", or notes crossing out the
paragraph above — edit the paragraph. The exception is a decision whose *reasoning*
still binds: record the reason, not the change. Every stale "formerly" is a token
every future reader pays for.
