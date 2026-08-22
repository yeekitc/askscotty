# AskScotty — Build Checklist

Working checklist derived from [PRD.md](./docs/PRD.md). Tick boxes as you go.

**Where things are**

| | |
|---|---|
| **§0. Everyone — first hour** | setup, and what to read before writing anything |
| **§1. Shared decisions — settled** | model, embeddings, vector store, web search, auth scope |
| **§2. The API contract — frozen** | request/response shapes both sides code against |
| **B0–B6** | backend: foundations · RAG · live tools · web verify · planner · connectors · ops |
| **F0–F6** | frontend: foundations · ask flow · citations · polish · connectors · phone · demo |
| **§3. Demo & submission** | the run-through |
| **§4. Guardrails** | PRD §10, checked before submitting |

**How to use**

- Claim a task by appending your name: `- [ ] Wire `campus_search` — @yeekit`
- Commit the checked box in the same PR as the work, so `main` always shows real state.
- `P0` = required for a working demo · `P1` = strong submission · `P2` = stretch / pitch-only.
- Anything marked **Mock** must be visibly labelled as mock in the UI (PRD §10).

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
- [x] **Web search: Claude's built-in `web_search` / `web_fetch`, no separate provider.** They are **server-side** tools that run on Anthropic's infrastructure under `ANTHROPIC_API_KEY` — no second key, no client to write. **No domain filters:** the built-in toolset the planner runs on is not known to accept `allowed_domains` / `blocked_domains`, and PRD §6 holds without them — `web_fetch` carries no credentials, so Canvas / SIO / Stellic have nothing to give it. Source choice is steered by prompt guidance seeded from PRD Appendix B instead. The risk that accepts is written up in [docs/b4-planner.md](./docs/b4-planner.md) §4.
- [x] **RAG takes precedence over web search.** The index is the default; web verify is the fallback, not the reflex. It is a cost decision with a measured number behind it: one searching query is **~35.9k input tokens and ~26 seconds**, and those results then sit in the message list and are re-sent as input on *every* subsequent call in that turn — our cache breakpoint is on the system block, so nothing in message position is ever cached. A four-hop answer that searched once pays for it four times. Enforced in three places, weakest to strongest: the tool description (which is what actually decides whether the model picks it), the lane ordering in the system prompt, and `max_uses` as the only hard cap. Search when the index has nothing or the page is genuinely stale — see [docs/b3-web-verify.md](./docs/b3-web-verify.md).
- [x] **Vector store:** **pgvector** in the existing Postgres. Fewer moving parts, and `docker compose down -v && ./setup.sh` still has to work on a teammate's laptop.
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
- [x] **Each citation also carries `id` and `snippet`** — both live in the serializer
      and `types.ts`, both defaulting to `""`.
      `id` is the stable handle the planner issues (`"S1"`, `"S2"`, …) and the *only*
      thing the model ever writes about a source, so it can neither invent one nor
      relabel a mock as live (PRD §10 by construction). It is explicit rather than
      positional so that filtering the citation list later cannot silently rebind
      every marker; the planner assigns it and a tool never sets it.
      `snippet` is the supporting excerpt, `""` when there isn't one: `campus_search`
      returns the matched chunk, the live tools a one-line rendering of the row they
      matched, web verify the excerpt the API already gives us. `domain` is *not*
      stored — derive it from `url` at render time.
      See [docs/b4-planner.md](./docs/b4-planner.md).
- [ ] **Proposed: add `artifacts: []` to the response — the empty seam only.** Some
      answers want to be more than prose: a campus map with a route, a study plan you
      can tick off, a schedule grid. Adding the (always empty) array and its
      discriminated-union type costs nothing now and makes the first real artifact an
      additive change rather than a contract renegotiation during demo week. **No
      artifact types are proposed here** — only the channel. Two rules travel with it
      because the PRD forces them: an unknown `type` must never crash an older client
      (so every artifact carries `fallback_text`), and anything derived from a
      personal tool is session-scoped like everything else user-scoped (PRD §7).
      See [docs/artifact-plan.md](./docs/artifact-plan.md), a draft that marks what is
      fixed vs. still open.
