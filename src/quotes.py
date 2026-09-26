"""Shared quote matching for the Analyst and the single-source check."""

from __future__ import annotations

import re


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def letters_only(text: str) -> str:
    """Drop punctuation so 'C.K.' and 'CK' compare as the same name."""
    return re.sub(r"[^a-z0-9\s]", "", normalize_text(text))


def quote_appears(quote: str, passage_text: str, title: str = "") -> bool:
    """The quote must appear in the passage body or its page title."""
    haystack = f"{title}\n{passage_text}"
    needle = normalize_text(quote)
    if needle and needle in normalize_text(haystack):
        return True
    loose_needle = letters_only(quote)
    return bool(loose_needle) and loose_needle in letters_only(haystack)
