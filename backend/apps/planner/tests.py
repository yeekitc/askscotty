"""Session-driver tests, run against a scripted event stream.

The scripted-*model* harness this replaces no longer applies: Anthropic drives
the loop, so what the planner actually consumes is a session's event stream. The
fake below scripts one, in rounds — and a round after the first only arrives once
the driver has answered the previous round's tool calls, which is the same
ordering a real session enforces. A driver that forgets to send a tool result
fails here instead of hanging in the demo.

The success path brings its own tool rather than driving a real one, because the
real ones reach live campus APIs and a suite must not. That is not a workaround:
the registry is the planner's only view of what exists, so a tool registered here
exercises exactly the code a real one will.

    docker compose exec backend python manage.py test apps.planner
"""

from __future__ import annotations

import json
import logging
import threading
from types import SimpleNamespace
from unittest import mock

from apps.core.models import Thread
from apps.personal.models import UserConnection
from apps.tools import registry
from apps.tools.registry import ToolError, register_tool
from django.test import TestCase, TransactionTestCase, override_settings

from . import client, loop
from .citations import validate_markers
from .errors import PlannerError

EMPTY_SCHEMA = {"type": "object", "properties": {}, "required": []}

PLANNER_DEFAULTS = dict(
    PLANNER_AGENT_ID="agent_test",
    PLANNER_ENVIRONMENT_ID="env_test",
    PLANNER_SESSION_BUDGET_CENTS=500,
    PLANNER_CITATION_MARKERS=False,
)


# --- Scripting a session ------------------------------------------------------


def agent_message(*bodies: str) -> SimpleNamespace:
    """The buffered text of one model turn — what the answer is built from.

    Takes several bodies because a real one arrives split at citation
    boundaries: quoted spans are their own blocks, and the sentence around them
    is in the blocks either side.
    """
    return SimpleNamespace(
        type="agent.message",
        id=_next_id(),
        content=[SimpleNamespace(type="text", text=body) for body in bodies],
    )


def text_delta(body: str) -> SimpleNamespace:
    """A live preview fragment. Stream-only, never replayed, has no id."""
    return SimpleNamespace(
        type="event_delta",
        event_id="preview",
        delta=SimpleNamespace(
            type="content_delta",
            index=0,
            content=SimpleNamespace(type="text", text=body),
        ),
    )


def custom_tool_use(name: str, event_id: str = "", **arguments) -> SimpleNamespace:
    """The session asking us to run one of our tools."""
    return SimpleNamespace(
        type="agent.custom_tool_use",
        id=event_id or _next_id(),
        name=name,
        input=arguments,
    )


def tool_use(name: str, event_id: str = "", **arguments) -> SimpleNamespace:
    """A built-in tool — Anthropic runs these, we only watch."""
    return SimpleNamespace(
        type="agent.tool_use", id=event_id or _next_id(), name=name, input=arguments
    )


def tool_result(tool_use_id: str, *content, is_error: bool = False) -> SimpleNamespace:
    """A built-in tool's result. `content` is the blocks it came back with.

    None rather than `[]` when there are none, matching the SDK: the field is
    optional on `BetaManagedAgentsAgentToolResultEvent`.
    """
    return SimpleNamespace(
        type="agent.tool_result",
        id=_next_id(),
        tool_use_id=tool_use_id,
        is_error=is_error,
        content=list(content) or None,
    )


# The three result-block shapes the web tools come back with. Field names are
# the SDK's, because the harvest in loop.py reads them by name.


def search_result(url: str, title: str, *texts: str) -> SimpleNamespace:
    """One web_search hit: the url is `source`, the snippet is in `content`."""
    return SimpleNamespace(
        type="search_result",
        source=url,
        title=title,
        content=[SimpleNamespace(type="text", text=text) for text in texts],
        citations=SimpleNamespace(enabled=True),
    )


def url_document(url: str, title: str = "") -> SimpleNamespace:
    """web_fetch's result when the block names the page it read."""
    return SimpleNamespace(
        type="document",
        source=SimpleNamespace(type="url", url=url),
        title=title,
        context=None,
    )


def text_document(text: str, title: str = "") -> SimpleNamespace:
    """web_fetch's result when the block carries only the page's text.

    There is no url anywhere on it, so a citation can only come from the one the
    matching `agent.tool_use` asked for.
    """
    return SimpleNamespace(
        type="document",
        source=SimpleNamespace(type="text", media_type="text/plain", data=text),
        title=title,
        context=None,
    )


def result_text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def idle(reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        type="session.status_idle", id=_next_id(), stop_reason=SimpleNamespace(type=reason)
    )


def waiting(*event_ids: str) -> SimpleNamespace:
    """Idle because the session wants a tool result from us. Not done."""
    event = idle("requires_action")
    event.stop_reason.event_ids = list(event_ids)
    return event


def terminated() -> SimpleNamespace:
    return SimpleNamespace(type="session.status_terminated", id=_next_id())


_ids = iter(range(1, 10_000))


def _next_id() -> str:
    return f"sevt_{next(_ids)}"


class FakeSession:
    """A scripted session: rounds of events, and every call we made to it."""

    def __init__(self, *rounds: list, session_id: str = "sesn_test") -> None:
        self.session_id = session_id
        self.rounds = [list(round_) for round_ in rounds]
        self.sent: list[list[dict]] = []
        self.created: list[dict] = []
        self.refreshed: list[str] = []
        #: Rounds to fail the stream after, once each, so a reconnect can be
        #: tested. A reopened stream resumes rather than replaying, like a real
        #: one — what happened during the gap is only in the event list.
        self.drop_after: set[int] = set()
        self.gap: list = []
        self.delivered = 0
        self.opened = 0

    # The three calls the driver makes, recorded and answered.

    def create_session(self, tools, *, title="", web=True):
        self.created.append({"tools": list(tools), "title": title, "web": web})
        return self.session_id

    def refresh_toolset(self, session_id, tools, *, web=True):
        self.refreshed.append(session_id)

    def send_events(self, session_id, events):
        self.sent.append(list(events))

    def events_since(self, session_id, since):
        # The gap a dropped stream left behind. Populated by the reconnect test.
        return list(self.gap)

    def stream_events(self, session_id):
        self.opened += 1
        return _FakeStream(self)

    @property
    def dispatches(self) -> list[list[dict]]:
        """Everything sent back after the opening user message."""
        return self.sent[1:]

    @property
    def question(self) -> str:
        return self.sent[0][0]["content"][0]["text"]


