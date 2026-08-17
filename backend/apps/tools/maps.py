"""Maps tools — mock fixture for CMU campus buildings.

No public REST API exists for CMU building coordinates or walking distances, so
this module uses a hardcoded fixture. Every result carries is_mock=True per PRD §9.

Two tools:
  nearby(building, radius_minutes?) → {results: buildings in range, citations}
  walk_time(a, b) → {results: [one estimate], citations}
"""

from __future__ import annotations

from apps.tools.registry import ToolError, register_tool

# Lat/lng for display only; walking times come from the adjacency table below.
_BUILDINGS: dict[str, dict] = {
    "Gates-Hillman Center": {
        "aliases": ["gates", "ghc", "gates hillman", "gates-hillman"],
        "lat": 40.4432,
        "lng": -79.9453,
        "note": "School of Computer Science",
    },
    "Wean Hall": {
        "aliases": ["wean"],
        "lat": 40.4428,
        "lng": -79.9436,
        "note": "CS, Math, ECE departments",
    },
    "Doherty Hall": {
        "aliases": ["doherty", "dh"],
        "lat": 40.4418,
        "lng": -79.9438,
        "note": "Chemistry, Physics, Statistics",
    },
    "Tepper Building": {
        "aliases": ["tepper", "posner/tepper"],
        "lat": 40.4443,
        "lng": -79.9466,
        "note": "Tepper School of Business",
    },
    "Cohon University Center": {
        "aliases": ["uc", "cohon", "university center"],
        "lat": 40.4430,
        "lng": -79.9440,
        "note": "Student hub with dining",
    },
    "Hunt Library": {
        "aliases": ["hunt", "hunt library"],
        "lat": 40.4427,
        "lng": -79.9427,
        "note": "Main CMU research library",
    },
    "Baker Hall": {
        "aliases": ["baker", "bh"],
        "lat": 40.4412,
        "lng": -79.9444,
        "note": "Humanities, Psychology, Philosophy",
    },
    "Posner Hall": {
        "aliases": ["posner"],
        "lat": 40.4437,
        "lng": -79.9462,
        "note": "Tepper School of Business (annex)",
    },
    "Hamerschlag Hall": {
        "aliases": ["hamerschlag", "hh"],
        "lat": 40.4413,
        "lng": -79.9429,
        "note": "Electrical & Computer Engineering",
    },
    "Mellon Institute": {
        "aliases": ["mellon", "mi"],
        "lat": 40.4448,
        "lng": -79.9489,
        "note": "Research institute; MCS",
    },
}

# Symmetric walking-minutes table between pairs of landmarks (approximate).
# Only the upper triangle is stored; lookup normalises order.
_WALK: dict[tuple[str, str], int] = {
    ("Baker Hall", "Cohon University Center"): 5,
    ("Baker Hall", "Doherty Hall"): 3,
    ("Baker Hall", "Gates-Hillman Center"): 8,
    ("Baker Hall", "Hamerschlag Hall"): 5,
    ("Baker Hall", "Hunt Library"): 6,
    ("Baker Hall", "Mellon Institute"): 13,
    ("Baker Hall", "Posner Hall"): 9,
    ("Baker Hall", "Tepper Building"): 9,
    ("Baker Hall", "Wean Hall"): 6,
    ("Cohon University Center", "Doherty Hall"): 4,
    ("Cohon University Center", "Gates-Hillman Center"): 4,
    ("Cohon University Center", "Hamerschlag Hall"): 5,
    ("Cohon University Center", "Hunt Library"): 3,
    ("Cohon University Center", "Mellon Institute"): 9,
    ("Cohon University Center", "Posner Hall"): 5,
    ("Cohon University Center", "Tepper Building"): 5,
    ("Cohon University Center", "Wean Hall"): 3,
    ("Doherty Hall", "Gates-Hillman Center"): 5,
    ("Doherty Hall", "Hamerschlag Hall"): 3,
    ("Doherty Hall", "Hunt Library"): 4,
    ("Doherty Hall", "Mellon Institute"): 12,
    ("Doherty Hall", "Posner Hall"): 7,
    ("Doherty Hall", "Tepper Building"): 7,
    ("Doherty Hall", "Wean Hall"): 3,
    ("Gates-Hillman Center", "Hamerschlag Hall"): 7,
    ("Gates-Hillman Center", "Mellon Institute"): 11,
    ("Gates-Hillman Center", "Posner Hall"): 7,
    ("Gates-Hillman Center", "Tepper Building"): 7,
    ("Gates-Hillman Center", "Wean Hall"): 2,
    ("Hamerschlag Hall", "Hunt Library"): 6,
    ("Hamerschlag Hall", "Mellon Institute"): 13,
    ("Hamerschlag Hall", "Posner Hall"): 10,
    ("Hamerschlag Hall", "Tepper Building"): 10,
    ("Hamerschlag Hall", "Wean Hall"): 6,
    ("Hunt Library", "Mellon Institute"): 11,
    ("Hunt Library", "Posner Hall"): 7,
    ("Hunt Library", "Tepper Building"): 7,
    ("Hunt Library", "Wean Hall"): 2,
    ("Mellon Institute", "Posner Hall"): 5,
    ("Mellon Institute", "Tepper Building"): 4,
    ("Mellon Institute", "Wean Hall"): 10,
    ("Posner Hall", "Tepper Building"): 1,
    ("Posner Hall", "Wean Hall"): 6,
    ("Tepper Building", "Wean Hall"): 6,
}


