"""Offline tests for independent citation audit."""

from pathlib import Path

import httpx

from src.audit import (
    assign_source_ids,
    audit_claims,
    finalize_audit,
    unique_cited_urls,
)
from src.cost import CostRecord
from src.llm import StructuredResult
from src.models import (
    AnalystClaim,
    AuditDraft,
    AuditItemDraft,
    AuditSourceNote,
)
from src.tools.fetch import ParallelFetcher
from src.trace import JsonlTracer
from tests.test_config import valid_settings
from tests.test_plan_research import titan_specified

QUOTE = "The transition will take effect on January 1, 2026."
SUPPORTING_BODY = (
    "Ajoy Chawla succeeds C.K. Venkataraman as Managing Director of "
    "Titan Company. The appointment is effective January 1, 2026. "
) * 4
UNRELATED_BODY = (
    "Retail store traffic in Mumbai rose after the festival season. "
    "Jewellery demand stayed steady across several city malls. "
) * 4


class FakeLLM:
    def __init__(self, drafted: AuditDraft) -> None:
        self.drafted = drafted
        self.calls = 0
        self.system_prompt = ""
        self.user_prompt = ""

    def complete_structured(self, **kwargs: object) -> StructuredResult:
        self.calls += 1
        self.system_prompt = str(kwargs.get("system_prompt") or "")
        self.user_prompt = str(kwargs.get("user_prompt") or "")
        return StructuredResult(
            value=self.drafted,
            cost=CostRecord(120, 50, 170, 0.0003, 0.03),
            generation_id="fake-audit",
        )


def claim(
    *,
    claim_id: str = "C01",
    urls: list[str],
    text: str = "Ajoy Chawla is MD from January 1, 2026.",
) -> AnalystClaim:
    return AnalystClaim(
        claim_id=claim_id,
        field="effective date",
        text=text,
        quote=QUOTE,
        passage_ids=["P0008"],
        urls=urls,
        period="2026",
    )


def html(url: str, body: str, title: str = "Story") -> httpx.Response:
    markup = (
        f"<html><head><title>{title}</title></head>"
        f"<body><article><h1>{title}</h1><p>{body}</p></article></body></html>"
    )
    return httpx.Response(
        200,
        content=markup.encode(),
        headers={"content-type": "text/html"},
        request=httpx.Request("GET", url),
    )


def pages(*pairs: tuple[str, str]):
    bodies = dict(pairs)

    def http_get(url: str, **_: object) -> httpx.Response:
        return html(url, bodies[url])

    return http_get


def run_audit(
    tmp_path: Path,
    claims: list[AnalystClaim],
    drafted: AuditDraft,
    http_get,
) -> tuple[StructuredResult, FakeLLM]:
    settings = valid_settings()
    tracer = JsonlTracer(tmp_path / "audit.jsonl", reset=True)
    llm = FakeLLM(drafted)
    result = audit_claims(
        claims,
        titan_specified(),
        settings,
        tracer,
        llm=llm,  # type: ignore[arg-type]
        fetcher=ParallelFetcher(settings, tracer, http_get=http_get),
    )
    return result, llm


def test_unique_urls_keep_order_and_source_ids() -> None:
    urls = unique_cited_urls(
        [
            claim(urls=["https://et.example/a", "https://titan.example/b"]),
            claim(
                claim_id="C02",
                urls=["https://titan.example/b", "https://et.example/a"],
            ),
        ]
    )
    assert urls == ["https://et.example/a", "https://titan.example/b"]
    assert assign_source_ids(urls)["https://titan.example/b"] == "S02"


def test_uncited_claim_needs_no_llm_or_fetch(tmp_path: Path) -> None:
    settings = valid_settings()
    tracer = JsonlTracer(tmp_path / "audit.jsonl", reset=True)
    llm = FakeLLM(AuditDraft(items=[]))

    def boom(url: str, **_: object) -> httpx.Response:
        raise AssertionError(f"should not fetch {url}")

    result = audit_claims(
        [claim(urls=[])],
        titan_specified(),
        settings,
        tracer,
        llm=llm,  # type: ignore[arg-type]
        fetcher=ParallelFetcher(settings, tracer, http_get=boom),
    )
    assert result.value.verdicts[0].verdict == "UNCITED"
    assert llm.calls == 0


