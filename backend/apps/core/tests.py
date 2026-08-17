"""Tests for apps.core — the shared HTTP helper (tasklist B0) and the personal
connections endpoint (B5).

    docker compose exec backend python manage.py test apps.core
"""

from __future__ import annotations

import threading
import time
from unittest import mock

import httpx
from apps.personal import crypto
from apps.personal.models import UserConnection
from cryptography.fernet import Fernet
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from . import http

URL = "https://api.example.edu/locations"


class GetJsonTests(SimpleTestCase):
    """The shared HTTP helper, against `httpx.MockTransport`.

    The point of the helper is the behaviour *around* a request (retry,
    User-Agent, throttle, cache), and a real socket would make that slow and
    flaky to assert on. The one thing a mock cannot prove, that api.cmueats.com
    really answers a `get_json` call, was checked by hand once; see the commit
    message.
    """

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


# --- Personal connections (B5) ------------------------------------------------

SESSION = "session-under-test"
OTHER_SESSION = "someone-else"

CANVAS_TOKEN = "canvas-pat-do-not-leak"
PIAZZA_PASSWORD = "piazza-password-do-not-leak"

# Generated per run rather than committed: a real key in a repo file reads like
# a secret even when it guards nothing.
_TEST_KEY = Fernet.generate_key().decode()


@override_settings(CONNECTOR_ENCRYPTION_KEY=_TEST_KEY)
class ConnectionEndpointTests(TestCase):
    """GET/POST /api/connections/ and DELETE /api/connections/{provider}/.

    Every assertion about a credential is made against the raw response bytes,
    not the parsed body: PRD §9 is that a credential never leaves the backend,
    and a key-by-key check would miss one that leaked in an error message.
    """

    def setUp(self):
        # _fernet() is lru_cached, so without this it keeps whichever key the
        # first encrypting test happened to see. It also matters that the key is
        # overridden at all: the test runner forces DEBUG=False, and crypto
        # refuses to derive a development key once it is — so an environment
        # with no CONNECTOR_ENCRYPTION_KEY would fail here rather than in the
        # code under test.
        crypto._fernet.cache_clear()
        self.addCleanup(crypto._fernet.cache_clear)

        self.list_url = reverse("connections")

    def detail_url(self, provider: str) -> str:
        return reverse("connection-detail", args=[provider])

    def get(self, session_id: str | None = SESSION):
        return self.client.get(self.list_url, **_session_header(session_id))

    def post(self, body: dict, session_id: str | None = SESSION):
        return self.client.post(
            self.list_url,
            data=body,
            content_type="application/json",
            **_session_header(session_id),
        )

    def delete(self, provider: str, session_id: str | None = SESSION):
        return self.client.delete(self.detail_url(provider), **_session_header(session_id))

    def connect_canvas(self, session_id: str = SESSION, token: str = CANVAS_TOKEN):
        return self.post({"provider": "canvas", "credential": {"token": token}}, session_id)

    # --- Connecting -----------------------------------------------------------

    def test_connecting_canvas_stores_an_encrypted_credential(self):
        response = self.connect_canvas()

        self.assertEqual(response.status_code, 200)
        connection = UserConnection.objects.get(session_id=SESSION, provider="canvas")
        self.assertEqual(connection.get_credential(), {"token": CANVAS_TOKEN})
        # The ciphertext is the only copy in the database.
        self.assertNotIn(CANVAS_TOKEN, connection.encrypted_token)

    def test_the_connect_response_carries_no_credential(self):
        response = self.connect_canvas()

        self.assertNotIn(CANVAS_TOKEN.encode(), response.content)
        self.assertNotIn(b"credential", response.content)
        self.assertNotIn(b"token", response.content)
        self.assertEqual(
            set(response.json()), {"provider", "connected_at", "last_sync_at"}
        )

    def test_canvas_tools_can_still_read_the_credential_as_a_token(self):
        # apps/personal/tools.py calls get_token(), not get_credential(); the
        # JSON storage shape has to stay invisible to it.
        self.connect_canvas()

        connection = UserConnection.objects.get(session_id=SESSION, provider="canvas")
        self.assertEqual(connection.get_token(), CANVAS_TOKEN)

    def test_a_two_field_credential_round_trips(self):
        response = self.post(
            {
                "provider": "piazza",
                "credential": {"email": "student@andrew.cmu.edu", "password": PIAZZA_PASSWORD},
            }
        )

        self.assertEqual(response.status_code, 200)
        connection = UserConnection.objects.get(session_id=SESSION, provider="piazza")
        self.assertEqual(
            connection.get_credential(),
            {"email": "student@andrew.cmu.edu", "password": PIAZZA_PASSWORD},
        )
        self.assertNotIn(PIAZZA_PASSWORD.encode(), response.content)

    def test_surrounding_whitespace_is_stripped(self):
        self.connect_canvas(token=f"  {CANVAS_TOKEN}\n")

        connection = UserConnection.objects.get(session_id=SESSION, provider="canvas")
        self.assertEqual(connection.get_token(), CANVAS_TOKEN)

    def test_undeclared_credential_keys_are_not_stored(self):
        self.post(
            {
                "provider": "canvas",
                "credential": {"token": CANVAS_TOKEN, "password": PIAZZA_PASSWORD},
            }
        )

        connection = UserConnection.objects.get(session_id=SESSION, provider="canvas")
        self.assertEqual(connection.get_credential(), {"token": CANVAS_TOKEN})

    # --- Rejecting ------------------------------------------------------------

    def test_a_partial_credential_is_rejected(self):
        response = self.post(
            {"provider": "piazza", "credential": {"email": "student@andrew.cmu.edu"}}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.json()["error"]["message"])
        # Not silently stored minus the missing key.
        self.assertFalse(UserConnection.objects.exists())

    def test_a_blank_credential_field_is_rejected(self):
        response = self.connect_canvas(token="   ")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(UserConnection.objects.exists())

    def test_a_credential_that_is_not_an_object_is_a_400(self):
        # JSONField would accept any of these; the per-provider key check would
        # then raise AttributeError and turn a bad request into a 500.
        for credential in ["just-a-string", ["a", "list"], 42, None]:
            with self.subTest(credential=credential):
                response = self.post({"provider": "canvas", "credential": credential})
                self.assertEqual(response.status_code, 400)

    def test_an_unknown_provider_is_a_400(self):
        response = self.post({"provider": "banner", "credential": {"token": "x"}})

        self.assertEqual(response.status_code, 400)

    def test_stellic_cannot_be_connected_with_a_login(self):
        # A valid Provider with no CREDENTIAL_FIELDS entry — an uploaded degree
        # audit, not a login. Must be a 400, not the KeyError a straight lookup
        # would raise.
        response = self.post({"provider": "stellic", "credential": {"token": "x"}})

        self.assertEqual(response.status_code, 400)

    # --- Reconnecting ---------------------------------------------------------

    def test_reconnecting_replaces_the_credential_in_place(self):
        self.connect_canvas()
        self.connect_canvas(token="a-freshly-rotated-token")

        connection = UserConnection.objects.get(session_id=SESSION, provider="canvas")
        self.assertEqual(
            UserConnection.objects.filter(session_id=SESSION, provider="canvas").count(), 1
        )
        self.assertEqual(connection.get_token(), "a-freshly-rotated-token")

    def test_a_duplicate_row_is_impossible(self):
        self.connect_canvas()

        # The endpoint updates in place, but the constraint is what guarantees it
        # rather than the view remembering to.
        with self.assertRaises(IntegrityError), transaction.atomic():
            UserConnection.objects.create(
                session_id=SESSION, provider="canvas", encrypted_token="whatever"
            )

    # --- Listing --------------------------------------------------------------

    def test_listing_returns_connections_without_credentials(self):
        self.connect_canvas()
        self.post(
            {
                "provider": "piazza",
                "credential": {"email": "student@andrew.cmu.edu", "password": PIAZZA_PASSWORD},
            }
        )

        response = self.get()

        self.assertEqual(response.status_code, 200)
        connections = response.json()["connections"]
        self.assertEqual({c["provider"] for c in connections}, {"canvas", "piazza"})
        self.assertNotIn(CANVAS_TOKEN.encode(), response.content)
        self.assertNotIn(PIAZZA_PASSWORD.encode(), response.content)
        self.assertNotIn(b"credential", response.content)
        for connection in connections:
            self.assertEqual(set(connection), {"provider", "connected_at", "last_sync_at"})
            self.assertIsNone(connection["last_sync_at"])

    def test_listing_is_empty_before_anything_is_connected(self):
        self.assertEqual(self.get().json(), {"connections": []})

    def test_one_session_cannot_see_anothers_connections(self):
        self.connect_canvas(session_id=OTHER_SESSION)

        self.assertEqual(self.get().json(), {"connections": []})

    # --- Disconnecting --------------------------------------------------------

    def test_disconnecting_deletes_the_connection(self):
        self.connect_canvas()

        response = self.delete("canvas")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(UserConnection.objects.filter(session_id=SESSION).exists())

    def test_disconnecting_something_unconnected_is_a_404(self):
        response = self.delete("canvas")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_one_session_cannot_disconnect_anothers_source(self):
        self.connect_canvas(session_id=OTHER_SESSION)

        response = self.delete("canvas")

        self.assertEqual(response.status_code, 404)
        self.assertTrue(
            UserConnection.objects.filter(session_id=OTHER_SESSION, provider="canvas").exists()
        )

    # --- Session scoping ------------------------------------------------------

    def test_every_route_needs_a_session_header(self):
        UserConnection.objects.create(
            session_id=SESSION, provider="canvas", encrypted_token="x"
        )

        for label, response in [
            ("GET", self.get(session_id=None)),
            ("POST", self.connect_canvas(session_id=None)),
            ("DELETE", self.delete("canvas", session_id=None)),
        ]:
            with self.subTest(method=label):
                self.assertEqual(response.status_code, 400)
                self.assertIn("X-Session-Id", response.json()["error"]["message"])


