# AskScotty — Build Checklist

Working checklist derived from [PRD.md](./docs/PRD.md). Tick boxes as you go.

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
- [ ] Read [PRD.md](./docs/PRD.md) §2 (signature query) and §9 (P0 scope) end to end
- [ ] Read [CLAUDE.md](./CLAUDE.md) — how the repo is laid out and the rules AI assistants must follow
- [ ] Skim `backend/apps/core/views.py` and `frontend/app/app/index.tsx` — that's the whole app today
- [ ] Pick a lane below and put your name on the tasks

---

## 1. Shared decisions — settled ✅

These blocked both sides. **Decided — do not re-litigate without editing this section.**

- [x] **Freeze the `/api/ask/` response contract** (see §2 below). Frontend codes against it; backend fills it in.
- [x] **LLM + model:** Anthropic **`claude-sonnet-5`** (`PLANNER_MODEL` in `.env`). The planner is mostly routing and tool selection rather than deep reasoning, and Sonnet is roughly half Opus's cost per token. Switch the env var to `claude-opus-5` if multi-hop answers come out weak — no code change needed.
- [x] **Embeddings:** OpenAI **`text-embedding-3-small`**, 1536 dimensions (`OPENAI_API_KEY`, `EMBEDDING_MODEL`). Anthropic has no embeddings endpoint, so this is a second provider for one narrow job. Dimensions must match the pgvector column, so changing the model means a migration *and* a full re-index.
- [x] **Web search: none — use Claude's built-in `web_search` / `web_fetch`.** *(Reversed 2026-08-15; was Tavily.)* These are **server-side** tools: declare them in the `tools` array and they run on Anthropic's infrastructure under `ANTHROPIC_API_KEY`. No second provider, no second key, no client to write. Verified live on `claude-sonnet-5` — `allowed_domains` gives B3's site-filtered search with zero off-domain leaks, and `blocked_domains` refuses Canvas with a distinct `url_not_allowed` (vs `url_not_accessible` when the denylist doesn't cover it), which is PRD §6's denylist enforced by the API. **Budget for it:** one searching query cost ~35.9k input tokens / ~26s. Use `max_uses` and `max_content_tokens`, and only verify when the index is actually stale.
- [x] **Vector store:** **pgvector** in the existing Postgres. Fewer moving parts, and `docker compose down -v && ./setup.sh` still has to work on a teammate's laptop. *(The extension still needs enabling on the DB — tasklist B0.)*
- [x] **Auth scope:** **anonymous session id**, passed as `session_id` in the request body. The app generates one and keeps it on the device; no login screen to build. Trade-off, stated plainly: anyone who learns a session id can read that session's connected data. It is a bearer token, not an identity — real accounts are the upgrade path if this outlives the hackathon.
- [x] Add every new key to `.env.example` (never `.env`) and post it in the team chat

**How the toolset is assembled** (`backend/apps/tools/registry.py`): tools register themselves with `@register_tool(name, description, json_schema, mode, is_mock=False, requires_connector=None)`. `tools_for_session(session_id)` returns the public tools plus any personal ones that session has actually connected — so a tool the planner is never told about is a tool it cannot call. Public tools never receive `session_id`, which is the mechanical version of PRD §3's "personal data never enters a shared-index call".

---

## 2. The API contract (owned by both sides) — frozen ✅

Frontend and backend both code against this. Change it only by editing this section and telling everyone.

Defined in `backend/apps/core/serializers.py` and `frontend/app/lib/types.ts`. The
backend validates its own responses against the serializers before returning them,
so a malformed answer fails in the backend rather than rendering wrong in the app.

