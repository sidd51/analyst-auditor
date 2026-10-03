"""Offline tests for question specification and the wave page policy."""

from src.cost import CostRecord
from src.llm import StructuredResult
from src.models import QuestionSpecification
from src.page_budget import next_fetch_wave, page_policy_from_settings
from src.specify import (
    apply_compare_rank_contract,
    asks_which_wins,
    drop_unrequested_chosen_fields,
    drop_unrequested_citation_fields,
    is_name_n_ranking,
    rewrite_comparison_winner_fields,
    specify_question,
)
from tests.test_config import valid_settings


class FakeLLM:
    """Return a prepared spec so tests never call OpenRouter."""

    def __init__(self, specification: QuestionSpecification) -> None:
        self.specification = specification
        self.user_prompt = ""
        self.system_prompt = ""
        self.calls = 0

    def complete_structured(self, **kwargs: object) -> StructuredResult:
        self.calls += 1
        self.user_prompt = str(kwargs.get("user_prompt") or "")
        self.system_prompt = str(kwargs.get("system_prompt") or "")
        return StructuredResult(
            value=self.specification,
            cost=CostRecord(
                input_tokens=80,
                output_tokens=40,
                total_tokens=120,
                cost_usd=0.0001,
                cost_inr=0.01,
            ),
            generation_id="fake-specify",
        )


def ranking_spec() -> QuestionSpecification:
    return QuestionSpecification(
        entities=["Indian jewellery retailers"],
        question_type="ranking",
        required_fields=["retailer names", "new stores opened"],
        time_period="last two years",
        geography="India",
        required_count=3,
        ranking=True,
        comparison=False,
        exhaustive=False,
        constraints=[],
        not_found_rule=(
            "If fewer than three retailers have dated store-opening evidence, "
            "mark the missing ranks as not_found."
        ),
    )


def test_python_attaches_the_same_wave_policy_to_a_ranking_question() -> None:
    settings = valid_settings()
    llm = FakeLLM(ranking_spec())

    result = specify_question(
        "Which three Indian jewellery retailers opened the most new stores "
        "in the last two years?",
        ["Need company names and store counts."],
        settings,
        llm,  # type: ignore[arg-type]
    )

    assert llm.calls == 1
    assert result.value.specification.ranking is True
    assert result.value.page_policy.initial_pages == 5
    assert result.value.page_policy.wave_size == 4
    assert result.value.page_policy.page_ceiling == 15
    assert result.value.page_policy.stop_when == "requirements_covered"
    assert result.value.as_of_date == "2026-09-26"
    assert result.value.resolved_time_period == "2024-09-26 to 2026-09-26"
    assert "As-of date (supplied by Python): 2026-09-26" in llm.user_prompt
    assert "chosen_figure_count" in llm.system_prompt
    assert "brand token" in llm.system_prompt


def test_next_fetch_wave_starts_at_five_then_adds_four_until_the_ceiling() -> None:
    settings = valid_settings()

    assert next_fetch_wave(0, settings) == 5
    assert next_fetch_wave(5, settings) == 4
    assert next_fetch_wave(9, settings) == 4
    assert next_fetch_wave(13, settings) == 2
    assert next_fetch_wave(15, settings) == 0
    assert next_fetch_wave(20, settings) == 0


def _spec_with_fields(*fields: str) -> QuestionSpecification:
    return QuestionSpecification(
        entities=["Reserve Bank of India"],
        question_type="multi_field",
        required_fields=list(fields),
        time_period="2026",
        geography="India",
        required_count=None,
        ranking=False,
        comparison=False,
        exhaustive=False,
        constraints=[],
        not_found_rule="not_found is allowed.",
    )


def test_q05_style_question_drops_invented_chosen_figure_fields() -> None:
    spec = drop_unrequested_chosen_fields(
        _spec_with_fields("repo rate", "decision date", "chosen_figure_count", "chosen figure reason"),
        "What is the Reserve Bank of India's repo rate after the most recent "
        "Monetary Policy Committee decision in 2026, and what was the date "
        "of that decision?",
        ["Required fields are only the repo rate and the decision date."],
    )
    assert spec.required_fields == ["repo rate", "decision date"]


def test_q09_style_question_drops_invented_chosen_figure_fields() -> None:
    spec = drop_unrequested_chosen_fields(
        _spec_with_fields("global employee count", "chosen_figure_count", "chosen_figure_reason"),
        "What Infosys global employee count is stated in the RBI press "
        "release for the most recent 2026 MPC repo-rate decision?",
        ["The only required field is that employee count."],
    )
    assert spec.required_fields == ["global employee count"]