def _session_header(session_id: str | None) -> dict:
    return {} if session_id is None else {"headers": {"x-session-id": session_id}}


@override_settings(CONNECTOR_ENCRYPTION_KEY=_TEST_KEY)
class CredentialStorageTests(TestCase):
    """UserConnection's credential accessors, independent of the endpoint."""

    def setUp(self):
        crypto._fernet.cache_clear()
        self.addCleanup(crypto._fernet.cache_clear)

    def test_set_token_and_get_token_still_pair_up(self):
        # The signature apps/personal/tools.py already calls. It is a wrapper
        # over the dict storage now, which has to stay invisible from here.
        connection = UserConnection(session_id=SESSION, provider="canvas")
        connection.set_token(f"  {CANVAS_TOKEN}  ")

        self.assertEqual(connection.get_token(), CANVAS_TOKEN)
        self.assertEqual(connection.get_credential(), {"token": CANVAS_TOKEN})

    def test_a_multi_field_credential_survives_the_round_trip(self):
        connection = UserConnection(session_id=SESSION, provider="gradescope")
        credential = {"email": "student@andrew.cmu.edu", "password": PIAZZA_PASSWORD}
        connection.set_credential(credential)

        self.assertEqual(connection.get_credential(), credential)
        self.assertNotIn(PIAZZA_PASSWORD, connection.encrypted_token)