class _FakeStream:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __enter__(self) -> "_FakeStream":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def __iter__(self):
        session = self.session
        while session.delivered < len(session.rounds):
            index = session.delivered
            # The opening send is sent[0]; each round after the first needs its
            # predecessor's tool results answered before the session would say
            # anything more.
            if index and len(session.sent) <= index:
                raise AssertionError(
                    f"the driver started round {index} without answering round {index - 1}"
                )
            yield from session.rounds[index]
            session.delivered += 1
            if index in session.drop_after:
                session.drop_after.discard(index)
                raise PlannerError("stream dropped", status_code=502)


class PlannerHarness:
    """Wires a scripted session into the driver, and a working tool into the registry."""

    def setUp(self) -> None:
        super().setUp()
        self.tool_calls: list[tuple[str, dict]] = []
        self.behaviour: dict = {}

        # run_tool logs a full traceback per failed call, and several tests fail
        # tools deliberately.
        logging.disable(logging.ERROR)
        self.addCleanup(logging.disable, logging.NOTSET)

    def register(
        self,
        name: str,
        *,
        mode: str,
        is_mock: bool = False,
        requires_connector: str | None = None,
    ) -> None:
        def run(**arguments):
            self.tool_calls.append((name, arguments))
            return self.behaviour[name](arguments)

        register_tool(
            name=name,
            description=f"Test tool {name}.",
            json_schema=EMPTY_SCHEMA,
            mode=mode,
            is_mock=is_mock,
            requires_connector=requires_connector,
        )(run)
        # The registry has no unregister — in production it is populated once at
        # import time, so a test that adds to it has to take it back out.
        self.addCleanup(registry._TOOLS.pop, name, None)

    def drive(self, session: FakeSession, query: str = "where can I eat?", **kwargs) -> list[dict]:
        """Run the planner over a scripted session and collect its events."""
        with mock.patch.multiple(
            client,
            create_session=session.create_session,
            refresh_toolset=session.refresh_toolset,
            send_events=session.send_events,
            events_since=session.events_since,
            stream_events=session.stream_events,
        ):
            return list(loop.run_planner(query, **kwargs))

    def answer(self, session: FakeSession, **kwargs) -> dict:
        return loop.drain(iter(self.drive(session, **kwargs)))


class PlannerTestCase(PlannerHarness, TestCase):
    """The harness for tests that touch no personal data."""


class PlannerTransactionTestCase(PlannerHarness, TransactionTestCase):
    """The harness for tests whose tools read the database.

    `TestCase` wraps each test in a transaction that is rolled back at the end,
    and a row written inside it is invisible to any *other* connection — which
    is exactly what a tool dispatched into the pool gets. A connector written in
    the test would look unconnected to the tool that checks for it, and the
    assertion would fail for a reason that has nothing to do with the planner.

    `TransactionTestCase` commits instead, at the cost of truncating tables
    between tests. Slower, and only worth it for the handful of tests that need
    a real cross-thread read.
    """


