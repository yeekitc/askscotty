# B3 — Web verify: implementation prompt

Hand this to whoever (or whatever) builds B3. It is written to be pasted whole.

**The one-line version:** there is no search provider to integrate. `web_search`
and `web_fetch` run on Anthropic's servers under the key we already have. B3 is
registry plumbing plus result parsing — declaring two tools we never execute, and
reading what comes back inside the *assistant* message.

---

## Read first, in this order

1. This document.
2. `CLAUDE.md` — repo rules, including comment style.
3. `backend/apps/tools/registry.py` — read it properly. `Tool`, `Tool.definition()`
   and `register_tool` all assume a tool is a Python function. A server tool is
   not, and that is the one structural change B3 makes.
4. `backend/apps/planner/loop.py` — where results get harvested. B3 adds a second
   harvest path; it should not need to change the loop's control flow.
5. `docs/b4-planner.md` §4 "Server-side tools don't fit the registry" — the four
   non-obvious API rules, already researched. Don't re-derive them.
6. `tasklist.md` §1 (the settled decisions, including cost precedence) and B3.

---

## The central design decision

**A server tool is declared and never dispatched.**

Everything else follows from that. `run_tool` must never be reachable for one;
`_dispatch` in the loop already ignores anything that isn't a `tool_use` block,
so it will skip them for free. The work is in two places instead:

```
registry   →  Tool.definition() must emit Anthropic's shape, not ours
citations  →  a second harvest path, reading the assistant message
```

`Tool.definition()` today returns `{name, description, input_schema}`. A server
tool needs `{"type": "web_search_20260318", "name": "web_search", "max_uses": …}`.
Suggested shape: give `Tool` an optional `server_spec: dict | None`, make
`func` optional, and have `definition()` branch on it. `is_server_tool` is then
just `server_spec is not None`, and `register_tool` gains a sibling —
`register_server_tool(name, description, mode, spec)` — because there is no
function to decorate.

Keep `run_tool` refusing a server tool explicitly, with a `ToolError`. It should
be unreachable; make it loud rather than mysterious if it ever isn't.

**Asked and settled: could the web tools just live outside the registry, leaving
`Tool` alone?** They could — the planner would append raw dicts to the tools
array. Don't. Of what the registry does, two things are load-bearing here:
`modes_for`, which is what puts `web_verify` in `modes_used`, and
`citation_defaults`, which is the PRD §9 guarantee that `is_mock` derives from
the producing tool rather than from its result. Bypassing it means hand-wiring
both somewhere else. And `all_tools()` is sorted for a reason — tools sit
*before* the system prompt in the cached prefix, so an unstable order silently
costs a re-cache on every request. A second hand-maintained list is one more
thing to keep sorted by hand. The exception is ~10 lines; the alternative is
more code in more places.

---

## Build, in phases — each is complete on its own

### Phase 1 — declare the tools

`backend/apps/tools/web.py`, imported from `ToolsConfig.ready()` (see CLAUDE.md
"Registering a tool" — two lines, and missing either means it silently never
registers).

- `web_search` — `web_search_20260318`, mode `web_verify`
- `fetch_url` — `web_fetch_20260318`, mode `web_verify`

Both take `allowed_domains`, `blocked_domains`, `max_uses`, `max_content_tokens`.
Set `response_inclusion: "excluded"` on the search tool or raw results are echoed
back and we pay output tokens for text nobody sees.

**Resolve this in the first ten minutes, because it decides the design:** check
whether `allowed_domains` and `blocked_domains` can be set on the *same* tool, or
whether they are mutually exclusive per request. Either way the answer is
allowlist-first — an allowlist excludes Canvas by construction, so PRD §6 is
satisfied without the denylist. The denylist is defence in depth and a clearer
error code (`url_not_allowed` vs `url_not_accessible`), not the safety mechanism.

Allowlist, public hosts only: `cmu.edu` and subdomains, `cs.cmu.edu`,
`ece.cmu.edu`, `coursecatalog.cmu.edu`, `computing.cmu.edu`, `cmueats.com`,
`tartanconnect.cmu.edu`, `scottylabs.org`, `cmu.guide`.