- [x] `modes_used` values are fixed strings: `rag` · `courses` · `dining` · `events` · `maps` · `web_verify` · `personal` — validated server-side against `MODES` in `backend/apps/tools/registry.py`
- [x] **Error shape:** `{"error": {"code", "message"}}` with a real HTTP status, for every failure. Codes: `validation_error` · `unauthenticated` · `forbidden` · `not_found` · `method_not_allowed` · `unsupported_media_type` · `rate_limited` · `upstream_error` · `unavailable` · `timeout` · `error`. See `backend/apps/core/errors.py`.
- [x] **Streaming: SSE, as progress events — `POST /api/ask/stream/`.**
      Events are `mode_start` / `mode_end` to drive the mode chips (F1 calls that the
      demo's wow moment), `text_delta`, and a final `done` carrying **the same
      validated `AskResponse` the plain endpoint returns**. That keeps SSE strictly
      additive: `POST /api/ask/` stays as the non-streaming fallback and the
      serializer validates either way.
      `text_delta` is *provisional* text — drop what has streamed when a `mode_start`
      arrives (it was preamble to a lookup) and let `done` replace it. Expect a
      handful of chunks, not a typewriter; the API batches its own output.
      **POST, not GET**, because the body carries `query`/`history` and `EventSource`
      is GET-only and absent on React Native. Transport is **XMLHttpRequest**, not
      `fetch`: RN's fetch is the whatwg-fetch polyfill, which exposes no
      `response.body`, so streaming is unreadable on iOS/Android. XHR works on all
      three, so it is one code path (`askEvents` in `lib/api.ts`).
      The backend uses `messages.stream()` internally for long turns — invisible to
      the app. See [docs/b4-planner.md](./docs/b4-planner.md).
- [x] Add `GET /api/sources/` returning the source registry (`name`, `tier`, `access`, `indexed_at`, plus `implemented` and `note`) — powers the credits/freshness UI
- [x] **Chat history endpoints.** `GET /api/threads/` → `{threads: [{id, title, messages, updated_at}]}` · `PUT /api/threads/{id}/` (upsert, body `{messages, title?}`) · `DELETE /api/threads/{id}/`. `title` is set only by an explicit rename — blank means the app derives it from the first message — and it is **optional on PUT**, where an omitted key leaves a stored rename alone and `""` clears it. A message is `{role, content}` where `content` is assistant-ui's *parts* array, not a string — that is what keeps citations alive across a reload. Scoped by an **`X-Session-Id` header**, not the body: it is a bearer token and query strings end up in server logs. Missing header → `validation_error`.
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
- [x] Create `backend/apps/planner/` app (orchestration)
- [x] Create `backend/apps/personal/` app (user-scoped connectors)
- [x] Register new apps in `backend/config/settings.py` `INSTALLED_APPS`
- [x] Add a settings block for external API keys, read from env with safe defaults
- [x] Add a shared HTTP client helper: timeout, retry, identifying User-Agent, per-host rate limit — `apps/core/http.py:get_json`, the one place `httpx` is imported. GET only; every known caller is a read.
- [x] Add a response cache (per-tool TTL) so demo reloads don't hammer public APIs — same function, `ttl=` per call. Django's default `LocMemCache`, so a second worker won't share a hit; accepted at this scale rather than adding Redis. **Defaults to off:** the key is only `(url, params)`, so caching an authenticated response would collide across students (PRD §9).
- [x] Add structured logging for every tool call: tool name, latency, cache hit/miss — name/mode/latency/outcome in `tools/registry.py:run_tool`; cache hit/miss is its own `http_cache` line from `core/http.py`, because tool dispatch runs in a thread pool and contextvars don't cross it. **Args are deliberately not logged** (a personal tool's args can identify a student). `settings.LOGGING` has to name `apps.*` explicitly — Django configures only the `django` logger, so anything else logs into the void.

## B1. Campus index / RAG — P0 (Days 1–2)

**Models**

