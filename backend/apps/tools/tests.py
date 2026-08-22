"""Offline unit tests for the B2 live tools.

No real network requests are made — `apps.core.http.get_json` is patched in each
module that calls it.

The fixtures below are the real API shapes, verified live and written down in
docs/b2-courses.md: units arrive as strings, meeting days as ints, and a course
number that does not exist comes back as a 500. An earlier suite invented
friendlier shapes and stayed green while the tool was broken against the real
thing.

Run with:
    docker compose exec backend python manage.py test apps.tools
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from django.test import SimpleTestCase

from apps.tools.courses import course_requisites, find_geneds, get_course, search_courses
from apps.tools.dining import find_dining
from apps.tools.events import find_events
from apps.tools.maps import find_place, nearby, walk_time
from apps.tools.registry import ToolError

# --- Shared helpers -----------------------------------------------------------


def _status_error(status: int) -> httpx.HTTPStatusError:
    response = MagicMock()
    response.status_code = status
    return httpx.HTTPStatusError(str(status), request=MagicMock(), response=response)


def _urls(citations: list[dict]) -> set[str]:
    return {citation["url"] for citation in citations}


# --- Courses ------------------------------------------------------------------

_BASE = "https://course-tools.apis.scottylabs.org"

_DOC_213 = {
    "courseID": "15-213",
    "name": "Introduction to Computer Systems",
    "units": "12.0",
    "department": "Computer Science",
    "desc": "Memory and machine code.",
    "prereqs": ["15-122"],
    "prereqString": "15122",
}

_DOC_251 = {
    "courseID": "15-251",
    "name": "Great Ideas in Theoretical Computer Science",
    "units": "9.0",
    "department": "Computer Science",
    "desc": "Combinatorics and graph theory.",
    "prereqs": [],
    "prereqString": "None",
}

_DOC_301 = {
    "courseID": "10-301",
    "name": "Introduction to Machine Learning",
    "units": "9.0",
    "department": "Machine Learning",
    "desc": "Supervised and unsupervised learning.",
    "prereqs": ["21-241"],
    "prereqString": "21241",
}


def _offering(course_id: str, semester: str, year: int, days: list[int], **extra) -> dict:
    return {
        "courseID": course_id,
        "semester": semester,
        "year": year,
        "session": None,
        "instructors": [],
        "lectures": [
            {
                "name": "Lec 1",
                "instructors": [extra.get("instructor", "Andersen, David")],
                "times": [
                    {
                        "begin": "01:30PM",
                        "end": "02:50PM",
                        "days": days,
                        "building": "WEH",
                        "room": "7500",
                    }
                ],
            }
        ],
        "sections": [],
    }


class _FakeApi:
    """Routes `get_json` by path and records every call, the way the real one splits."""

    def __init__(self, *, pages: dict | None = None, schedules: dict | None = None) -> None:
        self.pages = pages or {}
        self.schedules = schedules or {}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, *, params=None, timeout=None, ttl=0.0):
        params = dict(params or {})
        self.calls.append((url, params))

        if url.endswith("/courses/search"):
            return self.pages.get(params.get("page", 1), {"docs": [], "totalPages": 1})
        if url.endswith("/schedules"):
            return self.schedules.get(params["courseID"], [])
        return next(
            doc
            for doc in (_DOC_213, _DOC_251, _DOC_301)
            if url.endswith(f"/course/{doc['courseID']}")
        )

    @property
    def search_pages(self) -> list[int]:
        return [params.get("page", 1) for url, params in self.calls if url.endswith("/search")]

    @property
    def scheduled(self) -> list[str]:
        return [params["courseID"] for url, params in self.calls if url.endswith("/schedules")]


def _one_page(*docs: dict) -> dict:
    return {"totalDocs": len(docs), "totalPages": 1, "page": 1, "docs": list(docs)}


# Which offering counts as current depends on today's date, so the suite pins it
# rather than going stale on its own in January.
_NOW = (2026, 2)  # fall 2026


class CoursesToolTests(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        term = patch("apps.tools.courses._current_term", return_value=_NOW)
        term.start()
        self.addCleanup(term.stop)

    def _patch(self, api: _FakeApi):
        patcher = patch("apps.tools.courses.get_json", api)
        patcher.start()
        self.addCleanup(patcher.stop)
        return api

    def test_search_returns_normalized_results_and_citations(self) -> None:
        self._patch(_FakeApi(pages={1: _one_page(_DOC_213)}))

        payload = search_courses(query="computer systems")

        course = payload["results"][0]
        self.assertEqual(course["course_number"], "15-213")
        self.assertEqual(course["title"], "Introduction to Computer Systems")
        self.assertEqual(course["units"], 12.0, "the API sends units as a string")
        self.assertEqual(course["source"], "CMU Courses API")
        self.assertFalse(course["is_mock"])

        citation = payload["citations"][0]
        self.assertEqual(citation["title"], "15-213: Introduction to Computer Systems")
        self.assertIn("12 units", citation["snippet"])
        self.assertEqual(citation["url"], "", "no confirmed per-course page — never invent one")
        self.assertEqual(
            citation["source"],
            "CMU Courses API",
            "without this the ledger falls back to the tool name and the app "
            "groups the cards under 'search_courses'",
        )

    def test_a_citation_snippet_does_not_repeat_its_own_title(self) -> None:
        # The snippet is the only room a citation has to say something the
        # title doesn't. It used to be "15-213 · Introduction to Computer
        # Systems · 12 units" — the title again, plus units — which made every
        # card three copies of one string.
        self._patch(_FakeApi(pages={1: _one_page(_DOC_213)}))

        citation = search_courses(query="computer systems")["citations"][0]

        self.assertNotIn("Introduction to Computer Systems", citation["snippet"])
        self.assertNotIn("15-213", citation["snippet"])

    def test_a_citation_snippet_carries_the_meeting_times_once_known(self) -> None:
        # Schedules are only fetched when a day filter forces it, so this is
        # also the only path where the snippet can answer "when does it meet?".
        self._patch(
            _FakeApi(
                pages={1: _one_page(_DOC_213)},
                schedules={"15-213": [_offering("15-213", "fall", 2026, [2, 4])]},
            )
        )

        citation = search_courses(query="computer systems", days_excluded=["F"])["citations"][0]

        self.assertIn("12 units", citation["snippet"])
        self.assertIn("TR", citation["snippet"], "day codes for the offering")
        self.assertIn("Andersen, David", citation["snippet"])

    def test_the_units_filter_compares_against_the_coerced_number(self) -> None:
        # It used to compare a float parameter against the API's "9.0" string,
        # so it matched nothing at all on real data.
        api = self._patch(_FakeApi(pages={1: _one_page(_DOC_213, _DOC_251)}))

        payload = search_courses(query="15", units=9)

        self.assertEqual([c["course_number"] for c in payload["results"]], ["15-251"])
        self.assertEqual(len(payload["citations"]), 1)
        self.assertEqual(api.scheduled, [], "no schedule lookup is needed to filter on units")

    def test_a_filtered_search_reads_every_page(self) -> None:
        # `/courses/search` pages at 10, filters nothing server-side, and
        # shuffles equally-ranked results between calls — so a shallow read
        # answers the same question differently each time.
        api = self._patch(
            _FakeApi(
                pages={
                    1: {"totalDocs": 21, "totalPages": 3, "page": 1, "docs": [_DOC_213]},
                    2: {"totalDocs": 21, "totalPages": 3, "page": 2, "docs": [_DOC_213]},
                    3: {"totalDocs": 21, "totalPages": 3, "page": 3, "docs": [_DOC_301]},
                }
            )
        )

        payload = search_courses(query="machine learning", units=9)

        self.assertEqual(api.search_pages, [1, 2, 3])
        self.assertEqual([c["course_number"] for c in payload["results"]], ["10-301"])
        self.assertNotIn("note", payload, "nothing was left unread")

    def test_a_search_too_broad_to_finish_says_so(self) -> None:
        # Silently filtering 300 of 8395 matches reads as the whole catalog.
        self._patch(
            _FakeApi(
                pages={
                    page: {"totalDocs": 8395, "totalPages": 840, "page": page, "docs": [_DOC_251]}
                    for page in range(1, 31)
                }
            )
        )

        payload = search_courses(query="a", units=9)

        # 30 pages of one doc read, out of 8395 matches.
        self.assertIn("Searched the 30 best matches", payload["note"])
        self.assertIn("8365 more were not read", payload["note"])

    def test_an_unfiltered_search_costs_one_request(self) -> None:
        api = self._patch(
            _FakeApi(pages={1: {"totalDocs": 21, "totalPages": 3, "page": 1, "docs": [_DOC_213]}})
        )

        search_courses(query="machine learning")

        self.assertEqual(api.search_pages, [1])

    def test_days_excluded_filters_on_real_schedule_data(self) -> None:
        # The days filter used to loop over meetings that were always empty, so
        # it had never rejected a single course.
        api = self._patch(
            _FakeApi(
                pages={1: _one_page(_DOC_213, _DOC_251)},
                schedules={
                    # 1=Monday … 5=Friday: MWF and TR.
                    "15-213": [_offering("15-213", "fall", 2026, [1, 3, 5])],
                    "15-251": [_offering("15-251", "fall", 2026, [2, 4])],
                },
            )
        )

        payload = search_courses(query="15", days_excluded=["F"])

        self.assertEqual([c["course_number"] for c in payload["results"]], ["15-251"])
        self.assertEqual(sorted(api.scheduled), ["15-213", "15-251"])
        self.assertEqual(payload["results"][0]["meetings"][0]["days"], ["T", "R"])

    def test_a_course_with_no_schedule_survives_the_days_filter(self) -> None:
        # Nothing shows it meets on an excluded day. Dropping it would hide
        # every course that has never been scheduled.
        self._patch(_FakeApi(pages={1: _one_page(_DOC_213)}, schedules={"15-213": []}))

        payload = search_courses(query="15", days_excluded=["F"])

        self.assertEqual([c["course_number"] for c in payload["results"]], ["15-213"])
        self.assertEqual(payload["results"][0]["meetings"], [])

    def test_get_course_merges_in_the_schedule(self) -> None:
        api = self._patch(
            _FakeApi(
                schedules={
                    "15-213": [
                        _offering("15-213", "fall", 2020, [2, 4], instructor="Bryant, Randal"),
                        _offering("15-213", "fall", 2026, [1, 3], instructor="Andersen, David"),
                    ]
                }
            )
        )

        course = get_course(course_number="15-213")["results"][0]

        self.assertEqual(api.scheduled, ["15-213"])
        # This term's offering, not six years of rooms flattened together.
        self.assertEqual(course["semester"], "fall 2026")
        self.assertEqual(course["instructors"], ["Andersen, David"])
        self.assertEqual(course["meetings"], [
            {
                "days": ["M", "W"],
                "begin": "01:30PM",
                "end": "02:50PM",
                "room": "7500",
                "building": "WEH",
            }
        ])
        self.assertEqual(course["prereqs"], "15122")

    def test_a_course_with_nothing_scheduled_this_term_reports_no_meetings(self) -> None:
        """Reporting a 2020 room as this term's schedule is worse than silence.

        11-441 is the real case: it exists in the catalog, meets TR whenever it
        runs, and is not on the Fall 2026 schedule at all.
        """
        self._patch(
            _FakeApi(
                schedules={"15-213": [_offering("15-213", "spring", 2020, [2, 4])]},
            )
        )

        course = get_course(course_number="15-213")["results"][0]

        self.assertEqual(course["meetings"], [])
        self.assertEqual(course["instructors"], [])
        self.assertEqual(course["semester"], "")
        # Enough for an answer to say "not currently offered; last ran in 2020".
        self.assertEqual(course["last_offered"], "spring 2020")

    def test_the_soonest_unfinished_term_wins_not_the_newest_on_file(self) -> None:
        self._patch(
            _FakeApi(
                schedules={
                    "15-213": [
                        _offering("15-213", "fall", 2026, [1, 3]),
                        _offering("15-213", "spring", 2027, [2, 4]),
                    ]
                },
            )
        )

        course = get_course(course_number="15-213")["results"][0]

        self.assertEqual(course["semester"], "fall 2026", "this term, not next")
        self.assertEqual(course["last_offered"], "spring 2027")

    def test_a_semester_selects_which_offering_is_reported(self) -> None:
        self._patch(
            _FakeApi(
                pages={1: _one_page(_DOC_213)},
                schedules={
                    "15-213": [
                        _offering("15-213", "fall", 2024, [5]),
                        _offering("15-213", "fall", 2026, [2, 4]),
                    ]
                },
            )
        )

        # F24 met on a Friday, so excluding Friday drops it; the default
        # (most recent) offering would have survived.
        self.assertEqual(search_courses(query="15", days_excluded=["F"], semester="F24")["results"], [])
        self.assertEqual(len(search_courses(query="15", days_excluded=["F"])["results"]), 1)

    def test_an_unknown_course_number_is_not_found_rather_than_an_outage(self) -> None:
        # The upstream answers an unknown id with a bare 500.
        with patch("apps.tools.courses.get_json", side_effect=_status_error(500)):
            with self.assertRaises(ToolError) as caught:
                get_course(course_number="99-999")

        self.assertIn("not found", str(caught.exception))

    def test_an_unreachable_api_degrades_to_a_tool_error(self) -> None:
        with patch("apps.tools.courses.get_json", side_effect=httpx.ConnectError("no route")):
            with self.assertRaises(ToolError):
                search_courses(query="anything")

    def test_a_dead_schedules_endpoint_does_not_lose_the_course(self) -> None:
        def get_json(url, *, params=None, timeout=None, ttl=0.0):
            if url.endswith("/schedules"):
                raise httpx.ConnectError("no route")
            return _DOC_213

        with patch("apps.tools.courses.get_json", get_json):
            course = get_course(course_number="15-213")["results"][0]

        self.assertEqual(course["course_number"], "15-213")
        self.assertEqual(course["meetings"], [])
        self.assertEqual(course["description"], "Memory and machine code.")


# --- Dining -------------------------------------------------------------------

_LOCATION = {
    "name": "Rohr Café",
    "location": "Wean Hall 4th Floor",
    "conceptTitle": "Coffee & Pastries",
    "isOpen": True,
    "schedule": [{"day": "Monday", "startTime": "08:00am", "endTime": "05:00pm"}],
    "message": "",
}


class DiningToolTests(SimpleTestCase):
    def _patch(self, locations=None, **kwargs):
        payload = {"locations": [_LOCATION] if locations is None else locations}
        patcher = patch("apps.tools.dining.get_json", return_value=payload, **kwargs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_returns_normalized_locations_and_citations(self) -> None:
        self._patch()

        payload = find_dining()

        location = payload["results"][0]
        self.assertEqual(location["name"], "Rohr Café")
        self.assertTrue(location["is_open"])
        self.assertEqual(location["source"], "CMU Eats")
        self.assertFalse(location["is_mock"])

        citation = payload["citations"][0]
        self.assertEqual(citation["title"], "Rohr Café")
        self.assertIn("open now", citation["snippet"])
        self.assertEqual(citation["url"], "", "CMU Eats has no per-location page")

    def test_near_annotation(self) -> None:
        self._patch()

        results = find_dining(near="wean")["results"]

        # "wean" resolves to the canonical "Wean Hall" via _NEAR_ALIASES.
        self.assertEqual(results[0]["near_building"], "Wean Hall")

    def test_an_api_failure_raises_tool_error(self) -> None:
        with patch("apps.tools.dining.get_json", side_effect=_status_error(503)):
            with self.assertRaises(ToolError):
                find_dining()


# --- Events -------------------------------------------------------------------

_EVENT_FIELDS = (
    "date_separator,eventId,eventName,eventDates,eventCategory,eventLocation,"
    "clubName,eventUrl,eventTags,"
)

# The feed's own date separator: a row with a different `fields` list and no
# event on it at all.
_SEPARATOR = {
    "fields": "date_separator,date_text,displayType,",
    "p0": "true",
    "p1": "Ongoing",
    "p2": "separator",
}


def _event_row(
    event_id: str,
    name: str,
    dates: str,
    *,
    category: str = "Research",
    location: str = "GHC 6115",
    club: str = "SCS",
    tags: str = "",
) -> dict:
    """One event, in the feed's positional shape: `fields` names, `pN` values."""
    values = ["false", event_id, name, dates, category, location, club, f"/rsvp_boot?id={event_id}", tags]
    return {"fields": _EVENT_FIELDS, **{f"p{index}": value for index, value in enumerate(values)}}


