# B5 — Piazza and Gradescope connectors

Hand this to whoever (or whatever) builds it. Written to be pasted whole.

**The one-line version:** two new personal connectors, each backed by an
unofficial, reverse-engineered library that authenticates with the student's
actual CMU email and password — not a scoped token like Canvas or Ed. That
was a deliberate, explicit decision (not the default for this project — see
CLAUDE.md's "do not scrape behind logins"), made after being asked directly
whether to skip these, offer a manual-upload alternative instead, or accept
the risk. **The risk was accepted.** Build it accordingly: the same
encryption discipline as Canvas is the floor here, not optional polish.

**Depends on `docs/b5-connections.md`.** `Provider.PIAZZA`/`GRADESCOPE`, the
credential-shape convention (`get_credential()`/`set_credential()`,
`CREDENTIAL_FIELDS`), and the connections endpoint all need to exist first —
this doc only adds the tools themselves.

---

## Read first, in order

1. This document.
2. `docs/b5-connections.md` — the credential storage this builds on.
3. `CLAUDE.md` — "Do not scrape behind logins," and why this doc is an
   explicit, recorded exception rather than the rule bending quietly.
4. `backend/apps/personal/tools.py` — the Canvas stubs, still the closest
   existing example of `@register_tool` + `requires_connector` + translating
   a `LookupError` into a `ToolError`.
5. `backend/apps/personal/context.py` — `require_connection`, `mark_synced`.
6. `backend/apps/tools/registry.py` — `ToolError`, `citation_defaults`. Note
   `is_mock` is always `False` here — this is live data, just privately
   sourced.
7. `docs/dependencies.md` — add rows for both new packages in the same
   commit that adds them to `requirements.txt` (CLAUDE.md).

---

## Phase 0 — confirm the library interfaces before writing tool code

What's below is grounded in each project's current README, not verified
against a real login — confirm the exact call shape live before trusting it,
the same discipline `docs/b2-courses.md`'s Phase 0 used for the Courses API.
Unofficial libraries drift; there is no stability guarantee here the way
there is for a documented public API.

**`piazza-api`** (PyPI: `piazza-api`, import: `piazza_api`):

```python
from piazza_api import Piazza

p = Piazza()
p.user_login()  # documented as an interactive prompt by default
p.network("<network_id>").iter_all_posts(limit=N)
```

Two things to nail down before building on this:

- Whether `user_login()` accepts `email=`/`password=` keyword arguments
  instead of prompting — the tool obviously can't sit at an interactive
  prompt. If it doesn't, check `PiazzaRPC` (the lower-level class the docs
  mention) for a non-interactive login path instead.
