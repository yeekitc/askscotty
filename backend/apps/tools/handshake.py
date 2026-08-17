"""Handshake events tool — mock fixture with deep-link citations.

The real Handshake feed requires SSO; we do not scrape it (PRD §10). This module
supplies ~15 hardcoded career events. Citations include the real Handshake deep-link
so users can tap through to see live details and RSVP.

Every result carries is_mock=True (PRD §9).
"""

from __future__ import annotations

from apps.tools.registry import ToolError, register_tool

_EVENTS: list[dict] = [
    {
        "id": "h001",
        "title": "Fall 2026 Career Fair",
        "company": "CPDC (150+ employers)",
        "event_type": "career_fair",
        "date": "2026-09-16",
        "location": "Cohon University Center, Rangos Ballroom",
        "description": (
            "CMU's flagship fall recruiting event. 150+ employers recruiting for "
            "full-time and internship roles in tech, finance, consulting, and research."
        ),
        "handshake_url": "https://app.joinhandshake.com/career_fairs",
    },
    {
        "id": "h002",
        "title": "Spring 2027 Career Fair",
        "company": "CPDC (120+ employers)",
        "event_type": "career_fair",
        "date": "2027-02-17",
        "location": "Cohon University Center, Rangos Ballroom",
        "description": (
            "Spring recruiting event with 120+ employers. Strong showing of startups "
            "and mid-size tech companies alongside the usual large-cap recruiters."
        ),
        "handshake_url": "https://app.joinhandshake.com/career_fairs",
    },
    {
        "id": "h003",
        "title": "Google Info Session — SWE & Research Roles",
        "company": "Google",
        "event_type": "info_session",
        "date": "2026-09-23",
        "location": "Gates-Hillman Center 4401",
        "description": (
            "Google engineers present summer internship and new-grad SWE, research, "
            "and PM opportunities. Q&A to follow. Bring résumés."
        ),
        "handshake_url": "https://app.joinhandshake.com/events",
    },
    {
        "id": "h004",
        "title": "Jane Street Info Session",
        "company": "Jane Street",
        "event_type": "info_session",
        "date": "2026-09-30",
        "location": "Tepper Building 1000",
        "description": (
            "Jane Street traders and technologists discuss internship programs in "
            "quantitative trading, software engineering, and research."
        ),
        "handshake_url": "https://app.joinhandshake.com/events",
    },
    {
        "id": "h005",
        "title": "Meta On-Campus Interviews — SWE Intern",
        "company": "Meta",
        "event_type": "interview",
        "date": "2026-10-07",
        "location": "Cohon University Center, Room 2A",
        "description": (
            "On-campus technical interviews for Meta's summer SWE internship. "
            "Invitation-only; apply through Handshake by Sep 21."
        ),
        "handshake_url": "https://app.joinhandshake.com/jobs",
    },
    {
        "id": "h006",
        "title": "Amazon On-Campus Interviews — SDE & Applied Science",
        "company": "Amazon",
        "event_type": "interview",
        "date": "2026-10-14",
        "location": "Gates-Hillman Center 6501",
        "description": (
            "On-campus interviews for Amazon SDE intern and full-time roles, "
            "plus Applied Science internship (ML focus). Invitation-only."
        ),
        "handshake_url": "https://app.joinhandshake.com/jobs",
    },
    {
        "id": "h007",
        "title": "Two Sigma Quant Networking Night",
        "company": "Two Sigma",
        "event_type": "networking",
        "date": "2026-10-21",
        "location": "Tepper Building Simmons Auditorium",
        "description": (
            "Casual networking with Two Sigma quant researchers and software engineers. "
            "Open to CS, Math, Stats, ECE, and ML students. No prior finance knowledge required."
        ),
        "handshake_url": "https://app.joinhandshake.com/events",
    },
    {
        "id": "h008",
        "title": "Microsoft Info Session — Explore & SWE Programs",
        "company": "Microsoft",
        "event_type": "info_session",
        "date": "2026-10-28",
        "location": "Wean Hall 7500",
        "description": (
            "Microsoft recruiters and engineers discuss the Explore internship "
            "(freshmen/sophomores) and standard SWE intern pipelines."
        ),
        "handshake_url": "https://app.joinhandshake.com/events",
    },
    {
        "id": "h009",
        "title": "Palantir Tech Talk & Recruiting Dinner",
        "company": "Palantir Technologies",
        "event_type": "info_session",
        "date": "2026-11-04",
        "location": "Gates-Hillman Center 4307",
        "description": (
            "Palantir engineers present a deep dive on their data platform, followed "
            "by a catered dinner and networking with recruiters."
        ),
        "handshake_url": "https://app.joinhandshake.com/events",
    },
    {
        "id": "h010",
        "title": "Goldman Sachs Engineering Info Session",
        "company": "Goldman Sachs",
        "event_type": "info_session",
        "date": "2026-11-11",
        "location": "Tepper Building 1000",
        "description": (
            "Goldman Sachs Engineers present summer analyst and new analyst "
            "programs in technology across fixed income, equities, and risk."
        ),
        "handshake_url": "https://app.joinhandshake.com/events",
    },
    {
        "id": "h011",
        "title": "FAANG+ Diversity Networking Mixer",
        "company": "Multiple Employers",
        "event_type": "networking",
        "date": "2026-11-18",
        "location": "Cohon University Center, Kirr Commons",
        "description": (
            "Sponsored by CPDC. Networking mixer for students from underrepresented "
            "groups with recruiters from Google, Meta, Apple, Netflix, and Amazon."
        ),
        "handshake_url": "https://app.joinhandshake.com/events",
    },
    {
        "id": "h012",
        "title": "Spring 2027 Startup Career Fair",
        "company": "Swartz Center for Entrepreneurship",
        "event_type": "career_fair",
        "date": "2027-03-03",
        "location": "Cohon University Center, McConomy Auditorium Lobby",
        "description": (
            "35+ early- and growth-stage startups recruiting interns and full-time "
            "engineers, designers, and product managers."
        ),
        "handshake_url": "https://app.joinhandshake.com/career_fairs",
    },
    {
        "id": "h013",
        "title": "Citadel & Citadel Securities Info Session",
        "company": "Citadel",
        "event_type": "info_session",
        "date": "2027-01-20",
        "location": "Wean Hall 4623",
        "description": (
            "Citadel and Citadel Securities discuss trading, quant research, and "
            "software engineering internships. Karat virtual interview slots available."
        ),
        "handshake_url": "https://app.joinhandshake.com/events",
    },
    {
        "id": "h014",
        "title": "Apple Hardware & Software Engineering Presentation",
        "company": "Apple",
        "event_type": "info_session",
        "date": "2027-02-03",
        "location": "Gates-Hillman Center 6501",
        "description": (
            "Apple engineers from Core OS, Silicon, and ML Infrastructure present "
            "internship and new-grad opportunities. RSVP required."
        ),
        "handshake_url": "https://app.joinhandshake.com/events",
    },
    {
        "id": "h015",
        "title": "SWE / ACM Alumni Panel & Networking",
        "company": "CMU SWE & ACM",
        "event_type": "networking",
        "date": "2026-10-29",
        "location": "Cohon University Center, Room 2C",
        "description": (
            "Panel of CMU alumni from industry and academia discussing career paths, "
            "recruiting timelines, and work-life balance. Open to all students."
        ),
        "handshake_url": "https://app.joinhandshake.com/events",
    },
]

