"""Maps tools — CMU Maps public API.

  nearby(building, radius_minutes?)      → {results: buildings in range, citations}
  walk_time(from_building, to_building)  → {results: [one estimate], citations}
  find_place(query, limit?)              → {results: buildings and rooms, citations}

The upstream is api.maps.scottylabs.org (no auth), reached through
`apps.core.http.get_json`. Outages surface as ToolError so the planner degrades
gracefully (PRD §3).

**Walking times are derived, not routed.** The API's public routing endpoint
(`/path/public`) answers only when Cohon University Center is the destination —
every other pair returns "No path found" — so it is unusable as a general
router. Distances here are straight-line between real label coordinates, scaled
by the constants below. Every citation says so, so an estimate can never read as
a surveyed route.
"""

from __future__ import annotations

import math
import re

import httpx  # for httpx.HTTPError only

from django.utils import timezone

from apps.core.http import get_json
from apps.tools.registry import ToolError, register_tool

_BASE = "https://api.maps.scottylabs.org"
_SITE = "https://maps.scottylabs.org"
_TIMEOUT = 10.0

# Buildings do not move. One fetch serves a whole conversation, so `nearby`
# costs one request rather than one per candidate.
_CATALOG_TTL = 24 * 60 * 60.0

# Straight-line metres → minutes on foot. 1.4 m/s is the standard pedestrian
# speed; the detour factor is because campus paths bend around buildings, and
# without it every estimate reads low enough to make someone miss a class.
_WALK_SPEED_M_PER_S = 1.4
_DETOUR_FACTOR = 1.3

# The catalog is 74 buildings, so a generous radius can match dozens. Each match
# costs a citation card, and a wall of them buries the few the reader wants, so
# `nearby` returns the closest and says what it left out.
_NEARBY_LIMIT = 10

# Alias → building code, for what people actually type. Two entries here are
# load-bearing rather than convenient: `/search` ranks "hamerschlag" onto
# Hamerschlag *House* (a dorm) over Hamerschlag *Hall* (ECE), and "posner" onto
# Posner *Center* over Posner *Hall*. Resolution consults this table before it
# ever reaches search, so the common word lands on the building people mean.
#
# The long-form names are the ones our other tools already emit — `rooms.py`'s
# schema enum and `dining.py`'s `_NEAR_ALIASES` — kept resolvable so those keep
# composing with maps now that canonical names come from the live catalog
# ("Gates-Hillman Center" is "Gates & Hillman Centers" upstream).
_ALIASES: dict[str, str] = {
    "gates": "GHC",
    "ghc": "GHC",
    "gates hillman": "GHC",
    "gates hillman center": "GHC",
    "gates hillman centers": "GHC",
    "wean": "WEH",
    "weh": "WEH",
    "doherty": "DH",
    "dh": "DH",
    "tepper": "TEP",
    "posner tepper": "TEP",
    "uc": "CUC",
    "cuc": "CUC",
    "cohon": "CUC",
    "university center": "CUC",
    "hunt": "HL",
    "hunt library": "HL",
    "baker": "BH",
    "bh": "BH",
    "posner": "POS",
    "posner hall": "POS",
    "hamerschlag": "HH",
    "hh": "HH",
    "hamerschlag hall": "HH",
    "mellon": "MI",
    "mi": "MI",
    "mellon institute": "MI",
    "newell simon": "NSH",
    "nsh": "NSH",
    "scaife": "SH",
    "porter": "PH",
    "margaret morrison": "MM",
}


