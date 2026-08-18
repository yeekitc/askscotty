"""25Live room-availability tool — mock fixture.

The real 25Live system is behind CollegeNET SSO and we do not scrape it (PRD §10).
This module supplies a static weekly schedule for ~25 rooms in four buildings and
checks it against the real wall clock, so "is room X free right now" works without
touching the live system.

Every result carries is_mock=True (PRD §9).
"""

from __future__ import annotations

from datetime import datetime

from apps.tools.registry import ToolError, register_tool

# schedule entries: (weekday 0=Mon … 6=Sun, start_hour, end_hour)
_ROOMS: list[dict] = [
    # Gates-Hillman Center
    {
        "id": "ghc-4102",
        "name": "GHC 4102",
        "building": "Gates-Hillman Center",
        "capacity": 30,
        "features": ["projector", "whiteboard"],
        "schedule": [
            (0, 9, 10.5), (0, 12, 13.5), (0, 15, 16.5),
            (2, 9, 10.5), (2, 12, 13.5), (2, 15, 16.5),
            (4, 9, 10.5), (4, 12, 13.5),
        ],
    },
    {
        "id": "ghc-4307",
        "name": "GHC 4307",
        "building": "Gates-Hillman Center",
        "capacity": 20,
        "features": ["projector"],
        "schedule": [
            (1, 10.5, 12), (1, 13.5, 15), (1, 15, 16.5),
            (3, 10.5, 12), (3, 13.5, 15),
        ],
    },
    {
        "id": "ghc-6115",
        "name": "GHC 6115",
        "building": "Gates-Hillman Center",
        "capacity": 15,
        "features": ["whiteboard"],
        "schedule": [
            (0, 10.5, 12), (0, 13.5, 15),
            (2, 10.5, 12),
            (4, 10.5, 12), (4, 13.5, 15),
        ],
    },
    {
        "id": "ghc-6501",
        "name": "GHC 6501",
        "building": "Gates-Hillman Center",
        "capacity": 50,
        "features": ["projector", "whiteboard", "videoconferencing"],
        "schedule": [
            (0, 9, 10.5), (0, 10.5, 12), (0, 13.5, 15),
            (1, 9, 10.5), (1, 12, 13.5),
            (2, 9, 10.5), (2, 10.5, 12), (2, 15, 16.5),
            (3, 9, 10.5), (3, 12, 13.5), (3, 15, 16.5),
            (4, 9, 10.5), (4, 10.5, 12), (4, 13.5, 15),
        ],
    },
    {
        "id": "ghc-8102",
        "name": "GHC 8102",
        "building": "Gates-Hillman Center",
        "capacity": 40,
        "features": ["projector", "whiteboard"],
        "schedule": [
            (1, 9, 10.5), (1, 10.5, 12), (1, 15, 16.5),
            (3, 9, 10.5), (3, 10.5, 12), (3, 13.5, 15),
        ],
    },
    {
        "id": "ghc-7501",
        "name": "GHC 7501",
        "building": "Gates-Hillman Center",
        "capacity": 25,
        "features": ["projector", "videoconferencing"],
        "schedule": [
            (0, 12, 13.5), (0, 15, 16.5),
            (2, 12, 13.5),
            (4, 12, 13.5), (4, 15, 16.5),
        ],
    },
    # Wean Hall
    {
        "id": "wean-4623",
        "name": "Wean 4623",
        "building": "Wean Hall",
        "capacity": 30,
        "features": ["projector", "whiteboard"],
        "schedule": [
            (0, 9, 10.5), (0, 13.5, 15),
            (2, 9, 10.5), (2, 13.5, 15),
            (4, 9, 10.5),
        ],
    },
    {
        "id": "wean-5302",
        "name": "Wean 5302",
        "building": "Wean Hall",
        "capacity": 20,
        "features": ["whiteboard"],
        "schedule": [
            (1, 10.5, 12), (1, 13.5, 15),
            (3, 10.5, 12), (3, 13.5, 15), (3, 15, 16.5),
        ],
    },
    {
        "id": "wean-7500",
        "name": "Wean 7500",
        "building": "Wean Hall",
        "capacity": 60,
        "features": ["projector", "whiteboard", "videoconferencing"],
        "schedule": [
            (0, 9, 10.5), (0, 10.5, 12), (0, 12, 13.5), (0, 13.5, 15),
            (1, 9, 10.5), (1, 10.5, 12), (1, 13.5, 15),
            (2, 9, 10.5), (2, 10.5, 12), (2, 12, 13.5),
            (3, 9, 10.5), (3, 10.5, 12), (3, 13.5, 15), (3, 15, 16.5),
            (4, 9, 10.5), (4, 10.5, 12), (4, 12, 13.5),
        ],
    },
    {
        "id": "wean-8220",
        "name": "Wean 8220",
        "building": "Wean Hall",
        "capacity": 15,
        "features": ["whiteboard"],
        "schedule": [
            (0, 10.5, 12), (0, 15, 16.5),
            (2, 10.5, 12),
            (4, 10.5, 12),
        ],
    },
    {
        "id": "wean-4615",
        "name": "Wean 4615",
        "building": "Wean Hall",
        "capacity": 12,
        "features": ["whiteboard"],
        "schedule": [
            (1, 9, 10.5), (1, 15, 16.5),
            (3, 9, 10.5),
        ],
    },
    # Baker Hall
    {
        "id": "baker-a51",
        "name": "Baker A51",
        "building": "Baker Hall",
        "capacity": 100,
        "features": ["projector", "whiteboard", "videoconferencing"],
        "schedule": [
            (0, 9, 10.5), (0, 10.5, 12), (0, 12, 13.5), (0, 13.5, 15), (0, 15, 16.5),
            (1, 9, 10.5), (1, 10.5, 12), (1, 12, 13.5), (1, 13.5, 15),
            (2, 9, 10.5), (2, 10.5, 12), (2, 13.5, 15), (2, 15, 16.5),
            (3, 9, 10.5), (3, 10.5, 12), (3, 12, 13.5),
            (4, 9, 10.5), (4, 10.5, 12), (4, 12, 13.5), (4, 13.5, 15),
        ],
    },
    {
        "id": "baker-a53",
        "name": "Baker A53",
        "building": "Baker Hall",
        "capacity": 40,
        "features": ["projector"],
        "schedule": [
            (0, 9, 10.5), (0, 13.5, 15),
            (1, 10.5, 12), (1, 15, 16.5),
            (2, 9, 10.5), (2, 13.5, 15),
            (3, 10.5, 12),
            (4, 9, 10.5),
        ],
    },
    {
        "id": "baker-136a",
        "name": "Baker 136A",
        "building": "Baker Hall",
        "capacity": 25,
        "features": ["projector", "whiteboard"],
        "schedule": [
            (0, 10.5, 12), (0, 15, 16.5),
            (2, 10.5, 12),
            (4, 10.5, 12), (4, 15, 16.5),
        ],
    },
    {
        "id": "baker-140",
        "name": "Baker 140",
        "building": "Baker Hall",
        "capacity": 30,
        "features": ["projector"],
        "schedule": [
            (1, 9, 10.5), (1, 12, 13.5),
            (3, 9, 10.5), (3, 12, 13.5), (3, 15, 16.5),
        ],
    },
    # Doherty Hall
    {
        "id": "dh-1117",
        "name": "DH 1117",
        "building": "Doherty Hall",
        "capacity": 100,
        "features": ["projector", "whiteboard"],
        "schedule": [
            (0, 9, 10.5), (0, 10.5, 12), (0, 12, 13.5), (0, 13.5, 15),
            (1, 9, 10.5), (1, 10.5, 12), (1, 13.5, 15), (1, 15, 16.5),
            (2, 9, 10.5), (2, 10.5, 12), (2, 12, 13.5), (2, 15, 16.5),
            (3, 9, 10.5), (3, 10.5, 12), (3, 13.5, 15),
            (4, 9, 10.5), (4, 10.5, 12), (4, 13.5, 15),
        ],
    },
    {
        "id": "dh-2105",
        "name": "DH 2105",
        "building": "Doherty Hall",
        "capacity": 30,
        "features": ["projector"],
        "schedule": [
            (0, 10.5, 12), (0, 13.5, 15),
            (2, 10.5, 12), (2, 13.5, 15),
            (4, 10.5, 12),
        ],
    },
    {
        "id": "dh-2210",
        "name": "DH 2210",
        "building": "Doherty Hall",
        "capacity": 25,
        "features": ["whiteboard"],
        "schedule": [
            (1, 10.5, 12), (1, 13.5, 15),
            (3, 10.5, 12), (3, 13.5, 15),
        ],
    },
    {
        "id": "dh-4302",
        "name": "DH 4302",
        "building": "Doherty Hall",
        "capacity": 40,
        "features": ["projector", "whiteboard"],
        "schedule": [
            (0, 9, 10.5), (0, 15, 16.5),
            (1, 9, 10.5), (1, 12, 13.5),
            (2, 9, 10.5), (2, 15, 16.5),
            (3, 9, 10.5), (3, 12, 13.5),
            (4, 9, 10.5),
        ],
    },
    {
        "id": "dh-a302",
        "name": "DH A302",
        "building": "Doherty Hall",
        "capacity": 20,
        "features": ["projector"],
        "schedule": [
            (0, 12, 13.5),
            (2, 12, 13.5),
            (4, 12, 13.5), (4, 15, 16.5),
        ],
    },
    # Hamerschlag Hall
    {
        "id": "hh-1107",
        "name": "HH 1107",
        "building": "Hamerschlag Hall",
        "capacity": 50,
        "features": ["projector", "whiteboard"],
        "schedule": [
            (0, 9, 10.5), (0, 10.5, 12), (0, 13.5, 15),
            (1, 9, 10.5), (1, 10.5, 12), (1, 15, 16.5),
            (2, 9, 10.5), (2, 10.5, 12), (2, 13.5, 15),
            (3, 9, 10.5), (3, 10.5, 12),
            (4, 9, 10.5), (4, 10.5, 12),
        ],
    },
    {
        "id": "hh-b103",
        "name": "HH B103",
        "building": "Hamerschlag Hall",
        "capacity": 20,
        "features": ["projector"],
        "schedule": [
            (1, 13.5, 15),
            (3, 13.5, 15), (3, 15, 16.5),
        ],
    },
]