# The two `eventDates` shapes the feed uses, both HTML rather than a timestamp.
_SINGLE_DAY = "<p style='margin:0;'>Tue, Sep 01, 2026</p><p style='margin:0;'>3 PM &ndash; 4 PM</p>"
_MULTI_DAY = (
    "<p style='margin:0;'>Mon, Aug 10, 2026 8:00 AM &ndash; </p>"
    "<p style='margin:0;'>Fri, Aug 28, 2026 9:00 AM</p>"
)


class EventsToolTests(SimpleTestCase):
    def _patch(self, rows):
        patcher = patch("apps.tools.events.get_json", return_value=rows)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_positional_row_becomes_an_event(self) -> None:
        # Read as ordinary named JSON — as it was — every field comes back empty.
        self._patch([_SEPARATOR, _event_row("1", "AI Research Talk", _SINGLE_DAY)])

        payload = find_events()

        self.assertEqual(len(payload["results"]), 1, "the date separator is not an event")
        event = payload["results"][0]
        self.assertEqual(event["title"], "AI Research Talk")
        self.assertEqual(event["start"], "Tue, Sep 01, 2026 3 PM")
        self.assertEqual(event["end"], "Tue, Sep 01, 2026 4 PM")
        self.assertEqual(event["location"], "GHC 6115")
        self.assertEqual(event["org"], "SCS")
        self.assertEqual(event["link"], "https://tartanconnect.cmu.edu/rsvp_boot?id=1")

        citation = payload["citations"][0]
        self.assertEqual(citation["title"], "AI Research Talk")
        # Events is the one live tool with a real permalink to point at.
        self.assertEqual(citation["url"], "https://tartanconnect.cmu.edu/rsvp_boot?id=1")
        self.assertIn("SCS", citation["snippet"])

    def test_a_multi_day_event_keeps_both_ends(self) -> None:
        self._patch([_event_row("1", "The FAIR", _MULTI_DAY)])

        event = find_events()["results"][0]

        self.assertEqual(event["start"], "Mon, Aug 10, 2026 8:00 AM")
        self.assertEqual(event["end"], "Fri, Aug 28, 2026 9:00 AM")

    def test_a_short_keyword_matches_a_whole_word_only(self) -> None:
        # A plain substring test made "AI" fire on all four of these.
        self._patch(
            [
                _event_row("1", "The FAIR 2026", _SINGLE_DAY, category="Member Recruitment"),
                _event_row("2", "Saturday Board Games", _SINGLE_DAY, category="Entertainment"),
                _event_row("3", "Student Employment Fair", _SINGLE_DAY, club="CPDC"),
                _event_row("4", "AI Research Talk", _SINGLE_DAY, club="SCS"),
            ]
        )

        results = find_events(keywords=["AI"])["results"]

        self.assertEqual([event["title"] for event in results], ["AI Research Talk"])

    def test_a_longer_keyword_matches_a_word_it_starts(self) -> None:
        self._patch(
            [
                _event_row("1", "Startups on Tap", _SINGLE_DAY),
                _event_row("2", "Restart Your Résumé", _SINGLE_DAY),
            ]
        )

        # "startup" reaches "Startups"; it does not reach "Restart".
        results = find_events(keywords=["startup"])["results"]

        self.assertEqual([event["title"] for event in results], ["Startups on Tap"])

    def test_keyword_filter_reads_the_tags_out_of_their_markup(self) -> None:
        self._patch(
            [
                _event_row(
                    "1",
                    "AI Research Talk",
                    _SINGLE_DAY,
                    tags='<a aria-label="Free Food"></a><a aria-label="Technology"></a>',
                ),
                _event_row("2", "Pottery Workshop", _SINGLE_DAY, category="Arts", club="Arts Club"),
            ]
        )

        results = find_events(keywords=["free food"])["results"]

        self.assertEqual([event["title"] for event in results], ["AI Research Talk"])
        self.assertEqual(results[0]["categories"], ["Research", "Free Food", "Technology"])

    def test_time_window_filter(self) -> None:
        def at(hour: str) -> str:
            return f"<p>Tue, Sep 01, 2026</p><p>{hour} &ndash; 11 PM</p>"

        self._patch(
            [
                _event_row("10", "Morning", at("9 AM")),
                _event_row("11", "Afternoon", at("3 PM")),
                _event_row("12", "Evening", at("7 PM")),
            ]
        )

        # after= is inclusive, before= is exclusive — only the 3pm event qualifies.
        results = find_events(after="2026-09-01T12:00:00", before="2026-09-01T18:00:00")["results"]

        self.assertEqual([event["title"] for event in results], ["Afternoon"])

    def test_an_api_failure_raises_tool_error(self) -> None:
        with patch("apps.tools.events.get_json", side_effect=_status_error(503)):
            with self.assertRaises(ToolError):
                find_events()