- [ ] `Document` model: `url`, `title`, `source_tier`, `fetched_at`, `content_hash`, `robots_allowed`
- [ ] `Chunk` model: FK to `Document`, `text`, `token_count`, `embedding` (vector), `heading_path`
- [ ] `CrawlSeed` model: `url`, `label`, `enabled`, `last_crawled_at`
- [ ] Migrations written and applied

**Crawler**

- [ ] Seed loader for Appendix B course sites (all 10 URLs from the PRD)
- [ ] Seed loader for public `cmu.edu` sections: HUB, colleges, Student Affairs, CPDC, Housing, Health Services, `/about`, `/academics`
- [ ] Seed loader for Computing Services + public KB (`computing.cmu.edu`) — the "how do I connect to the VPN" lane
- [ ] Seed loader for the course catalog (`coursecatalog.cmu.edu`) — degree requirements, our only public substitute for Stellic
- [ ] Seed loader for the non-SCS college sites (`cit`, `dietrich`, `tepper`, `cfa`, `mcs`, `heinz`) — Appendix B only covers SCS
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
- [x] `campus_search(query, k, filters)` tool function — returns `{citations: [...]}`, not a bare list, or `CitationLedger` drops every hit
- [x] Every result returns `url` + `indexed_at` (PRD §4) — and the whole chunk as `snippet`, which is the only grounding text the model gets to answer from
- [x] Management command `python manage.py reindex` — `apps/rag/management/commands/reindex.py`
- [x] Ship a pre-built index so the demo doesn't depend on a live crawl — `backend/fixtures/rag_index.sql.gz` (174 docs / 1,439 embedded chunks), restored by `setup.sh` only when the index is empty

**HKN / LibGuides — P1**

- [ ] Crawl HKN ECE/CS Guide (public GitHub Pages)
- [ ] Crawl public LibGuides

## B2. Live tools — P0 (Days 1–2)

**Courses** (`course-tools.apis.scottylabs.org`, no auth)

**Endpoint facts, verified live against the real API.** An unknown course number
comes back as a bare 500, units are strings, meeting days are ints, and meeting
times exist only behind `/schedules?courseID=...`. The rest is in the module
docstring of [`backend/apps/tools/courses.py`](./backend/apps/tools/courses.py) —
read it before changing anything here.

- [x] Client for `/courses/search`, `/course/{id}`, `/schedules` — through `apps.core.http.get_json`
- [x] Normalize to an internal shape: number, title, units, instructors, meeting times, prereqs
- [x] `search_courses(query, units?, days_excluded?, semester?)` tool
- [x] `get_course(course_number)` tool — merges `/course/{id}` with `/schedules?courseID=...`, which is the only place instructors and meeting times exist
- [x] Filter support for "9-unit ML elective, no Friday" (PRD §8) — `units` filters client-side, because the API's own `units` param does nothing. A filtered search reads every page (~7s, capped at 30): the endpoint pages at 10 *and* shuffles equally-ranked results, so a shallow read answers the same question differently each time
- [x] Handle upstream 4xx/5xx gracefully — degrade, don't crash the answer

**Dining** (`api.cmueats.com/v2/locations`)

- [x] Client for the v2 locations endpoint (do **not** use the deprecated `dining.apis` endpoint)
- [x] Parse per-location open/close windows into a queryable form
- [x] `find_dining(open_at?, near?, limit?)` tool
- [ ] "Open after 8:20 near Wean" works end to end (joins with mock Maps)

**Events** (`tartanconnect.cmu.edu/mobile_ws/v17/mobile_events_list?range=0`)

- [x] Client for the mobile events JSON feed
- [x] Normalize: title, start/end, location, org, categories, link — the feed is JSON in transport only: a row names its columns in a `fields` string and sends the values as `p0`, `p1`, …, with dates as HTML
- [x] `find_events(before?, after?, keywords?, limit?)` tool
- [ ] Keyword match for "startup" / "AI" hits the signature query — **blocked on the feed, not the matcher.** Matching is word-start, so "startup" finds "startups" and "AI" does not fire on "the FAIR". But the feed carries only **~21 upcoming events**, about a week out, and `range` slides that window rather than paging it, so neither demo keyword hits anything today. Needs a second events source

