"""Step 4A: turn a research question into explicit requirements."""

from __future__ import annotations

import argparse
import re
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
- If the question asks to name N companies or list N results, set
  required_count to N. Reuse the same field labels on each row
  (company name, figure, period). Those are parallel answers, not one
  field with two competing values.
- Interpret relative periods such as "last two years" against the as-of date
  supplied in the user message. Do not invent a different today.
- If a detail is not in the question or notes, leave it null or false.
- Write a not_found_rule that says when a field must be reported missing.
- Include chosen_figure_count and chosen_figure_reason ONLY when the
  question asks you to choose one number among two or more competing
  figures. Confirming a name, date, or title, or citing a page, is not
  a chosen-figure task.
- If the question asks which / highest / lowest / versus on a metric,
  this is a comparison, not a ranking. Required fields are the winner
  identity and the winning figure for each metric. Do not list every
  candidate's stats as required fields.
- If the question asks to name N results in rank order, that is a
  ranking. Keep parallel rows for all N. Do not collapse it to one winner.
- A brand field must be the brand token only (for example Finacle or Tanishq),
  not a job title or sentence.
- "Cite one page" is not a required field named citation. The later
  claims already carry URLs.
- Do not invent extra research tasks.
- Do not decide how many pages to fetch. Page limits are set in Python.
"""

_CHOSEN_FIELDS = {"chosen_figure_count", "chosen_figure_reason"}
_CHOOSE_ONE = re.compile(
    r"\b(?:choose (?:which|one|among)|working estimate|chosen figure)\b",
    re.I,
)
_NAME_N = re.compile(
    r"\b(?:name the|list the|in rank order|rank order|top\s+\d)\b",
    re.I,
)
_WHICH_WINS = re.compile(
    r"\b(?:highest|lowest|versus|\bvs\.?\b|compar(?:e|ed|ison)|"
    r"which (?:of|reported|had|has)|larger|smaller|faster)\b",
    re.I,
)


def _field_key(field: str) -> str:
    return field.strip().casefold().replace(" ", "_")


def is_chosen_figure_task(question: str, notes: list[str]) -> bool:
    """True only when the user asked to pick one number among competing figures."""
    return bool(_CHOOSE_ONE.search(" ".join([question, *notes])))


def is_name_n_ranking(question: str, notes: list[str] | None = None) -> bool:
    """True when the user asked to name or rank a list, not pick one winner."""
    return bool(_NAME_N.search(" ".join([question, *(notes or [])])))


def asks_which_wins(question: str, notes: list[str] | None = None) -> bool:
    """True for which/highest/versus questions that are not a top-N list."""
    if is_name_n_ranking(question, notes):
        return False
    return bool(_WHICH_WINS.search(" ".join([question, *(notes or [])])))


def apply_compare_rank_contract(
    specification: QuestionSpecification,
    question: str,
    notes: list[str],
) -> QuestionSpecification:
    """Python owns comparison vs ranking when the specifier underspecifies."""
    ranking = bool(
        specification.ranking
        or specification.question_type == "ranking"
        or is_name_n_ranking(question, notes)
    )
    comparison = (not ranking) and (
        specification.comparison
        or specification.question_type == "comparison"
        or asks_which_wins(question, notes)
    )
    update: dict[str, object] = {}
    if ranking and not specification.ranking:
        update["ranking"] = True
        if specification.question_type not in {"ranking"}:
            update["question_type"] = "ranking"
    if comparison and not specification.comparison:
        update["comparison"] = True
        if specification.question_type not in {"comparison", "ranking"}:
            update["question_type"] = "comparison"
    if update:
        specification = specification.model_copy(update=update)
    return rewrite_comparison_winner_fields(specification, question, notes)


def rewrite_comparison_winner_fields(
    specification: QuestionSpecification,
    question: str,
    notes: list[str],
) -> QuestionSpecification:
    """Comparison required fields are winners, not every candidate's stats."""
    if specification.ranking or is_name_n_ranking(question, notes):
        return specification
    if not (specification.comparison or asks_which_wins(question, notes)):
        return specification
    joined = " ".join(_field_key(field) for field in specification.required_fields)
    if any(token in joined for token in ("highest", "lowest", "winner", "larger")):
        return specification
    metrics: list[str] = []
    seen: set[str] = set()
    for field in specification.required_fields:
        key = _field_key(field)
        if key in {"company_name", "company", "name"} or key.endswith("_company"):
            continue
        if key in seen:
            continue
        seen.add(key)
        metrics.append(field.strip())
    if len(metrics) < 2:
        return specification
    winners: list[str] = []
    for metric in metrics[:2]:
        winners.append(f"highest {metric} company")
        winners.append(f"highest {metric}")
    return specification.model_copy(
        update={"required_fields": winners, "comparison": True}
    )


def drop_unrequested_chosen_fields(
    specification: QuestionSpecification,
    question: str,
    notes: list[str],
) -> QuestionSpecification:
    """Python owns this: the model must not invent chosen_figure_* on Q05/Q09."""
    if is_chosen_figure_task(question, notes):
        return specification
    kept = [
        field
        for field in specification.required_fields
        if _field_key(field) not in _CHOSEN_FIELDS
    ]
    if not kept or kept == specification.required_fields:
        return specification
    return specification.model_copy(update={"required_fields": kept})


_CITATION_FIELDS = {"citation", "cite", "source", "source_url", "cited_page"}


def drop_unrequested_citation_fields(
    specification: QuestionSpecification,
    question: str,
    notes: list[str],
) -> QuestionSpecification:
    """'Cite one page' is not its own required field."""
    text = " ".join([question, *notes]).casefold()
    if re.search(r"\bwhat (?:is|was) the (?:citation|source url|cited page)\b", text):
        return specification
    kept = [
        field
        for field in specification.required_fields
        if _field_key(field) not in _CITATION_FIELDS
    ]
    if not kept or kept == specification.required_fields:
        return specification
    return specification.model_copy(update={"required_fields": kept})


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
    specification = apply_compare_rank_contract(
        drop_unrequested_citation_fields(
            drop_unrequested_chosen_fields(
                extracted.value,
                cleaned_question,
                cleaned_notes,
            ),
            cleaned_question,
            cleaned_notes,
        ),
        cleaned_question,
        cleaned_notes,
    )
    specified = SpecifiedQuestion(
        question=cleaned_question,
        notes=cleaned_notes,
        specification=specification,
        # Always overwrite: even a ranking question starts with 5 pages.
        page_policy=page_policy_from_settings(settings),
        as_of_date=as_of,
        resolved_time_period=resolve_time_period(
            specification.time_period,
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
