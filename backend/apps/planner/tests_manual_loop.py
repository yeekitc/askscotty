"""Tests for the hand-written fallback loop in `manual_loop.py`.

Kept alongside the session-driver tests in `tests.py` only for as long as the
fallback is: a loop reachable by flipping `PLANNER_MANAGED_AGENTS` off is a loop
that has to keep working. Delete this file when `manual_loop.py` goes.

These drive a scripted *model*, which is what the fallback still talks to. The
brakes it used to read from settings are module constants now, so the tests that
trip them patch the module rather than overriding a setting.

    docker compose exec backend python manage.py test apps.planner
"""

from __future__ import annotations

import json
import logging
from unittest import mock

from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from apps.tools import registry
from apps.tools.registry import ToolError, register_tool
from django.test import TestCase, override_settings

from . import manual_loop
from .loop import drain
from .manual_loop import run_planner

EMPTY_SCHEMA = {"type": "object", "properties": {}, "required": []}

PLANNER_DEFAULTS = dict(
    PLANNER_MANAGED_AGENTS=False,
    PLANNER_CITATION_MARKERS=False,
)

# The fallback's own brakes, tightened so a test can reach them without
# scripting eight turns. The deadline stays at its default here — the one test
# that trips it patches it separately, and listing it would overwrite that.
MANUAL_BRAKES = dict(MAX_ITERATIONS=4, MAX_PAUSE_RESUMES=2)


def text(body: str) -> TextBlock:
    return TextBlock(type="text", text=body, citations=None)


def tool_use(name: str, block_id: str = "tu_1", **arguments) -> ToolUseBlock:
    return ToolUseBlock(type="tool_use", id=block_id, name=name, input=arguments)


def reply(*content, stop_reason: str = "end_turn") -> Message:
    return Message(
        id="msg_test",
        model="test",
        role="assistant",
        type="message",
        stop_reason=stop_reason,
        usage=Usage(input_tokens=1, output_tokens=1),
        content=list(content),
    )


class FakeModel:
    """Stands in for `stream_message`: scripted replies, recorded requests.

    Yields text chunks then the Message, the same shape the real one has. The
    last reply repeats, so a test that wants the loop to run into a cap does not
    have to script every turn.
    """

    def __init__(self, *replies: Message, stream_text: bool = False) -> None:
        self.replies = list(replies)
        self.stream_text = stream_text
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        message = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]

        if self.stream_text:
            for block in message.content:
                if block.type == "text":
                    # Two chunks, so a test can tell appending from replacing.
                    yield block.text[:4]
                    yield block.text[4:]

        yield message


class FakeToolsMixin:
    """Lets a test put a working tool in the registry for its own duration."""

    def setUp(self) -> None:
        super().setUp()
        self.tool_calls: list[tuple[str, dict]] = []
        self.behaviour: dict = {}

        # run_tool logs a full traceback per failed call, and several tests fail
        # tools deliberately.
        logging.disable(logging.ERROR)
        self.addCleanup(logging.disable, logging.NOTSET)

    def register(self, name: str, *, mode: str, is_mock: bool = False) -> None:
        def run(**arguments):
            self.tool_calls.append((name, arguments))
            return self.behaviour[name](arguments)

        register_tool(
            name=name,
            description=f"Test tool {name}.",
            json_schema=EMPTY_SCHEMA,
            mode=mode,
            is_mock=is_mock,
        )(run)
        # The registry has no unregister — in production it is populated once at
        # import time, so a test that adds to it has to take it back out.
        self.addCleanup(registry._TOOLS.pop, name, None)