Denylist, if it can coexist: `canvas.cmu.edu`, `s3.andrew.cmu.edu`,
`stellic.com`, `autolab.andrew.cmu.edu`, `25live.collegenet.com`,
`cmu.joinhandshake.com`.

Ship phase 1 and confirm a real query reaches a real search before starting
phase 2.

### Phase 2 — harvest what comes back

The loop currently harvests citations only inside `_dispatch`. Add a second path
that reads **every** assistant message, because that is where server results
live. Three block kinds matter:

| Block | Do what |
|---|---|
| `server_tool_use` | the lane ran — append its registered name to `ran`, so `modes_for` puts `web_verify` in `modes_used` |
| `web_search_tool_result` | `content` is a **list** on success and an **object** on error. Branch before indexing. |
| `text` with `.citations` | **this is the one worth harvesting** — each is a `web_search_result_location` with `url`, `title` and `cited_text` |

The text-block citations are the claims the model actually leaned on, and they
arrive with the snippet already filled in: `snippet = cited_text`. `verified_at`
is **ours to stamp** — the API does not supply it. Dedupe by URL inside the
ledger; the same page cited in four sentences is one source, not four.

Errors arrive as **HTTP 200** with `web_search_tool_result_error` and codes like
`max_uses_exceeded`, `too_many_requests`, `unavailable`. Treat one the way a
`ToolError` is treated: a note on the answer, never an exception.

### Phase 3 — light the chip while the search runs

Optional but this is the demo. A search turn takes ~26 seconds, and right now
that is 26 seconds of dead air with no lane lit, because we only learn the search
happened once the turn is over.

`stream_message` in `planner/client.py` already sees every stream event. Have it
yield a marker when a `content_block_start` announces a `server_tool_use`, and
let the loop turn that into `mode_start` in real time. It currently yields
`str | Message`; a third kind is a small change.

### Phase 4 — the staleness policy

See "Cost precedence" below. This is the phase most likely to get skipped and
most likely to cost real money.

---

## Cost precedence — the rule this lane exists under

> **RAG first. Web search is the fallback, not the reflex.**

Settled decision, recorded in `tasklist.md` §1. The numbers behind it: one
searching query measured **~35.9k input tokens and ~26 seconds**. Worse, those
results then sit in the message list and are **re-sent as input on every
subsequent call in the same turn** — our cache breakpoint is on the system block,
so nothing in message position is ever cached. A four-hop answer that searched
once pays for those tokens four times.

Three levers, weakest to strongest:

1. **The tool description.** The registry's own docstring says it: the
   description is the main thing deciding whether a tool gets picked, so *say
   when not to use it*. Something like "Only after `campus_search` has returned
   nothing relevant, or when the indexed page is older than N days."
2. **The system prompt** — order the lanes explicitly in `planner/prompt.py`.
   Note it is frozen and cached; editing it is fine, it just re-caches once.
3. **`max_uses`.** The only hard cap. Start at **2**.

Make the threshold a setting (`WEB_VERIFY_STALE_AFTER_DAYS`), because the right
number is a demo-day judgement call, not a code change.

**Honest caveat:** `campus_search` does not exist yet — `apps/rag/tools.py` is
still an empty scaffold. Until B1 lands, "RAG first" cannot be verified end to
end, because there is no RAG to come first. Encode it in the description, the
prompt and `max_uses` now; verify it the day B1 registers its tool.

---

## Non-negotiables

- **Never dispatch a server tool.** Declare it; the API runs it.
- **Append assistant content byte-for-byte.** Search results carry
  `encrypted_content`; a reconstructed assistant turn is a 400 on the next call.
  The loop already does this — don't "tidy" it.
- **A mixed turn defers the search.** If the model calls `campus_search` *and*
  `web_search` in one batch, you get `stop_reason: tool_use` and the search
  **has not run yet**. Return our results; the API runs the search next request.
  The loop handles this correctly today. Don't add a special case.
- **Do not declare `code_execution` alongside these.** Dynamic filtering is
  built in, and a second execution environment confuses the model.