# --- Maps (live API, patched) -------------------------------------------------

# Real coordinates and names from api.maps.scottylabs.org/buildings, which keys
# by building code. HAM/PC are here on purpose: they are what `/search` returns
# ahead of HH/POS for "hamerschlag" and "posner", so they are what the alias
# table has to beat.
def _building(code: str, name: str, lat: float, lng: float) -> dict:
    return {
        "code": code,
        "name": name,
        "defaultOrdinal": None,
        "defaultFloor": "1",
        "labelLatitude": lat,
        "labelLongitude": lng,
        "shape": [],
        "hitbox": None,
        "floors": ["1"],
        "isMapped": True,
    }


_CATALOG = {
    "GHC": _building("GHC", "Gates & Hillman Centers", 40.44348909465742, -79.9446062625),
    "WEH": _building("WEH", "Wean Hall", 40.44268084296874, -79.94563372513628),
    "CUC": _building("CUC", "Cohon University Center", 40.443478, -79.942077),
    "BH": _building("BH", "Baker Hall", 40.441412, -79.944652),
    "DH": _building("DH", "Doherty Hall", 40.442523, -79.944677),
    "HL": _building("HL", "Hunt Library", 40.441090, -79.943641),
    "TEP": _building("TEP", "Tepper Building", 40.444982, -79.945304),
    "MI": _building("MI", "Mellon Institute", 40.446134, -79.951058),
    "HH": _building("HH", "Hamerschlag Hall", 40.44238029153567, -79.94678460859375),
    "HAM": _building("HAM", "Hamerschlag House", 40.44135313142273, -79.93879856796875),
    "POS": _building("POS", "Posner Hall", 40.44144832861169, -79.94208255156249),
    "PC": _building("PC", "Posner Center", 40.44150469133797, -79.94246261718749),
}