- **Piazza data is scoped per class** (`network_id`, what Piazza calls a
  "network" — roughly one per course). There's no single "the student's
  Piazza data" the way Canvas has "the student's courses." Decide: does the
  tool take a `network_id` argument per call (the model would need to already
  know it, which it won't), or does connecting Piazza involve picking one or
  more classes at connect time (extra fields in the credential, or a second
  step after connecting)? This is a real design gap, not a detail — resolve
  it before writing `piazza_search`'s signature.

**`gradescopeapi`** (PyPI package name — note it's *not* hyphenated
`gradescope-api` like the repo name; confirm the exact PyPI name before
adding it to `requirements.txt`):

```python
from gradescopeapi.classes.connection import GSConnection

connection = GSConnection()
connection.login(email, password)  # direct params, no interactive prompt

courses = connection.account.get_courses()  # {"instructor": [...], "student": [...]}
assignments = connection.account.get_assignments(course_id)
```

More straightforward than Piazza — direct `login(email, password)`, and
courses are already split by role, so `courses["student"]` is what a
`gradescope_get_assignments` tool wants. Confirm this shape still matches
the installed version before relying on it.

**Neither library's documentation mentions 2FA.** If CMU's Gradescope or
Piazza login ever routes through Andrew SSO / Duo for some or all courses
(unconfirmed — verify with a real CMU account before building further), an
automated `login()` call will hang or fail at the 2FA step, not silently
succeed. Confirm this works end-to-end with a real account in Phase 0, before
writing the tool functions — if it doesn't, the whole approach needs
rethinking, not a retry loop.

**Demo fallback for exactly that failure: `apps/personal/demo_only`.** A
captured session cookie has already cleared Duo, so injecting one skips
`login()` entirely — `_gradescope_account` / `_piazza_client` take a
`{"cookies": {...}}` credential and load it into the library's session instead
of authenticating. It is walled off (DEBUG-only route, its own folder, nothing
depends on it) because scraping a logged-in tab's cookies through a browser
extension is a demo convenience for reaching *our own* accounts, not something
we ship. Read that folder's README before touching it. The email/password path
above stays the real one.

---

## Design

### Credential shape (from `b5-connections.md`)

Both providers: `{"email": str, "password": str}`. Piazza may need a third
key (`network_id`, or a list) depending on what Phase 0 decides — if so, add
it to `CREDENTIAL_FIELDS[Provider.PIAZZA]` in that doc's model change, not
here as a separate mechanism.

### Where the library call happens

Neither library is async or built for a request/response web app — both do
a real login (network round trip) on every call, since there's no token to
cache and reuse safely (a session cookie could be cached, but neither
library's docs describe how to persist and reuse one across requests, and
guessing at that is exactly the kind of unverified assumption Phase 0 exists
to prevent). That means every tool call pays a real login's latency. Keep
tools synchronous and let `ToolError` carry a clear message if the library
call fails, mirroring Canvas's stub pattern:

```python
@register_tool(
    name="gradescope_get_assignments",
    description=(
        "Get the student's Gradescope assignments and due dates, from their own "
        "account. Only available when the student has connected Gradescope."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "course_id": {
                "type": "string",
                "description": "Restrict to one course. Omit for everything.",
            },
        },
        "required": [],
    },
    mode="personal",
    requires_connector=GRADESCOPE,
)
def gradescope_get_assignments(*, session_id: str, course_id: str | None = None) -> dict:
    connection = _gradescope_connection(session_id)
    credential = connection.get_credential()

    try:
        from gradescopeapi.classes.connection import GSConnection
        gs = GSConnection()
        gs.login(credential["email"], credential["password"])
    except Exception as exc:  # the library's own exception types are unverified — see Phase 0
        raise ToolError(f"Could not sign in to Gradescope: {exc}") from exc

    courses = gs.account.get_courses()
    student_courses = courses.get("student", [])
    if course_id:
        student_courses = [c for c in student_courses if c.get("id") == course_id]

    results = []
    for course in student_courses:
        for assignment in gs.account.get_assignments(course["id"]):
            results.append({**assignment, "course": course.get("name", "")})

    mark_synced(connection)
    return {"results": results, "citations": [_assignment_citation(a) for a in results]}
```

`_assignment_citation` follows the same convention as every other tool fixed
in `docs/b3-web-verify.md` Parts C–E: no invented `url` (there is no stable
public per-assignment Gradescope link), a one-line `snippet`, `indexed_at:
None`. Mirror `_flatten_schedule`-style helpers from that doc for structure,
not content — this is different data.

**Log nothing that includes `email` or `password`.** `registry.py`'s
`run_tool` already omits tool arguments from its log line specifically
because "a personal tool's arguments can identify a student" — for these two
connectors the argument set is a full login credential, so this rule matters
more here than anywhere else it's already enforced. Don't add a log line in
this file that captures `credential` for debugging; that's exactly the kind
of line that's fine in dev and forgotten in prod.

### Piazza's extra wrinkle

`piazza_search` (or whatever it ends up named, pending the `network_id`
decision in Phase 0) has one more consideration `gradescope_get_assignments`
doesn't: Piazza posts often contain other students' names and content, not
just the connecting student's own — unlike Gradescope assignments or Canvas
due dates, which are inherently personal to the account. Reading a shared
class discussion through one student's login is not the same privacy shape
as reading their own grades. Worth a line in the tool's `description` telling
the model this is the *student's view* of a shared space, not private data,
so it doesn't repeat other students' posts back verbatim without cause.

---

## Non-negotiables

- **Never log `email` or `password`**, anywhere — not in a tool's own code,
  not by relying on `run_tool`'s existing arg-omission alone (that covers
  planner-supplied *tool call* arguments; a credential pulled from
  `get_credential()` inside the tool function is a second place a stray
  `print`/`logger.info` could leak it).
- **Both packages get a `docs/dependencies.md` row in the same commit** that
  adds them to `requirements.txt`, including the credential-storage
  trade-off in the reasoning column — that's the honest version of "why this
  dependency," not just "does what we need."
- **The frontend connector row for these two must say, in the copy itself,
  that this stores the student's real password** — not soften it to sound
  like Canvas's token flow. `docs/b5-connections.md`'s settings UI section
  didn't specify per-provider copy; this is where that copy gets written.
- **Confirm the 2FA question (Phase 0) before shipping**, not after. A
  connector that silently hangs mid-demo because Duo interrupted an
  automated login is worse than not having built it.

---

## How to verify

New tests in `backend/apps/personal/tests.py` (doesn't exist yet — check
before assuming). Mock both libraries entirely; never call the real services
in the test suite (they're unofficial and could rate-limit or flag automated
logins from CI).

- [ ] A connected Gradescope session's `get_courses()`/`get_assignments()`
      call reaches the mocked library with the decrypted credential
- [ ] A library exception (bad credential, network failure, whatever Phase 0
      found the real exception types are) becomes a `ToolError`, not an
      unhandled exception
- [ ] No test, and no code path, ever asserts against or logs the literal
      password value
- [ ] `run_tool()` on either tool without the connector connected raises
      (existing `ToolError` gating, already correct — just confirm it still
      applies to the new providers)
- [ ] Citations from both tools carry no invented `url`

Then, once, with a real (test) account: confirm login actually succeeds
end-to-end outside of 2FA-interrupting the flow — this is the check Phase 0
exists to force, don't skip it because the mocked tests pass.

```
docker compose exec backend python manage.py test apps.personal
```

---

## Done when

- [ ] Both libraries' real call shape confirmed live, not assumed from a
      README (Phase 0)
- [ ] The Piazza `network_id` question has an actual answer, not a TODO
- [ ] Neither tool, nor anything it calls, ever logs a credential
- [ ] Both dependencies have a `docs/dependencies.md` row
- [ ] Settings UI copy for these two providers says plainly that this is a
      real password, not a token
- [ ] Boxes ticked in `tasklist.md` B5, same commit

## Style

Follow `CLAUDE.md`. Comments explain *why*, never what. If a comment could be
deleted without losing information, delete it.
