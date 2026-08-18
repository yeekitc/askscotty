# B5 — Canvas, Ed Discussion, Stellic

Hand this to whoever (or whatever) builds it. Written to be pasted whole.

**The one-line version:** the last three personal sources. Canvas finishes an
existing stub against a well-documented official API. Ed Discussion is new,
against an API confirmed by reading `edapi`'s actual source rather than
guessing — it turns out to be the same official token, not the scraper it
was assumed to be a few messages ago (correction below). Stellic is mock
only — no real integration, per explicit direction.

**Depends on `docs/b5-connections.md`** for the connections endpoint and the
`get_credential()`/`set_credential()` convention. Canvas and Ed also need
**Part 0 below**, a small extension to the shared HTTP client neither can
work without.

---

## Correction to something said earlier in this project's history

Ed Discussion's unofficial `edapi` library was described as authenticating
via "a scraped session cookie from a logged-in browser." Having now read its
actual source (`edapi/edapi.py`), that's wrong: it uses the exact same
official API token this doc builds against (`Authorization: Bearer
<token>`, generated at `https://edstem.org/us/settings/api-tokens`). The
recommendation to skip `edapi` in favor of the official token still stands —
there's no reason to add the dependency when the token path is this simple
to call directly — but the reasoning was inaccurate. Worth knowing since it
changes nothing about what to build, but the earlier claim shouldn't stand
uncorrected.

---

## Part 0 — the shared HTTP client can't send auth headers

`backend/apps/core/http.py`'s `get_json()` hardcodes one header
(`User-Agent`) and has no way for a caller to add another. Canvas and Ed both
need `Authorization: Bearer <token>` on every request — this has to be fixed
first, or both parts below are stuck reinventing B0 to work around it.

```python
def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    ttl: float = 0.0,
    headers: dict[str, str] | None = None,
) -> Any:
    # ...docstring gains a line about `headers`...
    key = _cache_key(url, params) if (ttl > 0 and not headers) else None
    ...
    data = _fetch(url, params=params, timeout=timeout, headers=headers)
    ...


def _fetch(url, *, params, timeout, headers=None) -> Any:
    host = httpx.URL(url).host
    request_headers = {"User-Agent": settings.CRAWLER_USER_AGENT}
    if headers:
        request_headers.update(headers)
    ...
    response = _client().get(url, params=params, timeout=timeout, headers=request_headers)
```

**The important line is `ttl > 0 and not headers`, not just a comment
telling people not to cache authenticated calls.** This is the third time in
this project a cache-key-doesn't-include-identity trap has come up (B0's own
non-negotiable, then again in `docs/b5-connections.md`) — worth actually
making it impossible this time instead of documenting it as a rule someone
has to remember. Any call that sends a header is never cached, full stop,
regardless of what `ttl` it passes.

---

## Part A — Canvas

Finishes `backend/apps/personal/tools.py`'s existing stubs
(`canvas_list_courses`, `canvas_get_assignments`) — both already registered,
gated, and call `connection.get_token()` correctly. They just
`raise ToolError(_NOT_WIRED)`. Replace that.

Grounded in Canvas's official public API docs
(`canvas.instructure.com/doc/api/`) — this is a large, stable, extensively
documented product, not a guess. Base URL: `https://canvas.cmu.edu/api/v1`
(PRD Appendix A). Auth: `Authorization: Bearer <token>`.

```python
from apps.core.http import get_json

_BASE = "https://canvas.cmu.edu/api/v1"


def canvas_list_courses(*, session_id: str) -> dict:
    connection = _canvas_connection(session_id)
    headers = {"Authorization": f"Bearer {connection.get_token()}"}

    try:
        courses = get_json(f"{_BASE}/courses", params={"enrollment_state": "active"}, headers=headers)
    except httpx.HTTPError as exc:
        raise ToolError(f"Canvas unreachable: {exc}") from exc

    mark_synced(connection)
    results = [{"id": c["id"], "name": c["name"], "course_code": c.get("course_code", "")} for c in courses]
    return {"results": results, "citations": [_course_citation(c) for c in results]}


def canvas_get_assignments(*, session_id: str, due_before: str | None = None, course_id: str | None = None) -> dict:
    connection = _canvas_connection(session_id)
    headers = {"Authorization": f"Bearer {connection.get_token()}"}

    params: dict[str, Any] = {}
    if due_before:
        params["end_date"] = due_before
    if course_id:
        params["context_codes[]"] = f"course_{course_id}"

    try:
        items = get_json(f"{_BASE}/planner/items", params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise ToolError(f"Canvas unreachable: {exc}") from exc

    mark_synced(connection)
    results = [_normalize_planner_item(item) for item in items]
    return {"results": results, "citations": [_assignment_citation(a) for a in results]}
```