# The real /search shape, and the real ranking: rooms come back above buildings.
_SEARCH_ROHR = [
    {
        "id": "ec67378d-bf14-4c5a-a830-0aadaca1c8fa",
        "nameWithSpace": "GHC 3101",
        "fullNameWithSpace": "Gates & Hillman Centers 3101",
        "labelPosition": {"latitude": 40.44347617300122, "longitude": -79.94480928001676},
        "type": "room",
        "roomType": "Food",
        "alias": "Rohr Café — La Prima",
        "numTerms": 107,
    },
    {
        "id": "GHC",
        "nameWithSpace": "Gates & Hillman Centers",
        "fullNameWithSpace": "Gates & Hillman Centers",
        "labelPosition": {"latitude": 40.44348909465742, "longitude": -79.9446062625},
        "type": "building",
        "alias": "",
        "numTerms": 12,
    },
]


class MapsResolutionTests(SimpleTestCase):
    """Name → building code. The part most likely to regress silently."""

    def _patch(self, **kwargs):
        patcher = patch("apps.tools.maps.get_json", **kwargs)
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started

    def _catalog_only(self):
        return self._patch(return_value=_CATALOG)

    def test_resolves_by_code_alias_and_full_name(self) -> None:
        self._catalog_only()
        for typed, expected in (
            ("WEH", "Wean Hall"),
            ("wean", "Wean Hall"),
            ("Wean Hall", "Wean Hall"),
            ("ghc", "Gates & Hillman Centers"),
            ("uc", "Cohon University Center"),
        ):
            with self.subTest(typed=typed):
                result = walk_time(from_building=typed, to_building="DH")["results"][0]
                self.assertEqual(result["from"], expected)

    def test_ambiguous_words_resolve_to_the_academic_building(self) -> None:
        # `/search` ranks Hamerschlag House and Posner Center first; the alias
        # table exists so the bare word still lands on the building people mean.
        self._catalog_only()

        walk = walk_time(from_building="hamerschlag", to_building="posner")["results"][0]
        self.assertEqual(walk["from_code"], "HH", "hamerschlag must not resolve to HAM")
        self.assertEqual(walk["to_code"], "POS", "posner must not resolve to PC")

    def test_names_our_other_tools_emit_still_resolve(self) -> None:
        # rooms.py's schema enum and dining.py's _NEAR_ALIASES were written
        # against the old fixture names. Upstream calls GHC "Gates & Hillman
        # Centers" and has no "University Center", so these must keep working
        # or those tools stop composing with maps.
        self._catalog_only()
        for legacy, expected in (
            ("Gates-Hillman Center", "GHC"),
            ("University Center", "CUC"),
            ("Hamerschlag Hall", "HH"),
            ("Posner Hall", "POS"),
            ("Wean Hall", "WEH"),
            ("Baker Hall", "BH"),
            ("Doherty Hall", "DH"),
        ):
            with self.subTest(legacy=legacy):
                result = walk_time(from_building=legacy, to_building="DH")["results"][0]
                self.assertEqual(result["from_code"], expected)

    def test_unknown_building_raises_tool_error(self) -> None:
        self._patch(side_effect=[_CATALOG, []])
        with self.assertRaises(ToolError):
            walk_time(from_building="Hogwarts", to_building="Wean")

    def test_search_is_only_consulted_when_nothing_else_matches(self) -> None:
        api = self._patch(return_value=_CATALOG)
        walk_time(from_building="wean", to_building="ghc")
        self.assertTrue(
            all("/search" not in call.args[0] for call in api.call_args_list),
            "a curated alias must not cost a search request",
        )