@override_settings(**PLANNER_DEFAULTS)
class PlannerLoopTests(FakeToolsMixin, TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.register("fake_dining", mode="dining", is_mock=True)
        self.register("fake_events", mode="events")

    def run_planner(self, model: FakeModel, query: str = "where can I eat?", **kwargs):
        with mock.patch.object(manual_loop, "stream_message", model), _brakes():
            return list(run_planner(query, **kwargs))

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

        model = FakeModel(
            reply(tool_use("fake_dining", near="Wean"), stop_reason="tool_use"),
            reply(text("Rohr Café is open until 5pm.")),
        )
        payload = drain(iter(self.run_planner(model)))

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

    def test_events_report_each_lane_starting_and_finishing(self) -> None:
        self.behaviour["fake_dining"] = lambda args: {"open_now": []}

        model = FakeModel(
            reply(tool_use("fake_dining"), stop_reason="tool_use"),
            reply(text("Nothing is open.")),
        )
        events = self.run_planner(model)

        self.assertEqual(
            [event["type"] for event in events],
            ["mode_start", "mode_end", "done"],
        )
        self.assertEqual(events[0]["data"], {"mode": "dining", "tool": "fake_dining"})
        self.assertEqual(events[1]["data"]["ok"], True)

    def test_answer_text_is_forwarded_as_it_arrives(self) -> None:
        self.behaviour["fake_dining"] = lambda args: {"open_now": []}

        model = FakeModel(
            reply(text("Looking…"), tool_use("fake_dining"), stop_reason="tool_use"),
            reply(text("Rohr Café is open.")),
            stream_text=True,
        )
        events = self.run_planner(model)

        self.assertEqual(
            [event["type"] for event in events],
            # Preamble, the lane, then the answer. The app drops what came before
            # a mode_start, so the "Look"/"ing…" pair never reaches the reader.
            ["text_delta", "text_delta", "mode_start", "mode_end", "text_delta", "text_delta", "done"],
        )
        streamed = "".join(e["data"]["text"] for e in events if e["type"] == "text_delta")
        self.assertEqual(streamed, "Looking…Rohr Café is open.")
        self.assertEqual(events[-1]["data"]["answer"], "Rohr Café is open.")

    def test_parallel_results_go_back_in_one_user_message(self) -> None:
        self.behaviour["fake_dining"] = lambda args: {"open_now": ["Rohr"]}
        self.behaviour["fake_events"] = lambda args: {"events": ["AI Club"]}

        model = FakeModel(
            reply(
                tool_use("fake_dining", block_id="tu_a"),
                tool_use("fake_events", block_id="tu_b"),
                stop_reason="tool_use",
            ),
            reply(text("Rohr, then AI Club.")),
        )
        payload = drain(iter(self.run_planner(model)))

        # Splitting these across two user messages trains the model out of
        # making parallel calls at all.
        last_sent = model.calls[1]["messages"][-1]
        self.assertEqual(last_sent["role"], "user")
        self.assertEqual([block["type"] for block in last_sent["content"]], ["tool_result"] * 2)
        self.assertEqual(
            [block["tool_use_id"] for block in last_sent["content"]], ["tu_a", "tu_b"]
        )
        self.assertEqual(payload["modes_used"], ["dining", "events"])

    # --- Degrading ------------------------------------------------------------

    def test_a_failed_tool_becomes_an_error_result_and_a_note(self) -> None:
        def boom(args):
            raise ToolError("CMU Eats returned 503.")

        self.behaviour["fake_dining"] = boom

        model = FakeModel(
            reply(tool_use("fake_dining"), stop_reason="tool_use"),
            reply(text("I could not reach dining data, but Wean is central.")),
        )
        payload = drain(iter(self.run_planner(model)))

        result = model.calls[1]["messages"][-1]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("503", result["content"])

        # A lane that failed contributed nothing, so it claims no chip.
        self.assertEqual(payload["modes_used"], [])
        self.assertIn("fake_dining: CMU Eats returned 503.", payload["note"])
        self.assertIn("Wean is central", payload["answer"])

    def test_a_crashing_tool_does_not_take_the_answer_down(self) -> None:
        def boom(args):
            raise ValueError("bad fixture")

        self.behaviour["fake_dining"] = boom

        model = FakeModel(
            reply(tool_use("fake_dining"), stop_reason="tool_use"),
            reply(text("Here is what I have.")),
        )
        payload = drain(iter(self.run_planner(model)))

        self.assertIn("ValueError: bad fixture", payload["note"])
        self.assertEqual(payload["answer"], "Here is what I have.")

    def test_an_invented_tool_name_is_an_error_result(self) -> None:
        model = FakeModel(
            reply(tool_use("no_such_tool"), stop_reason="tool_use"),
            reply(text("Sorry, I cannot do that.")),
        )
        payload = drain(iter(self.run_planner(model)))

        result = model.calls[1]["messages"][-1]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertEqual(payload["modes_used"], [])

    def test_an_uncited_answer_says_so(self) -> None:
        payload = drain(iter(self.run_planner(FakeModel(reply(text("Probably Wean."))))))
        self.assertIn("No campus source", payload["note"])

    # --- The brakes -----------------------------------------------------------

    def test_the_deadline_forces_a_text_only_turn(self) -> None:
        self.behaviour["fake_dining"] = lambda args: {"open_now": []}

        model = FakeModel(reply(text("Going on what I have: Wean is central.")))
        with mock.patch.object(manual_loop, "DEADLINE_SECONDS", 0):
            payload = drain(iter(self.run_planner(model)))

        self.assertEqual(len(model.calls), 1)
        self.assertEqual(model.calls[0]["tool_choice"], {"type": "none"})
        self.assertIn("time ran out", payload["note"])
        self.assertIn("Wean is central", payload["answer"])

    def test_the_iteration_cap_ends_in_prose(self) -> None:
        self.behaviour["fake_dining"] = lambda args: {"open_now": []}

        model = FakeModel(reply(tool_use("fake_dining"), stop_reason="tool_use"))
        payload = drain(iter(self.run_planner(model)))

        # Four tool rounds, then one forced call that cannot use tools.
        self.assertEqual(len(model.calls), 5)
        self.assertEqual(model.calls[-1]["tool_choice"], {"type": "none"})
        self.assertNotIn("tool_choice", model.calls[0])
        self.assertIn("more lookups than expected", payload["note"])

    def test_pause_turn_is_resumed(self) -> None:
        model = FakeModel(
            reply(text("Searching…"), stop_reason="pause_turn"),
            reply(text("Found it.")),
        )
        payload = drain(iter(self.run_planner(model)))

        self.assertEqual(len(model.calls), 2)
        self.assertEqual(model.calls[1]["messages"][-1]["role"], "assistant")
        self.assertEqual(payload["answer"], "Found it.")

    def test_endless_pause_turns_are_capped(self) -> None:
        model = FakeModel(reply(text("Still searching…"), stop_reason="pause_turn"))
        payload = drain(iter(self.run_planner(model)))

        self.assertEqual(len(model.calls), 4)
        self.assertIn("cut off", payload["note"])

    # --- The request we send --------------------------------------------------

    def test_forbidden_sampling_parameters_are_never_sent(self) -> None:
        model = FakeModel(reply(text("Hi.")))
        self.run_planner(model)

        sent = model.calls[0]
        for forbidden in ("temperature", "top_p", "top_k", "thinking"):
            self.assertNotIn(forbidden, sent, f"{forbidden} is a 400 on this model")
        self.assertEqual(sent["output_config"], {"effort": "medium"})

    def test_the_system_prompt_carries_the_cache_breakpoint(self) -> None:
        model = FakeModel(reply(text("Hi.")))
        self.run_planner(model)

        system = model.calls[0]["system"]
        self.assertEqual(system[-1]["cache_control"], {"type": "ephemeral"})
        # Caching is a prefix match, so a timestamp here would invalidate it on
        # every request. It belongs in the user turn.
        self.assertNotIn("2026", system[-1]["text"])
        self.assertIn("Right now it is", model.calls[0]["messages"][-1]["content"])

    def test_history_is_reshaped_into_what_the_api_accepts(self) -> None:
        model = FakeModel(reply(text("Friday, then.")))
        history = [
            # Dropped: an assistant turn cannot come first.
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "9-unit ML electives?"},
            {"role": "assistant", "content": "Try 10-601."},
            # Merged into the turn above: roles have to alternate.
            {"role": "assistant", "content": "Or 10-701."},
            # Dropped: an empty text block is a 400.
            {"role": "user", "content": "   "},
        ]
        self.run_planner(model, history=history)

        sent = model.calls[0]["messages"]
        self.assertEqual([turn["role"] for turn in sent], ["user", "assistant", "user"])
        self.assertEqual(sent[1]["content"], "Try 10-601.\n\nOr 10-701.")

    def test_no_tools_means_no_tool_choice(self) -> None:
        # tool_choice without tools is a 400, and a session can legitimately have
        # no tools at all.
        for name in ("fake_dining", "fake_events"):
            registry._TOOLS.pop(name, None)

        model = FakeModel(reply(text("Hi.")))
        self.run_planner(model)

        self.assertNotIn("tools", model.calls[0])
        self.assertNotIn("tool_choice", model.calls[0])

    # --- Markers --------------------------------------------------------------

    def test_markers_are_stripped_while_the_app_cannot_render_them(self) -> None:
        self.behaviour["fake_dining"] = lambda args: {
            "citations": [{"title": "Rohr Café hours", "url": "https://example.edu"}]
        }
        model = FakeModel(
            reply(tool_use("fake_dining"), stop_reason="tool_use"),
            reply(text("Rohr closes at 5pm [S1].")),
        )
        payload = drain(iter(self.run_planner(model)))

        self.assertEqual(payload["answer"], "Rohr closes at 5pm.")
        self.assertEqual(payload["citations"][0]["id"], "S1")

    @override_settings(PLANNER_CITATION_MARKERS=True)
    def test_issued_markers_survive_and_invented_ones_do_not(self) -> None:
        self.behaviour["fake_dining"] = lambda args: {
            "citations": [{"title": "Rohr Café hours", "url": "https://example.edu"}]
        }
        model = FakeModel(
            reply(tool_use("fake_dining"), stop_reason="tool_use"),
            reply(text("Rohr closes at 5pm [S1], and Hunt at 2am [S7].")),
        )
        payload = drain(iter(self.run_planner(model)))

        self.assertEqual(payload["answer"], "Rohr closes at 5pm [S1], and Hunt at 2am.")