**Maps — Mock**

- [x] Fixture file with ~10 landmark buildings: name, aliases, lat/lng
- [x] Adjacency / walking-minutes table between landmarks
- [x] `nearby(building, radius_or_minutes)` tool
- [x] `walk_time(a, b)` tool
- [x] Every Maps result flagged `is_mock: true` — on the result *and* the citation, the latter from the tool's own registration rather than anything the fixture claims
- [x] Cover the buildings the demo needs: Gates, Wean, Doherty, Tepper, UC, Hunt, Baker, Posner, Cohon, Hamerschlag

**25Live — Mock, P1**

- [ ] Fixture of room availability windows for demo buildings
- [ ] `find_free_room(near, duration_minutes, after)` tool
- [ ] Flagged `is_mock: true`; no SSO scraping (PRD §9 non-goals)

**Handshake / FCE — Mock, P1**

- [ ] Handshake events fixture, or `Link`-out only
- [ ] FCE ratings fixture for a handful of courses
- [ ] Both flagged `is_mock: true`

## B3. Web verify — P0 (Day 3)

**No search provider to integrate, and no tool to declare.** The planner runs on
the built-in `agent_toolset_20260401`, which already contains `web_search` /
`web_fetch`, so this lane arrives with the platform. There is no HTTP client to
write and no wrapper tool of ours in the registry.

**No domain filters**, so there is no allowlist or denylist to build: `web_fetch`
carries no credentials, so Canvas / SIO / Stellic return login pages either way and
PRD §6 is satisfied by that. Source choice is prompt guidance seeded from PRD
Appendix B. One thing still to check: whether environment
`networking.allowed_hosts` gates the built-in tools — that is the anti-exfiltration
control, not a quality one.

📋 **[docs/b3-web-verify.md](./docs/b3-web-verify.md)** — the result blocks to
parse, what B4 already handles so it does not get rebuilt, and its Status
section for what is still open.

- [ ] Test the *outcome* an allowlist would have given: a Canvas / SIO / Stellic fetch returns no usable content
- [x] Harvest `web_search` / `web_fetch` results into the ledger, deduped by url — nothing read them before, so the verify chip lit on an answer that cited nothing. The blocks come back on `agent.tool_result`; under Managed Agents an `agent.message` text block carries no per-sentence citations to prefer
- [x] Return `verified_at` on every fetch — ours to stamp; the API doesn't supply it
- [ ] `web_search(query, site?)` — wrap `web_search`; `site` becomes a `site:` prefix in the query, not `allowed_domains`
- [ ] Cap cost/latency per call (`max_uses`, `max_content_tokens`) — one search measured ~35.9k input tokens / ~26s
- [ ] Do **not** declare `code_execution` alongside these — dynamic filtering is built in, and a second execution environment confuses the model
- [x] Handle `pause_turn` — a long search turn ends early and looks like a finished answer, so an unresumed one truncates the demo silently. **Nothing to build: the platform owns the resume.** Don't reintroduce it
- [ ] `resolve_course_site(course_number)` — static map from Appendix B
- [x] Staleness policy: define what `indexed_at` age triggers a verify fetch (`WEB_VERIFY_STALE_AFTER_DAYS`) — the enforcement half of §1's RAG-first decision. The number is also prose in `prompt.py`, because a versioned system prompt cannot read a setting at request time; changing it means re-running `provision_planner`
- [ ] Confirm web search is **enabled for the org** before demo day: if an admin disabled it in the Console, *declaring* the tool is a 400, so every request fails rather than just searching ones. No kill-switch setting for this (decided) — it is our own org, so the fix is a Console toggle, and a flag nobody remembers to flip is not insurance
- [ ] Enqueue newly discovered URLs into `CrawlSeed` for the next crawl (PRD §6 planner default)

## B4. Planner — P0 (Days 1–2, then Day 4)

