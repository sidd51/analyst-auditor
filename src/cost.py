"""Turn one OpenRouter response into tokens + rupees.

OpenRouter puts `usage.cost` on every reply. That number is USD charged to the
account (1 credit = 1 USD). We multiply by the frozen USD_INR_RATE in .env so
the eight-question table is comparable even if FX moves later.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CostRecord:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    generation_id: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def cost_inr(self, usd_inr_rate: float) -> float:
        return self.cost_usd * usd_inr_rate

    def add(self, other: CostRecord) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.cost_usd += other.cost_usd


@dataclass
class CostAccumulator:
    """One of these per question. The eval harness will print Q1..Q8 from it."""

    usd_inr_rate: float
    items: list[CostRecord] = field(default_factory=list)

    def add(self, record: CostRecord) -> None:
        self.items.append(record)

    @property
    def total(self) -> CostRecord:
        out = CostRecord()
        for item in self.items:
            out.add(item)
        if self.items:
            out.model = self.items[-1].model
        return out

    def as_dict(self) -> dict:
        total = self.total
        return {
            "prompt_tokens": total.prompt_tokens,
            "completion_tokens": total.completion_tokens,
            "total_tokens": total.total_tokens,
            "cost_usd": round(total.cost_usd, 6),
            "cost_inr": round(total.cost_inr(self.usd_inr_rate), 4),
            "usd_inr_rate": self.usd_inr_rate,
            "calls": len(self.items),
        }
