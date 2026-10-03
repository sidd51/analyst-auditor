"""Offline tests for the deterministic completeness gate."""

from src.gate import citation_label, close_answer, collapse_duplicate_fields, render_answer
from src.models import (
    AnalystClaim,
    AnalystResult,
    AnswerLine,
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
    assert all(item.field != answer.disputed[0].field for item in answer.missing)
    rendered = render_answer(answer)
    assert "Disputed" in rendered
    assert "Cited page says April 2026." in rendered


def test_cross_check_conflict_does_not_veto_auditor_supported() -> None:
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
    assert answer.complete is True
    assert [item.claim_id for item in answer.accepted] == ["C01", "C02"]


def test_cross_check_conflict_still_drops_when_auditor_did_not_support() -> None:
    answer = close_answer(
        titan_specified(),
        analyst(titan_md(), titan_date()),
        audit(
            ("C01", "SUPPORTED", "Name is on the page."),
            ("C02", "UNSUPPORTED", "Cited page is silent."),
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
    assert [item.claim_id for item in answer.accepted] == ["C01"]
    assert answer.disputed[0].claim_id == "C02"


def test_collapse_prefers_dated_pdf_over_undated_blog() -> None:
    kept, disputed = collapse_duplicate_fields(
        [
            AnswerLine(
                field="store_network_number",
                text="Titan currently has 900 stores.",
                claim_id="C05",
                urls=["https://www.livemint.com/companies/titan"],
                sources=["livemint.com"],
            ),
            AnswerLine(
                field="store_network_number",
                text=(
                    "Titan had a retail chain of 3,377 stores as of Q4FY26."
                ),
                claim_id="C06",
                urls=["https://www.icicidirect.com/mailcontent/idirect_titan_q4fy26.pdf"],
                sources=["icicidirect.com PDF"],
            ),
        ],
        None,
    )
    assert [item.claim_id for item in kept] == ["C06"]
    assert disputed[0].claim_id == "C05"


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


def test_name_two_companies_keeps_both_rows() -> None:
    settings = valid_settings()
    specified = SpecifiedQuestion(
        question="Name two Indian IT companies and their headcount change.",
        notes=[],
        specification=QuestionSpecification(
            entities=["Indian IT services companies"],
            question_type="multi_field",
            required_fields=["company name", "headcount change number"],
            time_period="2026",
            geography="India",
            required_count=2,
            ranking=False,
            comparison=False,
            exhaustive=False,
            constraints=[],
            not_found_rule="not_found is allowed.",
        ),
        page_policy=page_policy_from_settings(settings),
        as_of_date="2026-09-26",
        resolved_time_period="2026",
    )
    answer = close_answer(
        specified,
        analyst(
            claim(claim_id="C01", field="company name", text="Wipro", urls=["https://et.com/a"]),
            claim(claim_id="C02", field="headcount change number", text="7,500", urls=["https://et.com/a"]),
            claim(claim_id="C03", field="company name", text="TCS", urls=["https://et.com/a"]),
            claim(
                claim_id="C04",
                field="headcount change number",
                text="-23,460",
                urls=["https://et.com/a"],
            ),
        ),
        audit(
            ("C01", "SUPPORTED", "Wipro is on the page."),
            ("C02", "SUPPORTED", "7500 is on the page."),
            ("C03", "SUPPORTED", "TCS is on the page."),
            ("C04", "SUPPORTED", "23460 is on the page."),
        ),
        CrossCheckReport(
            verdicts=[
                CrossCheckVerdict(claim_id="C01", status="single_source"),
                CrossCheckVerdict(claim_id="C03", status="corroborated"),
            ]
        ),
    )
    names = [item.text for item in answer.accepted if item.field == "company name"]
    assert names == ["Wipro", "TCS"]
    assert answer.disputed == []
    assert answer.complete is True


def test_comparison_keeps_both_winner_rows() -> None:
    settings = valid_settings()
    specified = SpecifiedQuestion(
        question=(
            "Which company had the highest FY26 revenue, and which had "
            "the highest FY26 growth rate?"
        ),
        notes=[],
        specification=QuestionSpecification(
            entities=["TCS", "HCLTech"],
            question_type="comparison",
            required_fields=["company name", "FY26 revenue", "FY26 growth"],
            time_period="FY26",
            geography="India",
            required_count=None,
            ranking=False,
            comparison=True,
            exhaustive=False,
            constraints=[],
            not_found_rule="not_found is allowed.",
        ),
        page_policy=page_policy_from_settings(settings),
        as_of_date="2026-09-26",
        resolved_time_period="FY26",
    )
    answer = close_answer(
        specified,
        analyst(
            claim(claim_id="C01", field="company name", text="TCS", urls=["https://et.com/a"]),
            claim(claim_id="C02", field="FY26 revenue", text="267000", urls=["https://et.com/a"]),
            claim(claim_id="C03", field="company name", text="HCLTech", urls=["https://et.com/a"]),
            claim(claim_id="C04", field="FY26 growth", text="11.18%", urls=["https://et.com/a"]),
        ),
        audit(
            ("C01", "SUPPORTED", "TCS is on the page."),
            ("C02", "SUPPORTED", "Revenue is on the page."),
            ("C03", "SUPPORTED", "HCLTech is on the page."),
            ("C04", "SUPPORTED", "Growth is on the page."),
        ),
        CrossCheckReport(verdicts=[]),
    )
    names = [item.text for item in answer.accepted if item.field == "company name"]
    assert names == ["TCS", "HCLTech"]
    assert answer.complete is True