- **`is_mock` still comes from the producing tool**, never from the result.
  PRD §9 is enforced in `citation_defaults`; route web citations through it.
- **Check the org has web search enabled** before demo day, once. If an admin
  disabled it in the Console, *declaring* the tool is a **400** — which means
  every request fails, not just searching ones. No kill switch for this
  deliberately (decided): it is our own Anthropic org, so the fix is a Console
  toggle rather than a deploy, and a setting nobody will remember to flip is not
  insurance. Just confirm it works before it matters.

---

## Interactions with what B4 already built

Read these before you change a planner setting.

- `pause_turn` **is already handled** (`PLANNER_MAX_PAUSE_RESUMES`). A long
  search turn ending early is the case it was written for. Don't rebuild it.
- **The deadline may be too tight.** `PLANNER_DEADLINE_SECONDS` is 60 and one
  search is ~26s. Two searches plus a final turn will trip it and you will get a
  forced-text answer with a "time ran out" note. If you raise it, raise
  `TIMEOUT_MS` in `frontend/app/lib/api.ts` too — deadline plus one final call
  has to fit inside the app's backstop, which is 120s.
- **Markers do not reach web citations.** With `PLANNER_CITATION_MARKERS` on,
  the model writes `[S1]` for *our* tool results, but web citations are harvested
  from its own output after the fact, so it never writes an id for them. They
  get an `id` and no marker. Known asymmetry; decide whether to close it.
- **Follow-ups re-search from scratch.** Our `history` contract is plain text, so
  `encrypted_content` does not survive a turn. "Is that still current?" pays the
  full search cost again. Acceptable for P0 — just don't treat follow-ups as
  cheap.

---

## Out of scope — do NOT build

- **Enqueuing discovered URLs into `CrawlSeed`.** The model does not exist yet
  (B1). Leave the hook, not the implementation.
- **`resolve_course_site`** — a static map of the ten Appendix B course
  homepages. Useful, trivial, and not what this lane is about. P1.
- **Anything that scrapes.** If it needs a login, it is out (PRD §9).

---

## How to verify

The happy accident of this lane: **it is fully testable offline**, unlike B4,
whose tools all raised `ToolError`. Server results are just blocks in a message,
so a scripted `FakeModel` can produce them. Use the existing harness in
`backend/apps/planner/tests.py` — `FakeModel`, `reply()`, `text()` — and add
block builders alongside them.

- Backend commands run inside the container: `docker compose exec backend …`
- Django's test runner. **No new dependency** without a row in
  `docs/dependencies.md` and a reason.

Cover at least:

- [ ] `fetch_url`'s spec carries the allowlist, and `canvas.cmu.edu` is not in it
- [ ] a `web_search_tool_result_error` produces a note, not an exception —
      one test per code, including `max_uses_exceeded`
- [ ] `content` as an object (error) does not get indexed as a list
- [ ] a text block's `web_search_result_location` becomes a `Citation` with
      `snippet == cited_text` and a stamped `verified_at`
- [ ] the same URL cited twice yields one citation
- [ ] a `server_tool_use` block puts `web_verify` in `modes_used`
- [ ] `run_tool("web_search", …)` raises rather than doing something surprising

Then, live and once: a real query that actually searches, and the denylist
control from `docs/dependencies.md` — a blocked host failing with
`url_not_allowed` while an uncovered one fails with `url_not_accessible`. That
control is the whole test; without it the result is meaningless, because Canvas
fails either way.

---

## Done when

- [ ] A question the index cannot answer triggers a real search and comes back
      cited, with `web_verify` in `modes_used`
- [ ] Those citations carry a real `snippet` and a stamped `verified_at`
- [ ] A search failure degrades to a note, never a 500
- [ ] Canvas cannot be fetched, and there is a test proving the denylist did it
- [ ] `max_uses` is capped and the description tells the model to prefer RAG
- [ ] Web search confirmed enabled for the org
- [ ] Boxes ticked in `tasklist.md` B3, same commit

## Style

Follow `CLAUDE.md`. Comments explain *why*, never what. If a comment could be
deleted without losing information, delete it.
