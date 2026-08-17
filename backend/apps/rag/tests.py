"""The two things about apps.rag that were broken without ever raising.

Retrieval itself is not covered here — it needs a populated index and an
embeddings key. What is covered is the shape `campus_search` hands the planner,
and whether `load_seeds` runs at all.

Run with:
    docker compose exec backend python manage.py test apps.rag
"""

from __future__ import annotations

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from apps.rag.models import CrawlSeed
from apps.rag.seed_urls import SEEDS
from apps.rag.tools import campus_search

_ROW = {
    "text": "Drop deadline is the tenth week of the semester.",
    "url": "https://www.cmu.edu/hub/registrar/",
    "title": "Registrar — deadlines",
    "indexed_at": "2026-08-01T00:00:00+00:00",
    "snippet": "Drop deadline is the tenth week of the semester.",
}


class CampusSearchToolTests(SimpleTestCase):
    def test_hits_are_wrapped_so_the_ledger_can_see_them(self) -> None:
        # A bare list fails CitationLedger.record's isinstance check, so every
        # RAG hit used to reach the model uncited.
        with mock.patch("apps.rag.search.campus_search", return_value=[_ROW]):
            result = campus_search(query="drop deadline")

        self.assertEqual(result, {"citations": [_ROW]})

    def test_k_is_capped_before_it_reaches_the_index(self) -> None:
        with mock.patch("apps.rag.search.campus_search", return_value=[]) as search:
            campus_search(query="drop deadline", k=500)

        self.assertEqual(search.call_args.kwargs["k"], 20)


class EmbedRetryTests(SimpleTestCase):
    """A 429 that says "out of credits" is not a rate limit."""

    def _client(self, error):
        client = mock.MagicMock()
        client.embeddings.create.side_effect = error
        return mock.patch("openai.OpenAI", return_value=client), client

    def _rate_limit_error(self, code: str):
        from openai import RateLimitError

        return RateLimitError(
            f"Error code: 429 - {{'error': {{'code': '{code}'}}}}",
            response=mock.MagicMock(status_code=429, headers={}),
            body={"error": {"code": code}},
        )

    @override_settings(OPENAI_API_KEY="sk-test")
    def test_a_quota_failure_does_not_burn_fifteen_seconds_of_backoff(self) -> None:
        from apps.rag.embedder import embed_texts

        patcher, client = self._client(self._rate_limit_error("insufficient_quota"))
        with patcher, mock.patch("time.sleep") as slept:
            with self.assertRaises(Exception):
                embed_texts(["anything"])

        # `campus_search` embeds the query, so this backoff is paid mid-answer.
        self.assertEqual(client.embeddings.create.call_count, 1)
        slept.assert_not_called()

    @override_settings(OPENAI_API_KEY="sk-test")
    def test_a_real_rate_limit_is_still_retried(self) -> None:
        from apps.rag.embedder import embed_texts

        patcher, client = self._client(self._rate_limit_error("rate_limit_exceeded"))
        with patcher, mock.patch("time.sleep"):
            with self.assertRaises(Exception):
                embed_texts(["anything"])

        self.assertEqual(client.embeddings.create.call_count, 5)


class LoadSeedsCommandTests(TestCase):
    def test_the_command_runs_and_reports_once(self) -> None:
        # It was a SyntaxError that also sat inside the loop, so the module did
        # not import and the summary would have printed once per seed.
        out = StringIO()
        call_command("load_seeds", stdout=out)

        self.assertEqual(CrawlSeed.objects.count(), len(SEEDS))
        self.assertEqual(out.getvalue().count("Done."), 1)
        self.assertIn(f"{len(SEEDS)} new seeds added", out.getvalue())

    def test_running_it_twice_adds_nothing(self) -> None:
        call_command("load_seeds", stdout=StringIO())
        out = StringIO()
        call_command("load_seeds", stdout=out)

        self.assertEqual(CrawlSeed.objects.count(), len(SEEDS))
        self.assertIn("0 new seeds added", out.getvalue())