@override_settings(**PLANNER_DEFAULTS)
class SessionDriverTests(PlannerTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.register("fake_dining", mode="dining", is_mock=True)
        self.register("fake_events", mode="events")

    # --- The success path -----------------------------------------------------

    def test_a_tool_runs_and_its_citation_is_harvested(self) -> None:
        self.behaviour["fake_dining"] = lambda args: {
            "open_now": ["Rohr Café"],
            "citations": [
                {
                    "title": "Rohr Café hours",
                    "url": "https://example.edu/rohr",
                    "snippet": "Open 08:00–17:00",
                    "verified_at": "2026-08-15T12:00:00Z",
                    "source": "CMU Eats",
                    # A tool cannot talk its way out of its own mock flag.
                    "is_mock": False,
                }
            ],
        }

        session = FakeSession(
            [custom_tool_use("fake_dining", near="Wean"), waiting()],
            [agent_message("Rohr Café is open until 5pm."), idle()],
        )
        payload = self.answer(session)

        self.assertEqual(self.tool_calls, [("fake_dining", {"near": "Wean"})])
        self.assertEqual(payload["answer"], "Rohr Café is open until 5pm.")
        self.assertEqual(payload["modes_used"], ["dining"])

        citation = payload["citations"][0]
        self.assertEqual(citation["id"], "S1")
        self.assertEqual(citation["title"], "Rohr Café hours")
        self.assertEqual(citation["snippet"], "Open 08:00–17:00")
        self.assertEqual(citation["source"], "CMU Eats")
        self.assertTrue(citation["is_mock"], "is_mock must come from the tool, not its result")
        self.assertIn("placeholder data", payload["note"])

    def test_a_crawled_title_is_flattened_onto_one_line(self) -> None:
        # A <title> lifted off a real page arrives with newlines and padding in
        # it, and a citation card is one line whatever it is handed.
        self.behaviour["fake_dining"] = lambda args: {
            "citations": [{"title": "Course Adds, Drops -\n      \n", "url": "https://x.edu"}]
        }
        session = FakeSession(
            [custom_tool_use("fake_dining"), waiting()],
            [agent_message("Week six."), idle()],
        )
        payload = self.answer(session)

        self.assertEqual(payload["citations"][0]["title"], "Course Adds, Drops -")

    def test_the_result_we_send_back_carries_the_ids_we_issued(self) -> None:
        self.behaviour["fake_dining"] = lambda args: {
            "citations": [{"title": "Rohr Café hours", "url": "https://example.edu"}]
        }

        session = FakeSession(
            [custom_tool_use("fake_dining", event_id="sevt_call"), waiting()],
            [agent_message("Open until 5pm."), idle()],
        )
        self.answer(session)

        result = session.dispatches[0][0]
        self.assertEqual(result["type"], "user.custom_tool_result")
        self.assertEqual(result["custom_tool_use_id"], "sevt_call")
        self.assertFalse(result["is_error"])
        # This is how the model learns the fact it just received is S1.
        sent_back = json.loads(result["content"][0]["text"])
        self.assertEqual(sent_back["citations"][0]["id"], "S1")

    def test_events_report_each_lane_starting_and_finishing(self) -> None:
        self.behaviour["fake_dining"] = lambda args: {"open_now": []}

        session = FakeSession(
            [custom_tool_use("fake_dining"), waiting()],
            [agent_message("Nothing is open."), idle()],
        )
        events = self.drive(session)

        self.assertEqual(
            [event["type"] for event in events], ["mode_start", "mode_end", "done"]
        )
        self.assertEqual(events[0]["data"], {"mode": "dining", "tool": "fake_dining"})
        self.assertEqual(events[1]["data"]["ok"], True)

    def test_answer_text_is_forwarded_as_it_arrives(self) -> None:
        self.behaviour["fake_dining"] = lambda args: {"open_now": []}

        session = FakeSession(
            [
                text_delta("Look"),
                text_delta("ing…"),
                agent_message("Looking…"),
                custom_tool_use("fake_dining"),
                waiting(),
            ],
            [text_delta("Rohr Café "), text_delta("is open."), agent_message("Rohr Café is open."), idle()],
        )
        events = self.drive(session)

        self.assertEqual(
            [event["type"] for event in events],
            # Preamble, the lane, then the answer. The app drops what came before
            # a mode_start, so the "Look"/"ing…" pair never reaches the reader.
            ["text_delta", "text_delta", "mode_start", "mode_end", "text_delta", "text_delta", "done"],
        )
        streamed = "".join(e["data"]["text"] for e in events if e["type"] == "text_delta")
        self.assertEqual(streamed, "Looking…Rohr Café is open.")
        # The preamble is narration, not answer: only the last turn's text is.
        self.assertEqual(events[-1]["data"]["answer"], "Rohr Café is open.")

    def test_a_parallel_batch_is_answered_in_one_send(self) -> None:
        self.behaviour["fake_dining"] = lambda args: {"open_now": ["Rohr"]}
        self.behaviour["fake_events"] = lambda args: {"events": ["AI Club"]}

        session = FakeSession(
            [
                custom_tool_use("fake_dining", event_id="sevt_a"),
                custom_tool_use("fake_events", event_id="sevt_b"),
                waiting(),
            ],
            [agent_message("Rohr, then AI Club."), idle()],
        )
        payload = self.answer(session)

        self.assertEqual(len(session.dispatches), 1, "one idle, one send")
        self.assertEqual(
            [result["custom_tool_use_id"] for result in session.dispatches[0]],
            ["sevt_a", "sevt_b"],
        )
        self.assertEqual(payload["modes_used"], ["dining", "events"])

    def test_a_batch_runs_in_parallel_rather_than_one_after_another(self) -> None:
        """The platform batches the model's requests; we still run the tools.

        Executing them in sequence would cost the sum of a batch rather than its
        slowest member — the whole reason a four-hop answer is worth batching.
        """
        started = threading.Barrier(2, timeout=5)

        def blocks_until_both_have_started(args):
            # Deadlocks and trips the timeout if the two calls are serialised,
            # so this fails loudly rather than merely running slowly.
            started.wait()
            return {"ok": True}

        self.behaviour["fake_dining"] = blocks_until_both_have_started
        self.behaviour["fake_events"] = blocks_until_both_have_started

        session = FakeSession(
            [custom_tool_use("fake_dining"), custom_tool_use("fake_events"), waiting()],
            [agent_message("Both."), idle()],
        )
        payload = self.answer(session)

        self.assertEqual(payload["modes_used"], ["dining", "events"])

    def test_citation_ids_follow_call_order_not_completion_order(self) -> None:
        """`S1` has to mean the same source every run.

        Tools finish in whatever order the network allows, so harvesting as they
        complete would shuffle the ids between runs — and a marker is only
        useful if it is stable.
        """
        finish_dining_last = threading.Event()

        def slow(args):
            finish_dining_last.wait(timeout=5)
            return {"citations": [{"title": "Dining, asked for first"}]}

        def quick(args):
            finish_dining_last.set()
            return {"citations": [{"title": "Events, asked for second"}]}

        self.behaviour["fake_dining"] = slow
        self.behaviour["fake_events"] = quick

        session = FakeSession(
            [custom_tool_use("fake_dining"), custom_tool_use("fake_events"), waiting()],
            [agent_message("Both."), idle()],
        )
        citations = self.answer(session)["citations"]

        self.assertEqual(
            [(citation["id"], citation["title"]) for citation in citations],
            [("S1", "Dining, asked for first"), ("S2", "Events, asked for second")],
        )

    def test_an_idle_with_nothing_left_to_dispatch_is_not_the_end_of_the_turn(self) -> None:
        """Regression: this truncated every multi-hop answer to nothing.

        A session idles again while it works through results we already sent.
        Reading that as "the turn is over" ends the answer right after the last
        lookup — tools run, citations collect, and the reader gets the
        no-answer fallback.
        """
        self.behaviour["fake_dining"] = lambda args: {"open_now": ["Rohr"]}

        session = FakeSession(
            [custom_tool_use("fake_dining", event_id="sevt_call"), waiting("sevt_call")],
            # Idle again, naming the call we have already answered.
            [waiting("sevt_call"), agent_message("Rohr Café is open."), idle()],
        )
        payload = self.answer(session)

        self.assertEqual(payload["answer"], "Rohr Café is open.")
        self.assertEqual(len(session.dispatches), 1, "the call is answered once, not twice")

    def test_an_idle_waiting_on_something_we_cannot_answer_stops(self) -> None:
        # A permission prompt, say. We set no policy so it should not happen, but
        # stopping beats hanging until the app's timeout gives up.
        session = FakeSession([agent_message("Half an answer."), waiting("sevt_unknown")])
        self.assertEqual(self.answer(session)["answer"], "Half an answer.")

    def test_a_built_in_web_tool_earns_the_verify_chip(self) -> None:
        session = FakeSession(
            [
                tool_use("web_search", event_id="sevt_web"),
                tool_result("sevt_web"),
                agent_message("The office moved to Warner Hall."),
                idle(),
            ]
        )
        events = self.drive(session)
        payload = events[-1]["data"]

        # Anthropic runs these, so `run_tool` never sees them — the mode has to
        # come from the events instead.
        self.assertEqual(payload["modes_used"], ["web_verify"])
        self.assertEqual(events[0]["data"], {"mode": "web_verify", "tool": "web_search"})
        self.assertEqual(events[1]["data"], {"mode": "web_verify", "tool": "web_search", "ok": True})

    def test_a_web_search_result_becomes_a_citation(self) -> None:
        """The chip lit long before this did — a verified answer cited nothing."""
        session = FakeSession(
            [
                tool_use("web_search", event_id="sevt_web", query="CMU startup week"),
                tool_result(
                    "sevt_web",
                    search_result(
                        "https://www.cmu.edu/events/",
                        "CMU Events Calendar",
                        # Escaped and ragged, the way a real excerpt arrives.
                        "Startup   Week runs\nSeptember 14&#x2013;18.",
                    ),
                ),
                agent_message("Startup Week runs September 14–18."),
                idle(),
            ]
        )
        payload = self.answer(session)

        citation = payload["citations"][0]
        self.assertEqual(citation["id"], "S1")
        self.assertEqual(citation["url"], "https://www.cmu.edu/events/")
        self.assertEqual(citation["title"], "CMU Events Calendar")
        self.assertEqual(citation["snippet"], "Startup Week runs September 14–18.")
        # The producing tool's name, the same convention our own tools follow.
        self.assertEqual(citation["source"], "web_search")
        self.assertFalse(citation["is_mock"], "nothing on this path is a fixture")
        self.assertIsNone(citation["indexed_at"], "a live fetch was never crawled")
        self.assertTrue(citation["verified_at"], "stamped by us at harvest time")
        self.assertEqual(payload["modes_used"], ["web_verify"])
        self.assertIsNone(payload["note"], "a cited answer has nothing to flag")

    def test_the_same_url_cited_twice_is_one_citation(self) -> None:
        hub = "https://www.cmu.edu/hub/"
        session = FakeSession(
            [
                tool_use("web_search", event_id="sevt_a"),
                tool_result(
                    "sevt_a",
                    search_result(hub, "The HUB", "Open 8:30am–5pm."),
                    search_result("https://www.cmu.edu/sio/", "SIO", "Student Information Online."),
                ),
                tool_use("web_fetch", event_id="sevt_b", url=hub),
                tool_result("sevt_b", url_document(hub, "The HUB")),
                agent_message("The HUB is open until 5pm."),
                idle(),
            ]
        )
        citations = self.answer(session)["citations"]

        # S3 has to mean one source everywhere it is referenced.
        self.assertEqual([citation["id"] for citation in citations], ["S1", "S2"])
        self.assertEqual(
            [citation["url"] for citation in citations], [hub, "https://www.cmu.edu/sio/"]
        )

    def test_a_fetched_page_falls_back_to_the_url_it_was_asked_for(self) -> None:
        # A document block carrying only text has no url of its own, and a
        # citation nobody can open is barely a citation.
        session = FakeSession(
            [
                tool_use("web_fetch", event_id="sevt_web", url="https://www.cmu.edu/hub/"),
                tool_result("sevt_web", text_document("The HUB is open 8:30am to 5pm.", "The HUB")),
                agent_message("Open until 5pm."),
                idle(),
            ]
        )
        citation = self.answer(session)["citations"][0]

        self.assertEqual(citation["url"], "https://www.cmu.edu/hub/")
        self.assertEqual(citation["source"], "web_fetch")
        self.assertEqual(citation["snippet"], "The HUB is open 8:30am to 5pm.")

    def test_a_fetched_page_is_quoted_from_its_prose_not_its_metadata(self) -> None:
        """The head of a real page is CMS front matter and nav, not content.

        Verbatim from a live `web_fetch` of www.cmu.edu/news: 400 characters of
        Drupal `meta-` keys before anything a reader would recognise.
        """
        page = (
            "---\n"
            "canonical: https://www.cmu.edu/news\n"
            "meta-Generator: Drupal 10 (https://www.drupal.org)\n"
            "meta-og:site_name: News\n"
            "title: CMU - News - Carnegie Mellon University\n"
            "---\n"
            "[https://www.googletagmanager.com/ns.html?id=GTM-5Q36JQ]"
            "(https://www.googletagmanager.com/ns.html?id=GTM-5Q36JQ)\n"
            "\n"
            "[Skip to main content](#main)\n"
            "[CMU to Lead National Study of AI in Arts Education]"
            "(https://www.cmu.edu/news/stories/archives/2026/august/ai-arts)\n"
        )
        session = FakeSession(
            [
                tool_use("web_fetch", event_id="sevt_web", url="https://www.cmu.edu/news/"),
                tool_result("sevt_web", text_document(page, "CMU - News")),
                agent_message("The latest is a study of AI in arts education."),
                idle(),
            ]
        )
        citation = self.answer(session)["citations"][0]

        self.assertEqual(citation["snippet"], "CMU to Lead National Study of AI in Arts Education")

    def test_a_broad_search_is_capped_rather_than_returning_a_wall(self) -> None:
        """One live question came back with 96 citations before this.

        A search returns about ten results and the model searches several times,
        so the ceiling is what keeps the source list readable. Results arrive in
        the search's own relevance order, so the ones kept are the best ones.
        """
        session = FakeSession(
            [
                tool_use("web_search", event_id="sevt_web"),
                tool_result(
                    "sevt_web",
                    *[
                        search_result(f"https://example.edu/{index}", f"Result {index}", "…")
                        for index in range(30)
                    ],
                ),
                agent_message("Plenty of coverage."),
                idle(),
            ]
        )
        citations = self.answer(session)["citations"]

        self.assertEqual(len(citations), loop._MAX_WEB_CITATIONS)
        self.assertEqual(citations[0]["url"], "https://example.edu/0")

    def test_a_failed_web_search_is_a_note_rather_than_an_exception(self) -> None:
        session = FakeSession(
            [
                tool_use("web_search", event_id="sevt_web", query="anything"),
                tool_result("sevt_web", result_text("search is rate limited"), is_error=True),
                agent_message("I could not check the web just now."),
                idle(),
            ]
        )
        payload = self.answer(session)

        self.assertEqual(payload["citations"], [])
        # A lane that failed contributed nothing, so it claims no chip.
        self.assertEqual(payload["modes_used"], [])
        self.assertIn("web_search: search is rate limited", payload["note"])

    def test_a_web_tool_is_still_unreachable_through_the_registry(self) -> None:
        # Anthropic runs these. Harvesting their results does not make them ours.
        with self.assertRaises(ToolError):
            registry.run_tool("web_search", {"query": "anything"})

    def test_a_cited_answer_is_one_piece_of_prose_not_one_paragraph_per_block(self) -> None:
        """Regression: this shredded every web-verified answer on screen.

        The model splits its text at citation boundaries, so a quote is its own
        block and the sentence around it is in the blocks either side — with an
        empty or whitespace block wherever the split lands. Joining those with
        blank lines turned each quoted span into a free-standing paragraph and
        left stray empty ones between them.
        """
        session = FakeSession(
            [
                agent_message(
                    "Startup Week is a month out, not tomorrow. ",
                    "Join 2000+ founders, investors and researchers.",
                    " ",
                    "It runs September 14–18.",
                    "",
                    " So there is nothing on tomorrow.",
                ),
                idle(),
            ]
        )
        answer = self.answer(session)["answer"]

        self.assertEqual(
            answer,
            "Startup Week is a month out, not tomorrow. "
            "Join 2000+ founders, investors and researchers. "
            "It runs September 14–18. So there is nothing on tomorrow.",
        )
        self.assertNotIn("\n", answer)

    def test_a_terminated_session_still_produces_the_answer(self) -> None:
        session = FakeSession([agent_message("Wean is central."), terminated()])
        self.assertEqual(self.answer(session)["answer"], "Wean is central.")

    # --- Degrading ------------------------------------------------------------

    def test_a_failed_tool_becomes_an_error_result_and_a_note(self) -> None:
        def boom(args):
            raise ToolError("CMU Eats returned 503.")

        self.behaviour["fake_dining"] = boom

        session = FakeSession(
            [custom_tool_use("fake_dining"), waiting()],
            [agent_message("I could not reach dining data, but Wean is central."), idle()],
        )
        payload = self.answer(session)

        result = session.dispatches[0][0]
        # A failure is a result, never a dropped block: an unanswered call leaves
        # the session idle for ever.
        self.assertTrue(result["is_error"])
        self.assertIn("503", result["content"][0]["text"])

        # A lane that failed contributed nothing, so it claims no chip.
        self.assertEqual(payload["modes_used"], [])
        self.assertIn("fake_dining: CMU Eats returned 503.", payload["note"])
        self.assertIn("Wean is central", payload["answer"])

    def test_a_crashing_tool_does_not_take_the_answer_down(self) -> None:
        def boom(args):
            raise ValueError("bad fixture")

        self.behaviour["fake_dining"] = boom

        session = FakeSession(
            [custom_tool_use("fake_dining"), waiting()],
            [agent_message("Here is what I have."), idle()],
        )
        payload = self.answer(session)

        self.assertIn("ValueError: bad fixture", payload["note"])
        self.assertEqual(payload["answer"], "Here is what I have.")

    def test_an_invented_tool_name_is_an_error_result(self) -> None:
        session = FakeSession(
            [custom_tool_use("no_such_tool"), waiting()],
            [agent_message("Sorry, I cannot do that."), idle()],
        )
        payload = self.answer(session)

        self.assertTrue(session.dispatches[0][0]["is_error"])
        self.assertEqual(payload["modes_used"], [])

    def test_an_uncited_answer_says_so(self) -> None:
        session = FakeSession([agent_message("Probably Wean."), idle()])
        self.assertIn("No campus source", self.answer(session)["note"])

    def test_a_lookup_that_found_nothing_still_counts_as_a_campus_source(self) -> None:
        """Nothing open at 4am is a live answer, not general knowledge.

        The tool ran, CMU Eats replied, and the reply was "none" — so there is
        nothing to cite and everything to stand behind.
        """
        self.behaviour["fake_dining"] = lambda args: {"results": [], "citations": []}

        session = FakeSession(
            [custom_tool_use("fake_dining", open_at="4:00am"), waiting()],
            [agent_message("Nothing is open at 4am."), idle()],
        )
        payload = self.answer(session)

        self.assertEqual(payload["citations"], [])
        self.assertEqual(payload["modes_used"], ["dining"])
        self.assertIsNone(payload["note"])

    def test_the_budget_is_the_runaway_bound_and_it_says_so(self) -> None:
        session = FakeSession([agent_message("Partial, sorry."), idle("budget_reached")])
        payload = self.answer(session)

        self.assertIn("lookup budget", payload["note"])
        self.assertEqual(payload["answer"], "Partial, sorry.")

    def test_a_session_error_is_not_by_itself_the_end(self) -> None:
        error = SimpleNamespace(
            type="session.error",
            id=_next_id(),
            error=SimpleNamespace(type="model_overloaded", message="overloaded"),
        )
        session = FakeSession([error, agent_message("Got there in the end."), idle()])

        self.assertEqual(self.answer(session)["answer"], "Got there in the end.")

    # --- Markers --------------------------------------------------------------

    def test_markers_are_stripped_while_the_app_cannot_render_them(self) -> None:
        self.behaviour["fake_dining"] = lambda args: {
            "citations": [{"title": "Rohr Café hours", "url": "https://example.edu"}]
        }
        session = FakeSession(
            [custom_tool_use("fake_dining"), waiting()],
            [agent_message("Rohr closes at 5pm [S1]."), idle()],
        )
        payload = self.answer(session)

        self.assertEqual(payload["answer"], "Rohr closes at 5pm.")
        self.assertEqual(payload["citations"][0]["id"], "S1")

    @override_settings(PLANNER_CITATION_MARKERS=True)
    def test_issued_markers_survive_and_invented_ones_do_not(self) -> None:
        self.behaviour["fake_dining"] = lambda args: {
            "citations": [{"title": "Rohr Café hours", "url": "https://example.edu"}]
        }
        session = FakeSession(
            [custom_tool_use("fake_dining"), waiting()],
            [agent_message("Rohr closes at 5pm [S1], and Hunt at 2am [S7]."), idle()],
        )
        payload = self.answer(session)

        # The agent is provisioned with the marker rules whatever the setting
        # says, so this branch is the runtime half — and the only reason turning
        # citations on is an env flip rather than a re-provision.
        self.assertEqual(payload["answer"], "Rohr closes at 5pm [S1], and Hunt at 2am.")


@override_settings(**PLANNER_DEFAULTS)
class SessionLifecycleTests(PlannerTestCase):
    """Which session a question runs in, and what that session is told."""

    def setUp(self) -> None:
        super().setUp()
        self.register("fake_dining", mode="dining")
        self.behaviour["fake_dining"] = lambda args: {"open_now": []}

    def test_the_stream_is_opened_before_anything_is_sent(self) -> None:
        session = FakeSession([agent_message("Hi."), idle()])

        opened_at_send: list[int] = []
        real_send = session.send_events
        session.send_events = lambda sid, events: (
            opened_at_send.append(session.opened),
            real_send(sid, events),
        )[1]

        self.drive(session)

        # The stream carries only what is emitted after it opens, and there is no
        # replay. Sending first races it and can lose the whole answer.
        self.assertEqual(opened_at_send, [1])

    def test_a_new_thread_gets_a_session_and_keeps_the_id(self) -> None:
        session = FakeSession([agent_message("Hi."), idle()], session_id="sesn_new")
        self.drive(session, session_id="anon-1", thread_id="thread-1")

        thread = Thread.objects.get(session_id="anon-1", client_id="thread-1")
        self.assertEqual(thread.cma_session_id, "sesn_new")
        self.assertEqual(len(session.created), 1)

    def test_a_follow_up_reuses_the_thread_session_and_does_not_repeat_history(self) -> None:
        Thread.objects.create(
            session_id="anon-1", client_id="thread-1", cma_session_id="sesn_existing"
        )
        session = FakeSession([agent_message("Still 5pm."), idle()])
        self.drive(
            session,
            query="is that still right?",
            session_id="anon-1",
            thread_id="thread-1",
            history=[{"role": "user", "content": "when does Rohr close?"}],
        )

        self.assertEqual(session.created, [], "a thread with a session must not open another")
        self.assertEqual(session.refreshed, ["sesn_existing"])
        # The session holds the conversation itself; replaying our copy into it
        # would say everything twice.
        self.assertNotIn("when does Rohr close?", session.question)

    def test_a_new_session_is_told_the_history_the_app_already_has(self) -> None:
        session = FakeSession([agent_message("Friday, then."), idle()])
        self.drive(
            session,
            query="what about Friday?",
            session_id="anon-1",
            thread_id="thread-1",
            history=[
                {"role": "user", "content": "9-unit ML electives?"},
                {"role": "assistant", "content": "Try 10-601."},
                # Dropped: an empty turn carries nothing.
                {"role": "user", "content": "   "},
            ],
        )

        question = session.question
        self.assertIn("9-unit ML electives?", question)
        self.assertIn("Try 10-601.", question)
        self.assertIn("what about Friday?", question)

    def test_a_stale_session_id_starts_a_new_one_rather_than_failing(self) -> None:
        Thread.objects.create(
            session_id="anon-1", client_id="thread-1", cma_session_id="sesn_deleted"
        )
        session = FakeSession([agent_message("Fresh start."), idle()], session_id="sesn_fresh")

        opens = iter([client.SessionGone("404"), None])

        def stream_events(session_id):
            problem = next(opens, None)
            if problem is not None:
                raise problem
            return session.stream_events(session_id)

        with mock.patch.multiple(
            client,
            create_session=session.create_session,
            refresh_toolset=session.refresh_toolset,
            send_events=session.send_events,
            events_since=session.events_since,
            stream_events=stream_events,
        ):
            events = list(
                loop.run_planner(
                    "hello", session_id="anon-1", thread_id="thread-1"
                )
            )

        self.assertEqual(events[-1]["data"]["answer"], "Fresh start.")
        thread = Thread.objects.get(session_id="anon-1", client_id="thread-1")
        self.assertEqual(thread.cma_session_id, "sesn_fresh")

    def test_no_thread_means_a_session_per_question(self) -> None:
        session = FakeSession([agent_message("Hi."), idle()])
        self.drive(session, session_id="anon-1")

        self.assertEqual(len(session.created), 1)
        self.assertFalse(Thread.objects.exists())

    def test_a_dropped_stream_recovers_the_tool_call_it_missed(self) -> None:
        preamble = agent_message("Let me check.")
        call = custom_tool_use("fake_dining", event_id="sevt_call")
        wait = waiting()

        session = FakeSession([preamble], [agent_message("Rohr Café."), idle()])
        # The connection dies just as the session asks for a tool. The stream has
        # no replay, so without the event list we would never learn about the
        # call — and the session would wait for a result for ever.
        session.drop_after = {0}
        session.gap = [preamble, call, wait]

        payload = self.answer(session)

        self.assertEqual(session.opened, 2, "the driver reconnected")
        # `preamble` is in the gap too, and it was already handled — deduping by
        # event id is what stops it running the lane twice.
        self.assertEqual(self.tool_calls, [("fake_dining", {})])
        self.assertEqual(len(session.dispatches), 1)
        self.assertEqual(payload["answer"], "Rohr Café.")

    def test_the_session_is_opened_with_this_request_s_toolset(self) -> None:
        session = FakeSession([agent_message("Hi."), idle()])
        self.drive(session)

        names = [tool.name for tool in session.created[0]["tools"]]
        self.assertIn("fake_dining", names)

        reference = client.agent_reference(session.created[0]["tools"])
        self.assertEqual(reference["type"], "agent_with_overrides")
        self.assertEqual(reference["id"], "agent_test")
        # Overrides replace in full, so the prebuilt toolset has to be listed
        # again or the web lane silently disappears.
        self.assertEqual(reference["tools"][0], client.AGENT_TOOLSET)
        # Everything else registered comes along too — the assertion is that the
        # request's own tool is offered, not that it is the only one.
        self.assertIn("fake_dining", [tool["name"] for tool in reference["tools"][1:]])
        self.assertTrue(all(tool["type"] == "custom" for tool in reference["tools"][1:]))

    @override_settings(PLANNER_AGENT_ID="")
    def test_an_unprovisioned_planner_fails_loudly_instead_of_provisioning(self) -> None:
        from .errors import PlannerError

        with self.assertRaises(PlannerError) as caught:
            client.agent_reference([])

        self.assertIn("provision_planner", str(caught.exception))


@override_settings(**PLANNER_DEFAULTS)
class PersonalToolGatingTests(PlannerTransactionTestCase):
    """A personal tool is offered — and runnable — only where it was connected."""

    def setUp(self) -> None:
        super().setUp()
        self.register("fake_canvas", mode="personal", requires_connector="canvas")
        self.behaviour["fake_canvas"] = lambda args: {"assignments": ["15-213 Lab 4"]}

    def test_a_session_without_the_connector_is_never_offered_the_tool(self) -> None:
        session = FakeSession([agent_message("I cannot see your Canvas."), idle()])
        self.drive(session, session_id="anon-1")

        names = [tool.name for tool in session.created[0]["tools"]]
        self.assertNotIn("fake_canvas", names)

    def test_naming_it_anyway_is_an_error_result_not_someone_else_s_data(self) -> None:
        session = FakeSession(
            [custom_tool_use("fake_canvas"), waiting()],
            [agent_message("I could not check Canvas."), idle()],
        )
        payload = self.answer(session, session_id="anon-1")

        # `run_tool` re-checks the connector on every dispatch, so a stale or
        # invented offer still cannot reach anyone's data.
        self.assertEqual(self.tool_calls, [])
        self.assertTrue(session.dispatches[0][0]["is_error"])
        self.assertEqual(payload["modes_used"], [])

    def test_a_connected_session_gets_the_tool_and_it_runs(self) -> None:
        # No token: what gates the tool is the connection existing, and storing
        # one would drag Fernet into a test about the registry.
        UserConnection.objects.create(session_id="anon-1", provider="canvas")

        session = FakeSession(
            [custom_tool_use("fake_canvas"), waiting()],
            [agent_message("Lab 4 is due Friday."), idle()],
        )
        payload = self.answer(session, session_id="anon-1")

        names = [tool.name for tool in session.created[0]["tools"]]
        self.assertIn("fake_canvas", names)
        self.assertEqual(payload["modes_used"], ["personal"])
        # The session reaches the tool from the request, never from the model:
        # it passes arguments, not whose data to read.
        self.assertEqual(self.tool_calls, [("fake_canvas", {"session_id": "anon-1"})])


@override_settings(**PLANNER_DEFAULTS)
class DisabledLaneTests(PlannerTestCase):
    """The app's source picker, honoured server-side.

    A lane the reader unchecked is applied by *not offering* its tools, the same
    mechanism that gates a personal tool — not by refusing them afterwards.
    """

    def setUp(self) -> None:
        super().setUp()
        self.register("fake_dining", mode="dining")
        self.register("fake_events", mode="events")
        self.behaviour["fake_dining"] = lambda args: {"open_now": []}
        self.behaviour["fake_events"] = lambda args: {"events": []}

    def test_an_unchecked_lane_is_never_offered(self) -> None:
        session = FakeSession([agent_message("Hi."), idle()])
        self.drive(session, disabled_modes=["dining"])

        names = [tool.name for tool in session.created[0]["tools"]]
        self.assertNotIn("fake_dining", names)
        self.assertIn("fake_events", names)

    def test_unchecking_web_verification_switches_off_the_built_in_pair(self) -> None:
        # Ours come off by being left out of the list. The prebuilt toolset is
        # one opaque entry, so its own per-tool config is the only way in.
        session = FakeSession([agent_message("Hi."), idle()])
        self.drive(session, disabled_modes=["web_verify"])

        self.assertFalse(session.created[0]["web"])
        prebuilt = client.toolset([], web=False)[0]
        self.assertEqual(
            prebuilt["configs"],
            [{"name": "web_fetch", "enabled": False}, {"name": "web_search", "enabled": False}],
        )

    def test_everything_is_on_when_nothing_is_unchecked(self) -> None:
        session = FakeSession([agent_message("Hi."), idle()])
        self.drive(session)

        names = [tool.name for tool in session.created[0]["tools"]]
        self.assertIn("fake_dining", names)
        self.assertTrue(session.created[0]["web"])

    def test_a_stale_session_asking_for_an_unchecked_tool_is_refused(self) -> None:
        # A thread's session outlives the turn, so one opened before the reader
        # unchecked dining is still holding the old offer.
        session = FakeSession(
            [custom_tool_use("fake_dining"), waiting()],
            [agent_message("I could not check dining."), idle()],
        )
        payload = self.answer(session, disabled_modes=["dining"])

        self.assertEqual(self.tool_calls, [], "it must not reach the tool at all")
        self.assertTrue(session.dispatches[0][0]["is_error"])
        self.assertEqual(payload["modes_used"], [])


@override_settings(**PLANNER_DEFAULTS)
class ProvisionedToolsetTests(PlannerTestCase):
    """What the *agent* declares, as opposed to what a session overrides."""

    def setUp(self) -> None:
        super().setUp()
        self.register("fake_dining", mode="dining")

    def test_the_agent_declares_the_prebuilt_toolset_and_nothing_of_ours(self) -> None:
        """Regression: declaring them made a new tool a re-provision.

        A session gets ours from the registry at request time, so putting them
        on the agent too buys nothing — nothing outside the request path can
        execute a custom tool anyway — and costs a second place for a tool
        definition to go stale.
        """
        from .management.commands.provision_planner import TOOLS

        self.assertEqual(TOOLS, [client.AGENT_TOOLSET])
        self.assertNotIn("fake_dining", [tool.get("name") for tool in TOOLS])



class MarkerValidationTests(TestCase):
    def test_only_issued_ids_are_kept(self) -> None:
        cleaned, uncited = validate_markers("A [S1] B [S3].", {"S1", "S2"})
        self.assertEqual(cleaned, "A [S1] B.")
        self.assertEqual(uncited, {"S2"})

    def test_an_empty_issue_set_strips_everything(self) -> None:
        cleaned, _ = validate_markers("Open until 5pm [S1][S2].", set())
        self.assertEqual(cleaned, "Open until 5pm.")

    def test_a_marker_carrying_several_ids_is_handled(self) -> None:
        """Regression: `[S25, S30-4]` reached the screen as a dead marker.

        Asked to cite two sources for one claim, the model writes what a person
        would rather than the `[S1]` the prompt asks for.
        """
        cleaned, _ = validate_markers("Startup Week runs in September [S25, S30-4].", set())
        self.assertEqual(cleaned, "Startup Week runs in September.")

        kept, uncited = validate_markers("Runs in September [S25, S30-4].", {"S25", "S9"})
        self.assertEqual(kept, "Runs in September [S25].")
        self.assertEqual(uncited, {"S9"})

    def test_bracketed_prose_is_left_alone(self) -> None:
        # The pattern is wide; it must not be wide enough to eat real text.
        for text in ("See [Section 3] for detail.", "Check [See below].", "Costs [S] nothing."):
            self.assertEqual(validate_markers(text, set())[0], text)


@override_settings(**PLANNER_DEFAULTS)
class AskEndpointTests(PlannerTestCase):
    """Both endpoints, over one scripted session, returning the same payload."""

    def setUp(self) -> None:
        super().setUp()
        self.register("fake_dining", mode="dining")
        self.behaviour["fake_dining"] = lambda args: {
            "open_now": ["Rohr Café"],
            "citations": [{"title": "Rohr Café hours", "url": "https://example.edu/rohr"}],
        }
        self.body = {"query": "what is open near Wean?", "session_id": "", "history": []}

    def script(self) -> FakeSession:
        return FakeSession(
            [custom_tool_use("fake_dining"), waiting()],
            [agent_message("Rohr Café."), idle()],
        )

    def patched(self, session: FakeSession):
        return mock.patch.multiple(
            client,
            create_session=session.create_session,
            refresh_toolset=session.refresh_toolset,
            send_events=session.send_events,
            events_since=session.events_since,
            stream_events=session.stream_events,
        )

    def post(self, path: str, session: FakeSession):
        with self.patched(session):
            return self.client.post(path, self.body, content_type="application/json")

    def stream(self, session: FakeSession) -> tuple:
        """POST to the streaming endpoint and read it to the end.

        The body has to be consumed inside the patch: a StreamingHttpResponse is
        lazy, so the planner does not run until something iterates the response.
        """
        with self.patched(session):
            response = self.client.post(
                "/api/ask/stream/", self.body, content_type="application/json"
            )
            body = b"".join(response.streaming_content).decode()
        return response, _parse_sse(body)

    def test_ask_returns_the_planner_answer(self) -> None:
        response = self.post("/api/ask/", self.script())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["answer"], "Rohr Café.")
        self.assertEqual(payload["modes_used"], ["dining"])
        self.assertEqual(payload["citations"][0]["id"], "S1")

    def test_stream_emits_mode_events_then_done(self) -> None:
        response, frames = self.stream(self.script())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        self.assertEqual([name for name, _ in frames], ["mode_start", "mode_end", "done"])
        self.assertEqual(frames[0][1]["mode"], "dining")
        self.assertEqual(frames[-1][1]["answer"], "Rohr Café.")

    def test_both_endpoints_return_the_identical_payload(self) -> None:
        plain = self.post("/api/ask/", self.script()).json()
        _, frames = self.stream(self.script())

        self.assertEqual(plain, frames[-1][1])

    def test_a_thread_id_is_optional(self) -> None:
        # The app may or may not send one; without it the answer is the same,
        # it just does not continue a conversation.
        self.body["thread_id"] = "thread-9"
        session = self.script()
        response = self.post("/api/ask/", session)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Thread.objects.exists(), "no session_id means no thread to key on")

    def test_a_bad_request_is_still_a_validation_error(self) -> None:
        self.body = {"query": ""}
        response = self.client.post("/api/ask/stream/", self.body, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "validation_error")


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    frames = []
    for chunk in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines())
        frames.append((lines["event"], json.loads(lines["data"])))
    return frames
