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
