"""Plant a false claim and run only the Auditor.

The locked Q1–Q9 Analyst never invents this sentence, so a normal eval cannot
prove the Auditor can say no. This command injects a lie that cites a real
Titan page, then asks the Auditor to judge that citation alone.
"""

from __future__ import annotations

import argparse
import sys

from src.audit import audit_claims
from src.config import load_settings
from src.llm import OpenRouterLLM
from src.models import AnalystClaim, QuestionSpecification, SpecifiedQuestion
from src.page_budget import page_policy_from_settings
from src.trace import JsonlTracer


PLANTED_TEXT = (
    "Titan Company operates 9,999 Tanishq stores in Antarctica as of March 2026."
)
PLANTED_QUOTE = "9,999 Tanishq stores in Antarctica"
PLANTED_URL = (
    "https://www.retail4growth.com/news/"
    "ajoy-chawla-takes-charge-as-managing-director-at-titan-company-limited-7699"
)


def planted_claim(*, claim_id: str = "C01") -> AnalystClaim:
    """A cited lie. The URL is real; the Antarctica store count is not on it."""
    return AnalystClaim(
        claim_id=claim_id,
        field="store_network_number",
        text=PLANTED_TEXT,
        quote=PLANTED_QUOTE,
        passage_ids=["P-PLANT"],
        urls=[PLANTED_URL],
        period="2026",
    )


def trap_claim_for_pages(pages: list, *, claim_id: str = "C99") -> AnalystClaim:
    """False store count citing a page we actually opened (or the MD article)."""
    url = PLANTED_URL
    for page in pages:
        candidate = getattr(page, "final_url", None) or getattr(page, "url", "")
        if getattr(page, "ok", False) and candidate:
            url = candidate
            break
    return planted_claim(claim_id=claim_id).model_copy(update={"urls": [url]})


def planted_specified(settings) -> SpecifiedQuestion:
    return SpecifiedQuestion(
        question="Planted false store count for Auditor proof only.",
        notes=["This is not an eval research question."],
        specification=QuestionSpecification(
            entities=["Titan Company"],
            question_type="identity",
            required_fields=["store_network_number"],
            time_period="2026",
            geography=None,
            required_count=1,
            ranking=False,
            comparison=False,
            exhaustive=False,
            constraints=[],
            not_found_rule="The planted claim is false.",
        ),
        page_policy=page_policy_from_settings(settings),
        as_of_date="2026-09-26",
        resolved_time_period="2026",
    )


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="Paid Auditor-only run on one planted false claim."
    )


def main(argv: list[str] | None = None) -> int:
    _parser().parse_args(argv)
    settings = load_settings()
    trace_path = settings.root / "logs" / "plant-auditor.jsonl"
    tracer = JsonlTracer(trace_path, reset=True)
    llm = OpenRouterLLM(settings, tracer)
    claim = planted_claim()
    tracer.event(
        "plant_start",
        claim=claim.text,
        url=PLANTED_URL,
        note="False store count on a real MD article.",
    )
    result = audit_claims(
        [claim],
        planted_specified(settings),
        settings,
        tracer,
        llm=llm,
    )
    verdict = result.value.verdicts[0]
    tracer.event(
        "plant_end",
        verdict=verdict.verdict,
        reason=verdict.reason,
        **result.cost.as_dict(),
    )
    print(f"Planted claim: {claim.text}")
    print(f"Cited: {PLANTED_URL}")
    print(f"Auditor: {verdict.verdict}")
    print(f"Reason: {verdict.reason}")
    print(f"Trace: {trace_path}")
    if verdict.verdict != "UNSUPPORTED":
        print(
            "Expected UNSUPPORTED. If this is SUPPORTED, the cited page "
            "may have changed; pick another URL."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