# Canonical building names (mirrors maps.py so nearby() + find_available_rooms() compose cleanly)
_BUILDINGS: set[str] = {r["building"] for r in _ROOMS}


def _is_free_now(room: dict, duration_minutes: int) -> bool:
    """True if a window of `duration_minutes` starting now has no overlap with any busy block."""
    from django.utils import timezone as dj_timezone

    now = dj_timezone.localtime(dj_timezone.now())
    weekday = now.weekday()  # 0=Monday … 6=Sunday
    current = now.hour + now.minute / 60
    end = current + duration_minutes / 60

    for block_weekday, block_start, block_end in room["schedule"]:
        if block_weekday != weekday:
            continue
        # Overlap iff windows intersect (not just touch)
        if current < block_end and end > block_start:
            return False
    return True


@register_tool(
    name="find_available_rooms",
    description=(
        "Find CMU classrooms and study rooms that are free right now for a given duration. "
        "Useful for 'empty room near Gates for 90 minutes' queries. "
        "Based on a mock weekly schedule — not connected to the live 25Live system. "
        "Pair with `nearby` to answer location-plus-availability questions."
    ),
    json_schema={
        "type": "object",
        "properties": {
            "building": {
                "type": "string",
                "description": (
                    "Filter to one building. Accepted values: "
                    "'Gates-Hillman Center', 'Wean Hall', 'Baker Hall', "
                    "'Doherty Hall', 'Hamerschlag Hall'. Omit for all buildings."
                ),
            },
            "duration_minutes": {
                "type": "integer",
                "description": "How long the room is needed, in minutes (default 60).",
                "default": 60,
            },
            "capacity_min": {
                "type": "integer",
                "description": "Minimum number of seats required (default 1).",
                "default": 1,
            },
        },
        "required": [],
    },
    mode="rooms",
    is_mock=True,
)
def find_available_rooms(
    building: str | None = None,
    duration_minutes: int = 60,
    capacity_min: int = 1,
) -> dict:
    if building is not None and building not in _BUILDINGS:
        raise ToolError(
            f"Building {building!r} not in the rooms fixture. "
            f"Known buildings: {', '.join(sorted(_BUILDINGS))}."
        )

    candidates = [
        r for r in _ROOMS
        if (building is None or r["building"] == building)
        and r["capacity"] >= capacity_min
    ]

    available = [r for r in candidates if _is_free_now(r, duration_minutes)]
    available.sort(key=lambda r: r["capacity"])
    available = available[:10]

    features_str = lambda r: ", ".join(r["features"]) if r["features"] else "none"
    results = [
        {
            "name": r["name"],
            "building": r["building"],
            "capacity": r["capacity"],
            "features": r["features"],
            "is_mock": True,
        }
        for r in available
    ]
    citations = [
        {
            "title": r["name"],
            "url": "",
            "snippet": (
                f"Available now · capacity {r['capacity']} · "
                f"features: {features_str(r)}"
            ),
            "indexed_at": None,
        }
        for r in available
    ]

    return {"results": results, "citations": citations}