def test_q07_keeps_chosen_figure_fields() -> None:
    spec = drop_unrequested_chosen_fields(
        _spec_with_fields(
            "institution_1_gdp_growth",
            "chosen_figure_count",
            "chosen_figure_reason",
        ),
        "Find two GDP figures, then choose which figure to treat as the "
        "working estimate and why.",
        ["Need one chosen figure and a short reason."],
    )
    assert "chosen_figure_count" in spec.required_fields
    assert "chosen_figure_reason" in spec.required_fields


def test_q06_style_question_drops_citation_field() -> None:
    spec = drop_unrequested_citation_fields(
        _spec_with_fields("MD full name", "appointment date", "citation"),
        "Confirm Titan Company's Managing Director full name and the "
        "effective appointment date in 2026. Cite one page.",
        ["Required fields are only the MD full name and the appointment date."],
    )
    assert spec.required_fields == ["MD full name", "appointment date"]


def test_specify_question_strips_chosen_fields_after_the_model() -> None:
    llm = FakeLLM(
        _spec_with_fields("repo rate", "decision date", "chosen_figure_count")
    )
    result = specify_question(
        "What is the RBI repo rate after the latest 2026 MPC decision?",
        [],
        valid_settings(),
        llm,  # type: ignore[arg-type]
    )
    assert result.value.specification.required_fields == ["repo rate", "decision date"]


def test_which_wins_is_not_a_name_n_ranking() -> None:
    compare = (
        "Among TCS, Infosys, and HCLTech, which reported the highest "
        "FY26 consolidated revenue, and which reported the highest "
        "FY26 year-on-year revenue growth rate?"
    )
    ranking = (
        "Name the three Indian IT companies with the highest FY26 "
        "consolidated revenue, in rank order."
    )
    assert asks_which_wins(compare, []) is True
    assert is_name_n_ranking(compare, []) is False
    assert asks_which_wins(ranking, []) is False
    assert is_name_n_ranking(ranking, []) is True


def test_compare_contract_sets_comparison_not_ranking() -> None:
    spec = apply_compare_rank_contract(
        _spec_with_fields("company name", "FY26 revenue"),
        "Among TCS and Infosys, which reported the highest FY26 revenue?",
        [],
    )
    assert spec.comparison is True
    assert spec.ranking is False
    assert spec.question_type == "comparison"


def test_name_n_contract_sets_ranking_not_comparison() -> None:
    spec = apply_compare_rank_contract(
        _spec_with_fields("company name", "FY26 revenue"),
        "Name the three Indian IT companies with the highest FY26 "
        "consolidated revenue, in rank order.",
        [],
    )
    assert spec.ranking is True
    assert spec.comparison is False
    assert spec.question_type == "ranking"


def test_comparison_table_fields_become_winner_labels() -> None:
    spec = rewrite_comparison_winner_fields(
        QuestionSpecification(
            entities=["TCS", "Infosys", "HCLTech"],
            question_type="comparison",
            required_fields=[
                "company name",
                "FY26 consolidated revenue",
                "company name",
                "FY26 year-on-year revenue growth rate",
            ],
            time_period="FY26",
            geography=None,
            required_count=None,
            ranking=False,
            comparison=True,
            exhaustive=False,
            constraints=[],
            not_found_rule="not_found is allowed.",
        ),
        "Among TCS, Infosys, and HCLTech, which reported the highest "
        "FY26 consolidated revenue, and which reported the highest "
        "FY26 year-on-year revenue growth rate?",
        [],
    )
    assert spec.required_fields == [
        "highest FY26 consolidated revenue company",
        "highest FY26 consolidated revenue",
        "highest FY26 year-on-year revenue growth rate company",
        "highest FY26 year-on-year revenue growth rate",
    ]


def test_specify_question_marks_a_which_wins_prompt_as_comparison() -> None:
    llm = FakeLLM(_spec_with_fields("highest revenue company", "highest revenue"))
    result = specify_question(
        "Which of TCS and Infosys reported the highest FY26 revenue?",
        [],
        valid_settings(),
        llm,  # type: ignore[arg-type]
    )
    assert result.value.specification.comparison is True


def test_page_policy_comes_from_settings_not_question_type() -> None:
    policy = page_policy_from_settings(valid_settings())

    assert policy.initial_pages == 5
    assert policy.wave_size == 4
    assert policy.page_ceiling == 15