class WalkTimeTests(SimpleTestCase):
    def _patch(self):
        patcher = patch("apps.tools.maps.get_json", return_value=_CATALOG)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_estimates_from_real_coordinates(self) -> None:
        self._patch()
        result = walk_time(from_building="Wean", to_building="Gates")["results"][0]

        self.assertEqual(result["from"], "Wean Hall")
        self.assertEqual(result["to"], "Gates & Hillman Centers")
        self.assertEqual(result["distance_m"], 125)
        self.assertEqual(result["walk_minutes"], 2)

    def test_same_building_is_zero_not_rounded_up_to_one(self) -> None:
        self._patch()
        result = walk_time(from_building="Wean", to_building="Wean Hall")["results"][0]
        self.assertEqual(result["walk_minutes"], 0)

    def test_nothing_is_flagged_as_a_fixture(self) -> None:
        self._patch()
        self.assertFalse(walk_time(from_building="Wean", to_building="Gates")["results"][0]["is_mock"])

    def test_an_api_failure_raises_tool_error(self) -> None:
        with patch("apps.tools.maps.get_json", side_effect=_status_error(503)):
            with self.assertRaises(ToolError):
                walk_time(from_building="Wean", to_building="Gates")

    def test_an_unreachable_api_degrades_to_a_tool_error(self) -> None:
        with patch("apps.tools.maps.get_json", side_effect=httpx.ConnectError("no route")):
            with self.assertRaises(ToolError):
                nearby(building="Wean Hall")


