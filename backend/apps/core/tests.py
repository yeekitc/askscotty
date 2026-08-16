"""Tests for the shared HTTP helper (tasklist B0).

Everything runs against `httpx.MockTransport` — the point of the helper is the
behaviour around a request (retry, User-Agent, throttle, cache), and a real
socket would make that slow and flaky to assert on. The one thing a mock cannot
prove, that api.cmueats.com really answers a `get_json` call, was checked by
hand once; see the commit message.

    docker compose exec backend python manage.py test apps.core
"""

from __future__ import annotations

import threading
import time
from unittest import mock

import httpx
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from . import http

URL = "https://api.example.edu/locations"


class GetJsonTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        # Module-level state, so one test's throttle must not leak into the next.
        http._host_gates.clear()
        http._host_last_request.clear()
        self.patch(_MIN_HOST_INTERVAL=0.0, _RETRY_BACKOFF=0.0)

    def patch(self, **constants):
        for name, value in constants.items():
            patcher = mock.patch.object(http, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def stub(self, *outcomes) -> list[httpx.Request]:
        """Install a transport replaying `outcomes`; return the requests it saw.

        An outcome is either `(status, payload)`, an `httpx.Response` for a body
        that is not JSON, or an exception to raise — between them that covers
        both halves of the retry policy. The last one repeats, so a single
        outcome means "always answer this".
        """
        seen: list[httpx.Request] = []
        lock = threading.Lock()

        def handler(request: httpx.Request) -> httpx.Response:
            with lock:
                seen.append(request)
                outcome = outcomes[min(len(seen) - 1, len(outcomes) - 1)]
            if isinstance(outcome, Exception):
                raise outcome
            if isinstance(outcome, httpx.Response):
                return httpx.Response(outcome.status_code, content=outcome.content)
            status, payload = outcome
            return httpx.Response(status, json=payload)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        self.patch(_client=lambda: client)
        return seen

    def test_decodes_a_200(self):
        seen = self.stub((200, {"locations": [{"name": "Schatz"}]}))

        data = http.get_json(URL, params={"campus": "pittsburgh"})

        self.assertEqual(data, {"locations": [{"name": "Schatz"}]})
        self.assertEqual(seen[0].url.params["campus"], "pittsburgh")

    @override_settings(CRAWLER_USER_AGENT="AskScottyBot/testing (+https://example.edu)")
    def test_identifies_itself(self):
        seen = self.stub((503, None), (200, {}))

        http.get_json(URL)

        # PRD §3: every request we make, including the retries.
        self.assertEqual(len(seen), 2)
        for request in seen:
            self.assertEqual(
                request.headers["user-agent"], "AskScottyBot/testing (+https://example.edu)"
            )

    def test_retries_a_503(self):
        seen = self.stub((503, None), (200, {"ok": True}))

        self.assertEqual(http.get_json(URL), {"ok": True})
        self.assertEqual(len(seen), 2)

    def test_does_not_retry_a_404(self):
        seen = self.stub((404, None))

        with self.assertRaises(httpx.HTTPStatusError):
            http.get_json(URL)
        self.assertEqual(len(seen), 1)

    def test_retries_a_connection_failure_to_the_cap(self):
        seen = self.stub(httpx.ConnectError("no route to host"))

        with self.assertRaises(httpx.ConnectError):
            http.get_json(URL)
        self.assertEqual(len(seen), http._MAX_ATTEMPTS)

    def test_stops_retrying_once_the_budget_is_gone(self):
        seen = self.stub(httpx.ReadTimeout("upstream hung"))
        self.patch(_RETRY_BUDGET=0.0)

        with self.assertRaises(httpx.ReadTimeout):
            http.get_json(URL)
        self.assertEqual(len(seen), 1)

    def test_a_body_that_is_not_json_stays_in_the_httpx_family(self):
        # An upstream serving an error page with a 200 is ordinary; the point is
        # that one `except httpx.HTTPError` at the call site catches it, rather
        # than a bare ValueError escaping past a tool and 500-ing the request.
        self.stub(httpx.Response(200, text="<html>maintenance</html>"))

        with self.assertRaises(httpx.HTTPError):
            http.get_json(URL)

    def test_ttl_serves_the_second_call_from_cache(self):
        seen = self.stub((200, {"ok": True}))

        first = http.get_json(URL, ttl=60)
        second = http.get_json(URL, ttl=60)

        self.assertEqual(first, second)
        self.assertEqual(len(seen), 1)

    def test_cache_distinguishes_params(self):
        seen = self.stub((200, {"ok": True}))

        http.get_json(URL, params={"campus": "pittsburgh"}, ttl=60)
        http.get_json(URL, params={"campus": "doha"}, ttl=60)

        self.assertEqual(len(seen), 2)

    def test_cache_ignores_param_order(self):
        seen = self.stub((200, {"ok": True}))

        http.get_json(URL, params={"campus": "pittsburgh", "day": "mon"}, ttl=60)
        http.get_json(URL, params={"day": "mon", "campus": "pittsburgh"}, ttl=60)

        # Two dicts spelling the same request are the same request. Without the
        # sort in _cache_key this is a miss and the demo refetches.
        self.assertEqual(len(seen), 1)

    def test_default_never_touches_the_cache(self):
        seen = self.stub((200, {"ok": True}))

        http.get_json(URL)
        http.get_json(URL)

        self.assertEqual(len(seen), 2)
        # Not just "it refetched" — nothing was written either, which is what
        # keeps a future personal call from caching by accident.
        self.assertIsNone(cache.get(http._cache_key(URL, None)))

    def test_throttles_hosts_independently(self):
        self.stub((200, {"ok": True}))
        self.patch(_MIN_HOST_INTERVAL=0.2)

        http.get_json("https://one.example.edu/a")

        started = time.monotonic()
        http.get_json("https://one.example.edu/a")
        same_host = time.monotonic() - started

        started = time.monotonic()
        http.get_json("https://two.example.edu/a")
        other_host = time.monotonic() - started

        self.assertGreaterEqual(same_host, 0.2)
        self.assertLess(other_host, 0.1)

    def test_throttles_concurrent_callers_to_one_host(self):
        # The reason for a lock per host rather than a bare timestamp: tool
        # dispatch is parallel (planner/loop.py), so the gate has to hold across
        # threads, not just across sequential calls on one.
        seen = self.stub((200, {"ok": True}))
        self.patch(_MIN_HOST_INTERVAL=0.1)

        threads = [
            threading.Thread(target=http.get_json, args=("https://one.example.edu/a",))
            for _ in range(4)
        ]
        started = time.monotonic()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        elapsed = time.monotonic() - started

        self.assertEqual(len(seen), 4)
        # Four requests spaced 0.1s apart: the first goes straight out, the
        # other three each wait their turn.
        self.assertGreaterEqual(elapsed, 0.3)