@override_settings(**PLANNER_DEFAULTS)
class AskEndpointTests(FakeToolsMixin, TestCase):
    """Both endpoints, over one scripted model, returning the same payload."""

    def setUp(self) -> None:
        super().setUp()
        self.register("fake_dining", mode="dining")
        self.behaviour["fake_dining"] = lambda args: {
            "open_now": ["Rohr Café"],
            "citations": [{"title": "Rohr Café hours", "url": "https://example.edu/rohr"}],
        }
        self.body = {"query": "what is open near Wean?", "session_id": "", "history": []}

    def script(self) -> FakeModel:
        return FakeModel(
            reply(tool_use("fake_dining"), stop_reason="tool_use"),
            reply(text("Rohr Café.")),
        )

    def post(self, path: str, model: FakeModel):
        with mock.patch.object(manual_loop, "stream_message", model), _brakes():
            return self.client.post(path, self.body, content_type="application/json")

    def stream(self, model: FakeModel) -> tuple:
        """POST to the streaming endpoint and read it to the end.

        The body has to be consumed inside the patch: a StreamingHttpResponse is
        lazy, so the planner does not run until something iterates the response.
        """
        with mock.patch.object(manual_loop, "stream_message", model), _brakes():
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

    def test_a_bad_request_is_still_a_validation_error(self) -> None:
        self.body = {"query": ""}
        response = self.client.post("/api/ask/stream/", self.body, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "validation_error")


def _brakes():
    """This loop's caps, tightened for the tests that need to reach them."""
    return mock.patch.multiple(manual_loop, **MANUAL_BRAKES)


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    frames = []
    for chunk in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines())
        frames.append((lines["event"], json.loads(lines["data"])))
    return frames