def test_support_plus_silent_second_url_is_supported(tmp_path: Path) -> None:
    et = "https://et.example/md"
    pdf = "https://titan.example/report"
    result, llm = run_audit(
        tmp_path,
        [claim(urls=[et, pdf])],
        AuditDraft(
            items=[
                AuditItemDraft(
                    claim_id="C01",
                    source_id="S01",
                    support="support",
                    reason="Same January 2026 appointment.",
                )
            ]
        ),
        pages((et, SUPPORTING_BODY), (pdf, UNRELATED_BODY)),
    )
    verdict = result.value.verdicts[0]
    assert verdict.verdict == "SUPPORTED"
    assert llm.calls == 1
    assert QUOTE not in llm.user_prompt
    assert "Do not treat an analyst quote as proof" in llm.system_prompt
    notes = {note.source_id: note.support for note in verdict.source_notes}
    assert notes["S01"] == "support"
    assert notes["S02"] == "silent"


def test_mixed_support_and_conflict_is_contradicted(tmp_path: Path) -> None:
    et = "https://et.example/md"
    other = "https://news.example/old"
    result, llm = run_audit(
        tmp_path,
        [claim(urls=[et, other])],
        AuditDraft(
            items=[
                AuditItemDraft(
                    claim_id="C01",
                    source_id="S01",
                    support="support",
                    reason="ET states January 2026.",
                ),
                AuditItemDraft(
                    claim_id="C01",
                    source_id="S02",
                    support="conflict",
                    reason="Other page says April 2026 for the same start.",
                ),
            ]
        ),
        pages((et, SUPPORTING_BODY), (other, SUPPORTING_BODY)),
    )
    assert result.value.verdicts[0].verdict == "CONTRADICTED"
    assert llm.calls == 1


def test_omitted_judgment_fails_closed_as_unsupported(tmp_path: Path) -> None:
    url = "https://et.example/md"
    result, llm = run_audit(
        tmp_path,
        [claim(urls=[url])],
        AuditDraft(items=[]),
        pages((url, SUPPORTING_BODY)),
    )
    assert result.value.verdicts[0].verdict == "UNSUPPORTED"
    assert "fail closed" in result.value.verdicts[0].reason
    assert llm.calls == 1


def test_junk_citation_is_unsupported_without_llm(tmp_path: Path) -> None:
    settings = valid_settings()
    tracer = JsonlTracer(tmp_path / "audit.jsonl", reset=True)
    llm = FakeLLM(AuditDraft(items=[]))

    def boom(url: str, **_: object) -> httpx.Response:
        raise AssertionError(f"should not fetch junk {url}")

    result = audit_claims(
        [claim(urls=["https://leadiq.com/c/error-page"])],
        titan_specified(),
        settings,
        tracer,
        llm=llm,  # type: ignore[arg-type]
        fetcher=ParallelFetcher(settings, tracer, http_get=boom),
    )
    assert result.value.verdicts[0].verdict == "UNSUPPORTED"
    assert llm.calls == 0
    assert result.value.urls_skipped == ["https://leadiq.com/c/error-page"]


def test_finalize_rollup_rules() -> None:
    support = AuditSourceNote(
        claim_id="C01",
        source_id="S01",
        url="https://et.example/a",
        support="support",
        reason="Matches.",
    )
    silent = AuditSourceNote(
        claim_id="C01",
        source_id="S02",
        url="https://titan.example/b",
        support="silent",
        reason="No date.",
    )
    conflict = AuditSourceNote(
        claim_id="C01",
        source_id="S02",
        url="https://news.example/c",
        support="conflict",
        reason="Different date.",
    )
    supported = finalize_audit([claim(urls=["https://a", "https://b"])], [support, silent])
    assert supported[0].verdict == "SUPPORTED"
    contradicted = finalize_audit(
        [claim(urls=["https://a", "https://c"])],
        [support, conflict],
    )
    assert contradicted[0].verdict == "CONTRADICTED"
    uncited = finalize_audit([claim(urls=[])], [])
    assert uncited[0].verdict == "UNCITED"
