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
from src.plan_research import finalize_plan, plan_research, targets_are_known
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


def test_memory_skip_matches_md_status_to_known_md_fact() -> None:
    fact = (
        "Titan Company / full name (corroborated): Ajoy Chawla is the "
        "Managing Director of Titan Company Limited."
    )
    assert targets_are_known(
        ["md status"],
        ["full name"],
        known_facts=[fact],
    )
    assert targets_are_known(
        ["appointment_date"],
        ["effective appointment date"],
    )


def test_memory_skip_does_not_treat_predecessor_as_the_md_fact() -> None:
    fact = (
        "Titan Company / full name (corroborated): Ajoy Chawla is the "
        "Managing Director of Titan Company Limited."
    )
    assert (
        targets_are_known(
            ["predecessor_name"],
            ["full name", "effective appointment date"],
            known_facts=[fact],
        )
        is False
    )
    assert (
        targets_are_known(
            ["jewellery brand"],
            ["full name"],
            known_facts=[fact],
        )
        is False
    )


def test_finalize_plan_skips_known_md_query_and_keeps_brand() -> None:
    settings = valid_settings()
    drafted = PlannerOutput(
        queries=[
            query("Titan Company Managing Director 2026 verify", "md status"),
            query("Titan jewellery brand Tanishq", "jewellery brand"),
        ]
    )
    fact = (
        "Titan Company / full name (corroborated): Ajoy Chawla is the "
        "Managing Director of Titan Company Limited."
    )
    plan = finalize_plan(
        titan_specified(),
        drafted,
        settings,
        known_facts=[fact],
        covered_fields=["full name"],
    )
    assert [item.query for item in plan.queries] == [
        "Titan jewellery brand Tanishq"
    ]
    assert [item.query for item in plan.skipped_queries] == [
        "Titan Company Managing Director 2026 verify"
    ]


def test_cite_a_page_keeps_the_known_md_query() -> None:
    settings = valid_settings()
    specified = titan_specified().model_copy(
        update={
            "question": (
                "Is Ajoy Chawla still Titan Company's Managing Director "
                "in 2026? Cite one page."
            )
        }
    )
    drafted = PlannerOutput(
        queries=[
            query("Titan Company Managing Director 2026 verify", "md status"),
            query("Titan jewellery brand Tanishq", "jewellery brand"),
        ]
    )
    plan = finalize_plan(
        specified,
        drafted,
        settings,
        known_facts=[
            "Titan Company / full name (corroborated): Ajoy Chawla is MD."
        ],
        covered_fields=["full name"],
        keep_covered_queries=True,
    )
    assert [item.query for item in plan.queries] == [
        "Titan Company Managing Director 2026 verify",
        "Titan jewellery brand Tanishq",
    ]
    assert plan.skipped_queries == []


def test_required_fields_match_stored_md_aliases() -> None:
    from src.models import MemoryFact, MemoryRecall
    from src.plan_research import memory_verify_urls, required_fields_are_known

    specified = titan_specified().model_copy(
        update={
            "specification": titan_specified().specification.model_copy(
                update={
                    "required_fields": [
                        "managing_director_name",
                        "effective_appointment_date",
                        "citation",
                    ]
                }
            )
        }
    )
    recalled = MemoryRecall(
        facts=[
            MemoryFact(
                entity="Titan Company",
                field="full name",
                text="Ajoy Chawla is MD.",
                urls=["https://dess.digital/ajoy-chawla/"],
                as_of_date="2026-09-26",
            ),
            MemoryFact(
                entity="Titan Company",
                field="effective appointment date",
                text="1 January 2026",
                urls=["https://economictimes.indiatimes.com/titan"],
                as_of_date="2026-09-26",
            ),
        ],
        known_facts=["Titan Company / full name: Ajoy Chawla is MD."],
        known_fields=["full name", "effective appointment date"],
    )
    assert required_fields_are_known(specified, recalled) is True
    assert memory_verify_urls(specified, recalled.facts) == [
        "https://dess.digital/ajoy-chawla/",
        "https://economictimes.indiatimes.com/titan",
    ]


def test_rbi_repo_aliases_count_as_known() -> None:
    from src.models import MemoryFact, MemoryRecall
    from src.plan_research import required_fields_are_known

    specified = titan_specified().model_copy(
        update={
            "specification": titan_specified().specification.model_copy(
                update={
                    "entities": ["Reserve Bank of India"],
                    "required_fields": ["policy_repo_rate", "mpc_decision_date"],
                }
            )
        }
    )
    recalled = MemoryRecall(
        facts=[
            MemoryFact(
                entity="Reserve Bank of India",
                field="repo_rate",
                text="5.25 percent",
                urls=["https://www.rbi.org.in/mpc"],
                as_of_date="2026-09-26",
            ),
            MemoryFact(
                entity="Reserve Bank of India",
                field="decision_date",
                text="June 5, 2026",
                urls=["https://www.rbi.org.in/mpc"],
                as_of_date="2026-09-26",
            ),
        ],
        known_fields=["repo_rate", "decision_date"],
    )
    assert required_fields_are_known(specified, recalled) is True


def test_empty_query_list_fails_closed() -> None:
    settings = valid_settings()
    drafted = PlannerOutput.model_construct(queries=[])

    with pytest.raises(ValueError, match="no usable search queries"):
        finalize_plan(titan_specified(), drafted, settings)
