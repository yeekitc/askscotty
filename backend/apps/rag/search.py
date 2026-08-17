"""Hybrid retrieval: vector similarity + Postgres full-text, fused with RRF.

Reciprocal Rank Fusion requires no weight tuning and is robust to the
differing score scales of the two retrieval methods.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_RRF_K = 60  # standard constant; controls the fusion curve shape


def campus_search(query: str, k: int = 6) -> list[dict]:
    """Search the campus index and return the top-k results.

    Each result: {text, url, title, indexed_at, snippet}.
    Falls back to full-text only if embedding fails (e.g. no API key).
    """
    from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
    from pgvector.django import CosineDistance

    from apps.rag.embedder import embed_texts
    from apps.rag.models import Chunk

    candidates = k * 5  # over-fetch before RRF re-ranking

    query_vector = None
    try:
        query_vector = embed_texts([query])[0]
    except Exception as exc:
        logger.warning("embed failed for campus_search, falling back to FTS only: %s", exc)

    vector_rows: list[dict] = []
    if query_vector is not None:
        vector_rows = list(
            Chunk.objects.filter(embedding__isnull=False)
            .order_by(CosineDistance("embedding", query_vector))[:candidates]
            .values("id", "text", "heading_path", "indexed_at", "document__url", "document__title")
        )

    fts_query = SearchQuery(query, config="english")
    fts_vector = SearchVector("text", config="english")
    fts_rows = list(
        Chunk.objects.annotate(rank=SearchRank(fts_vector, fts_query))
        .filter(rank__gt=0)
        .order_by("-rank")[:candidates]
        .values("id", "text", "heading_path", "indexed_at", "document__url", "document__title")
    )

    # Reciprocal Rank Fusion
    scores: dict[int, float] = {}
    for rank, row in enumerate(vector_rows, 1):
        scores[row["id"]] = scores.get(row["id"], 0.0) + 1.0 / (_RRF_K + rank)
    for rank, row in enumerate(fts_rows, 1):
        scores[row["id"]] = scores.get(row["id"], 0.0) + 1.0 / (_RRF_K + rank)

    all_rows = {row["id"]: row for row in vector_rows + fts_rows}
    top_ids = sorted(scores, key=lambda cid: -scores[cid])[:k]

    return _merge_by_document(all_rows[cid] for cid in top_ids)


def _merge_by_document(rows) -> list[dict]:
    """Chunk rows → one result per source page, best-ranked first.

    Several chunks of one page are several passages of one source, not several
    sources: a question about the registrar's rules matched five chunks of the
    same page and produced five identical-looking citations. They are joined
    instead, so the model keeps every passage and the reader sees one card.

    The whole text goes in `snippet`, not a preview: CitationLedger forwards
    `snippet` and drops `text`, so it is the only grounding content the model
    gets to answer from. The chunker already bounds each one (tasklist B1).
    """
    merged: dict[str, dict] = {}
    results: list[dict] = []

    for row in rows:
        url = row["document__url"]
        seen = merged.get(url)
        if seen is not None:
            seen["text"] += "\n\n" + row["text"]
            seen["snippet"] = seen["text"]
            continue

        indexed_at = row["indexed_at"]
        entry = {
            "text": row["text"],
            "url": url,
            "title": row["document__title"] or url,
            "indexed_at": indexed_at.isoformat() if indexed_at else None,
            "snippet": row["text"],
        }
        merged[url] = entry
        results.append(entry)

    return results
