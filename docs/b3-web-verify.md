# Citations sweep: web verify (B3), RAG, and B2 live tools

Hand this to whoever (or whatever) does the work. Written to be pasted whole.

**Five independent fixes, safe to run in parallel** — different files, no
shared state, nothing here blocks anything else here:

| Part | Files | Bug |
|---|---|---|
| A | `apps/planner/loop.py`, `apps/planner/citations.py` | B3: web search/fetch results never reach the citation ledger |
| B | `apps/rag/tools.py`, `apps/rag/search.py`, `apps/rag/management/commands/load_seeds.py` | `campus_search` returns a bare list (same root cause as A); `load_seeds` is a `SyntaxError` |
| C | `apps/tools/courses.py` | Wrong endpoint, never calls `/schedules`, misdiagnoses a 500 as generic failure, dead filters, no citations |
| D | `apps/tools/dining.py`, `apps/tools/events.py` | Hand-rolled HTTP client, no citations |
| E | `apps/tools/maps.py` | No citations (otherwise clean) |

**Why this is one document instead of five:** all five are the *same* bug —
a tool result that doesn't reach `CitationLedger` — found independently in
five places by an audit on 2026-08-16. One fix pattern, repeated. If you're
splitting this across parallel agents, give each one this whole document (for
the shared pattern below) plus "you own Part X."

---

## Status: all five parts have landed

Every code change below is in. What is **not** done, and cannot be done from a
checkout:

- **Confirm web search is enabled for the org** — a Console toggle. If it is
  off, declaring the toolset 400s *every* request (see the section below).
- **The live end-to-end check** — one real query through `/api/ask/` that has
  to search, checked for a citation with a real url, a real `verified_at`, and
  `web_verify` in `modes_used`.
- **`manage.py provision_planner`** — the staleness line added to `prompt.py`
  is inert until the agent is re-provisioned. The prompt is frozen on an agent
  version; editing the file changes nothing on its own.

Two things this document listed as unknown are now settled, and the code below
depends on both:

- **`agent.message` carries no citations under Managed Agents.** Its text
  blocks are `text` and nothing else — the per-sentence
  `web_search_result_location` objects exist on the raw Messages API, not here.
  So the harvest reads `agent.tool_result`, whose `content` is a list of
  `search_result` / `document` / `text` blocks.
- **The `days` integers are 1=Monday … 5=Friday.** Across 60 sampled courses
  the only values that appear are 1–5, and the two commonest patterns are
  `[1,3,5]` and `[2,4]` — MWF and TR. Weekend encoding is still untested and
  does not matter: the tool only filters M T W R F.

---

## The shared pattern every part below uses

`CitationLedger.record()` (`apps/planner/citations.py:38`) does not forward a
tool's raw result to the model. For each item in `result["citations"]` it
**rebuilds a new dict from scratch** — only `title`, `url`, `snippet`,
`indexed_at`, `verified_at`, `source` survive; anything else on that item
(full chunk text, a course's prereqs, lat/lng, a dining schedule) is silently
dropped. It *does* preserve any other top-level key on the dict you return —
`return {**result, "citations": issued}` — untouched.

So **don't just wrap a tool's output as `{"citations": [...raw items...]}`**
— that trades "no citations" for "citations, but the model can no longer see
the actual answer content." Two shapes, pick per tool:

- **RAG (Part B):** the only "extra" content beyond a citation is the chunk's
  full text, and a citation `snippet` is *just a string* — so put the whole
  chunk there. No second key needed.
- **Courses/Dining/Events/Maps (Parts C–E):** the extra content is
  genuinely structured (prereqs, meeting times, open/close windows, lat/lng)
  and doesn't fit one string well. Return **both** a `results` key (full
  normalized data, for the model to actually answer from) and a `citations`
  key (a compact one-line-per-item renderer, for the ledger/UI). Same
  underlying data, two views.

---

