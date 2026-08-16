"""Offline unit tests for the B2 live tools.

No real network requests are made — httpx is patched throughout.

Run with:
    docker compose exec backend python manage.py test apps.tools
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from django.test import TestCase

from apps.tools.courses import search_courses
from apps.tools.dining import find_dining
from apps.tools.events import find_events
from apps.tools.maps import nearby, walk_time
from apps.tools.registry import ToolError


# --- Shared helpers -----------------------------------------------------------


def _http_error(status: int) -> httpx.HTTPStatusError:
    response = MagicMock()
    response.status_code = status
    return httpx.HTTPStatusError(str(status), request=MagicMock(), response=response)


def _wire_courses_client(mock_client_class, json_body):
    """Return the mock inner client after wiring a single JSON response into it."""
    mock_instance = mock_client_class.return_value.__enter__.return_value
    mock_resp = MagicMock()
    mock_resp.json.return_value = json_body
    mock_instance.get.return_value = mock_resp
    return mock_instance


# Raw API payloads shared across courses tests.
_COURSE_MWF = {
    "courseID": "15-213",
    "name": "Intro to Computer Systems",
    "units": 12,
    "instructors": ["Bryant"],
    "lectures": [{"times": [{"days": "MWF", "begin": "10:30am", "end": "11:20am",
                              "room": "PH 100", "building": "Porter Hall"}]}],
    "prereqString": "15-122",
    "desc": "Memory and machine code.",
    "semester": "F24",
}

_COURSE_TR = {
    "courseID": "15-251",
    "name": "Great Theoretical Ideas",
    "units": 9,
    "instructors": ["Sleator"],
    "lectures": [{"times": [{"days": "TR", "begin": "1:30pm", "end": "2:50pm",
                              "room": "DH 1112", "building": "Doherty Hall"}]}],
    "prereqString": "",
    "desc": "Combinatorics and graph theory.",
    "semester": "F24",
}

# Raw API payload shared across dining tests.
_LOCATION = {
    "name": "Rohr Café",
    "location": "Wean Hall 4th Floor",
    "conceptTitle": "Coffee & Pastries",
    "isOpen": True,
    "schedule": [{"day": "Monday", "startTime": "08:00am", "endTime": "05:00pm"}],
    "message": "",
}

# Raw API payloads shared across events tests.
_EVENT_AI = {
    "id": "1",
    "name": "AI Research Talk",
    "starts_at": "2026-09-01T14:00:00",
    "ends_at": "2026-09-01T15:30:00",
    "location": "GHC 6115",
    "organization_name": "SCS",
    "categories": ["Research"],
    "permalink": "https://tartanconnect.cmu.edu/1",
    "description": "Machine learning and neural networks.",
}

_EVENT_OTHER = {
    "id": "2",
    "name": "Pottery Workshop",
    "starts_at": "2026-09-01T10:00:00",
    "ends_at": "2026-09-01T12:00:00",
    "location": "CFA",
    "organization_name": "Arts Club",
    "categories": ["Arts"],
    "permalink": "https://tartanconnect.cmu.edu/2",
    "description": "Handmade pottery.",
}


# --- Maps (pure fixture, no network) -----------------------------------------


class MapsToolTests(TestCase):
    def test_walk_time_by_alias(self):
        result = walk_time(from_building="Wean", to_building="Gates")
        self.assertEqual(result["from"], "Wean Hall")
        self.assertEqual(result["to"], "Gates-Hillman Center")
        self.assertEqual(result["walk_minutes"], 2)

    def test_walk_time_same_building_is_zero(self):
        result = walk_time(from_building="Wean", to_building="Wean Hall")
        self.assertEqual(result["walk_minutes"], 0)

    def test_nearby_radius_filter(self):
        # The fixture stores pairs in (smaller, larger) canonical order so the
        # min/max lookup works. Only entries whose key order matches are found:
        # "Cohon University Center" < "Wean Hall" (C < W) → 3 min ✓
        # "Gates-Hillman Center"   < "Wean Hall" (G < W) → 2 min ✓
        results = nearby(building="Wean Hall", radius_minutes=3)
        names = {r["name"] for r in results}
        self.assertIn("Gates-Hillman Center", names)
        self.assertIn("Cohon University Center", names)
        # Baker Hall is 6 min — well past the radius ceiling.
        self.assertNotIn("Baker Hall", names)
        # Every returned entry is within the requested radius.
        self.assertTrue(all(r["walk_minutes"] <= 3 for r in results))

    def test_unknown_building_raises_tool_error(self):
        with self.assertRaises(ToolError):
            walk_time(from_building="Hogwarts", to_building="Wean")

    def test_is_mock_true_on_all_results(self):
        self.assertTrue(walk_time(from_building="Wean", to_building="Gates")["is_mock"])
        self.assertTrue(all(r["is_mock"] for r in nearby(building="Wean Hall")))


# --- Courses ------------------------------------------------------------------


class CoursesToolTests(TestCase):
    @patch("apps.tools.courses.httpx.Client")
    def test_search_returns_normalized_shape(self, mock_client_class):
        _wire_courses_client(mock_client_class, [_COURSE_MWF])

        results = search_courses(query="computer systems")

        self.assertEqual(len(results), 1)
        course = results[0]
        self.assertEqual(course["course_number"], "15-213")
        self.assertEqual(course["title"], "Intro to Computer Systems")
        self.assertEqual(course["units"], 12)
        self.assertEqual(course["meetings"][0]["days"], "MWF")
        self.assertEqual(course["source"], "CMU Courses API")
        self.assertFalse(course["is_mock"])

    @patch("apps.tools.courses.httpx.Client")
    def test_units_filter(self, mock_client_class):
        _wire_courses_client(mock_client_class, [_COURSE_MWF, _COURSE_TR])

        results = search_courses(query="15", units=9)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["course_number"], "15-251")

    @patch("apps.tools.courses.httpx.Client")
    def test_days_excluded_filter(self, mock_client_class):
        _wire_courses_client(mock_client_class, [_COURSE_MWF, _COURSE_TR])

        # Exclude Friday — the MWF course is dropped; the TR course survives.
        results = search_courses(query="15", days_excluded=["F"])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["course_number"], "15-251")

    @patch("apps.tools.courses.httpx.Client")
    def test_4xx_raises_tool_error(self, mock_client_class):
        mock_instance = mock_client_class.return_value.__enter__.return_value
        mock_instance.get.return_value.raise_for_status.side_effect = _http_error(404)

        with self.assertRaises(ToolError):
            search_courses(query="anything")


# --- Dining -------------------------------------------------------------------


class DiningToolTests(TestCase):
    def _mock_response(self, mock_get, locations=None):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"locations": locations if locations is not None else [_LOCATION]}
        mock_get.return_value = mock_resp

    @patch("apps.tools.dining.httpx.get")
    def test_returns_normalized_locations(self, mock_get):
        self._mock_response(mock_get)

        results = find_dining()

        self.assertEqual(len(results), 1)
        loc = results[0]
        self.assertEqual(loc["name"], "Rohr Café")
        self.assertTrue(loc["is_open"])
        self.assertEqual(loc["source"], "CMU Eats")
        self.assertFalse(loc["is_mock"])

    @patch("apps.tools.dining.httpx.get")
    def test_near_annotation(self, mock_get):
        self._mock_response(mock_get)

        results = find_dining(near="wean")

        self.assertTrue(all("near_building" in r for r in results))
        # "wean" resolves to the canonical "Wean Hall" via _NEAR_ALIASES.
        self.assertEqual(results[0]["near_building"], "Wean Hall")

    @patch("apps.tools.dining.httpx.get")
    def test_api_error_raises_tool_error(self, mock_get):
        mock_get.return_value.raise_for_status.side_effect = _http_error(503)

        with self.assertRaises(ToolError):
            find_dining()


# --- Events -------------------------------------------------------------------


class EventsToolTests(TestCase):
    def _mock_response(self, mock_get, events=None):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"event": events if events is not None else [_EVENT_AI, _EVENT_OTHER]}
        mock_get.return_value = mock_resp

    @patch("apps.tools.events.httpx.get")
    def test_keyword_filter(self, mock_get):
        self._mock_response(mock_get)

        results = find_events(keywords=["AI"])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "AI Research Talk")

    @patch("apps.tools.events.httpx.get")
    def test_time_window_filter(self, mock_get):
        self._mock_response(mock_get, events=[
            {**_EVENT_OTHER, "id": "10", "name": "Morning Talk", "starts_at": "2026-09-01T09:00:00"},
            {**_EVENT_AI,    "id": "11", "name": "Afternoon Talk", "starts_at": "2026-09-01T15:00:00"},
            {**_EVENT_AI,    "id": "12", "name": "Evening Event", "starts_at": "2026-09-01T19:00:00"},
        ])

        # after= is inclusive, before= is exclusive — only the 3pm event qualifies.
        results = find_events(after="2026-09-01T12:00:00", before="2026-09-01T18:00:00")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Afternoon Talk")

    @patch("apps.tools.events.httpx.get")
    def test_api_error_raises_tool_error(self, mock_get):
        mock_get.return_value.raise_for_status.side_effect = _http_error(503)

        with self.assertRaises(ToolError):
            find_events()
