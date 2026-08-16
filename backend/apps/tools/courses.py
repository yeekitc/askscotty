"""Courses tools — ScottyLabs public API.

Two tools:
  search_courses(query, units?, days_excluded?, semester?) → list of course summaries
  get_course(course_number) → one course with full detail

The upstream is course-tools.apis.scottylabs.org (no auth). HTTP 4xx/5xx are
caught and turned into ToolError so the planner degrades gracefully rather than
crashing the answer (PRD §3 — "Live" access, must handle outages).
"""

from __future__ import annotations

import httpx

from apps.tools.registry import ToolError, register_tool

_BASE = "https://course-tools.apis.scottylabs.org"
_TIMEOUT = 10.0


def _client() -> httpx.Client:
    return httpx.Client(base_url=_BASE, timeout=_TIMEOUT)


def _normalize_course(raw: dict) -> dict:
    """Pull the fields the planner actually needs; ignore the rest."""
    lectures = raw.get("lectures") or raw.get("sections") or []
    meetings = []
    for lec in lectures:
        for time_slot in lec.get("times", []):
            meetings.append(
                {
                    "days": time_slot.get("days", ""),
                    "begin": time_slot.get("begin", ""),
                    "end": time_slot.get("end", ""),
                    "room": time_slot.get("room", ""),
                    "building": time_slot.get("building", ""),
                }
            )

    return {
        "course_number": raw.get("courseID") or raw.get("number") or raw.get("id", ""),
        "title": raw.get("name") or raw.get("title", ""),
        "units": raw.get("units"),
        "instructors": raw.get("instructors", []),
        "meetings": meetings,
        "prereqs": raw.get("prereqString") or raw.get("prereqs", ""),
        "description": raw.get("desc") or raw.get("description", ""),
        "semester": raw.get("semester", ""),
        "source": "CMU Courses API",
        "is_mock": False,
    }


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
                    "Days to exclude, e.g. [\"F\"] to find MWF-free courses. "
                    "Use single-letter codes: M T W R F."
                ),
            },
            "semester": {
                "type": "string",
                "description": "Semester string, e.g. 'F24' or 'S25'. Defaults to current.",
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
) -> list[dict]:
    params: dict[str, str | int] = {"name": query}
    if semester:
        params["semester"] = semester

    try:
        with _client() as client:
            resp = client.get("/courses", params=params)
        resp.raise_for_status()
        courses: list[dict] = resp.json()
    except httpx.HTTPStatusError as exc:
        raise ToolError(
            f"CMU Courses API returned {exc.response.status_code} for query {query!r}."
        ) from exc
    except httpx.RequestError as exc:
        raise ToolError(f"CMU Courses API unreachable: {exc}") from exc

    normalized = [_normalize_course(c) for c in courses]

    if units is not None:
        normalized = [c for c in normalized if c["units"] == units]

    if days_excluded:
        excluded_set = {d.upper() for d in days_excluded}
        def _no_excluded_days(course: dict) -> bool:
            for meeting in course["meetings"]:
                if any(d in meeting["days"].upper() for d in excluded_set):
                    return False
            return True
        normalized = [c for c in normalized if _no_excluded_days(c)]

    return normalized[:20]


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
        with _client() as client:
            resp = client.get(f"/course/{course_number}")
        resp.raise_for_status()
        raw = resp.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise ToolError(f"Course {course_number!r} not found in the CMU catalog.") from exc
        raise ToolError(f"CMU Courses API returned {status} for {course_number!r}.") from exc
    except httpx.RequestError as exc:
        raise ToolError(f"CMU Courses API unreachable: {exc}") from exc

    return _normalize_course(raw)