## Part A — Web verify: harvesting citations from `web_search`/`web_fetch`

**The one-line version:** `web_search`/`web_fetch` execution and the mode chip
already work — Anthropic runs them via the agent's prebuilt toolset, and
`loop.py` already lights `mode_start`/`mode_end` for them. What's missing is
turning what came back into a `Citation`: nothing in the codebase reads a web
result and writes it to the ledger, so a web-verified answer shows the chip and
cites nothing.

---

## Read first, in order

1. This document.
2. `CLAUDE.md` — repo rules, including comment style.
3. `backend/apps/planner/loop.py` — `_handle`, especially the `agent.tool_use` /
   `agent.tool_result` branches (~L352–366), and `_dispatch` (~L427), which is
   the pattern to mirror for a built-in tool instead of one of ours.
4. `backend/apps/planner/citations.py` — `CitationLedger`, the only class
   allowed to produce a `Citation`.
5. `backend/apps/planner/client.py` — `AGENT_TOOLSET`, `WEB_TOOLS`.
6. `backend/apps/planner/management/commands/provision_planner.py` — how the
   system prompt and toolset actually reach Anthropic. Re-run this after any
   prompt or tool-list change; it mints a new agent version, not a redeploy.
7. `backend/apps/planner/tests.py` — the event-stream harness: `FakeSession`,
   `tool_use()`, `tool_result()`, `agent_message()`, and the existing
   `test_a_built_in_web_tool_earns_the_verify_chip`.
8. `tasklist.md` §1 (cost precedence) and B3 (which boxes this closes).

---

## What already exists — do not rebuild

- **Declaring the tools is not this lane's job.**
  `client.AGENT_TOOLSET = {"type": "agent_toolset_20260401"}` is Anthropic's
  prebuilt toolset, applied in `agent_reference()`. There is no
  `Tool.server_spec` and no `register_server_tool` — an earlier version of this
  doc assumed that design; it doesn't apply since B4 moved to Managed Agents
  (`tasklist.md` §1, 2026-08-15). Don't add one back.
- **The runaway cap** is `client._budget()` — a dollar limit on the whole
  session, not a per-tool `max_uses`. The prebuilt toolset takes no
  `max_uses`/`max_content_tokens` config surface; don't look for one.
- **The chip.** `loop.py`'s `_handle` fires `mode_start` on `agent.tool_use`
  for `web_search`/`web_fetch`, and `mode_end` on the matching
  `agent.tool_result`. Tested (`test_a_built_in_web_tool_earns_the_verify_chip`).
  Leave this alone except where Phase 3 below explicitly extends it.
- **There is no host allowlist to add one to.**
  `provision_planner.ENVIRONMENT_CONFIG = {"type": "cloud", "networking": {"type":
  "unrestricted"}}`. That resolves the question `tasklist.md` B3 flagged as open
  ("whether `networking.allowed_hosts` gates the built-in tools") — it doesn't;
  there is no gate at any layer. PRD §6's exclusion of Canvas/SIO/Stellic holds
  only because `web_fetch` carries no credentials, never because of a host
  filter. `ENVIRONMENT_CONFIG` is a provisioning decision, not this lane's —
  leave it alone.

---

## The actual gap

Two things:

1. **Citations.** A web search or fetch happens, the chip lights, and
   `turn.ledger` never hears about it. `_handle`'s `agent.tool_result` branch
   (loop.py ~L361) only pops `turn.lanes` and sets `turn.web_verified` — it
   never touches `turn.ledger`. `CitationLedger.record()` (citations.py:38) is
   only ever called from `_dispatch`, the path for *our* tools.
2. **`verified_at`.** Follows from (1) — there's nowhere for it to be stamped
   because no citation is being built in the first place.

Nothing else from B3's original scope is missing except the two best-effort
items in Phase 4, and the items explicitly marked out of scope below.

---

## Phase 0 — what the events actually carry