class NearbyTests(SimpleTestCase):
    def _patch(self):
        patcher = patch("apps.tools.maps.get_json", return_value=_CATALOG)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_radius_filters_and_sorts(self) -> None:
        self._patch()
        results = nearby(building="Wean Hall", radius_minutes=3)["results"]

        names = {result["name"] for result in results}
        self.assertIn("Gates & Hillman Centers", names)  # 125 m, 2 min
        self.assertIn("Baker Hall", names)  # 164 m, 3 min
        self.assertNotIn("Mellon Institute", names)  # 599 m, 10 min
        self.assertTrue(all(r["walk_minutes"] <= 3 for r in results))
        self.assertEqual(
            [r["walk_minutes"] for r in results],
            sorted(r["walk_minutes"] for r in results),
        )

    def test_the_origin_is_not_listed_as_near_itself(self) -> None:
        self._patch()
        self.assertNotIn(
            "Wean Hall", {r["name"] for r in nearby(building="Wean Hall")["results"]}
        )

    def test_a_capped_list_says_what_it_left_out(self) -> None:
        # The live catalog is 74 buildings, so a generous radius can match
        # dozens; each one costs a citation card.
        self._patch()
        payload = nearby(building="Wean Hall", radius_minutes=8, limit=3)

        self.assertEqual(len(payload["results"]), 3)
        self.assertIn("closest of", payload["note"])
        self.assertEqual(len(payload["citations"]), 3, "a capped list must not over-cite")

    def test_one_upstream_call_serves_the_whole_lookup(self) -> None:
        with patch("apps.tools.maps.get_json", return_value=_CATALOG) as api:
            nearby(building="Wean Hall", radius_minutes=8)
        self.assertEqual(api.call_count, 1, "nearby must not fan out per building")