Lives in `backend/apps/planner/`. `run_planner` is a **generator** — it yields
progress events and finishes by yielding the validated `AskResponse`, which is
why `/api/ask/` and `/api/ask/stream/` are two thin wrappers over one loop.

**The loop runs on Managed Agents** — Anthropic drives it, we execute the tools it
asks for. It is the only path: a hand-written fallback would lack the web tools and
so could only answer uncited. The platform costs **~2× end to end and ~4× to first
token** against a hand-driven loop; the numbers, the four things the build turned
up, and the mitigations are in [b4-planner.md](./docs/b4-planner.md).

**One addition to §2, additive:** the ask request takes an optional `thread_id`.
The backend keeps one planner session per thread and has nothing to key that
session on without it, so a follow-up would start the conversation over. Omitting
it is still valid; response shapes and every SSE event are unchanged.

- [x] Replace the `AskView` stub in `backend/apps/core/views.py` with the real planner
- [x] Register every tool with the LLM as tool definitions (name, description, JSON schema)
- [x] Agentic loop: a drain loop over the session's event stream. There is no iteration cap or wall-clock deadline — the session's dollar `budget` is the runaway bound
- [x] System prompt: CMU context, cite everything, label mocks, never invent facts
- [x] Collect citations from every tool result into the response
- [x] Populate `modes_used` from which tool families actually ran — successful calls only, so a chip never claims a lane that failed
- [x] Graceful degradation when a tool hangs — **resumability rather than partial prose**: a session has no `tool_choice` to force a wrap-up call with, but a slow answer is resumable rather than lost, and `budget` bounds the runaway case
- [x] Never let personal data enter a shared-index call (PRD §10) — every dispatch goes through `run_tool`, which is what withholds `session_id` from public tools
- [x] Parallel tool dispatch, with **all** results returned in one send. The distinction is easy to lose and expensive to get wrong: the platform batches the model's tool *requests*, but every one of them still executes in our process, so serial dispatch costs the sum of a batch rather than its slowest member — measured at **3.0×** on a three-tool batch. Citations are harvested in call order rather than completion order, so `S1` means the same source on every run
- [x] A failed tool comes back as a `tool_result` with `is_error`, never a dropped block
- [x] Prompt caching: frozen system prompt on the agent version, the clock in the user turn, the session caching its own prefix — confirmed live via `cache_read_input_tokens`
- [x] Loop tests against a scripted **event stream** and a tool registered in the test (`apps/planner/tests.py`)
- [x] `Thread.cma_session_id` — one planner session per thread, so a follow-up reuses the previous turn's lookups instead of re-searching
- [x] Inline `[S1]` markers — behind `PLANNER_CITATION_MARKERS`, which defaults on now that F2 renders a marker as a chip. Marker rules stay in the prompt whatever the flag says, so turning it off strips markers rather than changing how the model writes
- [x] Server-side web tools — there is no `web_search_tool_result` block to parse under Managed Agents; results arrive as an `agent.tool_result` **event** and are harvested into the ledger from there. Only the web pair earns a chip — `bash` and the file tools come with the prebuilt toolset and the planner has no use for them
- [x] **Signature multi-hop works**: "I get out of 15-213 at 4:20 tomorrow. Find somewhere nearby to eat and then an interesting startup or AI event before 8." → Courses → Maps → Dining → Events. Verified end to end from a cold start: three lanes dispatched through `run_tool`, three citations, `modes_used` correct
- [ ] Verify each PRD §8 example query returns something sane

## B5. Personal connectors — P0/P1 (Day 5)

📋 Three docs cover this lane:

| Doc | Covers |
|---|---|
| [docs/b5-connections.md](./docs/b5-connections.md) | the connections contract and endpoint every connector is built on |
| [docs/b5-piazza-gradescope.md](./docs/b5-piazza-gradescope.md) | Piazza and Gradescope |
| [docs/b5-canvas-ed-stellic.md](./docs/b5-canvas-ed-stellic.md) | Canvas, Ed Discussion, and the Stellic mock |

