"""Events tool — TartanConnect public mobile feed.

find_events(before?, after?, keywords?, limit?) → {results: events, citations}.

The upstream is the mobile_events_list JSON feed (no auth), reached through
`apps.core.http.get_json`. Outages are caught and surfaced as ToolError (PRD §3
— "Live" access).

It is JSON in transport only: a row names its columns in a `fields` string and
sends the values as `p0`, `p1`, …, with several of them HTML fragments rather
than data. `_decode` and `_text` are what turn that back into an event.

`results` and `citations` are two views of the same lookup: the ledger rebuilds
each citation from title/url/snippet alone, so an event's times and location
only reach the model through `results`.
"""

from __future__ import annotations

import html
import re
from datetime import datetime

import httpx  # for httpx.HTTPError only

from apps.core.http import get_json
from apps.tools.registry import ToolError, register_tool
from django.utils import timezone as dj_timezone

_URL = "https://tartanconnect.cmu.edu/mobile_ws/v17/mobile_events_list"
_SITE = "https://tartanconnect.cmu.edu"
_TIMEOUT = 15.0

_PARAGRAPH = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL)
_MARKUP = re.compile(r"<[^>]+>")
_TAG_LABEL = re.compile(r'aria-label="([^"]+)"')


def _fetch_events() -> list[dict]:
    try:
        data = get_json(_URL, params={"range": 0}, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise ToolError(f"TartanConnect unreachable: {exc}") from exc

    if isinstance(data, list):
        return data
    return data.get("event", data.get("events", []))


def _decode(raw: dict) -> dict:
    """One feed row, un-positioned.

    The feed sends no named JSON: every row carries a comma-separated `fields`
    list and its values as `p0`, `p1`, … in that order. Reading it by the field
    names an ordinary API would have used returns nothing but empty strings.
    """
    names = [name for name in (raw.get("fields") or "").split(",") if name]
    return {name: raw.get(f"p{index}") for index, name in enumerate(names)}


def _text(value: str | None) -> str:
    """Feed markup → plain text. Most string fields arrive as HTML fragments."""
    return " ".join(html.unescape(_MARKUP.sub(" ", value or "")).split())


def _window(value: str | None) -> tuple[str, str]:
    """`eventDates` → (start, end) as strings `_parse_dt` can read.

    Two shapes come back, one paragraph each:

        "Mon, Aug 10, 2026 8:00 AM –" / "Fri, Aug 28, 2026 9:00 AM"  multi-day
        "Wed, Aug 19, 2026"           / "1 PM – 2 PM"                single day
    """
    blocks = [_text(block) for block in _PARAGRAPH.findall(value or "")]
    if not blocks:
        return "", ""

    date = blocks[0].rstrip("–- ")
    rest = blocks[1] if len(blocks) > 1 else ""

    if "–" in rest:
        begin, _, finish = rest.partition("–")
        return f"{date} {begin.strip()}".strip(), f"{date} {finish.strip()}".strip()

    return date, rest


def _categories(row: dict) -> list[str]:
    """The event's own category plus its topic tags, read off the tag markup."""
    labels = [_text(label) for label in _TAG_LABEL.findall(row.get("eventTags") or "")]
    category = _text(row.get("eventCategory"))
    return list(dict.fromkeys([category, *labels] if category else labels))


def _normalize_event(raw: dict) -> dict:
    row = _decode(raw)
    start, end = _window(row.get("eventDates"))
    link = row.get("eventUrl") or ""

    return {
        "id": row.get("eventId") or "",
        "title": _text(row.get("eventName")),
        "start": start,
        "end": end,
        "location": _text(row.get("eventLocation")),
        "org": _text(row.get("clubName")),
        "categories": _categories(row),
        "link": f"{_SITE}{link}" if link.startswith("/") else link,
        "source": "TartanConnect events",
        "is_mock": False,
    }


def _event_citation(event: dict) -> dict:
    where = " · ".join(bit for bit in (event["org"], event["location"]) if bit)
    return {
        "title": event["title"],
        "url": event["link"],  # the one live tool with a real permalink to point at
        "snippet": " — ".join(bit for bit in (event["start"], where) if bit),
        "indexed_at": None,
    }


def _parse_dt(s: str) -> datetime | None:
    """The feed's own date formats, plus the ISO ones a caller passes in.

    A value with no offset is read as campus time, not UTC. Both the feed and
    the caller's `after`/`before` come through here, so a four-hour drift would
    apply to one side of the comparison only.
    """
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
        "%a, %b %d, %Y %I:%M %p",
        "%a, %b %d, %Y %I %p",
        "%a, %b %d, %Y",
    ):
        try:
            dt = datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dj_timezone.get_current_timezone())
        return dt
    return None


# A keyword matches at a word start, so "startup" still finds "startups" —
# but one this short has to match the whole word. A plain substring test made
# "AI" fire on "the FAIR" and on the category "Entertainment", which is four
# false positives out of four on the live feed.
_WHOLE_WORD_BELOW = 4


def _matches_keyword(haystack: str, keyword: str) -> bool:
    word = keyword.strip()
    if not word:
        return True
    boundary = r"\b" if len(word) < _WHOLE_WORD_BELOW else ""
    return re.search(rf"\b{re.escape(word)}{boundary}", haystack, re.IGNORECASE) is not None


def _matches_keywords(event: dict, keywords: list[str]) -> bool:
    haystack = " ".join([event["title"], event["org"], event["location"], *event["categories"]])
    return all(_matches_keyword(haystack, keyword) for keyword in keywords)


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
                    "location, or categories. Case-insensitive, and matched at "
                    "the start of a word, so 'startup' finds 'startups'."
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
) -> dict:
    # A titleless row is one of the feed's date separators, not an event.
    events = [event for event in map(_normalize_event, _fetch_events()) if event["title"]]

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

    filtered = filtered[: min(limit, 30)]
    return {"results": filtered, "citations": [_event_citation(e) for e in filtered]}