class MapsCitationTests(SimpleTestCase):
    def _patch(self):
        patcher = patch("apps.tools.maps.get_json", return_value=_CATALOG)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_citations_link_to_the_map_and_name_one_source(self) -> None:
        self._patch()
        payload = nearby(building="Wean Hall", radius_minutes=3)

        self.assertEqual(len(payload["citations"]), len(payload["results"]))
        self.assertTrue(all(c["source"] == "CMU Maps" for c in payload["citations"]))
        self.assertNotIn("", _urls(payload["citations"]), "live maps citations must link")
        self.assertTrue(
            all(url.startswith("https://maps.scottylabs.org/") for url in _urls(payload["citations"]))
        )
        self.assertTrue(all(c["verified_at"] is not None for c in payload["citations"]))

    def test_every_estimate_says_it_is_not_a_route(self) -> None:
        # The routing endpoint only answers for CUC, so these numbers are
        # straight-line. If that disclosure ever drops out, the model can
        # present an estimate as turn-by-turn directions.
        self._patch()
        walk = walk_time(from_building="Wean", to_building="Gates")["citations"][0]

        self.assertEqual(walk["title"], "Wean Hall → Gates & Hillman Centers")
        self.assertIn("straight-line", walk["snippet"])
        self.assertIn("not a walking route", walk["snippet"])
        self.assertTrue(
            all("straight-line" in c["snippet"] for c in nearby(building="Wean Hall")["citations"])
        )


