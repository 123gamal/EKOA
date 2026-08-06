"""Text processing utilities."""

from __future__ import annotations

import re
import unicodedata


def sanitize_text(text: str) -> str:
    """Normalise Unicode, collapse whitespace, and strip the result.

    This is a lightweight pre-processing step suitable for text that will be
    chunked and embedded.  It does **not** remove HTML tags — use a dedicated
    library for that if needed.

    Args:
        text: Raw input string.

    Returns:
        Cleaned string with normalised whitespace.
    """
    # Normalise to NFC (composed form)
    text = unicodedata.normalize("NFC", text)
    # Replace any run of whitespace (including newlines) with a single space
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def truncate_text(text: str, max_length: int = 512, suffix: str = "…") -> str:
    """Truncate *text* to at most *max_length* characters.

    If the text is longer than *max_length*, it is cut at the last word
    boundary before the limit and *suffix* is appended.

    Args:
        text: Input string.
        max_length: Maximum character count (including suffix).
        suffix: String appended when truncation occurs.

    Returns:
        Truncated string.
    """
    if len(text) <= max_length:
        return text

    cutoff = max_length - len(suffix)
    if cutoff <= 0:
        return suffix[:max_length]

    truncated = text[:cutoff]
    # Try to break at a word boundary
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]

    return truncated + suffix


def count_tokens(text: str, *, encoding_name: str = "cl100k_base") -> int:
    """Estimate the number of tokens in *text*.

    If the ``tiktoken`` library is available the specified encoding is used for
    an accurate count.  Otherwise, a simple whitespace-split heuristic is
    applied (roughly 0.75× word count).

    Args:
        text: Input string.
        encoding_name: Tiktoken encoding name (default ``cl100k_base`` used by
            OpenAI models; ignored when tiktoken is not installed).

    Returns:
        Estimated token count (always ≥ 0).
    """
    try:
        import tiktoken  # type: ignore[import-untyped]

        enc = tiktoken.get_encoding(encoding_name)
        return len(enc.encode(text))
    except ImportError:
        # Fallback: rough heuristic — ~4 characters per token on average
        return max(len(text) // 4, 1) if text else 0