There were two possible sources for the same data, and this SDK surface only
gives one. The answer is in the SDK's own generated models, which is where to
check it again if a version bump moves something:

    anthropic/types/beta/sessions/beta_managed_agents_agent_message_event.py
    anthropic/types/beta/sessions/beta_managed_agents_agent_tool_result_event.py

- **`agent.message` is not a source.** Its content blocks are `text` or
  `redacted`, and a text block has `text` and nothing else. The per-sentence
  `web_search_result_location` citations (`url`/`title`/`cited_text`) that the
  raw Messages API attaches to text blocks do not exist here. Preferring them
  would have been better — they are the snippet tied to the sentence the model
  actually wrote — but they are not on offer.
- **`agent.tool_result` is.** `content` is an optional list of blocks:
  - `search_result` — `source` (the url), `title`, `content` (a list of text
    blocks), `citations.enabled`
  - `document` — `source` (a url, plain-text, base64 or file variant), `title`,
    `context`
  - `text` — just `text`, no url anywhere on it
  - `is_error` marks a failure; the detail is in the text blocks.

A `web_fetch` block does not reliably name the page it read, so the harvest
keeps each `agent.tool_use`'s `input` and falls back to the url that was asked
for. The field names are repeated in a comment at the harvest site, because the
payload is not self-documenting from the code alone.

---

## Phase 1 — extend the ledger for sources with no `Tool`

`CitationLedger.record()` takes a `Tool` and calls `citation_defaults(tool)`
for `source`/`is_mock`. Web results have no `Tool` — they're not in the
registry — so that path doesn't fit. Add a sibling method:

```python
def record_web(self, *, title, url, snippet, verified_at, source) -> dict:
    """Like `record`, for a citation with no backing `Tool` (web_search/web_fetch)."""
```

`is_mock` is always `False` here — nothing this lane touches is a fixture.
`indexed_at` is always `None` — that field means "date we crawled it," which
doesn't apply to a live fetch. `verified_at` is stamped by us at harvest time
(`timezone.now()`); the API doesn't supply it. Pass the actual tool name
(`"web_search"` or `"web_fetch"`) as `source`, matching the existing
convention where `source` is the producing tool's name.

