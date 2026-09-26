"""Offline tests for the bounded research planner."""

from datetime import date

import pytest

from src.cost import CostRecord
from src.llm import StructuredResult
from src.models import (
    PlannedQuery,
    PlannerOutput,
    QuestionSpecification,
    SpecifiedQuestion,
)
from src.page_budget import page_policy_from_settings
from src.period import resolve_time_period, split_entities
from src.plan_research import finalize_plan, plan_research
from tests.test_config import valid_settings


class FakeLLM:
    """Return a prepared planner draft so tests never call OpenRouter."""

    def __init__(self, drafted: PlannerOutput) -> None:
        self.drafted = drafted
        self.user_prompt = ""
        self.calls = 0

    def complete_structured(self, **kwargs: object) -> StructuredResult:
        self.calls += 1
        self.user_prompt = str(kwargs.get("user_prompt") or "")
        return StructuredResult(
            value=self.drafted,
            cost=CostRecord(
                input_tokens=90,
                output_tokens=50,
                total_tokens=140,
                cost_usd=0.0002,
                cost_inr=0.02,
            ),
            generation_id="fake-plan",
        )


def titan_specified() -> SpecifiedQuestion:
    settings = valid_settings()
    return SpecifiedQuestion(
        question="Who is Titan Company's Managing Director in 2026?",
        notes=["Give the full name and effective appointment date."],
        specification=QuestionSpecification(
            entities=["Titan Company"],
            question_type="identity",
            required_fields=["full name", "effective appointment date"],
            time_period="2026",
            geography=None,
            required_count=1,
            ranking=False,
            comparison=False,
            exhaustive=False,
            constraints=[],
            not_found_rule=(
                "If the name or date is not stated in a source, mark that "
                "field as not_found."
            ),
        ),
        page_policy=page_policy_from_settings(settings),
        as_of_date="2026-09-26",
        resolved_time_period="2026",
    )


def query(text: str, target: str = "full name") -> PlannedQuery:
    return PlannedQuery(query=text, targets=[target], reason="Cover this field.")


def test_python_keeps_only_four_unique_queries() -> None:
    settings = valid_settings()
    drafted = PlannerOutput(
        queries=[
            query("Titan Company Managing Director 2026"),
            query("Titan Company Managing Director 2026"),
            query("Titan Company MD appointment January 2026", "effective appointment date"),
            query("Titan Company Limited regulatory filing MD 2026", "effective appointment date"),
            query("Titan Company Ajoy Chawla Managing Director"),
            query("Titan Company current MD name"),
            query("unused fifth unique query"),
        ]
    )

    plan = finalize_plan(titan_specified(), drafted, settings)

    assert [item.query for item in plan.queries] == [
        "Titan Company Managing Director 2026",
        "Titan Company MD appointment January 2026",
        "Titan Company Limited regulatory filing MD 2026",
        "Titan Company Ajoy Chawla Managing Director",
    ]
    assert plan.truncated is True
    assert plan.known_facts == []


def test_planner_skips_known_facts_in_the_prompt() -> None:
    settings = valid_settings()
    llm = FakeLLM(
        PlannerOutput(
            queries=[
                query(
                    "Titan Company Managing Director effective date January 2026",
                    "effective appointment date",
                )
            ]
        )
    )

    result = plan_research(
        titan_specified(),
        settings,
        llm,  # type: ignore[arg-type]
        known_facts=["Titan Company's MD is Ajoy Chawla"],
    )

    assert llm.calls == 1
    assert "Titan Company's MD is Ajoy Chawla" in llm.user_prompt
    assert "Known facts (do not research these)" in llm.user_prompt
    assert "Disputed fields (do not treat as known; search again): none yet" in (
        llm.user_prompt
    )
    assert result.value.known_facts == ["Titan Company's MD is Ajoy Chawla"]
    assert result.value.specified.page_policy.initial_pages == 5


def test_planner_prompt_uses_resolved_dates_and_forbids_guessed_names() -> None:
    settings = valid_settings()
    specified = SpecifiedQuestion(
        question=(
            "Which three Indian jewellery retailers opened the most new "
            "stores in the last two years?"
        ),
        notes=[],
        specification=QuestionSpecification(
            entities=["Indian jewellery retailers"],
            question_type="ranking",
            required_fields=["retailer name", "new-store count"],
            time_period="last two years",
            geography="India",
            required_count=3,
            ranking=True,
            comparison=False,
            exhaustive=False,
            constraints=[],
            not_found_rule="Mark missing ranks as not_found.",
        ),
        page_policy=page_policy_from_settings(settings),
        as_of_date="2026-09-26",
        resolved_time_period="2024-09-26 to 2026-09-26",
    )
    llm = FakeLLM(
        PlannerOutput(
            queries=[
                query(
                    "Indian jewellery retailers new store openings 2024 2025 2026",
                    "retailer name",
                )
            ]
        )
    )

    plan_research(specified, settings, llm)  # type: ignore[arg-type]

    assert "As-of date (supplied by Python): 2026-09-26" in llm.user_prompt
    assert "2024-09-26 to 2026-09-26" in llm.user_prompt
    assert "Named entities you may put in queries: none" in llm.user_prompt
    assert "Indian jewellery retailers" in llm.user_prompt


def test_last_two_years_resolves_from_the_as_of_date() -> None:
    assert resolve_time_period("last two years", date(2026, 9, 26)) == (
        "2024-09-26 to 2026-09-26"
    )
    named, categories = split_entities(
        ["Titan Company", "Indian jewellery retailers"]
    )
    assert named == ["Titan Company"]
    assert categories == ["Indian jewellery retailers"]


def test_empty_query_list_fails_closed() -> None:
    settings = valid_settings()
    drafted = PlannerOutput.model_construct(queries=[])

    with pytest.raises(ValueError, match="no usable search queries"):
        finalize_plan(titan_specified(), drafted, settings)
