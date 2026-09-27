"""One-shot baseline: one model call, no search, no fetch, no auditor."""

from __future__ import annotations

import argparse
import sys
import time

from pydantic import BaseModel, Field

from src.config import load_settings
from src.eval.questions import by_id
from src.llm import OpenRouterLLM
from src.trace import JsonlTracer

SYSTEM_PROMPT = """\
Answer the research question from your training knowledge.

Rules:
- Write a short factual answer.
- Add citation URLs if you are sure they exist. Do not invent quotes.
- If you do not know, say you cannot find it.
"""


class NaiveAnswer(BaseModel):
    """Single-call answer used only for the rejected shortcut experiment."""

    answer: str = Field(min_length=1)
    citations: list[str] = Field(default_factory=list)
    cannot_find: list[str] = Field(default_factory=list)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="One paid OpenRouter call with no tools. Compare to the loop."
    )
    parser.add_argument("--qid", default="Q01")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    item = by_id(args.qid)
    settings = load_settings()
    trace_path = settings.root / "logs" / f"{item.qid.lower()}-naive.jsonl"
    tracer = JsonlTracer(trace_path, reset=True)
    llm = OpenRouterLLM(settings, tracer)
    started = time.perf_counter()
    tracer.event("run_start", step="naive", qid=item.qid, question=item.question)
    try:
        result = llm.complete_structured(
            purpose="naive_answer",
            system_prompt=SYSTEM_PROMPT,
            user_prompt=(
                f"Question:\n{item.question}\n\n"
                f"Notes:\n" + "\n".join(f"- {note}" for note in item.notes)
            ),
            schema=NaiveAnswer,
        )
    except Exception as exc:
        tracer.event("run_end", ok=False, error=str(exc))
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1

    wall = time.perf_counter() - started
    tracer.event("naive_answer", **result.value.model_dump())
    tracer.event(
        "run_end",
        ok=True,
        wall_seconds=round(wall, 3),
        **result.cost.as_dict(),
    )
    print(result.value.answer)
    if result.value.citations:
        print("Citations:")
        for url in result.value.citations:
            print(f"- {url}")
    print(
        f"Tokens: {result.cost.total_tokens} | "
        f"${result.cost.cost_usd:.8f} / ₹{result.cost.cost_inr:.6f} | "
        f"{wall:.1f}s"
    )
    print(f"Trace: {trace_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
