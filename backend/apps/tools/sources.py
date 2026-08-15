"""The source registry behind `GET /api/sources/` — the credits list and the
freshness/mock honesty PRD §9 requires.

Kept separate from the tool registry because sources and tools are not the same
thing: one source can back several tools, and the campus index backs a single
tool while being the thing that needs a freshness date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

# "public" sources may be indexed and shared between everyone; "personal"
# sources are user-scoped and must never touch the shared index (PRD §3, §10).
TIERS: tuple[str, ...] = ("public", "personal")

# The PRD's accessibility legend (§3):
#   Crawl — we index the public pages ourselves
#   Live  — public API we call at query time
#   Token — the user pastes their own credential
#   Mock  — fixture data standing in for something we can't reach legally
ACCESS: tuple[str, ...] = ("Crawl", "Live", "Token", "Mock")


@dataclass(frozen=True)
class Source:
    """One thing AskScotty can draw on."""

    name: str
    tier: str
    access: str
    #: Called at request time. Crawled sources will read the newest
    #: Document.fetched_at once the crawler lands (tasklist B1); live and mock
    #: sources have no index date at all.
    indexed_at_resolver: Callable[[], datetime | None] | None = None
    #: False while the lane is a placeholder. Surfaced in the API on purpose so
    #: the credits page never implies more coverage than we have.
    implemented: bool = False
    #: One line explaining what this gives us, for the credits UI.
    note: str = ""

    def indexed_at(self) -> datetime | None:
        if self.indexed_at_resolver is None:
            return None
        return self.indexed_at_resolver()


_SOURCES: dict[str, Source] = {}


def register_source(
    name: str,
    tier: str,
    access: str,
    *,
    indexed_at_resolver: Callable[[], datetime | None] | None = None,
    implemented: bool = False,
    note: str = "",
) -> Source:
    """Add a source to the registry. Names are unique and user-visible."""
    if tier not in TIERS:
        raise ValueError(f"Unknown tier {tier!r} for source {name!r}. Expected one of {TIERS}.")
    if access not in ACCESS:
        raise ValueError(f"Unknown access {access!r} for source {name!r}. Expected one of {ACCESS}.")
    if name in _SOURCES:
        raise ValueError(f"Source {name!r} is already registered.")

    source = Source(
        name=name,
        tier=tier,
        access=access,
        indexed_at_resolver=indexed_at_resolver,
        implemented=implemented,
        note=note,
    )
    _SOURCES[name] = source
    return source


def all_sources() -> list[Source]:
    """Every registered source: public tier first, then alphabetical."""
    return sorted(_SOURCES.values(), key=lambda s: (s.tier != "public", s.name))


# --- The registry itself (PRD §3–§7) -----------------------------------------
#
# Adding a source here is what puts it in the credits. Flip `implemented` to True
# in the same commit that wires the tool, not before.

register_source(
    "CMU public web (campus index)",
    tier="public",
    access="Crawl",
    note="Public cmu.edu pages: HUB, colleges, Student Affairs, CPDC.",
)
register_source(
    "Course sites (campus index)",
    tier="public",
    access="Crawl",
    note="Seeded public course homepages and syllabi (PRD Appendix B).",
)
register_source(
    "cmu.guide",
    tier="public",
    access="Crawl",
    note="Student-written campus guide.",
)
register_source(
    "CMU Courses API",
    tier="public",
    access="Live",
    note="Catalog, schedules and prereqs. Unaffiliated consumer of a public API.",
)
register_source(
    "CMU Eats",
    tier="public",
    access="Live",
    note="Dining locations and opening hours. Unaffiliated consumer of a public API.",
)
register_source(
    "TartanConnect events",
    tier="public",
    access="Live",
    note="Public club and campus event feed.",
)
register_source(
    "Web verify",
    tier="public",
    access="Live",
    note="Live search and fetch used to re-check anything stale or missing.",
)
register_source(
    "Campus maps",
    tier="public",
    access="Mock",
    note="Mock landmark coordinates and walking times — no public REST API exists.",
)
register_source(
    "25Live room availability",
    tier="public",
    access="Mock",
    note="Mock fixture. The real system is behind SSO and we do not scrape it.",
)
register_source(
    "FCE ratings",
    tier="public",
    access="Mock",
    note="Mock subset. The real ratings are behind an Andrew login.",
)
register_source(
    "Handshake events",
    tier="public",
    access="Mock",
    note="Mock fixture or deep link. The real feed needs SSO.",
)
register_source(
    "Canvas",
    tier="personal",
    access="Token",
    note="Your courses, assignments and announcements. Read with a token you paste in.",
)
register_source(
    "Ed Discussion",
    tier="personal",
    access="Token",
    note="Your course discussion threads, read with your own API token.",
)
register_source(
    "Stellic degree audit",
    tier="personal",
    access="Mock",
    note="Mock or self-uploaded audit JSON. We do not scrape Stellic.",
)
