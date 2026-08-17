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

from apps.tools.courses import get_course, search_courses
from apps.tools.dining import find_dining
from apps.tools.events import find_events
from apps.tools.maps import nearby, walk_time
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


# --- Maps (pure fixture, no network) -----------------------------------------


class MapsToolTests(SimpleTestCase):
    def test_walk_time_by_alias(self) -> None:
        result = walk_time(from_building="Wean", to_building="Gates")["results"][0]

        self.assertEqual(result["from"], "Wean Hall")
        self.assertEqual(result["to"], "Gates-Hillman Center")
        self.assertEqual(result["walk_minutes"], 2)

    def test_walk_time_same_building_is_zero(self) -> None:
        result = walk_time(from_building="Wean", to_building="Wean Hall")["results"][0]
        self.assertEqual(result["walk_minutes"], 0)

    def test_nearby_radius_filter(self) -> None:
        results = nearby(building="Wean Hall", radius_minutes=3)["results"]

        names = {result["name"] for result in results}
        self.assertIn("Gates-Hillman Center", names)
        self.assertIn("Cohon University Center", names)
        # Baker Hall is 6 min — well past the radius ceiling.
        self.assertNotIn("Baker Hall", names)
        self.assertTrue(all(result["walk_minutes"] <= 3 for result in results))

    def test_unknown_building_raises_tool_error(self) -> None:
        with self.assertRaises(ToolError):
            walk_time(from_building="Hogwarts", to_building="Wean")

    def test_is_mock_true_on_all_results(self) -> None:
        self.assertTrue(walk_time(from_building="Wean", to_building="Gates")["results"][0]["is_mock"])
        self.assertTrue(all(r["is_mock"] for r in nearby(building="Wean Hall")["results"]))

    def test_citations_say_the_data_is_a_fixture_and_link_nowhere(self) -> None:
        payload = nearby(building="Wean Hall", radius_minutes=3)

        self.assertEqual(len(payload["citations"]), len(payload["results"]))
        self.assertEqual(_urls(payload["citations"]), {""})
        self.assertTrue(all("mock data" in c["snippet"] for c in payload["citations"]))

        walk = walk_time(from_building="Wean", to_building="Gates")["citations"][0]
        self.assertEqual(walk["title"], "Wean Hall → Gates-Hillman Center")
        self.assertIn("mock data", walk["snippet"])
