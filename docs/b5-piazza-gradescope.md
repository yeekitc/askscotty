# B5 — Piazza and Gradescope connectors

Two personal connectors, each backed by an unofficial, reverse-engineered
library. Built on the credential contract in
[b5-connections.md](./b5-connections.md); the tools themselves live in
`backend/apps/personal/tools.py` alongside Canvas and Ed.

---

## The credential trade-off — a real risk, accepted deliberately

**Piazza and Gradescope issue students no API token.** Their only login is the
student's real CMU email and password. So connecting either means we store a
password we can decrypt — not a scoped credential the student can revoke
without touching their account, which is what Canvas and Ed hand over
([b5-canvas-ed-stellic.md](./b5-canvas-ed-stellic.md)). That is a materially
worse failure mode, and it is the whole reason this doc exists.

**Gradescope is worse still.** Its `Assignment` objects carry `grade` and
`max_grade`, so a leaked Gradescope credential exposes the student's grades,
not just their deadlines.

This was raised explicitly — skip these two, offer a manual-upload alternative,
or accept the risk — and **the risk was accepted**, knowingly. It is not the
default pattern for this project: CLAUDE.md says "do not scrape behind logins,"
and these two are a recorded exception to that rule rather than the rule
bending quietly. Build accordingly — the encryption discipline is the floor
here, not optional polish.

What follows from it, all of it load-bearing:

- Credentials are Fernet-encrypted at rest and decrypted only inside the call
  that spends them; a decrypted credential is never logged, never attached to
  an exception, never returned.
- The Gradescope citation card deliberately withholds the grade. It reaches the
  model through `results`, but a citation card is the part of an answer that
  gets screenshotted.
- No failure path interpolates a library's own exception text into a
  `ToolError` — `piazza-api` assembles its message out of a login page we do
  not control, and a `ToolError`'s message travels into the planner's context
  and can reach an answer. The exception *type* is logged instead.
- The settings UI row says, in the copy itself, that this stores a real
  password (`frontend/app/components/ConnectionsModal.tsx`).
- [dependencies.md](./dependencies.md) records the same trade-off in each
  package's reasoning column — the honest version of "why this dependency."

---

## Read first

1. This section above.
2. [b5-connections.md](./b5-connections.md) — the credential storage this
   builds on.
3. `CLAUDE.md` — "Do not scrape behind logins," and why this is an explicit,
   recorded exception.
4. `backend/apps/tools/registry.py` — `ToolError`, `citation_defaults`. Note
   `is_mock` is `False` for both connectors: this is live data, just privately
   sourced.
5. [dependencies.md](./dependencies.md) — both packages, and why each is a risk.

---

## What the libraries actually do

Confirmed by reading the installed packages, not their READMEs. Unofficial
libraries drift and guarantee no stability, so re-confirm after any upgrade.

**`piazza-api`** (PyPI `piazza-api`, import `piazza_api`)

- `user_login(email=..., password=...)` prompts on stdin for anything it is
  *not* given, which a web request can never answer — so both keyword
  arguments are always passed, and a blank one is rejected at the connections
  endpoint rather than here.
- `get_user_classes()` → the student's classes, each with an `nid`.
- `network(nid).search_feed(query)` is a real server-side search, which is why
  the tool does not page through `iter_all_posts`.

**Piazza scopes everything to a "network" — one per class** — so there is no
single "the student's Piazza data" the way Canvas has "the student's courses."
The network id is discovered from the student's own account at query time
(`piazza_list_classes`), not asked for at connect time: the model has no way to
know a network id, and making someone paste one to connect would be a worse
version of the same lookup. `piazza_search` takes an optional `network_id` to
narrow to one class. Posts are capped per class — a feed search can match a
whole semester of discussion, and the planner pays for every row in context.

**`gradescopeapi`** (PyPI name is `gradescopeapi`; the repo's
`gradescope-api` is not on PyPI at all)

- `GSConnection().login(email, password)` — direct params, no prompt.
- `account.get_courses()` returns **dicts of dataclasses keyed by course id**,
  not the lists of dicts the README describes. Field names come off the
  package.
- `account.get_assignments(course_id)` → `Assignment` dataclasses.

Instructor courses are dropped at the source rather than filtered later: "the
student's assignments" must never include a class they grade. One unreadable
course is logged and skipped, so it does not cost the student the other five.

## 2FA, and the demo-only cookie path

**Neither library handles 2FA.** If a CMU Piazza or Gradescope login routes
through Andrew SSO / Duo, an automated `login()` call has no way past the
prompt — it hangs rather than failing cleanly. Confirming this end-to-end needs
a real CMU account, which the test suite must never hold; it is the one thing
here still open.

`backend/apps/personal/demo_only` is the fallback for exactly that failure. A
browser extension reads the session cookies of a tab **we are already logged in
to** and POSTs them; the tools then load that cookie jar into the library's
session instead of calling `login()`, which is the only path past Duo. It is
walled off deliberately — DEBUG-only route, its own package, nothing depends on
it — because scraping a logged-in tab's cookies is a demo convenience for
reaching *our own* accounts, not something we ship. Read that folder's README
and [browser-extension.md](./browser-extension.md) before touching it. **The
email/password path is the real one.**

## Piazza's privacy wrinkle

Piazza posts are written by classmates and course staff, not only by the
connecting student — unlike Gradescope assignments or Canvas due dates, which
are inherently personal to the account. Reading a shared class discussion
through one student's login is not the same privacy shape as reading their own
grades. `piazza_search`'s description says so: this is the student's *view* of
a shared space, so summarise what a thread established rather than repeating
posts back word for word, and do not name the students who wrote them.

---

## Non-negotiables

- **Never log `email` or `password`**, anywhere — not in a tool's own code, and
  not by relying on `run_tool`'s existing arg-omission alone. That covers
  planner-supplied *tool call* arguments; a credential pulled from
  `get_credential()` inside a tool function is a second place a stray
  `print`/`logger.info` could leak one. That is exactly the kind of line that
  is fine in dev and forgotten in prod.
- **Both packages keep their [dependencies.md](./dependencies.md) row**,
  including the credential-storage trade-off in the reasoning column.
- **The connector row for these two says plainly that this stores the
  student's real password** — never softened to sound like Canvas's token flow.
- **The demo cookie path stays DEBUG-only and stays walled off**, and is never
  widened to Canvas or Ed, which have a revocable token and do not need it.

---

## What the tests hold

`backend/apps/personal/tests.py`, with both libraries mocked entirely — the
real services are never called from the test suite (they are unofficial and
could rate-limit or flag automated logins from CI):

- Login is non-interactive and receives the decrypted credential.
- **Nothing logged by a failing call carries the credential**, and no test
  asserts against a literal password.
- Only courses the student takes are read; one unreadable course or class does
  not lose the others.
- A login failure, an upstream failure, and a credential encrypted under a
  different key each become a `ToolError` rather than an unhandled exception.
- Gradescope citations invent no url and withhold the grade; Piazza citations
  link to the class feed, not a guessed post anchor.
- Both tools are hidden from a session that has not connected them, and
  another session's connection does not unlock them.
- The demo cookie credential injects the cookie and never calls `login()`, the
  route is absent without `DEBUG`, and its response carries no cookie.

```
docker compose exec backend python manage.py test apps.personal
```