def _norm(text: str) -> str:
    """Lowercase, punctuation-free, single-spaced — so '&' and '-' stop mattering."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split())


def _catalog() -> dict[str, dict]:
    """Every building, keyed by code. Cached; one upstream call per day."""
    try:
        raw = get_json(f"{_BASE}/buildings", timeout=_TIMEOUT, ttl=_CATALOG_TTL)
    except httpx.HTTPError as exc:
        raise ToolError(f"CMU Maps API unreachable: {exc}") from exc

    if not isinstance(raw, dict) or not raw:
        raise ToolError("CMU Maps API returned no buildings.")
    return raw


def _search_buildings(query: str) -> str | None:
    """Last-resort resolution. Rooms outrank buildings upstream, so filter first."""
    try:
        hits = get_json(
            f"{_BASE}/search", params={"query": query, "n": 8}, timeout=_TIMEOUT
        )
    except httpx.HTTPError:
        # Only ever a fallback, and the caller already has a "not found" to
        # raise. A search outage must not mask that with an outage message.
        return None

    for hit in hits if isinstance(hits, list) else []:
        if isinstance(hit, dict) and hit.get("type") == "building" and hit.get("id"):
            return str(hit["id"])
    return None


def _resolve(name: str, catalog: dict[str, dict]) -> str:
    """Return a building code for whatever the model typed.

    Deterministic before it is fuzzy: code, then curated alias, then exact name,
    then unique prefix, and only then the search endpoint.
    """
    raw = str(name).strip()
    if raw.upper() in catalog:
        return raw.upper()

    key = _norm(raw)
    if not key:
        raise ToolError("No building name was given.")

    alias = _ALIASES.get(key)
    if alias in catalog:
        return alias

    by_name = {_norm(info.get("name", "")): code for code, info in catalog.items()}
    if key in by_name:
        return by_name[key]

    prefixed = [code for norm, code in by_name.items() if norm.startswith(key)]
    if len(prefixed) == 1:
        return prefixed[0]

    found = _search_buildings(raw)
    if found and found in catalog:
        return found

    raise ToolError(
        f"No CMU building matches {name!r}. Try a building name or code "
        "(e.g. 'Wean Hall' or 'WEH')."
    )


def _coords(info: dict) -> tuple[float, float] | None:
    lat, lng = info.get("labelLatitude"), info.get("labelLongitude")
    if lat is None or lng is None:
        return None
    return float(lat), float(lng)


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance. Haversine rather than equirectangular because the
    cost is irrelevant at this call volume and it has no failure mode."""
    radius = 6_371_000.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def _minutes(metres: float) -> int:
    """Walking minutes, rounded up. Zero distance stays zero rather than 1."""
    if metres <= 0:
        return 0
    return max(1, math.ceil(metres * _DETOUR_FACTOR / _WALK_SPEED_M_PER_S / 60))


def _estimate_note(metres: float) -> str:
    """The disclosure that keeps a derived number from reading as a route."""
    return f"{round(metres)} m straight-line, not a walking route"


def _building_url(code: str) -> str:
    return f"{_SITE}/{code}?dst={code}"


def _citation(title: str, url: str, snippet: str) -> dict:
    """`source` is set explicitly: without it the ledger falls back to the tool
    name and the UI groups these under "nearby" instead of one map source."""
    return {
        "title": title,
        "url": url,
        "snippet": snippet,
        "source": "CMU Maps",
        "indexed_at": None,
        "verified_at": timezone.now(),
    }


@register_tool(
    name="nearby",
    description=(
        "List CMU campus buildings within a walking radius of another building. "
        "Useful for 'what's near Wean?' or to pick a starting point for dining. "
        "Walking times are straight-line estimates from real coordinates, not "
        "routed directions — do not present them as turn-by-turn walking times."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "building": {
                "type": "string",
                "description": "Starting building name or code, e.g. 'Wean Hall' or 'WEH'.",
            },
            "radius_minutes": {
                "type": "integer",
                "description": "Maximum walking time in minutes (default 8).",
                "default": 8,
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum buildings to return, closest first (default {_NEARBY_LIMIT}).",
                "default": _NEARBY_LIMIT,
            },
        },
        "required": ["building"],
    },
    mode="maps",
    is_mock=False,
)
def nearby(building: str, radius_minutes: int = 8, limit: int = _NEARBY_LIMIT) -> dict:
    catalog = _catalog()
    code = _resolve(building, catalog)

    origin = _coords(catalog[code])
    if origin is None:
        raise ToolError(f"CMU Maps has no coordinates for {catalog[code].get('name', code)}.")

    results = []
    for other_code, info in catalog.items():
        if other_code == code:
            continue
        point = _coords(info)
        if point is None:
            continue
        metres = _metres(origin, point)
        minutes = _minutes(metres)
        if minutes > radius_minutes:
            continue
        results.append(
            {
                "name": info.get("name", other_code),
                "code": other_code,
                "walk_minutes": minutes,
                "distance_m": round(metres),
                "lat": point[0],
                "lng": point[1],
                "note": _estimate_note(metres),
                "is_mock": False,
            }
        )

    results.sort(key=lambda r: (r["walk_minutes"], r["distance_m"]))
    capped = max(1, min(int(limit or _NEARBY_LIMIT), 25))
    unread = max(0, len(results) - capped)
    results = results[:capped]

    origin_name = catalog[code].get("name", code)
    payload = {
        "results": results,
        "citations": [
            _citation(
                result["name"],
                _building_url(result["code"]),
                f"{result['name']}: about {result['walk_minutes']} min from "
                f"{origin_name} ({_estimate_note(result['distance_m'])})",
            )
            for result in results
        ],
    }
    if unread:
        # Same contract search_courses uses: a capped list must never read as
        # everything within the radius.
        payload["note"] = (
            f"Showing the {len(results)} closest of {len(results) + unread} buildings "
            f"within {radius_minutes} min of {origin_name}."
        )
    return payload


