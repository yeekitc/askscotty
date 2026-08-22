# B5 — Canvas, Ed Discussion, Stellic

The three personal sources that need no password. Canvas and Ed both
authenticate with a **scoped personal access token** the student generates and
can revoke without touching their account — the safe half of B5, unlike the
two connectors in [b5-piazza-gradescope.md](./b5-piazza-gradescope.md). Stellic
is a labelled mock: no real integration, by explicit direction.

Builds on [b5-connections.md](./b5-connections.md) for the connections endpoint
and the `get_credential()`/`get_token()` convention.

---

## Part 0 — authenticated calls through the shared HTTP client

`backend/apps/core/http.py`'s `get_json()` takes a `headers` argument, merged
over the `User-Agent` for one request, which is how a connector sends
`Authorization: Bearer <token>`.

**A request with headers is never cached, whatever `ttl` says.** The cache is
process-wide and keyed only on url and params, so caching an authenticated
response would let two students hitting the same endpoint with different tokens
collide and be served each other's data (PRD §9). A header makes the cache key
`None` outright: the trap is unreachable rather than being a rule every caller
has to remember. Don't route around it with a hand-rolled `httpx` call.

`_get_json()` in `backend/apps/personal/tools.py` wraps it with the other
thing every connector call needs: every `httpx` failure translated to a
`ToolError`, with the exception text dropped — an httpx error can carry the
request URL with its query string, and a personal call's params can identify
the student.

---

## Part A — Canvas

Base URL `https://canvas.cmu.edu/api/v1` (PRD Appendix A), auth
`Authorization: Bearer <token>`, grounded in Canvas's official public API docs
(`canvas.instructure.com/doc/api/`).

- **`canvas_list_courses`** — `GET /courses?enrollment_state=active`. Resolves
  a vague "my systems class" to a real course id.
- **`canvas_get_assignments`** — `GET /planner/items`, deliberately not
  per-course `/assignments`: it aggregates every enrolled course in one call,
  already ordered by date, which is exactly the "what's due this week"
  question. Looping `/courses/{id}/assignments` would be one request per class
  for the same answer. The `plannable` sub-object's fields vary by
  `plannable_type`, and the docs give no guarantee that every type carries
  `due_at`, so it is read through `.get()` with `plannable_date` as the
  fallback.
- **`canvas_get_announcements`** — `GET /announcements`, which requires
  `context_codes`, so the enrolled course list is fetched either way (it also
  supplies the course *names*, which the announcement payload does not carry).
  Both date bounds are always sent: with only `start_date`, Canvas narrows the
  window and returns nothing. The default lookback is a term, not Canvas's own
  14 days, which routinely comes back empty; every result carries `posted_at`
  so the model can still say what is genuinely recent.

**Pagination is Link-header based, and `get_json` only returns the decoded
body** — it never sees the `Link` header. `_PAGE = 100` is the maximum page
size and covers a normal student's course and thread load; a heavier account is
truncated at one page, which the tool descriptions *say* rather than hide. Link
following was not built; that is the known limit, not an oversight.

Citations use Canvas's own student-facing links — `html_url` from the response,
or `https://canvas.cmu.edu/courses/{id}` — never a hand-built assignment path.

---

## Part B — Ed Discussion

Base URL `https://us.edstem.org/api/`, and the **same official Bearer token**
as Canvas — the one generated at `edstem.org/us/settings/api-tokens`. This was
confirmed by reading the unofficial `edapi` library's own source rather than
its README: it authenticates with that same token, so there is no reason to add
the dependency when the token path is this simple to call directly.

- **`ed_list_courses`** — `GET user`, whose payload carries the student's
  course enrolments. Course resolution therefore mirrors Canvas's. Archived
  courses are dropped: a class the student cannot act on is noise in a "which
  class?" lookup.
- **`ed_search_threads`** — `GET courses/{course_id}/threads`. **Ed has no
  server-side thread search**; `list_threads` takes only `limit`/`offset`/
  `sort`. So this is an honest client-side keyword filter over one page of the
  most recent threads, and the tool description says so: a miss means "not in
  the recent threads", not "never discussed".
- **`ed_get_announcements`** — the same thread endpoint filtered on
  `type == "announcement"` (confirmed live). It is a field on the ordinary
  thread shape, so no separate endpoint is needed.

Ed threads are a shared class space written by classmates and staff, not the
student's private data — the same privacy shape as Piazza, and the tool
description carries the same instruction: summarise what a thread established,
don't repeat posts verbatim or name their authors.

**Ed citations carry no `url`.** The API response has no link field, and the
`discussion/{number}` pattern is a guess. Empty beats invented.

---

## Part C — Stellic (mock only)

**No real Stellic integration, and no scraping of Stellic.** The PRD's own
reasoning rules it out: Stellic offers an institutional PAT only, no student
OAuth, so there is no safe student-facing credential to build against at all.

`stellic_degree_audit` is fixture data, the same way
`backend/apps/tools/fce.py`'s ratings are — `is_mock=True` on every citation
it produces. Nothing in the app renders that flag yet (an open PRD §9 gap), so
what actually tells a reader the data is fake is the tool description, which
instructs the model to say in the answer that this is placeholder data rather
than the student's real record. It makes no network call.

It is still gated through the connections flow, connecting with an empty
credential (`CREDENTIAL_FIELDS[STELLIC] = ()`), so the settings UI has a real
toggle instead of a special case.

What makes the fixture *Stellic* and not the course catalog: it is keyed to the
student's progress — completed vs required units and what is left — not to what
courses exist. Programs are matched forgivingly on aliases, because the model
passes whatever the student typed ("information systems", "stats minor").

---

## Non-negotiables

- **Never log a token, a response header, or anything containing
  `Authorization`.** `run_tool()` already omits tool call *arguments* from its
  log line; a `headers` dict built inside a tool function is a second place a
  stray debug line could leak one. A token is revocable, which makes this one
  degree less severe than the password warning in
  [b5-piazza-gradescope.md](./b5-piazza-gradescope.md) — and nothing about that
  makes logging it acceptable.
- **`get_json`'s `headers` argument is never cached, structurally.** Part 0's
  whole point.
- **Stellic never becomes real.** Anything more than this mock means scraping
  behind an SSO login, which CLAUDE.md and the PRD both forbid.
- **No citation from any of these three carries an invented `url`.**

---

## What the tests hold

`backend/apps/personal/tests.py`, with `get_json` mocked — the real APIs are
never called from the test suite:

- Canvas's tools send `Authorization: Bearer <token>` and hit `/courses`,
  `/planner/items` and `/announcements`, passing the `due_before`/`course_id`
  filters and both announcement date bounds.
- Citations use Canvas's own `html_url` and course path.
- Ed sends the same header shape against `us.edstem.org/api/`, and its
  citations invent no thread url.
- An HTTP error from either becomes a `ToolError` that leaks neither the
  credential nor the request URL.
- `stellic_degree_audit` is `is_mock` on every citation and makes no network
  call.
- A successful call stamps `last_sync_at`.

```
docker compose exec backend python manage.py test apps.personal
```
