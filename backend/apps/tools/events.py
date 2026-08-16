"""Events tool — TartanConnect public mobile feed.

find_events(before?, after?, keywords?, limit?) → list of campus events.

The upstream is the mobile_events_list JSON feed (no auth). Outages are caught
and surfaced as ToolError (PRD §3 — "Live" access).
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from apps.tools.registry import ToolError, register_tool

_URL = "https://tartanconnect.cmu.edu/mobile_ws/v17/mobile_events_list"
_TIMEOUT = 15.0


def _fetch_events() -> list[dict]:
    try:
        resp = httpx.get(_URL, params={"range": 0}, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise ToolError(f"TartanConnect returned {exc.response.status_code}.") from exc
    except httpx.RequestError as exc:
        raise ToolError(f"TartanConnect unreachable: {exc}") from exc
    except (ValueError, TypeError) as exc:
        raise ToolError(f"TartanConnect returned invalid JSON: {exc}") from exc

    # The feed returns {"event": [...]} or a bare list depending on the version.
    if isinstance(data, list):
        return data
    return data.get("event", data.get("events", []))


def _normalize_event(raw: dict) -> dict:
    return {
        "id": raw.get("id") or raw.get("event_id", ""),
        "title": raw.get("name") or raw.get("event_name") or raw.get("title", ""),
        "start": raw.get("starts_at") or raw.get("start_date") or raw.get("start", ""),
        "end": raw.get("ends_at") or raw.get("end_date") or raw.get("end", ""),
        "location": raw.get("location", ""),
        "org": raw.get("organization_name") or raw.get("org", ""),
        "categories": raw.get("categories", []),
        "link": raw.get("permalink") or raw.get("url", ""),
        "description": (raw.get("description", "") or "")[:500],
        "source": "TartanConnect events",
        "is_mock": False,
    }


def _parse_dt(s: str) -> datetime | None:
    """Try a few common datetime formats from the feed."""
    if not s:
        return None

    cleaned = s.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"

    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(cleaned, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _matches_keywords(event: dict, keywords: list[str]) -> bool:
    haystack = (
        event["title"] + " " + event["org"] + " " + event["description"] + " "
        + " ".join(str(c) for c in event["categories"])
    ).lower()
    return all(kw.lower() in haystack for kw in keywords)


@register_tool(
    name="find_events",
    description=(
        "Find upcoming CMU campus events from TartanConnect. "
        "Filter by time window and/or keywords. "
        "Good for startup events, AI talks, club meetings, and general campus activities. "
        "Returns live data — use before= and after= to narrow the window."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "after": {
                "type": "string",
                "description": (
                    "Only return events that start at or after this ISO 8601 datetime, "
                    "e.g. '2025-02-10T16:20:00'."
                ),
            },
            "before": {
                "type": "string",
                "description": "Only return events that start before this datetime (ISO 8601).",
            },
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "All keywords must appear somewhere in the event title, org, "
                    "description, or categories. Case-insensitive."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results to return (default 10, max 30).",
                "default": 10,
            },
        },
        "required": [],
    },
    mode="events",
    is_mock=False,
)
def find_events(
    after: str | None = None,
    before: str | None = None,
    keywords: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    raw_events = _fetch_events()
    events = [_normalize_event(e) for e in raw_events]

    after_dt = _parse_dt(after) if after else None
    before_dt = _parse_dt(before) if before else None

    filtered: list[dict] = []
    for event in events:
        if after_dt or before_dt:
            start_dt = _parse_dt(event["start"])
            if start_dt is None:
                continue
            if after_dt and start_dt < after_dt:
                continue
            if before_dt and start_dt >= before_dt:
                continue
        if keywords and not _matches_keywords(event, keywords):
            continue
        filtered.append(event)

    return filtered[: min(limit, 30)]
