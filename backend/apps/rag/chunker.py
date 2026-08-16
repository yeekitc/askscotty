"""Heading-aware text chunker for the campus index.

Splits heading-segmented sections into token-bounded chunks with overlap.
Token count is approximated (words × 1.3) to avoid a tokenizer dependency.
"""

TARGET_TOKENS = 600
OVERLAP_TOKENS = 100
# Words × this ≈ tokens for English prose (GPT tokenizers average ~1.3 tokens/word).
_TOKENS_PER_WORD = 1.3


def _approx_tokens(text: str) -> int:
    return int(len(text.split()) * _TOKENS_PER_WORD)


def chunk_sections(sections: list[tuple[str, str]]) -> list[tuple[str, str, int]]:
    """Split heading-segmented sections into sized chunks with overlap.

    Args:
        sections: list of (heading_path, text) produced by the crawler.

    Returns:
        list of (chunk_text, heading_path, token_count).
    """
    target_words = int(TARGET_TOKENS / _TOKENS_PER_WORD)
    overlap_words = int(OVERLAP_TOKENS / _TOKENS_PER_WORD)
    chunks: list[tuple[str, str, int]] = []

    for heading_path, text in sections:
        words = text.split()
        if not words:
            continue

        if len(words) <= target_words:
            chunks.append((text, heading_path, _approx_tokens(text)))
            continue

        # Sliding window with overlap between consecutive chunks.
        start = 0
        while start < len(words):
            end = min(start + target_words, len(words))
            chunk_text = " ".join(words[start:end])
            chunks.append((chunk_text, heading_path, _approx_tokens(chunk_text)))
            if end >= len(words):
                break
            start = end - overlap_words

    return chunks