- [x] `POST /api/ask/` request grows from `{query}` to `{query, session_id?, history?}` — `history` is `[{role: "user"|"assistant", content}]`, oldest first, max 40 turns
- [x] Response keeps `answer`, `citations[]`, `modes_used[]`, `note` (`note` is nullable)
- [x] Each citation carries `title`, `url`, `source`, `indexed_at`, `verified_at` (PRD §3 — every answer shows freshness)
- [x] Add `is_mock: bool` to each citation so the UI can badge mock sources
- [x] `modes_used` values are fixed strings: `rag` · `courses` · `dining` · `events` · `maps` · `web_verify` · `personal` — validated server-side against `MODES` in `backend/apps/tools/registry.py`
- [x] **Error shape:** `{"error": {"code", "message"}}` with a real HTTP status, for every failure. Codes: `validation_error` · `unauthenticated` · `forbidden` · `not_found` · `method_not_allowed` · `unsupported_media_type` · `rate_limited` · `upstream_error` · `unavailable` · `timeout` · `error`. See `backend/apps/core/errors.py`.
- [x] **Streaming: no.** Non-streaming for P0 — one request, one JSON answer. The app reports which modes ran from `modes_used` after the fact. Revisit only if the demo feels slow, and agree SSE here first.
- [x] Add `GET /api/sources/` returning the source registry (`name`, `tier`, `access`, `indexed_at`, plus `implemented` and `note`) — powers the credits/freshness UI
- [x] **Chat history endpoints.** `GET /api/threads/` → `{threads: [{id, messages, updated_at}]}` · `PUT /api/threads/{id}/` (upsert, body `{messages}`) · `DELETE /api/threads/{id}/`. A message is `{role, content}` where `content` is assistant-ui's *parts* array, not a string — that is what keeps citations alive across a reload. Scoped by an **`X-Session-Id` header**, not the body: it is a bearer token and query strings end up in server logs. Missing header → `validation_error`.
- [x] Update the API table in [README.md](./README.md) when this changes

---

# BACKEND

Django 5.1 + DRF + Postgres. Everything lives under `backend/`. Code is bind-mounted, so edits reload.

## B0. Foundations — P0

- [x] Add planner/RAG deps to `backend/requirements.txt` (LLM SDK, HTTP client, crawler, embeddings, `pgvector`)
- [x] Rebuild the backend image after changing requirements: `docker compose build backend`
- [ ] Enable the `pgvector` extension on the Postgres container (migration or init SQL)
- [ ] Create `backend/apps/rag/` app (crawler, chunker, index, `campus_search`)
- [x] Create `backend/apps/tools/` app (live tools + mocks + web verify) — registry + source registry done; the tools themselves are B2
- [ ] Create `backend/apps/planner/` app (orchestration)
- [x] Create `backend/apps/personal/` app (user-scoped connectors)
- [x] Register new apps in `backend/config/settings.py` `INSTALLED_APPS`
- [x] Add a settings block for external API keys, read from env with safe defaults
- [ ] Add a shared HTTP client helper: timeout, retry, identifying User-Agent, per-host rate limit
- [ ] Add a response cache (per-tool TTL) so demo reloads don't hammer public APIs
- [ ] Add structured logging for every tool call: tool name, args, latency, cache hit/miss — name/mode/latency/outcome done in `tools/registry.py:run_tool`; cache fields pending the cache. **Args are deliberately not logged** (a personal tool's args can identify a student).

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

**No search provider to integrate.** Claude's server-side `web_search_20260318` /
`web_fetch_20260318` do this lane — the work here is wrapping them as tools in our
registry with the right domain lists, not writing an HTTP client. Both take
`allowed_domains`, `blocked_domains`, `max_uses`, `max_content_tokens`.

- [ ] `fetch_url(url)` — wrap `web_fetch` with an **allowlist** of public hosts (`allowed_domains`)
- [ ] Explicit denylist so Canvas / SIO / Stellic can never be fetched here (`blocked_domains`, PRD §6) — assert on `url_not_allowed` in a test
- [ ] Return `verified_at` on every fetch — ours to stamp; the API doesn't supply it
- [ ] `web_search(query, site?)` — wrap `web_search`; `site` maps to `allowed_domains`
- [ ] Cap cost/latency per call (`max_uses`, `max_content_tokens`) — one search measured ~35.9k input tokens / ~26s
- [ ] Do **not** declare `code_execution` alongside these — dynamic filtering is built in, and a second execution environment confuses the model
- [ ] Handle `pause_turn`: a long search turn ends the loop early and looks like a finished answer. Resume it, or the demo silently truncates.
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
- [x] Multi-turn: keep a question/answer history in the page — threads persist to `GET/PUT/DELETE /api/threads/`, scoped to the device's anonymous session (`lib/session.ts`). Saves are debounced ~600ms and skip empty threads, so "New Chat" doesn't create a row for a conversation that never happened. **Still open:** the adapter does not yet send `history` on `/api/ask/`, so the *planner* has no memory across turns even though the UI does — see the next box.
- [ ] Send prior turns as `history` in the ask request so follow-ups ("what about Friday?") work — backend already accepts it (max 40 turns); `createHttpAdapter` currently forwards only the latest user message
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
