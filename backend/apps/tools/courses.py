"""Courses tools — ScottyLabs public API.

Two tools:
  search_courses(query, units?, days_excluded?, semester?) → {results, citations}
  get_course(course_number) → {results: [one course in full], citations}

`results` and `citations` are two views of the same lookup: the ledger rebuilds
each citation from title/url/snippet alone, so prereqs, units and meeting times
only reach the model through `results`.

The upstream is course-tools.apis.scottylabs.org (no auth), reached through
`apps.core.http.get_json`, which raises one exception family for every failure.
Those become ToolError so the planner degrades gracefully rather than crashing
the answer (PRD §3 — "Live" access, must handle outages).

Endpoint facts are verified live and written down in docs/b2-courses.md; the two
that shape the code here are that an unknown course number comes back as a bare
500, and that meeting times exist only behind `/schedules?courseID=...`.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

import httpx  # for httpx.HTTPError / httpx.HTTPStatusError only
from apps.core.http import get_json
from apps.tools.registry import ToolError, register_tool
from django.utils import timezone

_BASE = "https://course-tools.apis.scottylabs.org"

_MAX_RESULTS = 20

# `/courses/search` pages at 10 docs and filters nothing server-side — neither
# `units` nor `semester` changes the result set, both verified live — so a
# client-side filter only ever sees the pages we ask for. It also shuffles
# equally-ranked results between calls, which means a shallow read answers the
# same question differently each time: "machine learning" has 259 matches over
# 26 pages, 37 of them 9-unit, and three pages found 3 of those 37 — a different
# 3 on each run.
#
# So a filtered search reads the lot. Measured at ~0.26s a page (the 250ms
# per-host gate in apps.core.http dominates), which is ~7s at this ceiling. Paid
# only when there is a filter to feed; an ordinary search still costs one page.
_MAX_FILTER_PAGES = 30

# Enriching a candidate costs one `/schedules` request, and apps.core.http gates
# a host to one request every 250ms, so this is a stagger rather than true
# parallelism. Worth it for the handful of candidates a filter leaves.
_MAX_PARALLEL_SCHEDULES = 4

# 1=Monday … 5=Friday, confirmed against the live API: across 60 sampled courses
# the only values that ever appear are 1–5, and the two commonest patterns are
# [1,3,5] and [2,4] — MWF and TR. Whether a weekend day would be 0 or 6 is
# untested and does not matter, because the tool only filters M T W R F.
_DAY_CODES = {1: "M", 2: "T", 3: "W", 4: "R", 5: "F"}

_SEASONS = {"spring": 0, "summer": 1, "fall": 2}
_SEASON_LETTERS = {"s": "spring", "m": "summer", "u": "summer", "f": "fall"}

# Which season a date falls in, by month. Approximate on purpose — it decides
# which offering to report, not anything a registrar would sign off on.
_SEASON_BY_MONTH = ("spring",) * 4 + ("summer",) * 3 + ("fall",) * 5


def _normalize_course(raw: dict) -> dict:
    """Pull the fields the planner actually needs; ignore the rest."""
    units = raw.get("units")
    try:
        # The API sends units as a string ("12.0"), so a caller's `units=9`
        # would never match without this.
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
        #: The offering `meetings` and `instructors` describe. Empty when the
        #: course has nothing scheduled this term or next — `last_offered` then
        #: says when it last ran, so "not currently offered" is sayable.
        "semester": "",
        "last_offered": "",
        "source": "CMU Courses API",
        "is_mock": False,
    }


def _parse_semester(text: str) -> tuple[str, int] | None:
    """'F24', 'S2025', 'fall 2024' → ('fall', 2024). None if it does not parse."""
    match = re.fullmatch(r"([A-Za-z]+)\s*'?(\d{2}|\d{4})", (text or "").strip())
    if match is None:
        return None

    word, digits = match.group(1).lower(), match.group(2)
    season = word if word in _SEASONS else _SEASON_LETTERS.get(word[0], "")
    if not season:
        return None

    year = int(digits)
    return season, year + 2000 if year < 100 else year


def _offering_order(entry: dict) -> tuple[int, int]:
    return entry.get("year") or 0, _SEASONS.get((entry.get("semester") or "").lower(), -1)


def _current_term() -> tuple[int, int]:
    """Today, as an `_offering_order` key."""
    now = timezone.localtime()
    return now.year, _SEASONS[_SEASON_BY_MONTH[now.month - 1]]


def _pick_offering(entries: list, semester: str | None) -> tuple[dict | None, dict | None]:
    """(the offering to report, the most recent one on file).

    `/schedules` returns every semester a course has ever run — 20 entries for
    15-213, going back to 2020. Flattening them answers "when does it meet?"
    with six years of rooms at once, so exactly one is chosen.

    Which one matters more than it looks. Taking the newest on file reports a
    Spring 2020 room for a course nobody has taught since, dressed as current.
    So without an explicit semester the choice is the *soonest term that has not
    already finished* — this one or the next — and a course with nothing in that
    window reports no meeting times at all rather than an archived guess. The
    second return value is what lets the answer say "last offered spring 2020"
    instead of going quiet.
    """
    offerings = [entry for entry in entries if isinstance(entry, dict)]
    latest = max(offerings, key=_offering_order, default=None)

    wanted = _parse_semester(semester) if semester else None
    if wanted is not None:
        season, year = wanted
        matched = [
            entry
            for entry in offerings
            if (entry.get("semester") or "").lower() == season and entry.get("year") == year
        ]
        return max(matched, key=_offering_order, default=None), latest

    current = _current_term()
    upcoming = [entry for entry in offerings if _offering_order(entry) >= current]
    return min(upcoming, key=_offering_order, default=None), latest


def _offering_label(entry: dict | None) -> str:
    if entry is None:
        return ""
    return " ".join(str(part) for part in (entry.get("semester"), entry.get("year")) if part)


def _day_codes(days: list) -> list[str]:
    return [_DAY_CODES[day] for day in days if day in _DAY_CODES]


def _flatten_schedule(entry: dict | None) -> tuple[list[str], list[dict]]:
    """One `/schedules` offering → (sorted instructor names, meeting dicts).

    Lectures and sections are merged: the raw nesting is API plumbing, and a
    student asking when a course meets wants both.
    """
    if entry is None:
        return [], []

    instructors: set[str] = set(entry.get("instructors") or [])
    meetings: list[dict] = []
    for group_key in ("lectures", "sections"):
        for group in entry.get(group_key) or []:
            instructors.update(group.get("instructors") or [])
            for slot in group.get("times") or []:
                meetings.append(
                    {
                        "days": _day_codes(slot.get("days") or []),
                        "begin": slot.get("begin") or "",
                        "end": slot.get("end") or "",
                        "room": slot.get("room") or "",
                        "building": slot.get("building") or "",
                    }
                )

    return sorted(instructors), meetings


def _offering_for(course_number: str, semester: str | None) -> tuple[dict | None, dict | None]:
    """The chosen `/schedules` offering and the most recent one on file.

    Never called without a `courseID`: bare `/schedules` does not respond at all
    (docs/b2-courses.md). A failure returns nothing rather than raising —
    schedule data is a bonus on top of description/prereqs/units.
    """
    try:
        entries = get_json(f"{_BASE}/schedules", params={"courseID": course_number})
    except httpx.HTTPError:
        return None, None

    return _pick_offering(entries if isinstance(entries, list) else [], semester)


def _add_schedules(courses: list[dict], semester: str | None) -> None:
    """Fill in instructors, meetings and semesters from `/schedules`, in place."""
    if not courses:
        return

    with ThreadPoolExecutor(max_workers=min(len(courses), _MAX_PARALLEL_SCHEDULES)) as pool:
        picked = list(
            pool.map(lambda course: _offering_for(course["course_number"], semester), courses)
        )

    for course, (offering, latest) in zip(courses, picked):
        course["instructors"], course["meetings"] = _flatten_schedule(offering)
        course["semester"] = _offering_label(offering)
        course["last_offered"] = _offering_label(latest)


#: Sections beyond this go unlisted in a citation — a big lecture has a dozen,
#: and the snippet is a preview, not the schedule.
_CITATION_MEETINGS = 2


def _meeting_label(meeting: dict) -> str:
    """"MW 09:30AM-10:50AM", or as much of it as the slot actually carries."""
    days = "".join(meeting["days"])
    span = "–".join(part for part in (meeting["begin"], meeting["end"]) if part)
    return " ".join(part for part in (days, span) if part)


def _course_citation(course: dict) -> dict:
    """The card, and the preview behind an inline chip.

    The title already carries the number and the name, so the snippet must not
    repeat them — it is the only room a citation has to say something the title
    doesn't, and what a student asking about a course wants there is when it
    meets and who teaches it.
    """
    bits = []
    if course["units"] is not None:
        bits.append(f"{course['units']:g} units")
    bits.extend(_meeting_label(meeting) for meeting in course["meetings"][:_CITATION_MEETINGS])
    if course["instructors"]:
        bits.append(", ".join(course["instructors"][:2]))

    return {
        "title": f"{course['course_number']}: {course['title']}",
        "url": "",  # no confirmed public per-course page — don't invent one (docs/b2-courses.md)
        # Without this the ledger falls back to the tool's name, and the app
        # groups the cards under "search_courses".
        "source": course["source"],
        "snippet": " · ".join(bit for bit in bits if bit),
        "indexed_at": None,
    }


def _search_docs(query: str, pages: int) -> tuple[list[dict], int]:
    """Search docs, and how many matches were left unread behind the page cap."""
    try:
        payload = get_json(f"{_BASE}/courses/search", params={"keywords": query})
    except httpx.HTTPError as exc:
        raise ToolError(f"CMU Courses API unreachable for query {query!r}: {exc}") from exc

    if not isinstance(payload, dict):
        return [], 0

    docs = list(payload.get("docs") or [])
    total_pages = payload.get("totalPages") or 1
    read = 1

    for page in range(2, min(pages, total_pages) + 1):
        try:
            more = get_json(f"{_BASE}/courses/search", params={"keywords": query, "page": page})
        except httpx.HTTPError:
            # A later page failing still leaves the earlier ones worth returning.
            break
        docs.extend(more.get("docs") or [] if isinstance(more, dict) else [])
        read = page

    unread = max(0, (payload.get("totalDocs") or 0) - len(docs)) if read < total_pages else 0
    return [doc for doc in docs if isinstance(doc, dict)], unread


@register_tool(
    name="search_courses",
    description=(
        "Search the CMU course catalog. Returns courses matching the query, "
        "optionally filtered by unit count or excluded days. "
        "Use get_course to fetch full details (prereqs, meeting times) for one course. "
        "Always check this tool before answering questions about course schedules."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Course name, number, or topic to search for.",
            },
            "units": {
                "type": "number",
                "description": "Only return courses worth this many units (e.g. 9, 12).",
            },
            "days_excluded": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Days to exclude, e.g. [\"F\"] to find Friday-free courses. "
                    "Use single-letter codes: M T W R F."
                ),
            },
            "semester": {
                "type": "string",
                "description": (
                    "Which offering to read meeting times from, e.g. 'F24' or 'S25'. "
                    "Defaults to the most recent one on file."
                ),
            },
        },
        "required": ["query"],
    },
    mode="courses",
    is_mock=False,
)
def search_courses(
    query: str,
    units: float | None = None,
    days_excluded: list[str] | None = None,
    semester: str | None = None,
) -> dict:
    filtering = units is not None or bool(days_excluded)
    docs, unread = _search_docs(query, pages=_MAX_FILTER_PAGES if filtering else 1)
    normalized = [_normalize_course(doc) for doc in docs]

    if units is not None:
        normalized = [course for course in normalized if course["units"] == units]

    normalized = normalized[:_MAX_RESULTS]

    if days_excluded:
        # The catalog search carries no schedule data at all, so the filter has
        # to fetch it before it can reject anything.
        _add_schedules(normalized, semester)
        excluded = {day.strip().upper()[:1] for day in days_excluded if day.strip()}
        normalized = [
            course
            for course in normalized
            # A course with no schedule on file is kept: nothing shows it meets
            # on an excluded day, and dropping it would hide every course that
            # has never been scheduled.
            if not any(excluded.intersection(meeting["days"]) for meeting in course["meetings"])
        ]

    result = {
        "results": normalized,
        "citations": [_course_citation(course) for course in normalized],
    }
    if unread:
        # Say so rather than let a partial sweep read as the whole catalog.
        result["note"] = (
            f"Searched the {len(docs)} best matches for {query!r}; {unread} more were not "
            "read. Narrow the query if the answer needs to be exhaustive."
        )
    return result


@register_tool(
    name="get_course",
    description=(
        "Fetch full details for one CMU course by its course number (e.g. '15-213'). "
        "Returns prereqs, all meeting times, instructors, and description. "
        "Call this after search_courses to enrich a specific result."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "course_number": {
                "type": "string",
                "description": "The course number, e.g. '15-213' or '10-701'.",
            },
        },
        "required": ["course_number"],
    },
    mode="courses",
    is_mock=False,
)
def get_course(course_number: str) -> dict:
    try:
        raw = get_json(f"{_BASE}/course/{course_number}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 500):
            # Confirmed live: the upstream answers an unknown course number with
            # a bare 500, so reporting it as an outage would send the model
            # looking for a working API rather than a real course number.
            raise ToolError(f"Course {course_number!r} not found in the CMU catalog.") from exc
        raise ToolError(
            f"CMU Courses API returned {exc.response.status_code} for {course_number!r}."
        ) from exc
    except httpx.HTTPError as exc:
        raise ToolError(f"CMU Courses API unreachable: {exc}") from exc

    course = _normalize_course(raw if isinstance(raw, dict) else {})
    course["course_number"] = course["course_number"] or course_number
    _add_schedules([course], None)

    return {"results": [course], "citations": [_course_citation(course)]}


# --- Requisites and gen-eds ---------------------------------------------------

# Schools whose gen-ed lists the upstream actually publishes. DC, CFA, TSB and
# SHS all answer 200 with an empty array rather than an error, so an unlisted
# school would otherwise look like "no gen-eds" instead of "not published".
_GENED_SCHOOLS: tuple[str, ...] = ("SCS", "CIT", "MCS")

_MAX_GENEDS = 40

# A gen-ed list is a quarter of a megabyte and changes once a semester, so it is
# the one courses call worth caching between requests.
_GENED_TTL = 6 * 60 * 60.0


def _unit_value(raw: object) -> float | None:
    """Units arrive as a string ("9.0"); mirror _normalize_course's handling."""
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _requisite_citation(course_number: str, prereqs: list, postreqs: list) -> dict:
    bits = []
    bits.append(f"prereqs: {', '.join(prereqs)}" if prereqs else "no prereqs")
    if postreqs:
        bits.append(f"{len(postreqs)} courses require it")
    return {
        "title": f"{course_number}: requisites",
        "url": "",  # no confirmed public per-course page (docs/b2-courses.md)
        "source": "CMU Courses",
        "snippet": " · ".join(bits),
        "indexed_at": None,
        "verified_at": timezone.now(),
    }