`GET /planner/items` (not per-course `/assignments`) is the deliberate
choice: it aggregates across every enrolled course in one call, already
sorted by due date, which is exactly "what's due this week" (tasklist B5) —
looping `/courses/{id}/assignments` per course would mean one request per
class for the same answer.

**Two things to confirm before trusting this, both from reading docs rather
than a live token — same discipline as every other doc in this project:**

- The `plannable` field's exact shape per `plannable_type` (`assignment`,
  `quiz`, `discussion_topic`, ...) — the sample response shows
  `plannable: {...}` without full detail. Confirm the fields you actually
  need (`title`, `due_at`) exist on every type you plan to surface, or filter
  to `plannable_type == "assignment"` if the others turn out to be noisy.
- **Pagination is Link-header based** (confirmed: "List endpoints use Link
  header pagination"), and `get_json` only returns the decoded body — it
  never sees the `Link` header. For a hackathon-scale course load this is a
  real but survivable gap: don't build Link-header following, just note the
  limit (`per_page` up to 100 covers a normal student's course list
  comfortably) rather than silently truncating without saying so.

Citation `url`: Canvas courses and assignments both come with a real,
student-visible page — construct it as `https://canvas.cmu.edu/courses/{id}`
/ the `html_url` field the planner-items response already includes (use the
API's own `html_url`, don't hand-build the assignment path yourself).

---

## Part B — Ed Discussion

New from scratch. Confirmed by reading `edapi/edapi.py` directly (see the
correction above) — this is real, not a guess from a README summary.

- Base URL: `https://us.edstem.org/api/`
- Auth: `Authorization: Bearer <token>` (the token from
  `edstem.org/us/settings/api-tokens` — the same one PRD already names)
- `GET user` → the logged-in user's own info
- `GET courses/{course_id}/threads?limit=&offset=&sort=new` → `{"threads": [...]}`
- `GET threads/{thread_id}` → one thread with comments

```python
_ED_BASE = "https://us.edstem.org/api/"


def ed_search_threads(*, session_id: str, course_id: str, keywords: str | None = None, limit: int = 20) -> dict:
    connection = _ed_connection(session_id)
    headers = {"Authorization": f"Bearer {connection.get_token()}"}

    try:
        payload = get_json(
            f"{_ED_BASE}courses/{course_id}/threads",
            params={"limit": min(limit, 100), "offset": 0, "sort": "new"},
            headers=headers,
        )
    except httpx.HTTPError as exc:
        raise ToolError(f"Ed Discussion unreachable: {exc}") from exc

    mark_synced(connection)
    threads = payload.get("threads", [])
    if keywords:
        needle = keywords.lower()
        threads = [t for t in threads if needle in (t.get("title", "") + t.get("content", "")).lower()]

    return {"results": threads, "citations": [_thread_citation(t, course_id) for t in threads]}
```

**Two open questions Phase 0 has to resolve, not guess at:**

- **There is no confirmed "list my Ed courses" endpoint.** `edapi`'s source
  doesn't show one. Check whether `GET user` returns course enrollments in
  its response — if it does, that's how `ed_search_threads` resolves a vague
  "my systems class" reference to a real `course_id`, the same way
  `canvas_list_courses` does for Canvas. If it doesn't, this tool needs
  `course_id` supplied some other way (stored at connect time? asked of the
  model?) — don't ship a tool the model can never actually call because it
  has no way to learn a valid `course_id`.
- **No native keyword search was found in the API.** `list_threads` takes
  `limit`/`offset`/`sort`, not a query string. The client-side filter above
  is a stopgap — it only searches whatever page of recent threads got
  fetched, not the whole course's history. Good enough for "did staff say
  anything about the late policy recently"; not a real search. Say so in the
  tool's `description` rather than let the model assume it's exhaustive.

Citation `url`: **don't invent one.** No confirmed frontend URL pattern for
a single Ed thread was found in what got read here — check whether the API
response itself carries a usable link (Canvas's does; Ed's might not), and
if nothing reliable turns up, leave `url` empty rather than guess at
`edstem.org/us/courses/{id}/discussion/{thread_id}` — same rule
`docs/b2-courses.md` and `docs/b3-web-verify.md` already established for
Courses and web results.

---

## Part C — Stellic (mock only)

**Explicitly scoped down: no real Stellic integration, no JSON upload
parser.** PRD's own reasoning already rules out anything else — Stellic has
"institutional PAT only; no student OAuth," so there is no safe student-facing
credential to build against at all, live or otherwise.

Register it the same shape as `apps/tools/maps.py` — a pure fixture, always
`is_mock: True` — but still gated through the connections flow so the
settings UI (F4) has something real to toggle, matching Ed/Canvas's UX
rather than being a special case:

```python
STELLIC = "stellic"

@register_tool(
    name="stellic_degree_audit",
    description=(
        "Check progress toward a degree or minor requirement, using a mock degree "
        "audit. This is placeholder data, not the student's real Stellic record — "
        "say so in the answer. Combine with search_courses/get_course for live "
        "course data; this tool only covers what's 'required,' not what's offered."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "program": {"type": "string", "description": "e.g. 'CS minor', 'ECE major'."},
        },
        "required": ["program"],
    },
    mode="personal",
    requires_connector=STELLIC,
    is_mock=True,
)
def stellic_degree_audit(*, session_id: str, program: str) -> dict:
    _ = require_connection(session_id, STELLIC)  # confirms it's "connected"; nothing else read from it
    audit = _MOCK_AUDITS.get(program.lower(), _MOCK_AUDITS["cs minor"])
    return {"results": [audit], "citations": [{
        "title": f"{audit['program']} — mock degree audit",
        "url": "",
        "snippet": f"{audit['completed']}/{audit['required']} units completed (mock data)",
        "indexed_at": None,
    }]}
```

"Connecting" Stellic through `POST /api/connections/` doesn't need a real
credential — `{"provider": "stellic", "credential": {}}` is enough, since
nothing here is ever actually authenticated against anything. Don't add
`STELLIC` to `CREDENTIAL_FIELDS`' required-keys check in
`docs/b5-connections.md` (or map it to an empty tuple) so an empty
credential isn't rejected as incomplete.

`_MOCK_AUDITS`: two or three canned programs (CS minor is the PRD's own
example query) with made-up but plausible-looking requirement/completed
counts — this is fixture data the same way `maps.py`'s buildings are.

---

## Non-negotiables

- **Never log a token, a Canvas/Ed response header, or anything containing
  `Authorization`.** `run_tool()` already omits tool call *arguments* from
  its log line; a `headers` dict built inside a tool function is a second
  place a stray debug line could leak one — same caution as the
  Piazza/Gradescope doc's password warning, one level less severe (a token
  is revocable; nothing here should still make logging it acceptable).
