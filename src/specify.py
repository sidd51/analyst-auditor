"""Step 4A: turn a research question into explicit requirements."""

from __future__ import annotations

import argparse
import sys

from src.config import Settings, load_settings
from src.llm import OpenRouterLLM, StructuredResult
from src.models import QuestionSpecification, SpecifiedQuestion
from src.page_budget import page_policy_from_settings
from src.period import resolve_time_period
from src.trace import JsonlTracer

# Keep this prompt about *what the question asks*, not how to research it.
# Page counts stay out of the schema so the model cannot inflate the budget.
SYSTEM_PROMPT = """\
You extract a research question into a strict specification.

Rules:
- Name the entities the answer must be about.
- List every required answer field as a short label a later checker can use.
- Capture time period, geography, requested count, ranking, comparison, and
  exhaustive-list wording when they are present.
- Interpret relative periods such as "last two years" against the as-of date
  supplied in the user message. Do not invent a different today.
- If a detail is not in the question or notes, leave it null or false.
- Write a not_found_rule that says when a field must be reported missing.
- If the question asks you to pick the latest figure, include both
  chosen_figure_count and chosen_figure_reason as required fields.
- A jewellery-brand or brand field must be the brand token only
  (for example Tanishq, Mia, or CaratLane), not a job title or sentence.
- Do not invent extra research tasks.
- Do not decide how many pages to fetch. Page limits are set in Python.
"""


def specify_question(
    question: str,
    notes: list[str],
    settings: Settings,
    llm: OpenRouterLLM,
) -> StructuredResult[SpecifiedQuestion]:
    """Call the model for the spec, then attach the wave page policy in Python."""
    cleaned_question = question.strip()
    cleaned_notes = [note.strip() for note in notes if note.strip()]
    if not cleaned_question:
        raise ValueError("question must not be empty")

    as_of = settings.as_of_date.isoformat()
    user_prompt = (
        f"As-of date (supplied by Python): {as_of}\n\n"
        f"Question:\n{cleaned_question}"
    )
    if cleaned_notes:
        user_prompt += "\n\nNotes:\n" + "\n".join(
            f"- {note}" for note in cleaned_notes
        )

    extracted = llm.complete_structured(
        purpose="specify_question",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=QuestionSpecification,
    )
    specified = SpecifiedQuestion(
        question=cleaned_question,
        notes=cleaned_notes,
        specification=extracted.value,
        # Always overwrite: even a ranking question starts with 5 pages.
        page_policy=page_policy_from_settings(settings),
        as_of_date=as_of,
        resolved_time_period=resolve_time_period(
            extracted.value.time_period,
            settings.as_of_date,
        ),
    )
    return StructuredResult(
        value=specified,
        cost=extracted.cost,
        generation_id=extracted.generation_id,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract question requirements. This makes one paid model call."
    )
    parser.add_argument("question")
    parser.add_argument(
        "--note",
        action="append",
        default=[],
        help="Repeat this option for extra required fields or constraints.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = load_settings()
    trace_path = settings.root / "logs" / "step4-specify.jsonl"
    tracer = JsonlTracer(trace_path, reset=True)
    llm = OpenRouterLLM(settings, tracer)

    tracer.event("run_start", step="step4a_specify", question=args.question)
    try:
        result = specify_question(args.question, args.note, settings, llm)
    except Exception as exc:
        tracer.event("run_end", ok=False)
        print(f"FAIL: {type(exc).__name__}: {exc}")
        print(f"Trace: {trace_path}")
        return 1

    specified = result.value
    tracer.event(
        "specified_question",
        specification=specified.specification.model_dump(),
        page_policy=specified.page_policy.model_dump(),
        as_of_date=specified.as_of_date,
        resolved_time_period=specified.resolved_time_period,
    )
    tracer.event("run_end", ok=True, total_cost=result.cost.as_dict())

    print(specified.model_dump_json(indent=2))
    print(
        "Page policy: "
        f"start {specified.page_policy.initial_pages}, "
        f"then +{specified.page_policy.wave_size} if fields are missing, "
        f"ceiling {specified.page_policy.page_ceiling}"
    )
    print(
        f"As-of date: {specified.as_of_date} | "
        f"Resolved period: {specified.resolved_time_period or 'none'}"
    )
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
