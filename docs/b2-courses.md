# B2 — Courses tool: implementation prompt

Hand this to whoever (or whatever) builds it. Written to be pasted whole.

**The one-line version:** `search_courses` and `get_course`, backed by
`course-tools.apis.scottylabs.org` — confirmed live, no auth, tested directly
below. Scope explicitly **excludes** degree/program requirements; that data
isn't in this API at all and is already RAG's job per PRD §4.

---

## Status: `courses.py` follows this doc

The endpoint facts below were verified live and are what the merged
`backend/apps/tools/courses.py` is built on. The tests in
`backend/apps/tools/tests.py` use these shapes — string units, int meeting
days, a 500 for an unknown course — rather than friendlier invented ones,
which is the only reason they say anything about whether the tool works.

---

## Endpoint verification — done, use these facts, don't re-derive them

Base: `https://course-tools.apis.scottylabs.org`. Confirmed live, no auth
required, every row below tested directly against the real API.

| Endpoint | Status | Notes |
|---|---|---|
| `GET /courses/search?keywords=...` | 200 | Paginated: `{totalDocs, totalPages, page, docs: [...]}`. Empty `keywords` returns the whole catalog (8395 docs). |
| `GET /course/{id}` | 200 | One record — same fields as a search doc, plus internal `id`/`v` (Mongo fields, ignore both). |
| `GET /schedules?courseID={id}` | 200 | **The source for instructors and meeting times.** See the correction below. |
| `GET /schedules` (no `courseID`) | hangs / no response | **Never call it bare.** Always pass `courseID`. |
| `GET /course/{nonexistent-id}` | **500** | Upstream's "not found" is a 500, not a 404 — build around this explicitly (see Non-negotiables). |
| `GET /schedules?courseID={nonexistent-id}` | 200, `[]` | Softer failure mode than `/course/{id}` for the same bad input. |
| `course.apis.scottylabs.org` (the *other* URL PRD Appendix A lists) | **502** | Dead. Use `course-tools.apis.scottylabs.org` only — the Appendix A row is stale, worth a follow-up fix once this ships. |

**Correction to earlier guidance in this project:** `/schedules` was reported
as non-responsive and the plan was to source meeting times some other way.
That was based on calling it unfiltered. `/schedules?courseID=15-213` returns
200 with real data — lectures, sections, instructors, times, rooms. Build
against it; don't work around a limitation that isn't real.

Sample `/schedules?courseID=15-213` shape (list, one entry per
semester/year the course ran):

```json
[
  {
    "courseID": "15-213", "semester": "...", "session": "...", "year": 2024,
    "lectures": [
      {"id": "...", "name": "Lec 1", "instructors": ["Lucia, Brandon", "Railing, Brian"],
       "location": "Pittsburgh, Pennsylvania",
       "times": [{"begin": "01:30PM", "end": "02:50PM", "days": [2, 4], "building": null, "room": "CMU REMOTE"}]}
    ],
    "sections": [
      {"id": "...", "name": "A", "lecture": "Lec 1", "instructors": ["Lucia, Brandon", "Railing, Brian"],
       "times": [{"begin": "10:40AM", "end": "11:30AM", "days": [1], "building": "MI", "room": "MELLON"}]}
    ]
  }
]
```

Sample `/course/{id}` / `/courses/search` doc shape:

```json
{
  "courseID": "15-213", "name": "Introduction to Computer Systems", "units": "12.0",
  "department": "Computer Science", "desc": "...",
  "prereqs": ["15-122"], "prereqString": "15122", "coreqs": [], "crosslisted": ["15-513"]
}
```

---

## Scope: what this tool does NOT cover

