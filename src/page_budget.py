"""Python-owned page limits. The model never chooses how many pages to fetch."""

from src.config import Settings
from src.models import PagePolicy


def page_policy_from_settings(settings: Settings) -> PagePolicy:
    """Attach the same fetch policy to every question, regardless of type.

    We start small and add pages only if required fields are still missing.
    Ranking or exhaustive questions do not get a larger first wave.
    """
    return PagePolicy(
        initial_pages=settings.initial_page_budget,
        wave_size=settings.page_wave_size,
        page_ceiling=settings.absolute_page_ceiling,
        stop_when="requirements_covered",
    )


def next_fetch_wave(pages_used: int, settings: Settings) -> int:
    """How many new pages the next wave may fetch.

    Wave 1 uses the initial budget (5). Later waves use `page_wave_size` (4)
    until the ceiling (15) is reached. Return 0 when no more pages are allowed.
    """
    if pages_used < 0:
        raise ValueError("pages_used cannot be negative")

    remaining = settings.absolute_page_ceiling - pages_used
    if remaining <= 0:
        return 0
    if pages_used == 0:
        return min(settings.initial_page_budget, remaining)
    return min(settings.page_wave_size, remaining)