- **`get_json`'s `headers` param never gets cached, structurally** — Part 0's
  whole point. Don't build a version of Canvas/Ed that routes around it with
  a hand-rolled `httpx` call "just this once."
- **Stellic never becomes real.** If someone's tempted to add actual Stellic
  scraping later, that's the exact SSO-login question already settled
  earlier in this project — re-read that reasoning before revisiting it, not
  after.
- **No citation from any of these three carries an invented `url`** — same
  rule as everywhere else in this project.

---

## How to verify

`backend/apps/personal/tests.py` (doesn't exist yet). Mock `get_json`
entirely for Canvas/Ed — don't call the real APIs from the test suite.

- [ ] `canvas_list_courses`/`canvas_get_assignments` send `Authorization:
      Bearer <token>` and hit the right endpoints (`/courses`,
      `/planner/items`)
- [ ] `ed_search_threads` sends the same header shape against
      `us.edstem.org/api/`
- [ ] Neither tool ever calls `get_json` with `ttl > 0`
- [ ] A 401/403 from either API becomes a `ToolError`, not an unhandled
      exception
- [ ] `stellic_degree_audit` returns `is_mock: True` on every citation and
      never makes a network call
- [ ] `Provider.STELLIC` connects with an empty credential without a
      validation error

Then, once, live: a real Canvas PAT against a real course load, checked for
correct `due_before`/`course_id` filtering. Ed's live check depends on
Phase 0's two open questions actually being answered first — don't attempt
it before then.

```
docker compose exec backend python manage.py test apps.personal
```

---

## Done when

- [ ] `get_json` accepts `headers`, and caching is structurally impossible
      when they're present
- [ ] Canvas's two tools return real data, with citations
- [ ] Ed's course-resolution and search-scope questions have real answers,
      not TODOs
- [ ] Stellic returns mock data, clearly labeled, no network calls
- [ ] Boxes ticked in `tasklist.md` B5, same commit

## Style

Follow `CLAUDE.md`. Comments explain *why*, never what. If a comment could be
deleted without losing information, delete it.
