# Web verify (B3) and the citation contract

How a tool result becomes a `Citation`, and what binds the web-verify lane.

The code: [`citations.py`](../backend/apps/planner/citations.py) (the ledger),
[`loop.py`](../backend/apps/planner/loop.py) (`_harvest_web`, and the chip),
[`client.py`](../backend/apps/planner/client.py) (the toolset).

## The citation contract

`CitationLedger.record()` does not forward a tool's raw result to the model. For
each item in `result["citations"]` it rebuilds a new dict from scratch — only
`title`, `url`, `snippet`, `indexed_at`, `verified_at` and `source` survive.
Anything else on that item (a chunk's full text, prereqs, lat/lng, opening
hours) is dropped. Other top-level keys on the dict a tool returns pass through
untouched.

So a tool must not return `{"citations": [...raw items...]}` and nothing else —
that trades "no citations" for "citations the model cannot answer from." Two
shapes, one per kind of tool:

- **RAG.** The only content beyond the citation is the chunk's own text, and
  `snippet` is just a string, so the whole chunk goes there. A 300-character
  preview would throw away most of a retrieved passage before the model ever
  saw it.
- **Courses, dining, events, maps.** The extra content is structured (meeting
  times, hours, coordinates) and doesn't fit one string, so these return both
  `results` — the full normalized data, what the model answers from — and
  `citations`, one compact line per item for the ledger and the UI. Same data,
  two views.

Skipping this fails *silently*. An audit on 2026-08-16 found `campus_search` and
all four B2 tools running successfully and citing nothing: a bare list fails
`record()`'s `isinstance(result, dict)` guard, and a dict with no `citations`
key has nothing to harvest. Test that a `Citation` actually lands in
`turn.ledger`, not merely that no exception was raised.

## Where web citations come from

Anthropic runs `web_search` and `web_fetch` server-side under
`ANTHROPIC_API_KEY`, as part of the prebuilt `agent_toolset_20260401`. There is
no third-party search provider and no second key. `loop.py` lights the
`web_verify` chip on `agent.tool_use` and closes it on the matching
`agent.tool_result`, which is also where `_harvest_web` reads results into the
ledger via `record_web()`. Those citations are never mock, carry `indexed_at:
None` (nothing was crawled), name the producing tool as their `source`, and get
a `verified_at` we stamp — the API does not supply one. They dedupe by url: one
search returns several results and the model may cite one across two calls, and
`S3` has to mean one source everywhere it is referenced.

**The results are on `agent.tool_result`, not `agent.message`.** On the raw
Messages API, text blocks carry per-sentence `web_search_result_location`
citations — the better source, since the snippet is tied to the sentence the
model actually wrote — but under Managed Agents an `agent.message` text block
carries `text` and nothing else. If an SDK version bump moves something, the
answer is in its generated models:

    anthropic/types/beta/sessions/beta_managed_agents_agent_message_event.py
    anthropic/types/beta/sessions/beta_managed_agents_agent_tool_result_event.py

A `web_fetch` result does not name the page it read, so the harvest keeps each
`agent.tool_use`'s input and falls back to the url that was asked for.

### Search is the expensive lane

One searching query measured **~35.9k input tokens and ~26 seconds**, and those
results then sit in the message list and are re-sent as input on *every*
subsequent call in that turn — the cache breakpoint is on the system block, so
nothing in message position is ever cached. A four-hop answer that searched once
pays for it four times. The index is the default; verify only when it has
nothing or the page is genuinely stale ([`../tasklist.md`](../tasklist.md) §1).

There is no per-call cap to reach for: the prebuilt toolset takes no `max_uses`
or `max_content_tokens`. The runaway bound is `client._budget()`, a dollar
ceiling on the whole session — the thread, not one question — and
`_MAX_WEB_CITATIONS` bounds how many web sources a turn can put in front of the
model.

### No domain filters

`provision_planner.ENVIRONMENT_CONFIG` is `{"type": "cloud", "networking":
{"type": "unrestricted"}}`, and the prebuilt toolset exposes no allowlist or
denylist surface — its per-tool `configs` only enable or disable a tool by name,
which is how unchecking web verification switches the pair off. PRD §6's
exclusion of Canvas/SIO/Stellic holds because `web_fetch` carries no
credentials, never because of a host filter.

