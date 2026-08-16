"""Dining tool — CMU Eats public API v2.

find_dining(open_at?, near?, limit?) → list of locations with hours.

The upstream is api.cmueats.com/v2/locations (no auth). Outages are caught and
surfaced as ToolError so the planner degrades gracefully (PRD §3).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

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


def _is_open_at(location: dict, target_minutes: int) -> bool:
    """Return True if any schedule window covers target_minutes on today's weekday."""
    today = datetime.now(timezone.utc).strftime("%A").lower()[:3]  # "mon", "tue", ...
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
) -> list[dict]:
    try:
        resp = httpx.get(_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        raw_locations: list[dict] = resp.json().get("locations", resp.json())
    except httpx.HTTPStatusError as exc:
        raise ToolError(f"CMU Eats API returned {exc.response.status_code}.") from exc
    except httpx.RequestError as exc:
        raise ToolError(f"CMU Eats API unreachable: {exc}") from exc

    locations = [_normalize_location(loc) for loc in raw_locations]

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

    return locations[: min(limit, 20)]
