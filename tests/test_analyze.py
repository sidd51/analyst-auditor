"""Offline tests for the fail-closed Analyst."""

from src.analyze import (
    analyze_evidence,
    drop_mismatched_chosen_reason,
    finalize_analyst,
    merge_analyst_results,
    missing_required_fields,
    should_fetch_wave2,
)
from src.cost import CostRecord
from src.llm import StructuredResult
from src.models import (
    AnalystClaim,
    AnalystDraft,
    AnalystResult,
    DraftClaim,
    EvidencePacket,
    EvidencePassage,
    FetchResponse,
    ResearchPlan,
    RetrievalResponse,
    UnansweredField,
)
from src.page_budget import page_policy_from_settings
from src.models import QuestionSpecification, SpecifiedQuestion
from tests.test_config import valid_settings
from tests.test_plan_research import titan_specified


class FakeLLM:
    def __init__(self, drafted: AnalystDraft) -> None:
        self.drafted = drafted
        self.system_prompt = ""
        self.user_prompt = ""
        self.calls = 0

    def complete_structured(self, **kwargs: object) -> StructuredResult:
        self.calls += 1
        self.system_prompt = str(kwargs.get("system_prompt") or "")
        self.user_prompt = str(kwargs.get("user_prompt") or "")
        return StructuredResult(
            value=self.drafted,
            cost=CostRecord(80, 40, 120, 0.0001, 0.01),
            generation_id="fake-analyze",
        )


def passage() -> EvidencePassage:
    return EvidencePassage(
        passage_id="P0006",
        url="https://example.com/titan",
        title="Titan stores",
        document_kind="html",
        chunk_index=1,
        text=(
            "By September 2025, Titan added only 19 new jewellery retail "
            "locations in Q1 FY26."
        ),
        matched_terms=["titan", "stores"],
        relevance_score=10.0,
        estimated_tokens=40,
    )


