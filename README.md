# AskScotty

Ask Scotty anything about CMU (and *your* CMU) — get a cited, multi-hop answer.

Named for Scotty, CMU’s mascot — **not** affiliated with ScottyLabs or other campus “Scotty*” products.

**Product requirements:** see [PRD.md](./PRD.md).

Hackathon: [Stellic Pathfinders Challenge](https://www.stellic.com/pathfinders).

---

## Quick start (teammates)

You only need **Docker Desktop**. For the phone app, also install **Node.js (LTS)**.

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and open it until it says **Running**.
2. (Optional, for mobile) Install [Node.js LTS](https://nodejs.org/).
3. In a terminal, from this folder:

```bash
./setup.sh
```

That script copies `.env`, builds containers, starts Postgres + Django API + Vite web, and installs Expo deps.

Then open:

| What | URL |
|------|-----|
| Web app | http://localhost:5173 |
| API health | http://localhost:8000/api/health/ |

Stop everything later with:

```bash
docker compose down
```

---

## Repo layout

```
.
├── PRD.md                 # product requirements
├── setup.sh               # one-command local setup
├── docker-compose.yml     # db + backend + web
├── backend/               # Django REST API
└── frontend/
    ├── web/               # Vite + React (browser)
    └── mobile/            # Expo + React Native (phone)
```

Backend and frontend are intentionally separate. Shared product truth lives in `PRD.md`.

---

## Daily workflow

### Web + API (Docker)

```bash
docker compose up -d
docker compose logs -f
```

Code under `backend/` and `frontend/web/` is bind-mounted, so most edits reload automatically.

### Mobile (Expo)

Expo is **not** run inside Docker (device/simulator networking is simpler on your machine):

```bash
cd frontend/mobile
npm start
```

Scan the QR code with Expo Go, or press `i` / `a` for simulator.

On a **physical phone**, `localhost` points at the phone, not your laptop. Set `EXPO_PUBLIC_API_URL` in `.env` to your laptop’s LAN IP (example: `http://192.168.1.20:8000`), then restart Expo.

---

## API stub

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health/` | health check |
| `POST` | `/api/ask/` | stub planner (`{"query": "..."}`) |

Replace the stub in `backend/apps/core/views.py` with the real planner (RAG → live tools → web verify) from the PRD.

---

## Environment

Defaults live in `.env.example`. `./setup.sh` creates `.env` if missing. Common knobs:

- `VITE_API_URL` — browser → API
- `EXPO_PUBLIC_API_URL` — mobile → API
- `POSTGRES_*` — database
- `DJANGO_SECRET_KEY` — change before any shared deploy

---

## Credits

Uses publicly available CMU web pages and public campus APIs, including open APIs published by ScottyLabs (e.g. Courses). **We are not affiliated with ScottyLabs.**
