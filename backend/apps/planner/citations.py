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
MARKER = re.compile(r"\[S(\d+)\]")


class CitationLedger:
    """Numbers citations as they arrive and keeps them in issue order."""

    def __init__(self) -> None:
        self._citations: list[dict[str, Any]] = []

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
                "title": str(item.get("title") or tool.name),
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
    """
    referenced: set[str] = set()

    def keep(match: re.Match[str]) -> str:
        marker_id = f"S{match.group(1)}"
        if marker_id in issued_ids:
            referenced.add(marker_id)
            return match.group(0)
        return ""

    cleaned = MARKER.sub(keep, answer)
    # Removing a marker can leave " ." or a double space behind it.
    cleaned = re.sub(r" +([.,;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)

    return cleaned.strip(), issued_ids - referenced
