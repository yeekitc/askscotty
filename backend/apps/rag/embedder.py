"""Embeddings via OpenAI text-embedding-3-small.

Only chunks missing an embedding are processed, so reruns are always safe.
"""

import logging
import time

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100  # well under OpenAI's 2048-input-per-call limit

# OpenAI answers "too fast" and "out of credits" with the same 429. Only the
# first is worth waiting out; the second cannot become true by trying again, and
# retrying it costs 15 seconds of backoff on the way to the same failure. That
# is paid inside a planner turn, because `campus_search` embeds the query.
_TERMINAL_429 = ("insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached")


def _is_terminal(error: Exception) -> bool:
    body = getattr(error, "body", None) or {}
    detail = body.get("error", body) if isinstance(body, dict) else {}
    code = str(detail.get("code") or detail.get("type") or "") if isinstance(detail, dict) else ""
    return code in _TERMINAL_429 or any(marker in str(error) for marker in _TERMINAL_429)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return one embedding vector per input text.

    Batches calls and retries with exponential backoff on rate-limit errors —
    but not on a quota failure, which no amount of waiting fixes.
    """
    from openai import OpenAI, RateLimitError

    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set — cannot embed.")

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    results: list[list[float]] = []

    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        for attempt in range(5):
            try:
                response = client.embeddings.create(
                    model=settings.EMBEDDING_MODEL,
                    input=batch,
                )
                results.extend(item.embedding for item in response.data)
                break
            except RateLimitError as exc:
                if attempt == 4 or _is_terminal(exc):
                    raise
                wait = 2**attempt
                logger.warning("embed rate-limited, retrying in %ds", wait)
                time.sleep(wait)

    return results


def embed_pending(*, force: bool = False, stdout=None) -> int:
    """Embed all chunks missing embeddings (or all chunks when force=True).

    Returns the number of chunks embedded.
    """
    from apps.rag.models import Chunk

    qs = Chunk.objects.all() if force else Chunk.objects.filter(embedding__isnull=True)
    total = qs.count()
    if total == 0:
        if stdout:
            stdout.write("No chunks to embed.")
        return 0

    if stdout:
        stdout.write(f"Embedding {total} chunks...")

    ids = list(qs.order_by("id").values_list("id", flat=True))
    embedded = 0

    for i in range(0, len(ids), _BATCH_SIZE):
        batch_ids = ids[i : i + _BATCH_SIZE]
        chunks = list(Chunk.objects.filter(id__in=batch_ids).order_by("id"))
        texts = [c.text for c in chunks]

        vectors = embed_texts(texts)
        now = timezone.now()

        for chunk, vector in zip(chunks, vectors):
            chunk.embedding = vector
            chunk.indexed_at = now

        Chunk.objects.bulk_update(chunks, ["embedding", "indexed_at"])
        embedded += len(chunks)

        if stdout:
            stdout.write(f"  {embedded}/{total}")

    return embedded