_VALID_TYPES: set[str] = {"career_fair", "info_session", "interview", "networking"}

_HANDSHAKE_HOME = "https://app.joinhandshake.com/events"


@register_tool(
    name="find_handshake_events",
    description=(
        "Search upcoming Handshake career events at CMU: career fairs, employer info "
        "sessions, on-campus interviews, and networking events. "
        "Results are a mock fixture — the real Handshake feed requires SSO. "
        "Each citation includes a Handshake deep-link so users can RSVP on the real site."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keyword to match against event title, company, or description.",
            },
            "event_type": {
                "type": "string",
                "description": (
                    "Filter by event type: 'career_fair', 'info_session', "
                    "'interview', or 'networking'."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of events to return (default 5).",
                "default": 5,
            },
        },
        "required": [],
    },
    mode="handshake",
    is_mock=True,
)
def find_handshake_events(
    query: str | None = None,
    event_type: str | None = None,
    limit: int = 5,
) -> dict:
    if event_type is not None and event_type not in _VALID_TYPES:
        raise ToolError(
            f"Unknown event_type {event_type!r}. "
            f"Expected one of: {', '.join(sorted(_VALID_TYPES))}."
        )

    matches = list(_EVENTS)

    if event_type is not None:
        matches = [e for e in matches if e["event_type"] == event_type]

    if query:
        q = query.lower()
        matches = [
            e for e in matches
            if q in e["title"].lower()
            or q in e["company"].lower()
            or q in e["description"].lower()
        ]

    matches = matches[:limit]

    results = [
        {
            "id": e["id"],
            "title": e["title"],
            "company": e["company"],
            "event_type": e["event_type"],
            "date": e["date"],
            "location": e["location"],
            "description": e["description"],
            "is_mock": True,
        }
        for e in matches
    ]
    citations = [
        {
            "title": e["title"],
            "url": e["handshake_url"],
            "snippet": f"{e['company']} · {e['date']} · {e['location']}",
            "indexed_at": None,
        }
        for e in matches
    ]
    # Trailing "see all" citation pointing to the Handshake events landing page.
    citations.append(
        {
            "title": "All events on Handshake",
            "url": _HANDSHAKE_HOME,
            "snippet": "View and RSVP to upcoming CMU career events on Handshake.",
            "indexed_at": None,
        }
    )

    return {"results": results, "citations": citations}