Every connector lives in `apps/personal/tools.py`, so one module docstring covers
every credential model. **Piazza and Gradescope authenticate with the student's
real password rather than a token** — an explicit accepted risk, argued in the
opening section of their doc, and not the pattern to copy for a new connector.
Stellic is a mock, with no real integration, by explicit direction.

- [x] `UserConnection` model: user/session, provider, encrypted token, `connected_at`, `last_sync_at` — `apps/personal/models.py`
- [x] Encrypt tokens at rest; never log them; never return them in any API response — `apps/personal/crypto.py`
- [x] `GET`/`POST /api/connections/` (list, connect), `DELETE /api/connections/{provider}/` (disconnect)
- [x] **Disconnect deletes all synced data** (PRD §7 — required)
- [x] Piazza (`piazza_list_classes`, `piazza_search`) and Gradescope (`gradescope_get_assignments`) — **P1**
- [x] Confirm a real CMU Piazza/Gradescope login is not interrupted by Duo — **verified live 2026-08-18**: both log in with email/password, no 2FA step; Piazza search returns a bare list, snippet key is `content_snipet`, class URL confirmed (`scripts/check_connector_login.py`)
- [x] `get_json` accepts an `Authorization` header, and a header structurally disables caching (Part 0 of the doc — the identity-in-cache-key trap made unreachable, not just documented)
- [x] Canvas client against `canvas.cmu.edu/api/v1` using a student PAT — **P0** — verified live 2026-08-18 (9 courses, correct Bearer auth + citation URLs)
- [x] Canvas: courses, assignments + due dates (via `/planner/items`), **and announcements** (`/announcements`, both date bounds) — all verified live. Ed also has `ed_get_announcements` (threads where `type == "announcement"`, confirmed live)
- [ ] `personal_search(query)` tool, scoped to the current user only — not built (no doc covers it yet)
- [x] "What's due this week?" — `canvas_get_assignments` verified live against a real PAT (100 planner items, all with due dates)
- [x] Ed Discussion via settings API token — `ed_list_courses` + `ed_search_threads` — **P1** — verified live 2026-08-18 against a real token (courses resolve, threads return, no invented URL); token path works, no cookies needed
- [x] Stellic: mock degree audit — **P1** — mock only, no upload parser (by explicit direction; see doc)
- [~] "On track for CS minor?" — the pieces exist (`stellic_degree_audit` mock + live `search_courses`); not verified end to end
- [ ] Assert in code + test that personal chunks are never written to the shared index — belongs to `apps.rag`, not these connectors

## B6. Ops & pitch material — P1

- [x] Re-index job runnable on demand (manual is fine — PRD §9 says even manual counts) — `manage.py reindex`
- [ ] Record `indexed_at` per source and expose it via `GET /api/sources/`
- [x] Seed script that populates a demo-ready database in one command — `setup.sh` restores `backend/fixtures/rag_index.sql.gz` on first run, so a fresh clone can answer public questions without a live crawl
- [ ] Basic tests: one per tool, one planner smoke test on the signature query
- [ ] README section on how to run the crawl and re-index

---

# FRONTEND

**One** Expo + React Native codebase (`frontend/app/`) that runs on iOS, Android, and
the browser. There is no separate web project — editing a screen changes all three
surfaces at once. See [CLAUDE.md](./CLAUDE.md) for the component rules (`<View>` not
`<div>`, all text inside `<Text>`, `StyleSheet` not CSS).

## F0. Foundations — P0

- [x] Extract the inline `fetch` into `frontend/app/lib/api.ts`
- [x] Create a types file matching the §2 contract (`frontend/app/lib/types.ts`)
- [x] Add `is_mock` to the `Citation` type
- [x] Bring citation fields (`url`, `indexed_at`, `verified_at`) to parity — one codebase, so parity is automatic
- [x] Centralize `API_URL` handling and surface a clear error when the backend is unreachable — `lib/api.ts`
- [x] Client timeout is a **2-minute backstop** (`TIMEOUT_MS`), not the 30s it started as: one search turn alone measures ~26s, so 30s failed every multi-hop answer
- [ ] Keep `npx tsc --noEmit` clean

