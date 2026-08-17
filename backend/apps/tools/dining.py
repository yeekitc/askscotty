"""Dining tool — CMU Eats public API v2.

find_dining(open_at?, near?, limit?) → {results: locations with hours, citations}.

The upstream is api.cmueats.com/v2/locations (no auth), reached through
`apps.core.http.get_json`. Outages are caught and surfaced as ToolError so the
planner degrades gracefully (PRD §3).

`results` and `citations` are two views of the same lookup: the ledger rebuilds
each citation from title/url/snippet alone, so a location's hours only reach the
model through `results`.
"""

from __future__ import annotations

import re

import httpx  # for httpx.HTTPError only

from apps.core.http import get_json
from apps.tools.registry import ToolError, register_tool

_URL = "https://api.cmueats.com/v2/locations"
_TIMEOUT = 10.0

# Map common near-location keywords to building names the maps tool understands.
# Approximate only — exact routing is maps' job.
_NEAR_ALIASES: dict[str, str] = {
    "wean": "Wean Hall",
    "gates": "Gates-Hillman Center",
    "doherty": "Doherty Hall",
    "tepper": "Tepper Building",
    "uc": "University Center",
    "cohon": "Cohon University Center",
    "hunt": "Hunt Library",
    "baker": "Baker Hall",
    "posner": "Posner Hall",
    "hamerschlag": "Hamerschlag Hall",
}


def _normalize_location(raw: dict) -> dict:
    """Extract what the planner needs."""
    schedule = raw.get("schedule", [])
    open_windows: list[dict] = []
    for window in schedule:
        open_windows.append(
            {
                "day": window.get("day", ""),
                "open": window.get("startTime", ""),
                "close": window.get("endTime", ""),
            }
        )

    return {
        "name": raw.get("name", ""),
        "location": raw.get("location", ""),
        "concept_title": raw.get("conceptTitle", ""),
        "is_open": raw.get("isOpen", False),
        "schedule": open_windows,
        "message": raw.get("message", ""),
        "source": "CMU Eats",
        "is_mock": False,
    }


def _time_str_to_minutes(t: str) -> int | None:
    """'08:20am' or '20:30' → minutes since midnight. Returns None on parse failure."""
    t = t.strip().lower()
    m = re.match(r"(\d{1,2}):(\d{2})\s*(am|pm)?", t)
    if not m:
        return None
    h, mn, meridiem = int(m.group(1)), int(m.group(2)), m.group(3)
    if meridiem == "pm" and h != 12:
        h += 12
    elif meridiem == "am" and h == 12:
        h = 0
    return h * 60 + mn


def _dining_citation(location: dict) -> dict:
    status = "open now" if location["is_open"] else "closed now"
    concept = f" ({location['concept_title']})" if location["concept_title"] else ""
    return {
        "title": location["name"],
        "url": "",  # CMU Eats has no public per-location page
        "snippet": f"{location['name']}{concept} — {status}",
        "indexed_at": None,
    }


def _is_open_at(location: dict, target_minutes: int) -> bool:
    """Return True if any schedule window covers target_minutes on today's weekday."""
    from django.utils import timezone as dj_timezone
    today = dj_timezone.localtime(dj_timezone.now()).strftime("%A").lower()[:3]  # "mon", "tue", ...
    day_map = {
        "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
        "thu": "Thursday", "fri": "Friday", "sat": "Saturday", "sun": "Sunday",
    }
    today_full = day_map[today]

    for window in location["schedule"]:
        if today_full.lower() not in window["day"].lower():
            continue
        start = _time_str_to_minutes(window["open"])
        end = _time_str_to_minutes(window["close"])
        if start is None or end is None:
            continue
        if start <= target_minutes < end:
            return True
    return False


@register_tool(
    name="find_dining",
    description=(
        "Find CMU dining locations. Optionally filter by opening time and/or a "
        "nearby campus building. Use near= with a building name to help the user "
        "find somewhere convenient relative to a class or meeting location. "
        "Returns live hours from CMU Eats."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "open_at": {
                "type": "string",
                "description": (
                    "Only return locations open at this time. Format: 'HH:MMam/pm', "
                    "e.g. '8:20pm'. Uses today's date."
                ),
            },
            "near": {
                "type": "string",
                "description": (
                    "Building name or alias, e.g. 'Wean Hall' or 'Wean'. "
                    "Results are annotated with the building so maps can give walking times."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results to return (default 8, max 20).",
                "default": 8,
            },
        },
        "required": [],
    },
    mode="dining",
    is_mock=False,
)
def find_dining(
    open_at: str | None = None,
    near: str | None = None,
    limit: int = 8,
) -> dict:
    try:
        data = get_json(_URL, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise ToolError(f"CMU Eats API unreachable: {exc}") from exc

    raw_locations: list[dict] = data.get("locations", []) if isinstance(data, dict) else data

    # A nameless location has nothing to cite and nothing to tell anyone.
    locations = [loc for loc in map(_normalize_location, raw_locations) if loc["name"]]

    if open_at:
        target = _time_str_to_minutes(open_at)
        if target is not None:
            locations = [loc for loc in locations if _is_open_at(loc, target)]

    # Resolve near alias and annotate each result so maps tool can compute distances.
    resolved_near: str | None = None
    if near:
        key = near.lower().strip()
        resolved_near = _NEAR_ALIASES.get(key, near)
        for loc in locations:
            loc["near_building"] = resolved_near

    locations = locations[: min(limit, 20)]
    return {
        "results": locations,
        "citations": [_dining_citation(location) for location in locations],
    }