class FindPlaceTests(SimpleTestCase):
    def test_returns_rooms_with_their_building(self) -> None:
        with patch("apps.tools.maps.get_json", return_value=_SEARCH_ROHR):
            payload = find_place(query="rohr cafe")

        room = payload["results"][0]
        self.assertEqual(room["type"], "room")
        self.assertEqual(room["alias"], "Rohr Café — La Prima")
        self.assertEqual(room["building_code"], "GHC", "a room must report its building")
        self.assertEqual(payload["results"][1]["building_code"], "GHC")
        self.assertFalse(room["is_mock"])

    def test_the_alias_titles_the_citation(self) -> None:
        with patch("apps.tools.maps.get_json", return_value=_SEARCH_ROHR):
            citation = find_place(query="rohr cafe")["citations"][0]

        self.assertEqual(citation["title"], "Rohr Café — La Prima")
        self.assertEqual(citation["source"], "CMU Maps")
        self.assertEqual(citation["url"], "https://maps.scottylabs.org/GHC?dst=GHC")

    def test_no_matches_raises_tool_error(self) -> None:
        with patch("apps.tools.maps.get_json", return_value=[]):
            with self.assertRaises(ToolError):
                find_place(query="atlantis")


# --- Requisites and gen-eds ---------------------------------------------------

# The real /courses/requisites/15-213 shape: prereqRelations rides along beside
# prereqs, and postreqs is the list nothing else in the API exposes.
_REQUISITES_213 = {
    "prereqs": ["15-122"],
    "prereqRelations": [["15122"]],
    "postreqs": ["15-411", "15-418", "15-440"],
}

_GENEDS_SCS = [
    {
        "courseID": "03-121",
        "name": "Modern Biology",
        "units": "9.0",
        "desc": "An introductory course ...",
        "tags": ["Science"],
        "fces": [],
        "startsCounting": None,
        "stopsCounting": None,
    },
    {
        "courseID": "76-101",
        "name": "Interpretation and Argument",
        "units": "9.0",
        "desc": "Writing ...",
        "tags": ["Writing"],
        "fces": [],
        "startsCounting": None,
        "stopsCounting": None,
    },
]


class CourseRequisitesTests(SimpleTestCase):
    def test_returns_prereqs_and_the_postreqs_nothing_else_exposes(self) -> None:
        with patch("apps.tools.courses.get_json", return_value=_REQUISITES_213):
            result = course_requisites(course_number="15-213")["results"][0]

        self.assertEqual(result["prereqs"], ["15-122"])
        self.assertEqual(result["postreqs"], ["15-411", "15-418", "15-440"])
        self.assertEqual(result["coreqs"], [])
        self.assertFalse(result["is_mock"])

    def test_the_citation_summarizes_both_directions(self) -> None:
        with patch("apps.tools.courses.get_json", return_value=_REQUISITES_213):
            citation = course_requisites(course_number="15-213")["citations"][0]

        self.assertEqual(citation["source"], "CMU Courses")
        self.assertIn("15-122", citation["snippet"])
        self.assertIn("3 courses require it", citation["snippet"])

    def test_an_unknown_course_number_is_not_found_rather_than_an_outage(self) -> None:
        # Same upstream quirk get_course documents: a bare 500 for a course
        # number that does not exist.
        with patch("apps.tools.courses.get_json", side_effect=_status_error(500)):
            with self.assertRaises(ToolError) as caught:
                course_requisites(course_number="99-999")
        self.assertIn("not found", str(caught.exception))

    def test_an_unreachable_api_degrades_to_a_tool_error(self) -> None:
        with patch("apps.tools.courses.get_json", side_effect=httpx.ConnectError("no route")):
            with self.assertRaises(ToolError):
                course_requisites(course_number="15-213")


class GenedsTests(SimpleTestCase):
    def test_projects_the_fields_worth_context(self) -> None:
        with patch("apps.tools.courses.get_json", return_value=_GENEDS_SCS):
            payload = find_geneds(school="SCS")

        first = payload["results"][0]
        self.assertEqual(first["course_number"], "03-121")
        self.assertEqual(first["units"], 9.0, "units arrive as a string upstream")
        self.assertEqual(first["tags"], ["Science"])
        self.assertNotIn("desc", first, "the 266 KB payload must not reach the model whole")
        self.assertIsNone(payload.get("note"), "nothing was truncated")

    def test_a_capped_list_says_so(self) -> None:
        with patch("apps.tools.courses.get_json", return_value=_GENEDS_SCS):
            payload = find_geneds(school="SCS", limit=1)

        self.assertEqual(len(payload["results"]), 1)
        self.assertIn("1 of 2", payload["note"])

    def test_a_school_that_publishes_no_list_is_refused_by_name(self) -> None:
        # DC/CFA/TSB/SHS answer 200 with [], which would otherwise read as
        # "this college has no gen-eds".
        with self.assertRaises(ToolError) as caught:
            find_geneds(school="DC")
        self.assertIn("SCS", str(caught.exception))

    def test_an_empty_upstream_list_is_not_an_empty_answer(self) -> None:
        with patch("apps.tools.courses.get_json", return_value=[]):
            with self.assertRaises(ToolError):
                find_geneds(school="SCS")