def packet(*, ranking: bool = False) -> EvidencePacket:
    specified = titan_specified()
    if ranking:
        settings = valid_settings()
        specified = SpecifiedQuestion(
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
    return EvidencePacket(
        plan=ResearchPlan(specified=specified, queries=[]),
        fetched=FetchResponse(requested_count=1, selected_count=1, skipped_count=0),
        retrieval=RetrievalResponse(
            question=specified.question,
            documents_considered=1,
            passages_considered=1,
            passages_selected=1,
            passages_omitted=0,
            estimated_tokens=40,
            token_budget=8000,
            passages=[passage()],
        ),
        pages_used=1,
        next_wave_size=4,
    )


def supported_draft() -> DraftClaim:
    return DraftClaim(
        field="new-store count",
        text="Titan added 19 jewellery stores in Q1 FY26.",
        quote="Titan added only 19 new jewellery retail locations in Q1 FY26",
        passage_ids=["P0006"],
        period="Q1 FY26",
    )


def test_quoted_in_passage_claim_is_kept() -> None:
    result = finalize_analyst(
        packet(),
        AnalystDraft(claims=[supported_draft()], unanswered=[]),
    )

    assert len(result.claims) == 1
    assert result.claims[0].claim_id == "C01"
    assert result.claims[0].urls == ["https://example.com/titan"]
    assert result.dropped_drafts == 0


def test_unquoted_or_unknown_passage_draft_is_dropped() -> None:
    result = finalize_analyst(
        packet(),
        AnalystDraft(
            claims=[
                DraftClaim(
                    field="full name",
                    text="Sam Altman is the MD.",
                    quote="Sam Altman is the MD",
                    passage_ids=["P0006"],
                ),
                DraftClaim(
                    field="effective appointment date",
                    text="January 1, 2026",
                    quote="Titan added only 19 new jewellery retail locations",
                    passage_ids=["P9999"],
                ),
            ]
        ),
    )

    assert result.claims == []
    assert result.dropped_drafts == 2
    fields = {item.field for item in result.unanswered}
    assert "full name" in fields
    assert "effective appointment date" in fields


def test_ranking_question_records_missing_count() -> None:
    result = finalize_analyst(
        packet(ranking=True),
        AnalystDraft(claims=[supported_draft()]),
    )

    assert len(result.claims) == 1
    reasons = {item.field: item.reason for item in result.unanswered}
    assert "retailer name" in reasons
    assert "requested count" in reasons


def test_title_quote_with_initials_is_kept() -> None:
    titled = packet(ranking=True)
    titled.retrieval.passages[0] = titled.retrieval.passages[0].model_copy(
        update={
            "title": "Ajoy Chawla to succeed CK Venkataraman as MD of Titan Company",
            "text": "C.K. Venkataraman, the current Managing Director, will retire.",
        }
    )

    result = finalize_analyst(
        titled,
        AnalystDraft(
            claims=[
                DraftClaim(
                    field="predecessor's name",
                    text="Ajoy Chawla will succeed C.K. Venkataraman.",
                    quote=(
                        "Ajoy Chawla to succeed C.K. Venkataraman as MD "
                        "of Titan Company"
                    ),
                    passage_ids=["P0006"],
                )
            ]
        ),
    )

    assert len(result.claims) == 1
    assert result.dropped_drafts == 0


def test_analyze_prompt_forbids_plans_and_forced_rankings() -> None:
    llm = FakeLLM(AnalystDraft(claims=[supported_draft()]))
    analyze_evidence(packet(ranking=True), valid_settings(), llm)  # type: ignore[arg-type]

    assert llm.calls == 1
    assert "plans, targets" in llm.system_prompt
    assert "Do not force a top-N ranking" in llm.system_prompt
    assert "single in-window" in llm.system_prompt
    assert "chosen_figure_count" in llm.system_prompt
    assert "brand token" in llm.system_prompt
    assert "2024-09-26 to 2026-09-26" in llm.user_prompt
    assert "P0006" in llm.user_prompt


def test_python_keeps_only_three_short_notes() -> None:
    result = finalize_analyst(
        packet(ranking=True),
        AnalystDraft(
            claims=[supported_draft()],
            notes=[
                "Kalyan plans 170 stores in FY26.",
                "Senco anticipates 18-20 stores.",
                "Forevermark fashion show and a very long brand story " * 8,
                "This fourth note must be dropped.",
            ],
        ),
        valid_settings(),
    )

    assert len(result.notes) == 3
    assert "fourth note" not in " ".join(result.notes)
    assert all(len(note) <= 220 for note in result.notes)


def test_wave2_is_skipped_when_required_fields_are_covered() -> None:
    first = finalize_analyst(
        packet(),
        AnalystDraft(
            claims=[
                DraftClaim(
                    field="full name",
                    text="Ajoy Chawla is MD.",
                    quote="Titan added only 19 new jewellery retail locations in Q1 FY26",
                    passage_ids=["P0006"],
                ),
                DraftClaim(
                    field="effective appointment date",
                    text="Q1 FY26",
                    quote="Titan added only 19 new jewellery retail locations in Q1 FY26",
                    passage_ids=["P0006"],
                ),
            ]
        ),
    )
    ready = packet()
    ready.unused_urls = ["https://example.com/extra"]
    ready.next_wave_size = 4
    assert missing_required_fields(first, ready.plan.specified) == []
    assert should_fetch_wave2(ready, first, valid_settings()) is False


def test_wave2_runs_only_for_open_required_fields_with_leftovers() -> None:
    first = finalize_analyst(packet(), AnalystDraft(claims=[]))
    ready = packet()
    ready.unused_urls = ["https://example.com/extra"]
    ready.next_wave_size = 4
    assert "full name" in missing_required_fields(first, ready.plan.specified)
    assert should_fetch_wave2(ready, first, valid_settings()) is True
    ready.unused_urls = []
    assert should_fetch_wave2(ready, first, valid_settings()) is False


def test_wave2_is_skipped_on_memory_verify() -> None:
    first = finalize_analyst(packet(), AnalystDraft(claims=[]))
    ready = packet()
    ready.unused_urls = ["https://example.com/extra"]
    ready.next_wave_size = 4
    ready.memory_verify = True
    assert should_fetch_wave2(ready, first, valid_settings()) is False


def test_merge_appends_new_claims_and_drops_covered_gaps() -> None:
    first = AnalystResult(
        claims=[
            AnalystClaim(
                claim_id="C01",
                field="full name",
                text="Ajoy Chawla is MD.",
                quote="Ajoy Chawla",
                passage_ids=["P0001"],
                urls=["https://example.com/a"],
            )
        ],
        unanswered=[
            UnansweredField(field="effective appointment date", reason="Not in wave 1.")
        ],
    )
    second = AnalystResult(
        claims=[
            AnalystClaim(
                claim_id="C01",
                field="effective appointment date",
                text="January 1, 2026",
                quote="January 1, 2026",
                passage_ids=["P0001"],
                urls=["https://example.com/b"],
            )
        ]
    )
    merged = merge_analyst_results(first, second, packet(), valid_settings())
    assert [item.claim_id for item in merged.claims] == ["C01", "C02"]
    assert merged.claims[1].field == "effective appointment date"
    assert not any(
        item.field == "effective appointment date" for item in merged.unanswered
    )


def test_mismatched_chosen_reason_is_unanswered_without_llm() -> None:
    result = finalize_analyst(
        packet(),
        AnalystDraft(
            claims=[
                DraftClaim(
                    field="chosen_figure_count",
                    text="over 2,000 retail stores",
                    quote="Titan added only 19 new jewellery retail locations in Q1 FY26",
                    passage_ids=["P0006"],
                ),
                DraftClaim(
                    field="chosen_figure_reason",
                    text="528 is the latest dated store-network figure.",
                    quote="Titan added only 19 new jewellery retail locations in Q1 FY26",
                    passage_ids=["P0006"],
                ),
            ]
        ),
    )
    fields = [item.field for item in result.claims]
    assert "chosen_figure_count" in fields
    assert "chosen_figure_reason" not in fields
    assert result.dropped_drafts == 1
    gap = next(
        item for item in result.unanswered if item.field == "chosen_figure_reason"
    )
    assert "does not match" in gap.reason


def test_chosen_reason_is_kept_when_it_repeats_the_count() -> None:
    claims, dropped, mismatch = drop_mismatched_chosen_reason(
        [
            AnalystClaim(
                claim_id="C01",
                field="chosen_figure_count",
                text="over 2,000 retail stores",
                quote="over 2,000 retail stores",
                passage_ids=["P0001"],
                urls=["https://example.com/a"],
            ),
            AnalystClaim(
                claim_id="C02",
                field="chosen_figure_reason",
                text="2,000 is later than the 528 scrape figure.",
                quote="2,000 is later than the 528 scrape figure.",
                passage_ids=["P0001"],
                urls=["https://example.com/a"],
            ),
        ]
    )
    assert dropped == 0
    assert mismatch is None
    assert [item.claim_id for item in claims] == ["C01", "C02"]
