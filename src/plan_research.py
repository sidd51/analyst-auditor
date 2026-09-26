"""Step 4B: turn a question spec into a short, bounded search plan."""

from __future__ import annotations

import argparse
import sys

from src.config import Settings, load_settings
from src.llm import OpenRouterLLM, StructuredResult
from src.memory import EntityMemory
from src.models import PlannerOutput, ResearchPlan, SpecifiedQuestion
from src.period import split_entities
from src.specify import specify_question
from src.trace import JsonlTracer

# The planner only writes queries. It must not fetch pages or invent answers.
SYSTEM_PROMPT = """\
You write a short web-search plan for a research question.

Rules:
- Propose 2 to 4 focused search queries.
- Use the resolved time period and as-of date in every dated query.
- Do not convert "last two years" into older years than the resolved range.
- Tag every query with the required fields it is trying to cover.
- Prefer official, news, and regulatory wording over vague questions.
- Do not repeat the same query with tiny wording changes.
- Do not answer the question.
- Do not decide how many pages to fetch.
- If known facts are listed, do not search for those facts again.
- If a field is listed as disputed, do not treat either value as known.
  Search again for that field.
- Do not reuse rejected sentences as answers.
- Do not invent company, person, or product names.
- If the spec only has category entities, write discovery queries using that
  category. Name a specific company only if it already appears in the spec
  entities or in known facts.
"""


def finalize_plan(
    specified: SpecifiedQuestion,
    drafted: PlannerOutput,
    settings: Settings,
    *,
    known_facts: list[str] | None = None,
    disputed_notes: list[str] | None = None,
    rejected_notes: list[str] | None = None,
) -> ResearchPlan:
    """Deduplicate queries and keep only the first `max_planner_queries`."""
    seen: set[str] = set()
    kept = []
    for item in drafted.queries:
        query = " ".join(item.query.split())
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        kept.append(item.model_copy(update={"query": query}))

    if not kept:
        raise ValueError("planner returned no usable search queries")

    limit = settings.max_planner_queries
    return ResearchPlan(
        specified=specified,
        queries=kept[:limit],
        known_facts=list(known_facts or []),
        disputed_notes=list(disputed_notes or []),
        rejected_notes=list(rejected_notes or []),
        truncated=len(kept) > limit,
    )


def plan_research(
    specified: SpecifiedQuestion,
    settings: Settings,
    llm: OpenRouterLLM,
    *,
    known_facts: list[str] | None = None,
    disputed_notes: list[str] | None = None,
    rejected_notes: list[str] | None = None,
) -> StructuredResult[ResearchPlan]:
    """Ask the model for queries, then cap and clean the list in Python."""
    facts = [fact.strip() for fact in (known_facts or []) if fact.strip()]
    disputed = [note.strip() for note in (disputed_notes or []) if note.strip()]
    rejected = [note.strip() for note in (rejected_notes or []) if note.strip()]
    spec = specified.specification
    named, categories = split_entities(spec.entities)
    user_prompt = (
        f"Question:\n{specified.question}\n\n"
        f"As-of date (supplied by Python): {specified.as_of_date}\n"
        f"Stated time period: {spec.time_period or 'not specified'}\n"
        f"Resolved time period (use this in queries): "
        f"{specified.resolved_time_period or 'not specified'}\n"
        f"Entities: {', '.join(spec.entities)}\n"
        f"Named entities you may put in queries: "
        f"{', '.join(named) or 'none'}\n"
        f"Category entities (do not replace these with guessed names): "
        f"{', '.join(categories) or 'none'}\n"
        f"Required fields: {', '.join(spec.required_fields)}\n"
        f"Geography: {spec.geography or 'not specified'}\n"
        f"Required count: {spec.required_count or 'not specified'}\n"
        f"Question type: {spec.question_type}\n"
        f"Ranking: {spec.ranking}\n"
        f"Comparison: {spec.comparison}\n"
        f"Exhaustive: {spec.exhaustive}\n"
        f"Constraints: {'; '.join(spec.constraints) or 'none'}\n"
        f"Not-found rule: {spec.not_found_rule}\n"
        f"Known facts (do not research these): "
        f"{'; '.join(facts) or 'none yet'}\n"
        f"Disputed fields (do not treat as known; search again): "
        f"{'; '.join(disputed) or 'none yet'}\n"
        f"Rejected claims (do not reuse these sentences): "
        f"{'; '.join(rejected) or 'none yet'}\n"
    )

    drafted = llm.complete_structured(
        purpose="plan_research",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=PlannerOutput,
    )
    plan = finalize_plan(
        specified,
        drafted.value,
        settings,
        known_facts=facts,
        disputed_notes=disputed,
        rejected_notes=rejected,
    )
    return StructuredResult(
        value=plan,
        cost=drafted.cost,
        generation_id=drafted.generation_id,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Specify a question, then plan 2-4 searches. "
            "This makes two paid model calls."
        )
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
    trace_path = settings.root / "logs" / "step4-plan.jsonl"
    tracer = JsonlTracer(trace_path, reset=True)
    llm = OpenRouterLLM(settings, tracer)

    tracer.event("run_start", step="step4b_plan", question=args.question)
    try:
        specified = specify_question(args.question, args.note, settings, llm)
        recalled = EntityMemory.load(settings).recall(
            specified.value,
            limit=settings.max_memory_prompt_items,
        )
        planned = plan_research(
            specified.value,
            settings,
            llm,
            known_facts=recalled.known_facts,
            disputed_notes=recalled.disputed_notes,
            rejected_notes=recalled.rejected_notes,
        )
    except Exception as exc:
        tracer.event("run_end", ok=False)
        print(f"FAIL: {type(exc).__name__}: {exc}")
        print(f"Trace: {trace_path}")
        return 1

    plan = planned.value
    tracer.event(
        "research_plan",
        queries=[item.model_dump() for item in plan.queries],
        truncated=plan.truncated,
        known_facts=plan.known_facts,
    )
    tracer.event(
        "run_end",
        ok=True,
        specify_cost=specified.cost.as_dict(),
        plan_cost=planned.cost.as_dict(),
    )

    print(plan.model_dump_json(indent=2))
    print(
        f"As-of date: {plan.specified.as_of_date} | "
        f"Resolved period: {plan.specified.resolved_time_period or 'none'}"
    )
    print(f"Queries kept: {len(plan.queries)} / {settings.max_planner_queries}")
    if plan.truncated:
        print("Planner returned extra queries; Python kept the first four.")
    print(
        "Specify tokens: "
        f"{specified.cost.total_tokens} | "
        f"Plan tokens: {planned.cost.total_tokens}"
    )
    print(
        "Estimated cost: "
        f"${specified.cost.cost_usd + planned.cost.cost_usd:.8f} / "
        f"₹{specified.cost.cost_inr + planned.cost.cost_inr:.6f}"
    )
    print(f"Trace: {trace_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