The Messages API tools *do* take `allowed_domains` / `blocked_domains`, and
those were verified live rather than read off a docs page: a search restricted
to `cs.cmu.edu` returned 30 hits with **zero** off-domain leaks, and a blocked
fetch of `canvas.cmu.edu` failed with `url_not_allowed` while the same url under
a *non-covering* denylist failed with `url_not_accessible`. Two different codes,
so the denylist did real work rather than coinciding with Canvas being
login-walled — the control is the whole test, because Canvas fails either way.
That surface is not on offer through the prebuilt toolset, so reviving it is a
provisioning-level conversation, not a code change here. See
[`dependencies.md`](./dependencies.md).

### Two wiring traps

- **Do not declare `code_execution` alongside the web pair.** Dynamic filtering
  is built into the tools, and a second execution environment confuses the model.
- **`pause_turn`.** A long search turn ends early and looks like a finished
  answer, so it has to be resumed or the demo silently truncates. Managed Agents
  owns the resume now — and this is why the SDK's `tool_runner` was rejected: it
  returns a paused turn as if finished, with no error.

### Staleness

`WEB_VERIFY_STALE_AFTER_DAYS` (default 30, in `.env.example`, passed through
`docker-compose.yml`) is the enforcement half of the RAG-first decision. The
number is *also* written out as prose in
[`prompt.py`](../backend/apps/planner/prompt.py), because the system prompt is
frozen on an agent version and cannot read a setting at request time. Changing
it means editing both and re-running `manage.py provision_planner`, which mints
a new agent version. Editing `prompt.py` alone changes nothing.

## Not verifiable from a checkout

- **Web search enabled for the org** — a Console toggle. The prebuilt toolset
  leads every session's tool list, so if it is off, *every* request 400s, not
  just searching ones. Check it by running one real query through `/api/ask/`
  that has to search.
- **One live end-to-end run** — a question the index and the live tools cannot
  answer, coming back with a citation carrying a real url, a real `verified_at`,
  and `web_verify` in `modes_used`.

## What the tools return, and the upstream quirks behind it

Every tool below returns `results` + `citations` (RAG returns `citations` with
the full chunk as the snippet). The details are commented in the code; what
follows is the shape of each upstream, because none of it is guessable.

| Tool | Upstream | What it forces |
|---|---|---|
| `campus_search` | pgvector + Postgres FTS | The whole chunk is the `snippet` — it is the model's only grounding text, since `text` is dropped by the ledger |
| `search_courses`, `get_course` | `course-tools.apis.scottylabs.org` | `/courses/search` pages at 10 docs, filters nothing server-side, and reshuffles equally-ranked results between calls, so a filtered search has to read every page; `units` arrives as a string (`"12.0"`); an unknown course number comes back as a bare 500, not a 404; meeting times exist only behind `/schedules?courseID=...`, where `days` are ints — 1=Monday … 5=Friday, the only values seen across 60 sampled courses; no confirmed public per-course page, so the citation carries no url |
| `find_dining` | CMU Eats | No public per-location page, so no url |
| `find_events` | TartanConnect mobile feed | JSON in transport only: a row names its columns in a `fields` string and sends the values as `p0`, `p1`, …, several of them HTML fragments. Read by name it yields 31 blank events. The one live tool with a real permalink to cite |
| `nearby`, `walk_time`, `find_place` | `api.maps.scottylabs.org` | 74 buildings keyed by code, each with label coordinates; `/search` outranks buildings with rooms, and returns Hamerschlag *House* for "hamerschlag" and Posner *Center* for "posner", so resolution consults a curated alias table first. `/path/public` routes only when Cohon University Center is the destination — unusable as a router, so walking times are straight-line estimates and every citation says so |
| `course_requisites`, `find_geneds` | `course-tools.apis.scottylabs.org` | `/courses/requisites/{id}` is the only source of `postreqs` (what a course unlocks). `GET /geneds?school=` is published for SCS, CIT and MCS only; the others answer 200 with `[]`, which would read as "no gen-eds" rather than "not published". Its `fces` field is always empty without a token |

## Out of scope

- **`resolve_course_site`** — the static Appendix B map (PRD §6). Useful, but it
  doesn't touch citations. P1.
- **Enqueuing discovered urls into `CrawlSeed`** — the crawler reads seeds only;
  nothing writes back what web verify found.
