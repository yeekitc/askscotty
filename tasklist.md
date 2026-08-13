# AskScotty — Build Checklist

Working checklist derived from [PRD.md](./PRD.md). Tick boxes as you go.

**How to use**

- Claim a task by appending your name: `- [ ] Wire `campus_search` — @yeekit`
- Commit the checked box in the same PR as the work, so `main` always shows real state.
- `P0` = required for a working demo · `P1` = strong submission · `P2` = stretch / pitch-only.
- Anything marked **Mock** must be visibly labelled as mock in the UI (PRD §9, Privacy).

Legend for source access (PRD §3): `Live` = public API now · `Crawl` = we index it · `Token` = user pastes key · `Mock` = stub · `Link` = deep-link only.

---

## 0. Everyone — first hour

- [ ] Install Docker Desktop, open it until it says **Running**
- [ ] Install Node.js LTS (needed to run the app — get the **LTS** build, not "Current")
- [ ] Clone the repo and run `./setup.sh`
- [ ] Run `cd frontend/app && npx expo start`, press `w`, confirm the app loads at http://localhost:8081
- [ ] Confirm http://localhost:8000/api/health/ returns `{"status": "ok", ...}`
- [ ] Confirm `POST /api/ask/` returns the stub answer (use the app, or the form at http://localhost:8000/api/ask/)
- [ ] Read [PRD.md](./PRD.md) §2 (signature query) and §9 (P0 scope) end to end
- [ ] Read [CLAUDE.md](./CLAUDE.md) — how the repo is laid out and the rules AI assistants must follow
- [ ] Skim `backend/apps/core/views.py` and `frontend/app/app/index.tsx` — that's the whole app today
- [ ] Pick a lane below and put your name on the tasks

---

## 1. Shared decisions — settle these before parallel work starts

These block both sides. Decide in one sitting, write the answer in this file.

- [ ] **Freeze the `/api/ask/` response contract** (see §2 below). Frontend codes against it; backend fills it in.
- [ ] **Pick the LLM + model** for the planner. Default: Anthropic `claude-opus-5` (best tool-use / multi-hop reasoning, $5/$25 per MTok). Cheaper fallback for high-volume or simple routing: `claude-sonnet-5` ($3/$15, intro $2/$10 through 2026-08-31) or `claude-haiku-4-5` ($1/$5).
- [ ] **Pick an embeddings provider** for the vector half of hybrid retrieval — Anthropic has no embeddings endpoint, so this is a separate choice (hosted provider, or a local `sentence-transformers` model in the backend container).
- [ ] **Pick a web-search provider** for `web_search` (Brave / Serper / Tavily — PRD §6). Whoever picks it adds the key to `.env.example`.
- [ ] **Decide the vector store**: `pgvector` in the existing Postgres (fewer moving parts) vs. a separate service. Recommend pgvector.
- [ ] **Decide auth scope for the demo**: anonymous session ID vs. real Django user accounts. Personal connectors (§7) need *something* to scope tokens to.
- [ ] Add every new key to `.env.example` (never `.env`) and post it in the team chat

---

## 2. The API contract (owned by both sides)

Frontend and backend both code against this. Change it only by editing this section and telling everyone.

- [ ] `POST /api/ask/` request grows from `{query}` to `{query, session_id?, history?}`
- [ ] Response keeps `answer`, `citations[]`, `modes_used[]`, `note` — already in `backend/apps/core/serializers.py`
- [ ] Each citation carries `title`, `url`, `source`, `indexed_at`, `verified_at` (PRD §3 — every answer shows freshness)
- [ ] Add `is_mock: bool` to each citation so the UI can badge mock sources
- [ ] `modes_used` values are fixed strings: `rag` · `courses` · `dining` · `events` · `maps` · `web_verify` · `personal`
- [ ] Decide error shape: `{error: {code, message}}` with a real HTTP status
- [ ] Decide streaming or not. Non-streaming is fine for P0 — if streaming, agree on SSE before frontend builds the renderer.
- [ ] Add `GET /api/sources/` returning the source registry (name, tier, access, `indexed_at`) — powers the credits/freshness UI
- [ ] Update the API table in [README.md](./README.md) when this changes

---

# BACKEND

Django 5.1 + DRF + Postgres. Everything lives under `backend/`. Code is bind-mounted, so edits reload.

## B0. Foundations — P0

- [ ] Add planner/RAG deps to `backend/requirements.txt` (LLM SDK, HTTP client, crawler, embeddings, `pgvector`)
- [ ] Rebuild the backend image after changing requirements: `docker compose build backend`
- [ ] Enable the `pgvector` extension on the Postgres container (migration or init SQL)
- [ ] Create `backend/apps/rag/` app (crawler, chunker, index, `campus_search`)
- [ ] Create `backend/apps/tools/` app (live tools + mocks + web verify)
- [ ] Create `backend/apps/planner/` app (orchestration)
- [ ] Create `backend/apps/personal/` app (user-scoped connectors)
- [ ] Register new apps in `backend/config/settings.py` `INSTALLED_APPS`
- [ ] Add a settings block for external API keys, read from env with safe defaults
- [ ] Add a shared HTTP client helper: timeout, retry, identifying User-Agent, per-host rate limit
- [ ] Add a response cache (per-tool TTL) so demo reloads don't hammer public APIs
- [ ] Add structured logging for every tool call: tool name, args, latency, cache hit/miss

## B1. Campus index / RAG — P0 (Days 1–2)

**Models**

- [ ] `Document` model: `url`, `title`, `source_tier`, `fetched_at`, `content_hash`, `robots_allowed`
- [ ] `Chunk` model: FK to `Document`, `text`, `token_count`, `embedding` (vector), `heading_path`
- [ ] `CrawlSeed` model: `url`, `label`, `enabled`, `last_crawled_at`
- [ ] Migrations written and applied

**Crawler**

- [ ] Seed loader for Appendix B course sites (all 10 URLs from the PRD)
- [ ] Seed loader for public `cmu.edu` sections: HUB, colleges, Student Affairs, CPDC
- [ ] Seed loader for [cmu.guide](https://cmu.guide/) (site + GitHub Markdown)
- [ ] `robots.txt` fetch + honor (PRD §3 — non-negotiable)
- [ ] Per-host rate limiting and identifying crawler User-Agent
- [ ] Exclusion list enforced in code: SIO, Stellic UI, Canvas, Autolab, anything behind a login wall
- [ ] HTML → clean text extraction (strip nav, footer, scripts)
- [ ] URL de-duplication and `content_hash` skip on re-crawl
- [ ] Depth/page-count caps so a crawl can't run away
- [ ] Management command `python manage.py crawl [--seed=...] [--limit=N]`

**Index**

- [ ] Chunker: heading-aware split with overlap, target ~500–800 tokens
- [ ] Embedding generation with batching + retry
- [ ] BM25 / Postgres full-text index over `Chunk.text`
- [ ] Vector index (`pgvector` HNSW or IVFFlat)
- [ ] Hybrid retrieval: combine BM25 + vector scores, de-duplicate by document
- [ ] `campus_search(query, k, filters)` tool function
- [ ] Every result returns `url` + `indexed_at` (PRD §4)
- [ ] Management command `python manage.py reindex`
- [ ] Ship a pre-built index (fixture or dump) so the demo doesn't depend on a live crawl

**HKN / LibGuides — P1**

- [ ] Crawl HKN ECE/CS Guide (public GitHub Pages)
- [ ] Crawl public LibGuides

## B2. Live tools — P0 (Days 1–2)

**Courses** (`course-tools.apis.scottylabs.org`, no auth)

- [ ] Client for `/courses/search`, `/course/{id}`, `/schedules`
- [ ] Normalize to an internal shape: number, title, units, instructors, meeting times, prereqs
- [ ] `search_courses(query, units?, days_excluded?, semester?)` tool
- [ ] `get_course(course_number)` tool
- [ ] Filter support for "9-unit ML elective, no Friday" (PRD §8)
- [ ] Handle upstream 4xx/5xx gracefully — degrade, don't crash the answer

**Dining** (`api.cmueats.com/v2/locations`)

- [ ] Client for the v2 locations endpoint (do **not** use the deprecated `dining.apis` endpoint)
- [ ] Parse per-location open/close windows into a queryable form
- [ ] `find_dining(open_at?, near?, limit?)` tool
- [ ] "Open after 8:20 near Wean" works end to end (joins with mock Maps)

**Events** (`tartanconnect.cmu.edu/mobile_ws/v17/mobile_events_list?range=0`)

- [ ] Client for the mobile events JSON feed
- [ ] Normalize: title, start/end, location, org, categories, link
- [ ] `find_events(before?, after?, keywords?, limit?)` tool
- [ ] Keyword match for "startup" / "AI" hits the signature query

**Maps — Mock**

- [ ] Fixture file with ~10 landmark buildings: name, aliases, lat/lng
- [ ] Adjacency / walking-minutes table between landmarks
- [ ] `nearby(building, radius_or_minutes)` tool
- [ ] `walk_time(a, b)` tool
- [ ] Every Maps result flagged `is_mock: true`
- [ ] Cover the buildings the demo needs: Gates, Wean, Doherty, Tepper, UC, Hunt, Baker, Posner, Cohon, Hamerschlag

**25Live — Mock, P1**

- [ ] Fixture of room availability windows for demo buildings
- [ ] `find_free_room(near, duration_minutes, after)` tool
- [ ] Flagged `is_mock: true`; no SSO scraping (PRD §9 non-goals)

**Handshake / FCE — Mock, P1**

- [ ] Handshake events fixture, or `Link`-out only
- [ ] FCE ratings fixture for a handful of courses
- [ ] Both flagged `is_mock: true`

## B3. Web verify — P0 (Day 3)

- [ ] `fetch_url(url)` with an **allowlist** of public hosts
- [ ] Explicit denylist so Canvas / SIO / Stellic can never be fetched here (PRD §6)
- [ ] Return `verified_at` on every fetch
- [ ] `web_search(query, site?)` against the chosen provider
- [ ] Site-filtered search helper (`site:cs.cmu.edu`)
- [ ] `resolve_course_site(course_number)` — static map from Appendix B
- [ ] Staleness policy: define what `indexed_at` age triggers a verify fetch
- [ ] Enqueue newly discovered URLs into `CrawlSeed` for the next crawl (PRD §6 planner default)

## B4. Planner — P0 (Days 1–2, then Day 4)

- [ ] Replace the stub in `backend/apps/core/views.py:25` (`AskView`) with the real planner
- [ ] Register every tool with the LLM as tool definitions (name, description, JSON schema)
- [ ] Agentic loop: call tools until the model stops, with a max-iteration cap
- [ ] System prompt: CMU context, cite everything, label mocks, never invent facts
- [ ] Collect citations from every tool result into the response
- [ ] Populate `modes_used` from which tool families actually ran
- [ ] Timeout + graceful partial answer if one tool hangs
- [ ] Never let personal data enter a shared-index call (PRD §3)
- [ ] **Signature multi-hop works**: "I get out of 15-213 at 4:20 tomorrow. Find somewhere nearby to eat and then an interesting startup or AI event before 8." → Courses → Maps → Dining → Events
- [ ] Verify each PRD §8 example query returns something sane

## B5. Personal connectors — P0/P1 (Day 5)

- [ ] `UserConnection` model: user/session, provider, encrypted token, `connected_at`, `last_sync_at`
- [ ] Encrypt tokens at rest; never log them; never return them in any API response
- [ ] `POST /api/connections/` (connect), `DELETE /api/connections/{provider}/` (disconnect)
- [ ] **Disconnect deletes all synced data** (PRD §7 — required)
- [ ] Canvas client against `canvas.cmu.edu/api/v1` using a student PAT — **P0**
- [ ] Canvas: courses, assignments + due dates, announcements
- [ ] `personal_search(query)` tool, scoped to the current user only
- [ ] "What's due this week?" works end to end
- [ ] Ed Discussion via settings API token — **P1**
- [ ] Stellic: mock / uploaded JSON degree audit — **P1**
- [ ] "On track for CS minor?" using Stellic mock + live Courses — **P1**
- [ ] Assert in code + test that personal chunks are never written to the shared index

## B6. Ops & pitch material — P1

- [ ] Re-index job runnable on demand (manual is fine — PRD §9 says even manual counts)
- [ ] Record `indexed_at` per source and expose it via `GET /api/sources/`
- [ ] Seed script that populates a demo-ready database in one command
- [ ] Basic tests: one per tool, one planner smoke test on the signature query
- [ ] README section on how to run the crawl and re-index

---

# FRONTEND

**One** Expo + React Native codebase (`frontend/app/`) that runs on iOS, Android, and
the browser. There is no separate web project — editing a screen changes all three
surfaces at once. See [CLAUDE.md](./CLAUDE.md) for the component rules (`<View>` not
`<div>`, all text inside `<Text>`, `StyleSheet` not CSS).

## F0. Foundations — P0

- [x] Extract the inline `fetch` into `frontend/app/lib/api.ts` — done
- [x] Create a types file matching the §2 contract (`frontend/app/lib/types.ts`) — done
- [x] Add `is_mock` to the `Citation` type — done
- [x] Bring citation fields (`url`, `indexed_at`, `verified_at`) to parity — done, single codebase so parity is automatic now
- [x] Centralize `API_URL` handling and surface a clear error when the backend is unreachable — done in `lib/api.ts` (includes a 30s timeout)
- [ ] Keep `npx tsc --noEmit` clean

## F1. Ask flow — P0

- [x] Split the screen into components (`CitationCard`, `Credits` in `frontend/app/components/`) — partially done, add the rest below
- [ ] Loading state that shows *which mode is running* (not just "Asking…") — this is the demo's wow moment
- [ ] Render `modes_used` as labelled chips (RAG · Courses · Dining · Events · Maps · Web verify · Personal)
- [ ] Error state: network failure, 4xx, 5xx, timeout — each with a distinct message
- [ ] Empty state before the first question, with 3–4 clickable example queries from PRD §8
- [ ] Pre-fill the signature query as the default (already done — keep it)
- [ ] Multi-turn: keep a question/answer history in the page
- [ ] Cmd/Ctrl+Enter submits

## F2. Web — citations & trust — P0

Freshness and honesty are the product's differentiator (PRD §3, §9). Don't cut these.

- [ ] Every citation renders as a clickable link to its `url`
- [ ] Show `indexed_at` and/or `verified_at` as human-relative text ("indexed 3 days ago", "verified just now")
- [ ] Visible **Mock data** badge on any citation with `is_mock: true`
- [ ] Group citations by source type
- [ ] Numbered inline markers in the answer body that link down to the citation list
- [ ] Credits footer with the exact PRD §9 wording, including "**We are not affiliated with ScottyLabs.**"
- [ ] Footer is present on every screen, including mobile

## F3. Web — polish — P0/P1

- [ ] Responsive down to a narrow laptop window (that's what the demo will run on)
- [ ] Keyboard accessible: focus states, labelled form controls, `aria-live` on the answer region (partly done)
- [ ] Sensible `<title>` and favicon
- [ ] Skeleton or shimmer while the answer loads
- [ ] Answer text renders line breaks / lists readably (the planner will return structured prose)
- [ ] Copy-answer-to-clipboard button — **P1**

## F4. Web — connectors UI — P0/P1

- [ ] `/settings` route (or a modal) listing available connectors
- [ ] Canvas token input rendered as a **password field**, never plain text (PRD §9 Privacy) — **P0**
- [ ] Clear copy explaining what is synced and that it is user-scoped only
- [ ] Connected state with `last_sync_at`
- [ ] **Disconnect** button with a confirm step, wired to the delete endpoint
- [ ] Never render a token back to the user after saving
- [ ] Ed / Stellic connector rows — **P1**

## F5. Phone-specific polish — P1

The app already runs on iOS and Android from the same code as web, so there is no
separate mobile port to build. What is left is phone-specific behaviour:

- [x] Shared `api.ts`, citation parity, citation list, tappable links, mock badges,
      freshness timestamps, credits footer — all done once in `frontend/app/`
- [ ] Test on a real phone via Expo Go (needs `EXPO_PUBLIC_API_URL` set to your LAN IP
      in `frontend/app/.env` — see README troubleshooting)
- [ ] Keyboard handling: the input shouldn't be hidden behind the on-screen keyboard
      (`KeyboardAvoidingView`)
- [ ] Safe-area padding on notched devices (partly handled via `useSafeAreaInsets`)
- [ ] Pull-to-refresh on the answer view
- [ ] Check tap targets are at least 44pt
- [ ] Verify against a **physical phone**: set `EXPO_PUBLIC_API_URL` to the laptop's LAN IP, restart Expo
- [ ] Example-query shortcuts sized for thumbs
- [ ] Dark mode — **P2**

## F6. Demo surfaces — P1

- [ ] A "how it works" panel showing the four modes from PRD §3 (RAG / live tools / web verify / personal)
- [ ] Source freshness page driven by `GET /api/sources/` — shows tier, access type, `indexed_at`
- [ ] Visible marker when an answer used a web-verify fetch ("re-checked against the live page")

---

## 3. Demo & submission — P0 (Day 5)

- [ ] Signature multi-hop query runs clean, end to end, from a cold start
- [ ] All five PRD §8 example categories rehearsed at least once
- [ ] Demo database seeded and committed/exportable — no live crawl during the demo
- [ ] Fallback plan if a public API is down mid-demo (cached responses ready)
- [ ] Screen recording of the signature query as a backup
- [ ] Credits copy present in the app **and** in the submission text
- [ ] Submission explicitly states we are unaffiliated consumers of ScottyLabs' public APIs
- [ ] README quick start verified from scratch on a teammate's clean machine
- [ ] `docker compose down -v && ./setup.sh` produces a working app

---

## 4. Guardrails — check before submitting

Straight from PRD §9. Any unchecked box here is a problem.

- [ ] No auth-walled content (SIO, Canvas, Stellic, Autolab) in the shared index
- [ ] `robots.txt` respected; crawler identifies itself; rate-limited
- [ ] No SSO scraping of 25Live or Handshake
- [ ] No student PII in the shared index
- [ ] Personal data is user-scoped only; disconnect deletes it
- [ ] Tokens treated as passwords: encrypted at rest, password-type inputs, never logged, never returned
- [ ] Every mock source is labelled as mock in the UI
- [ ] Every answer shows `indexed_at` / `verified_at`
- [ ] Nothing in the app or the pitch implies a ScottyLabs partnership
- [ ] `DJANGO_SECRET_KEY` changed before any shared deploy
- [ ] `.env` is gitignored; only `.env.example` is committed
- [ ] No grade writes, no auto-registration