@register_tool(
    name="course_requisites",
    description=(
        "Fetch the prerequisite and postrequisite courses for one CMU course. "
        "`postreqs` are the courses that require this one, which is what answers "
        "'what does 15-213 unlock?' and what to build a dependency graph from. "
        "Use this rather than reading prereqs out of a course description."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "course_number": {
                "type": "string",
                "description": "The course number, e.g. '15-213'.",
            },
        },
        "required": ["course_number"],
    },
    mode="courses",
    is_mock=False,
)
def course_requisites(course_number: str) -> dict:
    try:
        raw = get_json(f"{_BASE}/courses/requisites/{course_number}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 500):
            # Same upstream quirk get_course documents: an unknown course number
            # is a bare 500, and reporting it as an outage sends the model
            # hunting for a working API instead of a real course number.
            raise ToolError(f"Course {course_number!r} not found in the CMU catalog.") from exc
        raise ToolError(
            f"CMU Courses API returned {exc.response.status_code} for {course_number!r}."
        ) from exc
    except httpx.HTTPError as exc:
        raise ToolError(f"CMU Courses API unreachable: {exc}") from exc

    payload = raw if isinstance(raw, dict) else {}
    prereqs = [str(c) for c in payload.get("prereqs") or []]
    postreqs = [str(c) for c in payload.get("postreqs") or []]
    coreqs = [str(c) for c in payload.get("coreqs") or []]

    result = {
        "course_number": course_number,
        "prereqs": prereqs,
        "postreqs": postreqs,
        "coreqs": coreqs,
        "source": "CMU Courses",
        "is_mock": False,
    }
    return {
        "results": [result],
        "citations": [_requisite_citation(course_number, prereqs, postreqs)],
    }


@register_tool(
    name="find_geneds",
    description=(
        "List the courses that count toward a college's general education "
        "requirement. Only SCS, CIT and MCS publish a list; the other colleges "
        "do not, so say the list is unavailable rather than guessing."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "school": {
                "type": "string",
                "enum": list(_GENED_SCHOOLS),
                "description": "College code: SCS, CIT or MCS.",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum courses to return (default {_MAX_GENEDS}).",
                "default": _MAX_GENEDS,
            },
        },
        "required": ["school"],
    },
    mode="courses",
    is_mock=False,
)
def find_geneds(school: str, limit: int = _MAX_GENEDS) -> dict:
    code = str(school).strip().upper()
    if code not in _GENED_SCHOOLS:
        raise ToolError(
            f"{school!r} does not publish a gen-ed list. Available: "
            f"{', '.join(_GENED_SCHOOLS)}."
        )

    try:
        raw = get_json(f"{_BASE}/geneds", params={"school": code}, ttl=_GENED_TTL)
    except httpx.HTTPError as exc:
        raise ToolError(f"CMU Courses API unreachable: {exc}") from exc

    rows = raw if isinstance(raw, list) else []
    if not rows:
        raise ToolError(f"CMU Courses published no gen-ed list for {code}.")

    capped = max(1, min(int(limit or _MAX_GENEDS), _MAX_RESULTS * 5))
    # The full payload is a quarter of a megabyte; only the identifying fields
    # are worth spending context on, and the model can call get_course for more.
    results = [
        {
            "course_number": str(row.get("courseID", "")),
            "title": str(row.get("name", "")),
            "units": _unit_value(row.get("units")),
            "tags": [str(tag) for tag in row.get("tags") or []],
            "school": code,
            "source": "CMU Courses",
            "is_mock": False,
        }
        for row in rows[:capped]
        if isinstance(row, dict)
    ]

    payload = {
        "results": results,
        "citations": [
            {
                "title": f"{course['course_number']}: {course['title']}",
                "url": "",
                "source": "CMU Courses",
                "snippet": " · ".join(
                    bit
                    for bit in (
                        f"{course['units']:g} units" if course["units"] is not None else "",
                        ", ".join(course["tags"][:3]),
                        f"{code} gen-ed",
                    )
                    if bit
                ),
                "indexed_at": None,
                "verified_at": timezone.now(),
            }
            for course in results
        ],
    }

    unread = len(rows) - len(results)
    if unread > 0:
        # Same contract search_courses uses: a capped list must never read as
        # the complete one.
        payload["note"] = (
            f"Showing {len(results)} of {len(rows)} {code} gen-ed courses. "
            "Raise limit or narrow the question if the answer needs all of them."
        )
    return payload
