"""Offline tests for the deterministic completeness gate."""

from src.gate import citation_label, close_answer, render_answer
from src.models import (
    AnalystClaim,
    AnalystResult,
    AuditReport,
    ClaimAudit,
    CrossCheckReport,
    CrossCheckVerdict,
    QuestionSpecification,
    SpecifiedQuestion,
    UnansweredField,
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
) -> AnalystClaim:
    return AnalystClaim(
        claim_id=claim_id,
        field=field,
        text=text,
        quote=text,
        passage_ids=["P0001"],
        urls=urls,
        period="2026",
    )


def audit(*pairs: tuple[str, str, str]) -> AuditReport:
    return AuditReport(
        verdicts=[
            ClaimAudit(claim_id=claim_id, verdict=verdict, reason=reason)
            for claim_id, verdict, reason in pairs
        ]
    )


def analyst(*claims: AnalystClaim, unanswered: list[UnansweredField] | None = None) -> AnalystResult:
    return AnalystResult(claims=list(claims), unanswered=unanswered or [])


def titan_md() -> AnalystClaim:
    return claim(
        claim_id="C01",
        field="full name",
        text="Ajoy Chawla is the Managing Director of Titan Company Limited.",
        urls=["https://dess.digital/ajoy-chawla/"],
    )


def titan_date() -> AnalystClaim:
    return claim(
        claim_id="C02",
        field="effective appointment date",
        text="Ajoy Chawla's appointment as MD took effect from January 2026.",
        urls=[
            "https://economictimes.indiatimes.com/industry/titan.cms",
            "https://www.titancompany.in/sites/default/files/2026-05/note.pdf",
        ],
    )


def test_citation_label_marks_pdf_hosts() -> None:
    assert citation_label("https://dess.digital/ajoy") == "dess.digital"
    assert (
        citation_label("https://www.titancompany.in/sites/default/files/note.pdf")
        == "titancompany.in PDF"
    )


def test_complete_when_every_required_field_is_supported() -> None:
    answer = close_answer(
        titan_specified(),
        analyst(titan_md(), titan_date()),
        audit(
            ("C01", "SUPPORTED", "Name is on the page."),
            ("C02", "SUPPORTED", "Date is on the page."),
        ),
    )
    assert answer.complete is True
    assert [item.field for item in answer.accepted] == [
        "full name",
        "effective appointment date",
    ]
    rendered = render_answer(answer)
    assert rendered.startswith("Answer (complete)")
    assert "dess.digital" in rendered
    assert "economictimes.indiatimes.com" in rendered
    assert "titancompany.in PDF" in rendered
    assert "Missing" not in rendered


def test_missing_required_field_makes_answer_incomplete() -> None:
    specified = titan_specified()
    specified = SpecifiedQuestion(
        question=specified.question,
        notes=specified.notes,
        specification=QuestionSpecification(
            **{
                **specified.specification.model_dump(),
                "required_fields": [
                    "full name",
                    "effective appointment date",
                    "predecessor's name",
                ],
            }
        ),
        page_policy=specified.page_policy,
        as_of_date=specified.as_of_date,
        resolved_time_period=specified.resolved_time_period,
    )
    answer = close_answer(
        specified,
        analyst(
            titan_md(),
            titan_date(),
            unanswered=[
                UnansweredField(
                    field="predecessor's name",
                    reason="not found in the pages we opened",
                )
            ],
        ),
        audit(
            ("C01", "SUPPORTED", "Name is on the page."),
            ("C02", "SUPPORTED", "Date is on the page."),
        ),
    )
    assert answer.complete is False
    rendered = render_answer(answer)
    assert rendered.startswith("Answer (incomplete)")
    assert "full name:" in rendered
    assert "Missing" in rendered
    assert "predecessor's name: not found in the pages we opened" in rendered


def test_unsupported_and_uncited_claims_are_not_shown() -> None:
    extra = claim(
        claim_id="C03",
        field="predecessor's name",
        text="Someone else was MD.",
        urls=[],
    )
    answer = close_answer(
        titan_specified(),
        analyst(titan_md(), extra),
        audit(
            ("C01", "SUPPORTED", "Name is on the page."),
            ("C03", "UNCITED", "Claim cites no URLs."),
        ),
    )
    assert [item.claim_id for item in answer.accepted] == ["C01"]
    assert answer.complete is False
    assert any(item.field == "effective appointment date" for item in answer.missing)


def test_contradicted_claim_goes_to_disputed() -> None:
    answer = close_answer(
        titan_specified(),
        analyst(titan_md(), titan_date()),
        audit(
            ("C01", "SUPPORTED", "Name is on the page."),
            ("C02", "CONTRADICTED", "Cited page says April 2026."),
        ),
    )
    assert answer.complete is False
    assert [item.claim_id for item in answer.accepted] == ["C01"]
    assert answer.disputed[0].claim_id == "C02"
    rendered = render_answer(answer)
    assert "Disputed" in rendered
    assert "Cited page says April 2026." in rendered


def test_cross_check_conflict_disputes_a_supported_claim() -> None:
    answer = close_answer(
        titan_specified(),
        analyst(titan_md(), titan_date()),
        audit(
            ("C01", "SUPPORTED", "Name is on the page."),
            ("C02", "SUPPORTED", "Date is on the cited page."),
        ),
        CrossCheckReport(
            verdicts=[
                CrossCheckVerdict(
                    claim_id="C02",
                    status="conflicting",
                    reason="Independent page says 2024.",
                )
            ]
        ),
    )
    assert answer.complete is False
    assert [item.claim_id for item in answer.accepted] == ["C01"]
    assert answer.disputed[0].reason == "Independent source conflicts with this claim."


def test_ranking_shortfall_is_incomplete() -> None:
    settings = valid_settings()
    specified = SpecifiedQuestion(
        question="Which three Indian jewellery retailers opened the most new stores?",
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
    answer = close_answer(
        specified,
        analyst(
            claim(
                claim_id="C01",
                field="retailer name",
                text="Malabar Gold & Diamonds",
                urls=["https://www.tradejini.com/blog"],
            ),
            claim(
                claim_id="C02",
                field="new-store count",
                text="12 new stores",
                urls=["https://www.tradejini.com/blog"],
            ),
            unanswered=[
                UnansweredField(
                    field="ranking",
                    reason="Not enough data to rank the top 3.",
                )
            ],
        ),
        audit(
            ("C01", "SUPPORTED", "Name is on the page."),
            ("C02", "SUPPORTED", "Count is on the page."),
        ),
    )
    assert answer.complete is False
    assert any(item.field == "ranking" for item in answer.missing)
    assert render_answer(answer).startswith("Answer (incomplete)")
