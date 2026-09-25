"""Offline tests for Step 2 accounting and trace output."""

import json

from pydantic import SecretStr

from src.config import Settings
from src.cost import calculate_cost
from src.trace import JsonlTracer


def test_cost_uses_frozen_model_and_exchange_rates() -> None:
    settings = Settings(
        openrouter_api_key=SecretStr("sk-or-v1-test-key-long-enough"),
        openrouter_model="google/gemini-2.5-flash",
        usd_inr_rate=95.5,
        input_usd_per_million=0.30,
        output_usd_per_million=2.50,
        max_model_input_tokens=12_000,
        max_model_output_tokens=2_000,
    )

    cost = calculate_cost(1_000, 200, settings)

    assert cost.total_tokens == 1_200
    assert cost.cost_usd == 0.0008
    assert cost.cost_inr == 0.0764


def test_trace_keeps_events_as_separate_json_lines(tmp_path) -> None:
    trace_path = tmp_path / "run.jsonl"
    tracer = JsonlTracer(trace_path, reset=True)

    tracer.event("first", value=1)
    tracer.event("second", value=2)

    rows = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["event"] for row in rows] == ["first", "second"]
    assert rows[1]["value"] == 2