@register_tool(
    name="walk_time",
    description=(
        "Estimate walking time between two CMU campus buildings. The estimate is "
        "straight-line distance between real building coordinates, not a routed "
        "path — say it is approximate and never describe it as turn-by-turn."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "from_building": {
                "type": "string",
                "description": "Starting building name or code.",
            },
            "to_building": {
                "type": "string",
                "description": "Destination building name or code.",
            },
        },
        "required": ["from_building", "to_building"],
    },
    mode="maps",
    is_mock=False,
)
def walk_time(from_building: str, to_building: str) -> dict:
    catalog = _catalog()
    start = _resolve(from_building, catalog)
    end = _resolve(to_building, catalog)

    a, b = _coords(catalog[start]), _coords(catalog[end])
    if a is None or b is None:
        raise ToolError("CMU Maps has no coordinates for one of those buildings.")

    metres = _metres(a, b)
    minutes = _minutes(metres)
    start_name = catalog[start].get("name", start)
    end_name = catalog[end].get("name", end)

    result = {
        "from": start_name,
        "to": end_name,
        "from_code": start,
        "to_code": end,
        "walk_minutes": minutes,
        "distance_m": round(metres),
        "note": _estimate_note(metres),
        "is_mock": False,
    }
    return {
        "results": [result],
        "citations": [
            _citation(
                f"{start_name} → {end_name}",
                _building_url(end),
                f"{start_name} to {end_name}: about {minutes} min "
                f"({_estimate_note(metres)})",
            )
        ],
    }


@register_tool(
    name="find_place",
    description=(
        "Find where something is on the CMU campus by name, including rooms and "
        "cafés inside buildings — 'Rohr Cafe', 'GHC 4401', 'the Cut'. Returns the "
        "building it is in. Use this when the question is where a named place is, "
        "rather than the distance between two buildings."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to look for, e.g. 'Rohr Cafe' or 'Wean 5409'.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum matches to return (default 5).",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    mode="maps",
    is_mock=False,
)
def find_place(query: str, limit: int = 5) -> dict:
    capped = max(1, min(int(limit or 5), 20))
    try:
        hits = get_json(
            f"{_BASE}/search", params={"query": query, "n": capped}, timeout=_TIMEOUT
        )
    except httpx.HTTPError as exc:
        raise ToolError(f"CMU Maps API unreachable: {exc}") from exc

    if not isinstance(hits, list) or not hits:
        raise ToolError(f"CMU Maps found nothing matching {query!r}.")

    results = []
    for hit in hits[:capped]:
        if not isinstance(hit, dict):
            continue
        position = hit.get("labelPosition") or {}
        # A room's own id is a uuid; its building is the leading token of the
        # short name ("GHC 3101"). A building's id is already its code.
        name = str(hit.get("nameWithSpace") or "")
        kind = str(hit.get("type") or "")
        code = str(hit.get("id") or "") if kind == "building" else name.split(" ")[0]
        results.append(
            {
                "name": name,
                "full_name": hit.get("fullNameWithSpace", name),
                "type": kind,
                "room_type": hit.get("roomType", ""),
                "alias": hit.get("alias", ""),
                "building_code": code,
                "lat": position.get("latitude"),
                "lng": position.get("longitude"),
                "is_mock": False,
            }
        )

    if not results:
        raise ToolError(f"CMU Maps found nothing matching {query!r}.")

    return {
        "results": results,
        "citations": [
            _citation(
                result["alias"] or result["full_name"] or result["name"],
                _building_url(result["building_code"]) if result["building_code"] else _SITE,
                f"{result['full_name'] or result['name']}"
                + (f" — {result['alias']}" if result["alias"] else ""),
            )
            for result in results
        ],
    }
