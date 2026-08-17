"""Tool results in, `Citation` dicts out.

The rule this file exists to enforce: **the model never writes a citation, it
only ever writes an id.** Tools return the source data, the ledger numbers it
`S1`, `S2`, … and `citation_defaults()` stamps `source` and `is_mock` from the
tool that produced it. So a mock tool cannot emit a citation that looks live and
the model cannot invent a source at all — PRD §9 by construction rather than by
prompt.
"""

from __future__ import annotations

import re
from typing import Any

from apps.tools.registry import Tool, citation_defaults

# What the model is asked to write, and the only thing it is trusted to write.
#
# Deliberately wider than the `[S1]` the prompt asks for. Told to cite several
# sources for one claim, the model writes what a person would — `[S25, S30-4]` —
# and a pattern that only matched the well-formed case left that on screen as a
# dead marker, which is the exact failure inline citations are supposed to
# prevent. So: anything that opens `[S<digit>` and contains nothing but ids,
# separators and digits. `[Section 3]` and `[See below]` do not match.
MARKER = re.compile(r"\[S\d[\d\s,S-]*\]")

# The ids inside one marker, however many it carries.
MARKER_ID = re.compile(r"S(\d+)")


def _one_line(text: Any) -> str:
    """Collapse whitespace. A crawled `<title>` arrives with newlines in it, and
    a citation card renders the title on one line whatever it contains."""
    return " ".join(str(text).split())


class CitationLedger:
    """Numbers citations as they arrive and keeps them in issue order."""

    def __init__(self) -> None:
        self._citations: list[dict[str, Any]] = []
        #: url -> the citation already issued for it, for the web path only. A
        #: search returns several results and the model may cite one across two
        #: calls, and `S3` has to mean one source everywhere it is referenced.
        #: Our own tools are deliberately exempt: every dispatch is a distinct
        #: call, so two results sharing a url are two real lookups.
        self._by_url: dict[str, dict[str, Any]] = {}

    def record(self, tool: Tool, result: Any) -> Any:
        """Harvest `result`'s citations, returning the result as the model sees it.

        The returned copy carries the ids we assigned, which is how the model
        learns that this fact is `S3`. A tool that returns no `citations` list
        passes through untouched — plenty of tools are pure lookups.
        """
        if not isinstance(result, dict):
            return result

        raw = result.get("citations")
        if not isinstance(raw, list):
            return result

        defaults = citation_defaults(tool)
        issued = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            citation = {
                "id": f"S{len(self._citations) + 1}",
                "title": _one_line(item.get("title") or tool.name),
                "url": str(item.get("url") or ""),
                "snippet": str(item.get("snippet") or ""),
                "indexed_at": item.get("indexed_at"),
                "verified_at": item.get("verified_at"),
                # A tool may give a friendlier label ("CMU Eats") than its own
                # name, but `is_mock` is never the tool's to claim.
                "source": str(item.get("source") or defaults["source"]),
                "is_mock": defaults["is_mock"],
            }
            self._citations.append(citation)
            issued.append(citation)

        return {**result, "citations": issued}

    def record_web(
        self,
        *,
        title: str,
        url: str,
        snippet: str,
        verified_at: Any,
        source: str,
    ) -> dict[str, Any]:
        """Like `record`, for a citation with no backing `Tool` (web_search/web_fetch).

        Anthropic runs those two, so there is no registry entry to take
        `citation_defaults` from. Both values it would have supplied are fixed
        here instead: nothing this path touches is a fixture, and `indexed_at`
        means "the date we crawled it", which does not apply to a page read
        seconds ago. `verified_at` is stamped by the caller — the API does not
        supply one.

        A url already cited returns its existing citation rather than a second
        id. Called with no url at all, it issues one anyway; that is the caller's
        judgement, not the ledger's.
        """
        seen = self._by_url.get(url) if url else None
        if seen is not None:
            return seen

        citation = {
            "id": f"S{len(self._citations) + 1}",
            "title": _one_line(title or url or source),
            "url": str(url or ""),
            "snippet": str(snippet or ""),
            "indexed_at": None,
            "verified_at": verified_at,
            "source": str(source),
            "is_mock": False,
        }
        self._citations.append(citation)
        if url:
            self._by_url[url] = citation
        return citation

    def cites(self, url: str) -> bool:
        """Whether the web path has already issued a citation for `url`."""
        return url in self._by_url

    @property
    def web_count(self) -> int:
        """How many citations `record_web` has issued."""
        return len(self._by_url)

    @property
    def citations(self) -> list[dict[str, Any]]:
        return list(self._citations)

    @property
    def issued_ids(self) -> set[str]:
        return {citation["id"] for citation in self._citations}

    @property
    def has_mock(self) -> bool:
        return any(citation["is_mock"] for citation in self._citations)


def validate_markers(answer: str, issued_ids: set[str]) -> tuple[str, set[str]]:
    """Strip markers we never issued; report which issued ids went uncited.

    One hallucinated `[S7]` renders as a dead marker in the app, so an id that
    was never handed out is removed rather than shown. Passing an empty
    `issued_ids` strips every marker, which is what the markers-off setting does.

    A marker carrying several ids is rewritten to the ones that survive, in the
    single-id form the app renders — `[S25, S30-4]` becomes `[S25]` if only S25
    was issued, and disappears entirely if neither was.
    """
    referenced: set[str] = set()

    def keep(match: re.Match[str]) -> str:
        kept = [
            marker_id
            for number in MARKER_ID.findall(match.group(0))
            if (marker_id := f"S{number}") in issued_ids
        ]
        referenced.update(kept)
        return "".join(f"[{marker_id}]" for marker_id in kept)

    cleaned = MARKER.sub(keep, answer)
    # Removing a marker can leave " ." or a double space behind it.
    cleaned = re.sub(r" +([.,;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)

    return cleaned.strip(), issued_ids - referenced