**This exact failure mode already happened, twice.** An audit of B1's
`campus_search` and all four B2 tools (2026-08-16) found none of them ever
call anything on `CitationLedger` — `campus_search` returns a bare list
(`CitationLedger.record()` early-returns on anything that isn't a dict), and
the B2 tools return dicts with no `citations` key at all. Every one of those
lookups runs successfully and produces zero citations, silently. Write a test
that asserts a `Citation` actually lands in `turn.ledger.citations` after a
scripted web-search round — not just that no exception was raised — or this
lane joins the same list.

## Phase 2 — dedupe by URL

A `web_search` call returns several results, and the model may cite more than
one across a turn. The same URL cited twice must be one `Citation`, not two —
`S3` should mean one source everywhere it's referenced. `CitationLedger` numbers
monotonically with no such check today, because every one of *our* tool results
is already a distinct call. Track seen URLs for the web path only (e.g.
`dict[url, citation_id]` on the ledger, checked before minting a new id) —
don't change `record()`'s behavior for our tools.

## Phase 3 — wire it into the loop

Extend whichever of `_handle`'s branches Phase 0 pointed you at
(`agent.tool_result` for the built-ins, and/or `agent.message` while `turn.answer`
is being built) to call `turn.ledger.record_web(...)` with what the tool
actually returned — the same way `_dispatch` calls `turn.ledger.record(...)`
for ours. `turn.web_verified` and the `mode_start`/`mode_end` chip logic are
unaffected; don't touch them beyond what's needed to reach the result payload.

## Phase 4 — staleness policy (best effort until B1 lands)

- Add `WEB_VERIFY_STALE_AFTER_DAYS` to `config/settings.py`, matching the
  other planner settings' pattern:
  `int(os.getenv("WEB_VERIFY_STALE_AFTER_DAYS") or 30)`. Add the row to
  `.env.example`.
- The system prompt is static and versioned on the agent
  (`prompt.agent_system_text()`, shipped once by `provision_planner`, never
  per-request) — it can't read the setting at request time. Bake the actual
  number into the "Which source to prefer" section of `prompt.py` as prose,
  then re-run `manage.py provision_planner`. That re-caches the agent once,
  which is expected and fine.
- **Can be verified end to end now, with a catch.** `campus_search` exists on
  `main` as of 2026-08-16 (B1 landed), so there's real `indexed_at` data to
  compare a staleness threshold against — but it's currently citation-broken
  (see the note in Phase 1 above), so `indexed_at` never reaches a `Citation`
  either. Ship the setting and the prompt line regardless; the actual
  end-to-end test needs B1's citation fix in first, not a wait for B1 to
  exist at all.

---

## Out of scope — do not build

- **`resolve_course_site`.** A static Appendix-B map. Useful, but it doesn't
  close the citation gap this doc is about. P1.
- **Any allowlist/denylist.** Confirmed twice over: no domain-filter surface
  on the prebuilt toolset, and the environment is `networking: unrestricted`.
  Revisiting this is a provisioning-level (`ENVIRONMENT_CONFIG`) conversation,
  not a code change here.
- **Enqueuing discovered URLs into `CrawlSeed`.** The model doesn't exist yet
  (B1). Leave the hook, not the implementation.

---

## Confirm web search is enabled for the org

Not a code change — a one-time Console check — but do it as part of this
work rather than leaving it for someone to forget. If it's off, declaring the
toolset 400s **every** request, not just searching ones, because
`AGENT_TOOLSET` is unconditional in `agent_reference()`. Verify by running one
real query through `/api/ask/` that has to search (nothing else can answer it)
and confirming it doesn't 400.

---

## How to verify

Extend the existing harness rather than building a new one — `tests.py`
already has `FakeSession`, `tool_use()`, `tool_result()`, `agent_message()`,
and `test_a_built_in_web_tool_earns_the_verify_chip` (~L474) to copy from.
`tool_use()`/`tool_result()` currently carry no payload (`input={}`, no
content field) — extend them with whatever field Phase 0 found real events
carry, using real field names, not placeholders.

Cover at least:

- [x] A `web_search` round with results produces `Citation`s with
      `is_mock: False`, `indexed_at: None`, and a stamped `verified_at`
- [x] The same URL appearing twice in one turn yields one `Citation`
- [x] A search error degrades to a note, never an exception — the existing
      failure-note pattern in `_note()`
- [x] `run_tool("web_search", …)` still raises — nothing here makes a web tool
      reachable through the registry
- [x] `test_a_built_in_web_tool_earns_the_verify_chip` still passes unmodified
- [x] A `web_fetch` block with no url of its own falls back to the one the
      `agent.tool_use` asked for

Then, live and once: a query that must search, checked for a citation with a
real URL, a real `verified_at`, and `web_verify` in `modes_used` — that's the
actual "done."

---

## Done when

- [ ] A question the index/live tools can't answer triggers a real search or
      fetch and comes back with a citation carrying a real URL and a stamped
      `verified_at` — needs a live run
- [x] The same URL cited twice is one citation, not two
- [x] `WEB_VERIFY_STALE_AFTER_DAYS` exists, is in `.env.example`, and the
      prompt names the actual number — inert until `provision_planner` re-runs
- [ ] Web search confirmed enabled for the org — a Console check
- [x] Boxes ticked in `tasklist.md` B3, same commit

---

## Part B — RAG: `campus_search` produces no citations, `load_seeds` can't run

Two independent bugs in `apps/rag/`.

### B.1 — `campus_search` never reaches the ledger

`backend/apps/rag/tools.py`'s registered `campus_search` returns exactly what
`apps/rag/search.py`'s `campus_search()` returns: a bare `list[dict]`.
`CitationLedger.record()` opens with `if not isinstance(result, dict): return
result` — a list fails that immediately, so every RAG hit is silently uncited.

Per the shared pattern above, RAG doesn't need a separate `results` key — the
only "extra" content is the chunk's own text, and `snippet` is just a string,
so put the whole chunk there instead of truncating it away. Fix, in
`apps/rag/tools.py`:

```python
def campus_search(query: str, k: int = 6) -> dict:
    from apps.rag.search import campus_search as _search

    return {"citations": _search(query, k=min(k, 20))}
```

And in `apps/rag/search.py`, change:

```python
"snippet": row["text"][:300],
```

to:

```python
"snippet": row["text"],
```

`CitationLedger.record()` only forwards `title`/`url`/`snippet`/`indexed_at`
to the model — `text` itself is dropped, so `snippet` is the *only* grounding
content a RAG hit gives the model to answer from, not just what a citation
card displays. Chunks are already bounded to ~500–800 tokens by the chunker
(tasklist B1), so the 300-character truncation was throwing away most of a
retrieved passage right before the model ever saw it.

### B.2 — `load_seeds` is a `SyntaxError`, not a bug

`backend/apps/rag/management/commands/load_seeds.py`, last two lines:

```python
            self.style.SUCCESS(f"Done. {created} new seeds added ({len(SEEDS)} total).")
        )
```

The closing `)` on its own line has no open paren left to match — the module
fails to import. It also runs once per loop iteration instead of once at the
end, and never passes the styled string to `self.stdout.write()`, so it
wouldn't print anything even if it parsed. Reads like an automated "potential
fix" removed the `self.stdout.write(` wrapper and left the loop indentation
behind (`git log` shows several "Potential fix for pull request finding"
commits around this area). Fix:

```python
    def handle(self, *args, **options):
        created = 0
        for url, label in SEEDS:
            seed, was_created = CrawlSeed.objects.get_or_create(
                url=url,
                defaults={"label": label},
            )
            if was_created:
                created += 1
            elif seed.label != label:
                seed.label = label
                seed.save(update_fields=["label"])

        self.stdout.write(
            self.style.SUCCESS(f"Done. {created} new seeds added ({len(SEEDS)} total).")
        )
```

Dedented out of the loop (report once, at the end) and wrapped in
`self.stdout.write(...)` so it actually prints. Verify with:
`docker compose exec backend python manage.py load_seeds`.

---

## Part C — `apps/tools/courses.py`: the most broken of the five files

Every item below is a real, independently verified bug — read against the
actual merged file, not a summary of it.

### C.1 — wrong endpoint, response parsed as the wrong shape

`search_courses` calls `client.get("/courses", params={"name": query})` and
treats the JSON body as a bare list. The real endpoint, confirmed live, is
`/courses/search?keywords=...`, and it returns `{"totalDocs", "totalPages",
"page", "docs": [...]}` — a dict. Iterating that dict yields its string keys
("totalDocs", ...), and `_normalize_course(raw)` calling `raw.get(...)` on a
string raises `AttributeError` — this doesn't degrade, it crashes the call
outright, unhandled by the existing `except httpx.HTTPStatusError`/
`RequestError` blocks (it isn't an HTTP error at all).

### C.2 — `get_course` never calls `/schedules`, so instructors/meetings are always empty

`_normalize_course` reads `raw.get("lectures") or raw.get("sections")` —
neither key exists on a `/course/{id}` response (verified fields: `id, v,
coreqs, courseID, crosslisted, department, desc, name, prereqString, prereqs,
units` — no schedule data at all). Meeting times and instructors live only
behind `/schedules?courseID=...` (confirmed live, `docs/b2-courses.md`),
which nothing in this file ever calls.

### C.3 — the days filter never ran, and can't without a design decision

`_no_excluded_days` loops over `course["meetings"]`, which was always `[]`
(see C.2) — the filter has never rejected a single course. Fixing C.2 alone
doesn't fix this: `search_courses` doesn't call `get_course`, so its results
still carry no schedule data. Two honest options — pick one, don't leave it
silently broken as it is today:

- **(Recommended) Fetch `/schedules?courseID=...` for every candidate that
  survives the `units` filter, in parallel** — mirror the
  `ThreadPoolExecutor` pattern already in `planner/loop.py:_dispatch` — then
  filter for real. The `units` filter usually narrows the set first, so this
  isn't 20 sequential requests.
- **(Simpler) Drop server-side days-filtering from `search_courses`
  entirely** and let the model chain `search_courses` → `get_course` on a
  promising candidate to see real meeting days — the system prompt already
  tells it to "chain dependent lookups deliberately" (`prompt.py`). Not a
  regression: the filter was never working.

**Taken: the parallel fetch.** `search_courses` enriches candidates from
`/schedules` only when `days_excluded` is set, so the common case still costs
one request.

Either way: **`days` is a list of ints** (e.g. `[2, 4]`), not the letter
string (`"MWF"`) an earlier version assumed — `meeting["days"].upper()` would
have crashed the moment it ran against real data. The mapping is **1=Monday …
5=Friday** (see the Status section), and `_day_codes` converts to letters at
the normalization boundary so neither the filter nor the model has to know
the encoding.

### C.4 — the `units` filter compares the wrong types

`c["units"] == units` compares against a `float | None` parameter, but the
real API returns `units` as a string (`"12.0"`, confirmed live) — always
`False`. Fix at the normalization boundary (see C.6's rewritten
`_normalize_course`), not at the comparison site.

### C.5 — its own `httpx.Client` instead of the shared one

`_client()` builds `httpx.Client(base_url=_BASE, timeout=_TIMEOUT)`. Replace
every call site with `apps.core.http.get_json(url, params=..., timeout=...)`
— real signature, confirmed by reading `apps/core/http.py`:
`get_json(url, *, params=None, timeout=DEFAULT_TIMEOUT, ttl=0.0) -> Any`,
raising `httpx.HTTPError` uniformly on any failure (connection, timeout,
non-2xx, or a non-JSON body). Delete `_client()`; keep `import httpx` only
for catching `httpx.HTTPError`/`httpx.HTTPStatusError`.

### C.6 — put it together

```python
from apps.core.http import get_json
import httpx  # for httpx.HTTPError / httpx.HTTPStatusError only now

_BASE = "https://course-tools.apis.scottylabs.org"


def _normalize_course(raw: dict) -> dict:
    units = raw.get("units")
    try:
        units = float(units) if units is not None else None
    except (TypeError, ValueError):
        units = None

    return {
        "course_number": raw.get("courseID") or raw.get("number") or raw.get("id", ""),
        "title": raw.get("name") or raw.get("title", ""),
        "units": units,
        "instructors": [],
        "meetings": [],
        "prereqs": raw.get("prereqString") or raw.get("prereqs", ""),
        "description": raw.get("desc") or raw.get("description", ""),
        "semester": raw.get("semester", ""),
        "source": "CMU Courses API",
        "is_mock": False,
    }


def _flatten_schedule(entries: list[dict]) -> tuple[list[str], list[dict]]:
    """/schedules?courseID=... -> (sorted instructor names, meeting dicts).

    One entry per semester/year the course ran — flattens across all of them
    rather than picking "the current one," since a semester-matching rule
    hasn't been decided. Revisit if a query needs only the current offering.
    """
    instructors: set[str] = set()
    meetings: list[dict] = []
    for entry in entries:
        for group_key in ("lectures", "sections"):
            for group in entry.get(group_key, []):
                instructors.update(group.get("instructors", []))
                for slot in group.get("times", []):
                    meetings.append({
                        "days": slot.get("days", []),
                        "begin": slot.get("begin", ""),
                        "end": slot.get("end", ""),
                        "room": slot.get("room", ""),
                        "building": slot.get("building", ""),
                    })
    return sorted(instructors), meetings


def _course_citation(course: dict) -> dict:
    bits = [course["course_number"], course["title"]]
    if course["units"] is not None:
        bits.append(f"{course['units']:g} units")
    return {
        "title": f"{course['course_number']}: {course['title']}",
        "url": "",  # no confirmed public per-course page — don't invent one (docs/b2-courses.md)
        "snippet": " · ".join(bits),
        "indexed_at": None,
    }


def search_courses(
    query: str,
    units: float | None = None,
    days_excluded: list[str] | None = None,
    semester: str | None = None,
) -> dict:
    params: dict[str, str] = {"keywords": query}
    if semester:
        params["semester"] = semester

    try:
        payload = get_json(f"{_BASE}/courses/search", params=params)
    except httpx.HTTPError as exc:
        raise ToolError(f"CMU Courses API unreachable for query {query!r}: {exc}") from exc

    docs = payload.get("docs", []) if isinstance(payload, dict) else []
    normalized = [_normalize_course(c) for c in docs]

    if units is not None:
        normalized = [c for c in normalized if c["units"] == units]

    # days_excluded: see C.3 — needs a decision (parallel /schedules fetch, or
    # drop and let the model chain into get_course) before it can filter anything.

    normalized = normalized[:20]
    return {"results": normalized, "citations": [_course_citation(c) for c in normalized]}


def get_course(course_number: str) -> dict:
    try:
        raw = get_json(f"{_BASE}/course/{course_number}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 500):
            # Confirmed live: the upstream's "not found" is a bare 500, not a 404.
            raise ToolError(f"Course {course_number!r} not found in the CMU catalog.") from exc
        raise ToolError(
            f"CMU Courses API returned {exc.response.status_code} for {course_number!r}."
        ) from exc
    except httpx.HTTPError as exc:
        raise ToolError(f"CMU Courses API unreachable: {exc}") from exc

    course = _normalize_course(raw)

    try:
        schedule = get_json(f"{_BASE}/schedules", params={"courseID": course_number})
    except httpx.HTTPError:
        # Schedule data is a bonus on top of description/prereqs/units, not the
        # whole result — don't fail a call that already has something to return.
        schedule = []

    course["instructors"], course["meetings"] = _flatten_schedule(schedule)
    return {"results": [course], "citations": [_course_citation(course)]}
```

Existing `register_tool(...)` decorators and JSON schemas are unaffected —
only the function bodies and `_normalize_course` change.

---

## Part D — `apps/tools/dining.py` and `apps/tools/events.py`

Two shared defects, same fix in both files — plus one that only `events.py`
has.

**`events.py`'s parser never matched the feed.** It read named keys
(`name`, `starts_at`, `permalink`); the feed names its columns in a `fields`
string and sends the values as `p0`, `p1`, …, with dates as HTML
(`<p>Wed, Aug 19, 2026</p><p>1 PM &ndash; 2 PM</p>`). Every event normalized to
empty strings, so `find_events` returned 31 blank records and the keyword and
time-window filters had nothing to match. Citations on top of that would have
been 31 cards titled after the tool. `_decode` and `_window` are the fix.

### D.1 — hand-rolled HTTP instead of the shared client

`dining.py`: `resp = httpx.get(_URL, timeout=_TIMEOUT)`. `events.py`: `resp =
httpx.get(_URL, params={"range": 0}, timeout=_TIMEOUT)`. Replace both with
`apps.core.http.get_json(_URL, params=..., timeout=_TIMEOUT)`, and replace the
current `except httpx.HTTPStatusError / httpx.RequestError / (ValueError,
TypeError)` triple with a single `except httpx.HTTPError` — `get_json`
already unifies all three (see Part C.5).

### D.2 — no citations

Neither tool returns a `citations` key, and both have genuinely structured
per-item data, so use the `results` + `citations` split:

```python
# dining.py
def _dining_citation(loc: dict) -> dict:
    status = "open now" if loc["is_open"] else "closed now"
    return {
        "title": loc["name"],
        "url": "",  # CMU Eats has no public per-location page
        "snippet": f"{loc['name']} ({loc['concept_title']}) — {status}",
        "indexed_at": None,
    }

# in find_dining, replace the final `return locations[: min(limit, 20)]` with:
locations = locations[: min(limit, 20)]
return {"results": locations, "citations": [_dining_citation(loc) for loc in locations]}
```

```python
# events.py
def _event_citation(event: dict) -> dict:
    return {
        "title": event["title"],
        "url": event["link"] or "",  # events.py actually has a real permalink — use it
        "snippet": f"{event['title']} — {event['org']}, {event['start']}",
        "indexed_at": None,
    }

# in find_events, replace the final `return filtered[: min(limit, 30)]` with:
filtered = filtered[: min(limit, 30)]
return {"results": filtered, "citations": [_event_citation(e) for e in filtered]}
```

---

## Part E — `apps/tools/maps.py`: citations only

Clean otherwise — `is_mock: True` is correctly set both on
`register_tool(..., is_mock=True)` and on every result dict. Just needs the
`results` + `citations` split, and since it's a fixture there's no upstream
URL at all:

```python
def _map_citation(item: dict) -> dict:
    return {
        "title": item.get("name") or f"{item.get('from')} → {item.get('to')}",
        "url": "",  # mock fixture, no public source page
        "snippet": item.get("_snippet", ""),
        "indexed_at": None,
    }
```

In `nearby`, before the final `return results`:

```python
for r in results:
    r["_snippet"] = f"{r['name']}: {r['walk_minutes']} min walk from {canon} (mock data)"
return {"results": results, "citations": [_map_citation(r) for r in results]}
```

In `walk_time`, before the final `return {...}`:

```python
result = {"from": a, "to": b, "walk_minutes": minutes, "is_mock": True}
result["_snippet"] = f"{a} to {b}: {minutes} min walk (mock data)"
return {"results": [result], "citations": [_map_citation(result)]}
```

(`_snippet` is a throwaway key used only to build the citation string — strip
it from `results` before returning if a stray internal-looking field bothers
you; the model won't care either way.)

---

## Done when — all five parts

- [x] Part A: the same URL cited twice is one citation; a harvested citation
      carries a real URL and a stamped `verified_at`. The live half — a
      question the index and live tools can't answer, answered by a real
      search — is still to run
- [x] Part A: `WEB_VERIFY_STALE_AFTER_DAYS` exists and is in `.env.example`,
      `docker-compose.yml` passes it through, and the prompt names the actual
      number. Web search being enabled for the org is still a Console check
- [x] Part B: `campus_search` produces real citations with real `snippet`
      text; `manage.py load_seeds` runs without a `SyntaxError`
- [x] Part C: `search_courses` hits `/courses/search`, `get_course` merges in
      `/schedules?courseID=...`, a nonexistent course degrades to a clear
      message (not a raw 500), and `days_excluded` filters on real meeting days
- [x] Part D: `find_dining` and `find_events` route through
      `apps.core.http.get_json` and return real citations — and `find_events`
      returns real events, which it never did before
- [x] Part E: `nearby` and `walk_time` return real citations, still flagged
      `is_mock: true`
- [x] Boxes ticked in `tasklist.md` B1/B2/B3 for the parts done, same commit

## Style

Follow `CLAUDE.md`. Comments explain *why*, never what. If a comment could be
deleted without losing information, delete it.