Per-course **prerequisites are real and present** — `prereqs`, `coreqs`,
`prereqString`, `crosslisted` are all live fields, confirmed above. **Degree
or program requirements are not in this API anywhere** — no field on any
endpoint says what a major or minor needs. That's not a gap to work around:
PRD §4 already routes it elsewhere — *"The Courses API gives schedules and
prereqs but not what a major needs... [the course catalog crawl] is our only
public route to 'on track for a CS minor?'"* That's `campus_search` against
`coursecatalog.cmu.edu` (RAG, B1, your teammate's lane). Don't build a
requirements engine here, and don't route a "what do I need for X" question
into this tool.

---

## The three unknowns, settled

- **The `days` integer encoding is 1=Monday … 5=Friday.** Across 60 courses
  sampled from the live API the only values that appear are 1–5, and the two
  commonest patterns are `[1,3,5]` and `[2,4]` — MWF and TR. Weekend encoding
  is untested and does not matter, since the tool only filters M T W R F.
  `_day_codes` converts to letters at the normalization boundary so nothing
  downstream carries the encoding.
- **`units` on `/courses/search` does not filter.** `keywords=machine
  learning&units=9` returns the same 259 `totalDocs` as without it, and the
  page still contains 6- and 12-unit courses. The filter has to be client-side
  — and because the endpoint pages at 10, a filtered search reads a few pages
  rather than one. `semester` is ignored server-side too.
- **"Current semester" is the most recent offering on file.**
  `/schedules?courseID=15-213` returns 20 entries spanning 2020–2026, so
  flattening them answers "when does it meet?" with six years of rooms at
  once. `_pick_offering` takes the one asked for, or the latest by
  `(year, spring<summer<fall)`. `semester` accepts `F24`, `S2025` or
  `fall 2024`.

---

## Read first, in order

1. This document.
2. `CLAUDE.md` — "Registering a tool," the `apps.tools` case (no new app
   needed — this tool has no models).
3. `backend/apps/tools/registry.py` — `Tool`, `register_tool`, `ToolError`,
   `citation_defaults`.
4. `backend/apps/personal/tools.py` — closest existing example of the
   `@register_tool` pattern, even though it's still a stub.
5. `backend/apps/core/http.py` — `get_json`, the one outbound HTTP path.
   Every fetch here goes through it; don't build a second retry/timeout/
   rate-limit layer.
6. `tasklist.md` B2 "Courses," PRD §5 and §8, PRD Appendix A.

---

## Design decisions

- **Location:** `backend/apps/tools/courses.py`. Two-line registration
  (`from . import courses` in `ToolsConfig.ready()`) — no new app, this tool
  has no models.
- **Two tools**, per `tasklist.md` B2: `search_courses(query?, units?,
  days_excluded?, semester?)` and `get_course(course_number)`. `mode="courses"`,
  `is_mock=False`, no `requires_connector` (public).
- **Normalize**, don't pass the raw API shape to the model: `number, title,
  units, department, description, prereqs, coreqs, crosslisted, offerings`
  where `offerings` is a flattened slice of the `/schedules` response
  (instructor names + meeting times) — the raw `lectures`/`sections` nesting
  is API plumbing the model doesn't need to see.
- **`get_course(course_number)` makes two upstream calls** — `/course/{id}`
  for description/prereqs/units, `/schedules?courseID={id}` for
  instructors/meeting times — merged into one tool result.
- **Citation `url`: don't invent one.** There's no per-course public page
  this API points at. Check whether `coursecatalog.cmu.edu` has a real,
  working, stable per-course URL pattern; if you can't confirm one in the
  time available, leave `url` empty rather than link somewhere unverified —
  `types.ts` already treats an empty `url` as valid ("no public URL"), and
  `prompt.py`'s system prompt already tells the model an invented URL is "the
  single worst failure this product can have." Use a synthesized one-line
  `snippet` instead ("15-213: Introduction to Computer Systems, 12 units,
  prereq 15-122") — `campus_search` gets its snippet for free from the
  matched chunk; this tool has to build one.
- **The 500-on-not-found behavior needs explicit handling.** Catch it in
  `get_course` and re-raise as a `ToolError` reading "no course numbered X" —
  read literally, a bare 500 says "upstream is broken," not "you asked for
  something that doesn't exist," and the model needs to tell those apart to
  answer sanely.

---

## Non-negotiables

- Never call `course.apis.scottylabs.org` — confirmed dead.
- Always pass `courseID` to `/schedules` — never call it bare.
- A `ToolError` for "course not found," never an uncaught exception — this is
  exactly `tasklist.md` B2's "degrade, don't crash the answer."
- Don't attempt degree/program requirements here — see Scope above.
- No new dependency without a `docs/dependencies.md` row (CLAUDE.md) — this
  shouldn't need one; `httpx` is already justified.

---

## How to verify

`backend/apps/tools/tests.py`. Patch `apps.tools.courses.get_json` — never hit
the real API from the suite.

Covered:

- [x] A normal `search_courses` call returns normalized results with citations
- [x] A normal `get_course` call merges `/course/{id}` and `/schedules` correctly
- [x] A nonexistent course degrades to a clear `ToolError`, not a raw 500
- [x] An empty `/schedules` result (course exists, never scheduled) doesn't crash
- [x] The days-filter, on int days rather than an invented letter string
- [x] No citation carries an invented `url`

Then, live and once: run `search_courses("machine learning")` and
`get_course("15-213")` against the real API and read the normalized output —
that's the actual check that the findings above still hold.

```
docker compose exec backend python manage.py test apps.tools
```

---

## Done when

- [x] `search_courses` and `get_course` registered, returning normalized
      results and citations with no invented `url`
- [x] Meeting times and instructors sourced from `/schedules?courseID=...`
- [x] "9-unit ML elective, no Friday" (PRD §8) returns something sane
- [x] A nonexistent course number degrades to a clear message, not a 500
- [x] Boxes ticked in `tasklist.md` B2 "Courses," same commit

## Style

Follow `CLAUDE.md`. Comments explain *why*, never what. If a comment could be
deleted without losing information, delete it.
