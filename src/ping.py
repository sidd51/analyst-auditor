"""Step 2: make one tiny paid structured-output call."""

from __future__ import annotations

import sys

from src.config import load_settings
from src.llm import OpenRouterLLM
from src.models import PingResponse
from src.trace import JsonlTracer


def main() -> int:
    settings = load_settings()
    trace_path = settings.root / "logs" / "step2-ping.jsonl"
    tracer = JsonlTracer(trace_path, reset=True)
    llm = OpenRouterLLM(settings, tracer)

    tracer.event("run_start", step="step2_ping")
    try:
        result = llm.complete_structured(
            purpose="ping",
            system_prompt=(
                "You are a setup checker. Follow the supplied response schema "
                "exactly and keep the explanation brief."
            ),
            user_prompt="Reply with pong to confirm structured output works.",
            schema=PingResponse,
        )
    except Exception as exc:
        tracer.event("run_end", ok=False)
        print(f"FAIL: {type(exc).__name__}: {exc}")
        print(f"Trace: {trace_path}")
        return 1

    tracer.event("run_end", ok=True, total_cost=result.cost.as_dict())

    print("Structured response:")
    print(result.value.model_dump_json(indent=2))
    print(
        "Tokens: "
        f"{result.cost.input_tokens} input + "
        f"{result.cost.output_tokens} output = "
        f"{result.cost.total_tokens} total"
    )
    print(
        f"Estimated cost: ${result.cost.cost_usd:.8f} / "
        f"₹{result.cost.cost_inr:.6f}"
    )
    print(f"Trace: {trace_path}")
    print("Step 2 ping is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