## F1. Ask flow — P0

- [x] Split the screen into components (`CitationCard`, `Credits` in `frontend/app/components/`)
- [x] Loading state that shows *which mode is running* (not just "Asking…") — the thinking indicator in `components/TypingIndicator.tsx`: running lanes by name, plus elapsed seconds. Progress rides `lib/progress.ts`, **not** the message channel: as assistant *text* it could be persisted by a debounced save firing mid-run, leaving "Checking Dining…" as somebody's stored answer. **Still a line, not chips** — see the next box, and it matters, because time-to-first-token is ~28s and this is what fills the wait
- [ ] Upgrade that line to labelled chips, reusing whatever `modes_used` renders
- [ ] Render `modes_used` as labelled chips (RAG · Courses · Dining · Events · Maps · Web verify · Personal)
- [ ] Error state: network failure, 4xx, 5xx, timeout — each with a distinct message
- [ ] Empty state before the first question, with 3–4 clickable example queries from PRD §8
- [ ] Pre-fill the signature query as the default (already done — keep it)
- [x] Multi-turn: keep a question/answer history in the page — threads persist to `GET/PUT/DELETE /api/threads/`, scoped to the device's anonymous session (`lib/session.ts`). Saves are debounced ~600ms and skip empty threads, so "New Chat" doesn't create a row for a conversation that never happened
- [x] Follow-ups ("what about Friday?") reach the planner — the adapter sends `thread_id` and the backend keeps one planner session per thread, so the previous turn's lookups are still in context. `history` on `/api/ask/` (max 40 turns) remains the stateless route for a caller with no thread
- [ ] Cmd/Ctrl+Enter submits

## F2. Web — citations & trust — P0

Freshness and honesty are the product's differentiator (PRD §3, §10). Don't cut these.

- [x] Every citation renders as a clickable link to its `url`
- [x] Show `indexed_at` and/or `verified_at` as human-relative text ("indexed 3 days ago", "verified just now") — hand-rolled in `CitationCard.tsx`; `Intl.RelativeTimeFormat` is not in Hermes
- [ ] Visible **Mock data** badge on any citation with `is_mock: true` — **not built, and it is the one open item that breaks a hard rule.** The backend half works: `is_mock` is stamped from the producing tool's registration and survives into `lib/types.ts`. It then reaches the console and nothing else, so a Maps, 25Live or Stellic answer is presented with nothing marking it as fixture data. PRD §10 rule 3 requires the label; this is a knowing deviation, not an oversight, and it is a `CitationCard` change
- [x] Group citations by source type — `components/CitationList.tsx`, rendered after the content because `renderSource` emits each source at its own position in the part list. **Folded by default** once the answer carries chips, to a row naming the count and the sources; open when it carries none, since there is then no inline route to a source. Freshness is a tap away rather than on screen — a knowing §10 deviation
- [x] Numbered inline markers in the answer body — **a chip that opens a source preview, not a jump link.** Tapping scrolls nobody anywhere; it opens the card over the answer, which is what a reader mid-sentence actually wants. `PLANNER_CITATION_MARKERS` is on
- [x] Credits footer — **attribution only, not the exact PRD §9 wording.** "We are not affiliated with ScottyLabs." is deliberately cut from the app for brevity and survives only in README.md. A knowing deviation from PRD §10 rule 9, alongside the mock badge
- [x] Footer is present on every screen, including mobile

**Markdown renders** in `lib/markdown.ts` + `components/AnswerText.tsx`, hand-rolled
rather than installed: the model writes bold, bullets and numbered lists, assistant-ui's
markdown package is React DOM, and `@assistant-ui/react-native` ships no renderer.
[dependencies.md](./docs/dependencies.md) records why the three RN markdown
libraries were all rejected.

**Everything above shares one seam**: `renderSpanText` in `AnswerText.tsx`, where
every leaf string becomes content. Both the word-at-a-time reveal and the `[S1]`
chips are transforms on exactly those words, so neither touches block layout. A
marker rides with the word before it rather than taking a reveal slot of its own,
so a citation never lands a tick ahead of the claim it supports.