def _map_citation(title: str, snippet: str) -> dict:
    """A citation for fixture data — no source page exists, so `url` is empty.

    `is_mock` is not set here: it comes from the tool's own registration, which
    is what stops a mock result ever citing itself as live (PRD §9).
    """
    return {"title": title, "url": "", "snippet": snippet, "indexed_at": None}


def _resolve_building(name: str) -> str | None:
    """Return the canonical building name, matching aliases case-insensitively."""
    key = name.lower().strip()
    for canon, info in _BUILDINGS.items():
        if canon.lower() == key or key in info["aliases"]:
            return canon
    return None


def _walk_minutes(a: str, b: str) -> int | None:
    """Look up walking time between two canonical names. Symmetric."""
    if a == b:
        return 0
    pair = (min(a, b), max(a, b))
    return _WALK.get(pair)


@register_tool(
    name="nearby",
    description=(
        "List CMU campus buildings within a given walking radius of a landmark. "
        "Useful for 'what's near Wean?' or 'dining near Gates'. "
        "All results are mock coordinates — flag them accordingly."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "building": {
                "type": "string",
                "description": "Starting building name or alias, e.g. 'Wean Hall' or 'Gates'.",
            },
            "radius_minutes": {
                "type": "integer",
                "description": "Maximum walking time in minutes (default 8).",
                "default": 8,
            },
        },
        "required": ["building"],
    },
    mode="maps",
    is_mock=True,
)
def nearby(building: str, radius_minutes: int = 8) -> dict:
    canon = _resolve_building(building)
    if canon is None:
        raise ToolError(
            f"Building {building!r} not found in the campus map fixture. "
            f"Known buildings: {', '.join(_BUILDINGS)}."
        )

    results = []
    for other_name, info in _BUILDINGS.items():
        if other_name == canon:
            continue
        minutes = _walk_minutes(canon, other_name)
        if minutes is not None and minutes <= radius_minutes:
            results.append(
                {
                    "name": other_name,
                    "walk_minutes": minutes,
                    "lat": info["lat"],
                    "lng": info["lng"],
                    "note": info["note"],
                    "is_mock": True,
                }
            )

    results.sort(key=lambda r: r["walk_minutes"])
    return {
        "results": results,
        "citations": [
            _map_citation(
                result["name"],
                f"{result['name']}: {result['walk_minutes']} min walk from {canon} (mock data)",
            )
            for result in results
        ],
    }


@register_tool(
    name="walk_time",
    description=(
        "Estimate walking time in minutes between two CMU campus buildings. "
        "Returns a mock estimate — real time may vary."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "from_building": {
                "type": "string",
                "description": "Starting building name or alias.",
            },
            "to_building": {
                "type": "string",
                "description": "Destination building name or alias.",
            },
        },
        "required": ["from_building", "to_building"],
    },
    mode="maps",
    is_mock=True,
)
def walk_time(from_building: str, to_building: str) -> dict:
    a = _resolve_building(from_building)
    if a is None:
        raise ToolError(f"Building {from_building!r} not found in the campus map fixture.")

    b = _resolve_building(to_building)
    if b is None:
        raise ToolError(f"Building {to_building!r} not found in the campus map fixture.")

    minutes = _walk_minutes(a, b)
    if minutes is None:
        raise ToolError(
            f"No walking-time entry between {a!r} and {b!r} in the fixture. "
            "This is a gap in the mock data."
        )

    result = {"from": a, "to": b, "walk_minutes": minutes, "is_mock": True}
    return {
        "results": [result],
        "citations": [
            _map_citation(f"{a} → {b}", f"{a} to {b}: {minutes} min walk (mock data)")
        ],
    }
