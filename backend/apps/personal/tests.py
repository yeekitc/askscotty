"""Tests for the personal connectors (tasklist B5).

Both libraries are mocked at their network boundary and never reached for real:
they are unofficial clients, and an automated login from CI is exactly the
traffic a service rate-limits or flags.

What is *not* mocked is their data shapes — `Course` and `Assignment` are
imported from the installed package rather than hand-rolled, so a release that
renames a field fails here rather than in front of a student. That matters more
than usual for these two: the README described `get_courses()` as returning
lists of dicts when it returns dicts of dataclasses keyed by id, and the tools
are written against what the package actually does.

The password below is generated per run. Committing a real-looking credential,
or asserting against a literal one, is the one thing this file must not do
(docs/b5-piazza-gradescope.md) — so the credential assertions compare what the
library received against what decryption returned, never against a constant.

    docker compose exec backend python manage.py test apps.personal
"""

from __future__ import annotations

import datetime
import logging
import secrets
from contextlib import contextmanager
from unittest import mock

from apps.tools.registry import ToolError, run_tool
from cryptography.fernet import Fernet
from django.test import TestCase, override_settings
from gradescopeapi.classes.assignments import Assignment
from gradescopeapi.classes.courses import Course

from . import crypto
from .models import UserConnection

SESSION = "personal-session"
OTHER_SESSION = "someone-else"
EMAIL = "student@andrew.cmu.edu"

# Generated rather than written down, and never compared against a literal.
PASSWORD = secrets.token_urlsafe(24)

_TEST_KEY = Fernet.generate_key().decode()

_DUE = datetime.datetime(2026, 8, 20, 23, 59, tzinfo=datetime.timezone.utc)


def _course(name: str) -> Course:
    return Course(
        name=name,
        full_name=f"{name}: A Course",
        semester="Fall",
        year="2026",
        num_grades_published="0",
        num_assignments="2",
    )


def _assignment(name: str, assignment_id: str = "a1") -> Assignment:
    return Assignment(
        assignment_id=assignment_id,
        name=name,
        release_date=None,
        due_date=_DUE,
        late_due_date=None,
        submissions_status="No Submission",
        grade=None,
        max_grade="100.0",
    )


@override_settings(CONNECTOR_ENCRYPTION_KEY=_TEST_KEY)
class ConnectorTestCase(TestCase):
    """A session with `provider` connected, and the credential accessors live."""

    provider = ""

    def setUp(self):
        # _fernet() is lru_cached; the test runner also forces DEBUG=False, and
        # crypto refuses to derive a development key once it is. See the same
        # note in apps/core/tests.py.
        crypto._fernet.cache_clear()
        self.addCleanup(crypto._fernet.cache_clear)

        self.connection = UserConnection(session_id=SESSION, provider=self.provider)
        self.connection.set_credential({"email": EMAIL, "password": PASSWORD})
        self.connection.save()

    def assertCredentialAbsent(self, text: str):
        """Nothing a student sees or a log keeps may carry the credential."""
        self.assertNotIn(PASSWORD, text)
        self.assertNotIn(EMAIL, text)

    @contextmanager
    def assertNothingLoggedCarriesTheCredential(self):
        # "apps" rather than the root logger: settings.LOGGING gives it
        # `propagate: False`, so every application record stops there and a
        # capture on root sees nothing at all — including the ones being
        # checked for. This covers apps.personal.tools and the
        # logger.exception in apps.tools.registry.run_tool alike.
        with self.assertLogs("apps", level=logging.DEBUG) as captured:
            yield
            # assertLogs fails an empty capture, so guarantee one record.
            logging.getLogger("apps.personal.tests").debug("test finished")
        self.assertCredentialAbsent("\n".join(captured.output))


# --- Gradescope ---------------------------------------------------------------


