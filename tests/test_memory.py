"""Offline tests for entity-scoped fact memory."""

from pathlib import Path

from src.memory import EntityMemory, resolve_entity
from src.models import (
    AnalystClaim,
    AnalystResult,
    AnswerLine,
    CrossCheckReport,
    CrossCheckVerdict,
    DisputedLine,
    FinalAnswer,
    QuestionSpecification,
    SpecifiedQuestion,
)
from src.page_budget import page_policy_from_settings
from tests.test_config import valid_settings
from tests.test_plan_research import titan_specified


def claim(
    *,
    claim_id: str,
    field: str,
    text: str,
    urls: list[str],
    quote: str = "",
) -> AnalystClaim:
    return AnalystClaim(
        claim_id=claim_id,
        field=field,
        text=text,
        quote=quote or text,
        passage_ids=["P0001"],
        urls=urls,
        period="2026",
    )


def titan_md() -> AnalystClaim:
    return claim(
        claim_id="C01",
        field="full name",
        text="Ajoy Chawla is the Managing Director of Titan Company Limited.",
        quote="Ajoy Chawla has been appointed as Managing Director",
        urls=["https://dess.digital/ajoy-chawla/"],
    )


def titan_date() -> AnalystClaim:
    return claim(
        claim_id="C02",
        field="effective appointment date",
        text="Ajoy Chawla's appointment as MD took effect from January 2026.",
        urls=["https://economictimes.indiatimes.com/industry/titan.cms"],
    )


def accepted_answer(*claims: AnalystClaim) -> FinalAnswer:
    return FinalAnswer(
        complete=True,
        accepted=[
            AnswerLine(
                field=item.field,
                text=item.text,
                claim_id=item.claim_id,
                urls=list(item.urls),
                sources=["example"],
            )
            for item in claims
        ],
    )


def jewellery_specified() -> SpecifiedQuestion:
    settings = valid_settings()
    return SpecifiedQuestion(
        question=(
            "Which three Indian jewellery retailers opened the most "
            "new stores in the last two years?"
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
            not_found_rule="Do not invent ranks.",
        ),
        page_policy=page_policy_from_settings(settings),
        as_of_date="2026-09-26",
        resolved_time_period="2024-09-26 to 2026-09-26",
    )


def test_accepted_facts_are_recalled_for_the_same_entity(tmp_path: Path) -> None:
    memory = EntityMemory(tmp_path / "memory.json")
    md = titan_md()
    memory.update_from_run(
        titan_specified(),
        AnalystResult(claims=[md]),
        accepted_answer(md),
        CrossCheckReport(
            verdicts=[
                CrossCheckVerdict(
                    claim_id="C01",
                    status="single_source",
                    reason="No second page.",
                )
            ]
        ),
    )
    recalled = memory.recall(titan_specified())
    assert recalled.known_facts
    assert "Titan Company / full name (single_source)" in recalled.known_facts[0]
    assert "Ajoy Chawla" in recalled.known_facts[0]
    assert recalled.facts[0].urls
    assert memory.snapshot.facts[0].quote.startswith("Ajoy Chawla has been")


def test_jewellery_question_does_not_recall_titan_facts(tmp_path: Path) -> None:
    memory = EntityMemory(tmp_path / "memory.json")
    md = titan_md()
    memory.update_from_run(
        titan_specified(),
        AnalystResult(claims=[md]),
        accepted_answer(md),
    )
    recalled = memory.recall(jewellery_specified())
    assert recalled.known_facts == []
    assert recalled.facts == []


def test_corroborated_tag_and_json_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    memory = EntityMemory(path)
    md = titan_md()
    memory.update_from_run(
        titan_specified(),
        AnalystResult(claims=[md]),
        accepted_answer(md),
        CrossCheckReport(
            verdicts=[
                CrossCheckVerdict(
                    claim_id="C01",
                    status="corroborated",
                    reason="Second page agrees.",
                )
            ]
        ),
    )
    memory.save()
    loaded = EntityMemory.load(valid_settings(), path=path)
    assert loaded.snapshot.facts[0].corroboration == "corroborated"
    assert "Answer (" not in loaded.path.read_text(encoding="utf-8")


def test_disputed_field_is_not_a_known_fact(tmp_path: Path) -> None:
    memory = EntityMemory(tmp_path / "memory.json")
    md = titan_md()
    dated = titan_date()
    memory.update_from_run(
        titan_specified(),
        AnalystResult(claims=[md, dated]),
        accepted_answer(md, dated),
    )
    assert any(item.field == "effective appointment date" for item in memory.snapshot.facts)

    disputed = FinalAnswer(
        complete=False,
        accepted=[
            AnswerLine(
                field=md.field,
                text=md.text,
                claim_id=md.claim_id,
                urls=list(md.urls),
            )
        ],
        disputed=[
            DisputedLine(
                field=dated.field,
                claim_id=dated.claim_id,
                reason="Independent source conflicts with this claim.",
                urls=list(dated.urls),
            )
        ],
    )
    memory.update_from_run(
        titan_specified(),
        AnalystResult(claims=[md, dated]),
        disputed,
    )
    recalled = memory.recall(titan_specified())
    assert any("full name" in line for line in recalled.known_facts)
    assert not any("January 2026" in line for line in recalled.known_facts)
    assert any("disputed" in line for line in recalled.disputed_notes)
    assert not any(
        item.field == "effective appointment date" for item in memory.snapshot.facts
    )


def test_rejected_claim_is_not_written_as_a_fact(tmp_path: Path) -> None:
    memory = EntityMemory(tmp_path / "memory.json")
    bad = claim(
        claim_id="C03",
        field="predecessor's name",
        text="Someone else was MD.",
        urls=[],
    )
    memory.update_from_run(
        titan_specified(),
        AnalystResult(claims=[bad]),
        FinalAnswer(complete=False),
    )
    recalled = memory.recall(titan_specified())
    assert recalled.known_facts == []
    assert recalled.rejected_notes
    assert "Someone else was MD." in recalled.rejected_notes[0]


def test_ranking_name_row_becomes_its_own_entity() -> None:
    line = AnswerLine(
        field="retailer name",
        text="Malabar Gold & Diamonds",
        claim_id="C01",
        urls=["https://www.tradejini.com/blog"],
    )
    assert resolve_entity(jewellery_specified(), line) == "Malabar Gold & Diamonds"


def test_rbi_alias_recalls_reserve_bank_facts(tmp_path: Path) -> None:
    from src.memory import entities_match, mentioned_in_question
    from src.models import MemoryFact, MemorySnapshot

    assert entities_match("RBI", "Reserve Bank of India")
    assert mentioned_in_question(
        "Reserve Bank of India",
        "Using stored RBI facts: confirm the repo rate.",
    )
    settings = valid_settings()
    memory = EntityMemory(
        tmp_path / "memory.json",
        MemorySnapshot(
            facts=[
                MemoryFact(
                    entity="Reserve Bank of India",
                    field="repo_rate",
                    text="5.25 percent",
                    urls=["https://www.rbi.org.in/mpc"],
                    as_of_date="2026-09-26",
                )
            ]
        ),
    )
    specified = titan_specified().model_copy(
        update={
            "question": "Using stored RBI facts: confirm the repo rate.",
            "specification": titan_specified().specification.model_copy(
                update={"entities": ["RBI"]}
            ),
        }
    )
    recalled = memory.recall(specified)
    assert recalled.known_fields == ["repo_rate"]

