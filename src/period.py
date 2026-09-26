"""Resolve relative dates in Python so the model does not guess the calendar."""

from __future__ import annotations

import re
from datetime import date, datetime

# Frozen evaluation date for this assignment unless `.env` overrides it.
DEFAULT_AS_OF_DATE = date(2026, 9, 26)
RELATIVE_YEARS = (
    (re.compile(r"\b(last|past|previous)\s+two\s+years\b"), 2),
    (re.compile(r"\b(last|past|previous)\s+three\s+years\b"), 3),
    (re.compile(r"\b(last|past|previous)\s+year\b"), 1),
)


def parse_as_of_date(value: str | None) -> date:
    """Read YYYY-MM-DD, or use the assignment's frozen as-of date."""
    if not value or not value.strip():
        return DEFAULT_AS_OF_DATE
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def shift_years(day: date, years: int) -> date:
    """Move a date back by whole years, with a 29 Feb fallback."""
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def resolve_time_period(time_period: str | None, as_of: date) -> str | None:
    """Turn phrases such as 'last two years' into an explicit date range."""
    if time_period is None:
        return None
    text = " ".join(time_period.split())
    if not text:
        return None
    lowered = text.casefold()
    for pattern, years in RELATIVE_YEARS:
        if pattern.search(lowered):
            start = shift_years(as_of, years)
            return f"{start.isoformat()} to {as_of.isoformat()}"
    return text


def split_entities(entities: list[str]) -> tuple[list[str], list[str]]:
    """Separate named subjects from category phrases the planner must not replace."""
    category_hints = (
        "retailers",
        "companies",
        "startups",
        "brands",
        "firms",
        "players",
        "lenders",
        "banks",
    )
    named: list[str] = []
    categories: list[str] = []
    for entity in entities:
        cleaned = entity.strip()
        if not cleaned:
            continue
        lowered = cleaned.casefold()
        if any(hint in lowered for hint in category_hints):
            categories.append(cleaned)
        else:
            named.append(cleaned)
    return named, categories