class GradescopeTests(ConnectorTestCase):
    provider = "gradescope"

    @contextmanager
    def gradescope(self, *, courses=None, assignments=None, login_error=None):
        """Stand in for a logged-in Gradescope account.

        Patches the class where the library defines it, because the tool imports
        it inside the function — a module-level import would make the package a
        hard requirement of merely registering the tool.
        """
        account = mock.Mock()
        account.get_courses.return_value = (
            courses if courses is not None else {"student": {"111": _course("14-513")}}
        )
        lookup = assignments if assignments is not None else {"111": [_assignment("Lab 1")]}
        account.get_assignments.side_effect = lambda course_id: lookup[course_id]

        connection = mock.Mock()
        connection.account = account
        if login_error is not None:
            connection.login.side_effect = login_error

        with mock.patch(
            "gradescopeapi.classes.connection.GSConnection", return_value=connection
        ):
            yield connection

    def call(self, **arguments):
        return run_tool("gradescope_get_assignments", arguments, session_id=SESSION)

    def test_login_receives_the_decrypted_credential(self):
        with self.gradescope() as connection:
            self.call()

        stored = self.connection.get_credential()
        # Two runtime values, so the expected password is never a literal here.
        self.assertEqual(connection.login.call_args.args, (stored["email"], stored["password"]))

    def test_only_courses_the_student_takes_are_read(self):
        courses = {
            "student": {"111": _course("14-513")},
            "instructor": {"999": _course("15-122")},
        }
        with self.gradescope(
            courses=courses, assignments={"111": [_assignment("Lab 1")]}
        ) as connection:
            results = self.call()["results"]

        connection.account.get_assignments.assert_called_once_with("111")
        self.assertEqual({result["course_id"] for result in results}, {"111"})

    def test_an_assignment_carries_its_course_and_an_iso_due_date(self):
        with self.gradescope():
            results = self.call()["results"]

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Lab 1")
        self.assertEqual(results[0]["course"], "14-513: A Course")
        self.assertEqual(results[0]["due_date"], _DUE.isoformat())
        # Absent dates stay absent rather than becoming today.
        self.assertIsNone(results[0]["late_due_date"])

    def test_course_id_narrows_the_call(self):
        courses = {"student": {"111": _course("14-513"), "222": _course("15-213")}}
        assignments = {"111": [_assignment("Lab 1")], "222": [_assignment("Lab 2")]}

        with self.gradescope(courses=courses, assignments=assignments) as connection:
            results = self.call(course_id="222")

        connection.account.get_assignments.assert_called_once_with("222")
        self.assertEqual([result["name"] for result in results["results"]], ["Lab 2"])

    def test_an_unknown_course_id_is_a_tool_error(self):
        with self.gradescope(), self.assertRaises(ToolError):
            self.call(course_id="does-not-exist")

    def test_one_unreadable_course_does_not_lose_the_others(self):
        courses = {"student": {"111": _course("14-513"), "222": _course("15-213")}}
        account_error = RuntimeError("Gradescope returned 500")

        def get_assignments(course_id):
            if course_id == "111":
                raise account_error
            return [_assignment("Lab 2")]

        with self.gradescope(courses=courses) as connection:
            connection.account.get_assignments.side_effect = get_assignments
            results = self.call()["results"]

        self.assertEqual([result["name"] for result in results], ["Lab 2"])

    def test_an_assignment_missing_a_field_costs_only_its_own_course(self):
        # What a library upgrade that renames a dataclass field looks like from
        # here. It must not leave the tool as an unhandled AttributeError —
        # `_assignment` reads those fields directly, so the read has to sit
        # inside the same try as the fetch.
        courses = {"student": {"111": _course("14-513"), "222": _course("15-213")}}
        renamed = mock.Mock(spec=[])  # no attributes at all

        with self.gradescope(courses=courses) as connection:
            connection.account.get_assignments.side_effect = lambda cid: (
                [renamed] if cid == "111" else [_assignment("Lab 2")]
            )
            results = self.call()["results"]

        self.assertEqual([result["name"] for result in results], ["Lab 2"])

    def test_a_login_failure_becomes_a_tool_error(self):
        # What the installed library actually raises on a bad credential.
        with self.gradescope(login_error=ValueError("Invalid credentials.")):
            with self.assertRaises(ToolError) as caught:
                self.call()

        self.assertCredentialAbsent(str(caught.exception))
        # `from None`: run_tool logs a failure with logger.exception, which would
        # otherwise walk the chain into the library's own message.
        self.assertIsNone(caught.exception.__cause__)

    def test_a_failure_to_list_courses_becomes_a_tool_error(self):
        with self.gradescope() as connection:
            connection.account.get_courses.side_effect = RuntimeError("Failed to access")
            with self.assertRaises(ToolError) as caught:
                self.call()

        self.assertCredentialAbsent(str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_citations_invent_no_url_and_withhold_the_grade(self):
        with self.gradescope():
            payload = self.call()

        citation = payload["citations"][0]
        self.assertEqual(citation["url"], "")
        self.assertIsNone(citation["indexed_at"])
        self.assertIn("14-513", citation["snippet"])
        # The grade reaches the model through `results`; a citation card is the
        # part of an answer that gets screenshotted.
        self.assertNotIn("max_grade", citation["snippet"])

    def test_a_successful_call_stamps_the_sync_time(self):
        self.assertIsNone(self.connection.last_sync_at)

        with self.gradescope():
            self.call()

        self.connection.refresh_from_db()
        self.assertIsNotNone(self.connection.last_sync_at)

    def test_nothing_logged_by_a_failing_call_carries_the_credential(self):
        with self.assertNothingLoggedCarriesTheCredential():
            with self.gradescope(login_error=ValueError("Invalid credentials.")):
                with self.assertRaises(ToolError):
                    self.call()


# --- Piazza -------------------------------------------------------------------


class PiazzaTests(ConnectorTestCase):
    provider = "piazza"

    CLASSES = [
        {"nid": "n1", "name": "Algorithms", "num": "15-451", "term": "Fall 2026", "is_ta": False},
        {"nid": "n2", "name": "Systems", "num": "15-213", "term": "Fall 2026", "is_ta": False},
    ]

    @contextmanager
    def piazza(self, *, classes=None, feeds=None, login_error=None):
        """Stand in for a logged-in Piazza client.

        `feeds` maps network id to whatever `search_feed` should return, which is
        where the shapes this tool has to tolerate get exercised.
        """
        client = mock.Mock()
        client.get_user_classes.return_value = self.CLASSES if classes is None else classes
        if login_error is not None:
            client.user_login.side_effect = login_error

        lookup = feeds if feeds is not None else {}

        def network(network_id):
            handle = mock.Mock()
            handle.search_feed.side_effect = lambda query: lookup[network_id]
            return handle

        client.network.side_effect = network

        with mock.patch("piazza_api.Piazza", return_value=client):
            yield client

    def search(self, **arguments):
        return run_tool("piazza_search", arguments, session_id=SESSION)

    def list_classes(self):
        return run_tool("piazza_list_classes", {}, session_id=SESSION)

    @staticmethod
    def post(number: int, subject: str) -> dict:
        # `content_snipet` is Piazza's own spelling.
        return {
            "id": f"cid{number}",
            "nr": number,
            "subject": subject,
            "content_snipet": "the answer is in the handout",
            "type": "note",
            "created": "2026-08-01T00:00:00Z",
        }

    def test_login_is_non_interactive_and_uses_the_stored_credential(self):
        with self.piazza() as client:
            self.list_classes()

        stored = self.connection.get_credential()
        # Both keyword arguments, always: user_login() prompts on stdin for
        # whatever it is not given, and a web request cannot answer a prompt.
        self.assertEqual(
            client.user_login.call_args.kwargs,
            {"email": stored["email"], "password": stored["password"]},
        )

    def test_classes_are_renamed_onto_the_schema_the_tool_advertises(self):
        with self.piazza():
            results = self.list_classes()["results"]

        self.assertEqual(
            results[0],
            {
                "network_id": "n1",
                "name": "Algorithms",
                "course_number": "15-451",
                "term": "Fall 2026",
            },
        )

    def test_a_class_with_no_network_id_is_dropped(self):
        classes = [*self.CLASSES, {"name": "Broken", "num": "", "term": ""}]

        with self.piazza(classes=classes):
            results = self.list_classes()["results"]

        self.assertEqual([klass["network_id"] for klass in results], ["n1", "n2"])

    def test_search_covers_every_class_the_student_is_in(self):
        feeds = {"n1": [self.post(1, "Midterm")], "n2": [self.post(2, "Cache lab")]}

        with self.piazza(feeds=feeds):
            results = self.search(query="midterm")["results"]

        self.assertEqual({result["class"] for result in results}, {"Algorithms", "Systems"})

    def test_network_id_narrows_the_search(self):
        feeds = {"n1": [self.post(1, "Midterm")]}

        with self.piazza(feeds=feeds) as client:
            results = self.search(query="midterm", network_id="n1")["results"]

        client.network.assert_called_once_with("n1")
        self.assertEqual([result["subject"] for result in results], ["Midterm"])

    def test_a_network_the_student_is_not_in_is_a_tool_error(self):
        with self.piazza(), self.assertRaises(ToolError) as caught:
            self.search(query="midterm", network_id="not-mine")

        # Refused because it is not in *their* class list, which is what stops a
        # guessed network id reading someone else's class.
        self.assertIn("not-mine", str(caught.exception))

    def test_the_documented_feed_shapes_are_tolerated(self):
        # Phase 0 confirmed the call by reading the package, but the response
        # body needs a real class — so a shape we did not expect must degrade to
        # "no results", never raise.
        # Exact counts, not an upper bound: "at most one" would hold just as
        # well if the tool returned nothing for every shape, including the two
        # it is supposed to read.
        for label, payload, expected in [
            ("bare list", [self.post(1, "Midterm")], 1),
            ("wrapped in feed", {"feed": [self.post(1, "Midterm")]}, 1),
            ("empty", [], 0),
            ("null", None, 0),
            ("unexpected", "surprise", 0),
            ("dict without feed", {"posts": [self.post(1, "Midterm")]}, 0),
            ("list of junk", ["not-a-post", 7], 0),
        ]:
            with self.subTest(shape=label):
                with self.piazza(feeds={"n1": payload, "n2": []}):
                    results = self.search(query="midterm", network_id="n1")["results"]
                self.assertEqual(len(results), expected)

    def test_either_spelling_of_the_snippet_key_is_read(self):
        corrected = {**self.post(1, "Midterm")}
        del corrected["content_snipet"]
        corrected["content_snippet"] = "spelled the other way"

        with self.piazza(feeds={"n1": [corrected]}):
            results = self.search(query="midterm", network_id="n1")["results"]

        self.assertEqual(results[0]["snippet"], "spelled the other way")

    def test_posts_are_capped_per_class(self):
        many = [self.post(number, f"Post {number}") for number in range(50)]

        with self.piazza(feeds={"n1": many}):
            results = self.search(query="midterm", network_id="n1")["results"]

        self.assertEqual(len(results), 10)

    def test_one_unreadable_class_does_not_lose_the_others(self):
        def network(network_id):
            handle = mock.Mock()
            if network_id == "n1":
                handle.search_feed.side_effect = RuntimeError("Piazza said no")
            else:
                handle.search_feed.return_value = [self.post(2, "Cache lab")]
            return handle

        with self.piazza() as client:
            client.network.side_effect = network
            results = self.search(query="midterm")["results"]

        self.assertEqual([result["subject"] for result in results], ["Cache lab"])

    def test_a_login_failure_becomes_a_tool_error(self):
        from piazza_api.exceptions import AuthenticationError

        # The real thing puts the login page's HTML in this message, which is
        # exactly what must not travel onward.
        leaky = AuthenticationError(f"Could not authenticate.\nemail was {EMAIL}")

        with self.piazza(login_error=leaky):
            with self.assertRaises(ToolError) as caught:
                self.search(query="midterm")

        self.assertCredentialAbsent(str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_a_failure_to_list_classes_becomes_a_tool_error(self):
        with self.piazza() as client:
            client.get_user_classes.side_effect = RuntimeError("nope")
            with self.assertRaises(ToolError) as caught:
                self.list_classes()

        self.assertCredentialAbsent(str(caught.exception))

    def test_citations_link_to_the_class_and_not_a_guessed_post_anchor(self):
        with self.piazza(feeds={"n1": [self.post(1, "Midterm")]}):
            payload = self.search(query="midterm", network_id="n1")

        citation = payload["citations"][0]
        self.assertEqual(citation["url"], "https://piazza.com/class/n1")
        # `?cid=` is widely assumed and unverified — Phase 0's whole point.
        self.assertNotIn("cid", citation["url"])
        self.assertIsNone(citation["indexed_at"])

    def test_a_successful_search_stamps_the_sync_time(self):
        with self.piazza(feeds={"n1": [], "n2": []}):
            self.search(query="midterm")

        self.connection.refresh_from_db()
        self.assertIsNotNone(self.connection.last_sync_at)

    def test_nothing_logged_by_a_failing_call_carries_the_credential(self):
        from piazza_api.exceptions import AuthenticationError

        with self.assertNothingLoggedCarriesTheCredential():
            with self.piazza(login_error=AuthenticationError(f"page said {EMAIL}")):
                with self.assertRaises(ToolError):
                    self.search(query="midterm")


# --- Gating -------------------------------------------------------------------


@override_settings(CONNECTOR_ENCRYPTION_KEY=_TEST_KEY)
class ConnectorGatingTests(TestCase):
    """The half of PRD §7 that does not depend on either library."""

    PERSONAL_TOOLS = (
        ("piazza_search", {"query": "midterm"}),
        ("piazza_list_classes", {}),
        ("gradescope_get_assignments", {}),
    )

    def setUp(self):
        crypto._fernet.cache_clear()
        self.addCleanup(crypto._fernet.cache_clear)

    def test_a_credential_encrypted_with_another_key_is_a_tool_error(self):
        # The realistic version of this: CONNECTOR_ENCRYPTION_KEY is unset in
        # this repo, so crypto.py derives one from DJANGO_SECRET_KEY — and
        # rotating that leaves every stored credential unreadable.
        # DecryptionError is not a ToolError, so unguarded it reaches the
        # planner as a 500 instead of "reconnect this in settings".
        for provider, name, arguments in [
            ("piazza", "piazza_search", {"query": "midterm"}),
            ("gradescope", "gradescope_get_assignments", {}),
            ("canvas", "canvas_list_courses", {}),
        ]:
            with self.subTest(provider=provider):
                UserConnection.objects.filter(session_id=SESSION).delete()
                connection = UserConnection(session_id=SESSION, provider=provider)
                connection.set_credential({"email": EMAIL, "password": PASSWORD, "token": "t"})
                connection.save()

                with override_settings(CONNECTOR_ENCRYPTION_KEY=Fernet.generate_key().decode()):
                    crypto._fernet.cache_clear()
                    with self.assertRaises(ToolError) as caught:
                        run_tool(name, arguments, session_id=SESSION)

                self.assertIn("reconnect", str(caught.exception).lower())

    def test_an_unconnected_session_cannot_run_them(self):
        for name, arguments in self.PERSONAL_TOOLS:
            with self.subTest(tool=name):
                with self.assertRaises(ToolError):
                    run_tool(name, arguments, session_id=SESSION)

    def test_a_sessionless_request_cannot_run_them(self):
        for name, arguments in self.PERSONAL_TOOLS:
            with self.subTest(tool=name):
                with self.assertRaises(ToolError):
                    run_tool(name, arguments, session_id=None)

    def test_another_sessions_connection_does_not_unlock_them(self):
        connection = UserConnection(session_id=OTHER_SESSION, provider="piazza")
        connection.set_credential({"email": EMAIL, "password": PASSWORD})
        connection.save()

        with self.assertRaises(ToolError):
            run_tool("piazza_search", {"query": "midterm"}, session_id=SESSION)

    def test_they_are_hidden_from_the_toolset_until_connected(self):
        from apps.tools.registry import tools_for_session

        offered = {tool.name for tool in tools_for_session(SESSION)}
        for name, _ in self.PERSONAL_TOOLS:
            self.assertNotIn(name, offered)

        connection = UserConnection(session_id=SESSION, provider="piazza")
        connection.set_credential({"email": EMAIL, "password": PASSWORD})
        connection.save()

        offered = {tool.name for tool in tools_for_session(SESSION)}
        self.assertIn("piazza_search", offered)
        # Connecting one source does not offer another's tools.
        self.assertNotIn("gradescope_get_assignments", offered)
