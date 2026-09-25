"""Convert model token usage into a transparent USD and INR estimate."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from src.config import Settings


@dataclass(frozen=True)
class CostRecord:
    """Usage and estimated price for one model call."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    cost_inr: float

    def as_dict(self) -> dict[str, int | float]:
        """Return JSON-safe data for traces and final reports."""
        return asdict(self)


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    settings: Settings,
) -> CostRecord:
    """Calculate cost from the frozen rates stored in `.env`.

    We freeze rates before the final Q1–Q8 run so every question uses the same
    exchange rate and model prices. This makes the cost trend comparable.
    """
    input_usd = (
        input_tokens / 1_000_000
    ) * settings.input_usd_per_million
    output_usd = (
        output_tokens / 1_000_000
    ) * settings.output_usd_per_million
    cost_usd = input_usd + output_usd

    return CostRecord(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cost_usd=round(cost_usd, 8),
        cost_inr=round(cost_usd * settings.usd_inr_rate, 6),
    )
