"""Offline tests for question specification and the wave page policy."""

from src.cost import CostRecord
from src.llm import StructuredResult
from src.models import QuestionSpecification
from src.page_budget import next_fetch_wave, page_policy_from_settings
from src.specify import specify_question
from tests.test_config import valid_settings


class FakeLLM:
    """Return a prepared spec so tests never call OpenRouter."""

    def __init__(self, specification: QuestionSpecification) -> None:
        self.specification = specification
        self.calls = 0

    def complete_structured(self, **_kwargs: object) -> StructuredResult:
        self.calls += 1
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


def test_next_fetch_wave_starts_at_five_then_adds_four_until_the_ceiling() -> None:
    settings = valid_settings()

    assert next_fetch_wave(0, settings) == 5
    assert next_fetch_wave(5, settings) == 4
    assert next_fetch_wave(9, settings) == 4
    assert next_fetch_wave(13, settings) == 2
    assert next_fetch_wave(15, settings) == 0
    assert next_fetch_wave(20, settings) == 0


def test_page_policy_comes_from_settings_not_question_type() -> None:
    policy = page_policy_from_settings(valid_settings())

    assert policy.initial_pages == 5
    assert policy.wave_size == 4
    assert policy.page_ceiling == 15