**Still open on the chip:** its vertical nudge is unverified on a physical Android
device (correct on iOS and web) — F5 carries that check.

## F3. Web — polish — P0/P1

- [ ] Responsive down to a narrow laptop window (that's what the demo will run on)
- [ ] Keyboard accessible: focus states, labelled form controls, `aria-live` on the answer region (partly done)
- [ ] Sensible `<title>` and favicon
- [ ] Skeleton or shimmer while the answer loads
- [x] Answer text renders line breaks / lists readably (the planner will return structured prose)
- [x] Streamed answers arrive a word at a time (`lib/reveal.ts`) — the API batches its own output into a handful of lumpy chunks, so the smoothing is faked client-side. Ported from assistant-ui's `StreamingText`, which is DOM and cannot be installed
- [ ] Copy-answer-to-clipboard button — **P1**

## F4. Web — connectors UI — P0/P1

Shipped as `components/ConnectionsModal.tsx` rather than a `/settings` route. Its
forms mirror the backend's `CREDENTIAL_FIELDS`, so a provider that wants an email
and password says so plainly rather than dressing it up as a token.

- [x] A modal listing available connectors, with a row for each of Canvas, Ed, Piazza, Gradescope and Stellic — **P1** rows included
- [ ] **Token inputs are not masked** — **P0, and a guardrail miss.** The password field for Piazza/Gradescope sets `secureTextEntry`; the **access-token field for Canvas and Ed does not**, so a Canvas PAT renders in plain text on screen. PRD §10 rule 7 wants tokens treated as passwords. One prop
- [x] Clear copy explaining what is synced and that it is user-scoped only
- [x] Connected state with `last_sync_at` — "Connected · synced 3 days ago"
- [x] **Disconnect** button with an inline confirm step, wired to the delete endpoint
- [x] Never render a credential back to the user after saving — nothing here reads one, because no response carries one

## F5. Phone-specific polish — P1

The app already runs on iOS and Android from the same code as web, so there is no
separate mobile port to build. What is left is phone-specific behaviour:

- [x] Shared `api.ts`, citation parity, citation list, tappable links, freshness
      timestamps, credits footer — all done once in `frontend/app/`. **Mock badges
      are not among them** — see F2
- [ ] Verify against a **physical phone** via Expo Go: set `EXPO_PUBLIC_API_URL` to
      the laptop's LAN IP in `frontend/app/.env`, restart Expo — see README
      troubleshooting. The `[S1]` chip's vertical nudge is the specific thing to look
      at; it is correct on iOS and web and unverified on Android
- [ ] Keyboard handling: the input shouldn't be hidden behind the on-screen keyboard
      (`KeyboardAvoidingView`)
- [ ] Safe-area padding on notched devices (partly handled via `useSafeAreaInsets`)
- [ ] Pull-to-refresh on the answer view
- [ ] Check tap targets are at least 44pt
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

Straight from PRD §10. Any unchecked box here is a problem.

- [ ] No auth-walled content (SIO, Canvas, Stellic, Autolab) in the shared index
- [ ] `robots.txt` respected; crawler identifies itself; rate-limited
- [ ] No SSO scraping of 25Live or Handshake
- [ ] No student PII in the shared index
- [ ] Personal data is user-scoped only; disconnect deletes it
- [ ] Tokens treated as passwords: encrypted at rest, password-type inputs, never logged, never returned
- [ ] Every mock source is labelled as mock in the UI — **not met.** `is_mock` is stamped and plumbed all the way to the client; nothing renders it. See F2
- [ ] Every answer shows `indexed_at` / `verified_at` — rendered on every citation card, but the card list folds by default, so freshness is one tap away rather than on screen. See F2
- [ ] Nothing in the app or the pitch implies a ScottyLabs partnership
- [ ] `DJANGO_SECRET_KEY` changed before any shared deploy
- [ ] `.env` is gitignored; only `.env.example` is committed
- [ ] No grade writes, no auto-registration
