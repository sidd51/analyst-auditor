"""Step 2: you run this. It spends a few tokens and prints rupees.

    python -m src.ping
"""

from __future__ import annotations

import sys

from src.config import load_settings
from src.llm import OpenRouterLLM
from src.trace import Tracer


def main() -> int:
    settings = load_settings()
    log_path = settings.root / "logs" / "step2-ping.jsonl"
    tracer = Tracer(log_path)
    llm = OpenRouterLLM(settings, tracer)

    payload, cost = llm.complete_json(
        [
            {
                "role": "system",
                "content": "Return a JSON object. No markdown.",
            },
            {
                "role": "user",
                "content": (
                    'Reply with JSON exactly of the form '
                    '{"ping":"pong","what_you_are":"a language model"}.'
                ),
            },
        ],
        purpose="step2_ping",
    )

    inr = cost.cost_inr(settings.usd_inr_rate)
    print("OpenRouter ping succeeded.")
    print(f"  model:              {cost.model}")
    print(f"  JSON:               {payload}")
    print(f"  prompt_tokens:      {cost.prompt_tokens}")
    print(f"  completion_tokens:  {cost.completion_tokens}")
    print(f"  total_tokens:       {cost.total_tokens}")
    print(f"  cost_usd:           {cost.cost_usd}")
    print(f"  usd_inr_rate:       {settings.usd_inr_rate}")
    print(f"  cost_inr:           {inr:.4f}")
    print(f"  trace:              {log_path}")
    print("Step 2 init is done. Tell me 'step 2 done' and paste these numbers (no keys).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
