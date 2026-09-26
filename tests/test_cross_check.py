"""Offline tests for batched single-source cross-check."""

from pathlib import Path

import httpx

from src.cost import CostRecord
from src.cross_check import (
    claim_domains,
    cross_check_claims,
    is_usable_independent_page,
    source_domain,
)
from src.llm import StructuredResult
from src.models import (
    AnalystClaim,
    CrossCheckDraft,
    CrossCheckItemDraft,
    FetchedPage,
    SearchHit,
    SearchResponse,
)
from src.tools.fetch import ParallelFetcher
from src.trace import JsonlTracer
from tests.test_config import valid_settings
from tests.test_plan_research import titan_specified


class ScriptedSearch:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.queries: list[str] = []

    def search(self, query: str, *, max_results: int | None = None) -> SearchResponse:
        self.queries.append(query)
        return SearchResponse(
            query=query,
            hits=self.hits,
            providers_attempted=["tavily"],
        )


class FakeLLM:
    def __init__(self, drafted: CrossCheckDraft) -> None:
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
            cost=CostRecord(100, 40, 140, 0.0002, 0.02),
            generation_id="fake-cross",
        )


def claim(*, claim_id: str = "C01", urls: list[str]) -> AnalystClaim:
    return AnalystClaim(
        claim_id=claim_id,
        field="effective date",
        text="Ajoy Chawla is MD from January 1, 2026.",
        quote="The transition will take effect on January 1, 2026.",
        passage_ids=["P0008"],
        urls=urls,
        period="2026",
    )


def page(url: str, text: str, title: str = "Story") -> FetchedPage:
    return FetchedPage(
        url=url,
        final_url=url,
        ok=True,
        kind="html",
        extractor="trafilatura",
        title=title,
        text=text,
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


def test_source_domain_treats_www_and_mobile_as_the_same_site() -> None:
    assert source_domain("https://www.marcamoney.com/a") == source_domain(
        "https://marcamoney.com/b"
    )
    assert source_domain(
        "https://hr.economictimes.indiatimes.com/a"
    ) == source_domain("https://m.economictimes.indiatimes.com/b")


def test_two_domains_are_not_cross_checked(tmp_path: Path) -> None:
    llm = FakeLLM(CrossCheckDraft(items=[]))
    result = cross_check_claims(
        [
            claim(
                urls=[
                    "https://www.marcamoney.com/a",
                    "https://hr.economictimes.indiatimes.com/b",
                ]
            )
        ],
        titan_specified(),
        valid_settings(),
        JsonlTracer(tmp_path / "x.jsonl", reset=True),
        llm=llm,  # type: ignore[arg-type]
        searcher=ScriptedSearch([]),  # type: ignore[arg-type]
    )
    assert result.value.verdicts[0].status == "skipped_multi_source"
    assert llm.calls == 0
    assert claim_domains(
        claim(
            urls=[
                "https://www.marcamoney.com/a",
                "https://hr.economictimes.indiatimes.com/b",
            ]
        )
    ) == {"marcamoney.com", "economictimes.indiatimes.com"}


def test_leadiq_error_page_is_not_usable() -> None:
    junk = page(
        "https://leadiq.com/c/error-page",
        "© LeadIQ, Inc. All rights reserved.",
        title="Get Full Access to LeadIQ Contacts",
    )
    assert is_usable_independent_page(junk, blocked=set()) is False


def test_wave1_page_is_reused_only_when_search_selects_that_url(tmp_path: Path) -> None:
    llm = FakeLLM(
        CrossCheckDraft(
            items=[
                CrossCheckItemDraft(
                    claim_id="C01",
                    support="yes",
                    reason="Same appointment date, different wording.",
                )
            ]
        )
    )
    searcher = ScriptedSearch(
        [
            SearchHit(
                title="Titan MD",
                url="https://www.marcamoney.com/md",
                snippet="",
                provider="tavily",
                query="q",
            )
        ]
    )
    long_text = (
        "The transition will take effect from January 1, 2026. "
        "Ajoy Chawla succeeds C.K. Venkataraman as Managing Director. "
    ) * 4
    result = cross_check_claims(
        [claim(urls=["https://www.indianretailer.com/story"])],
        titan_specified(),
        valid_settings(),
        JsonlTracer(tmp_path / "x.jsonl", reset=True),
        llm=llm,  # type: ignore[arg-type]
        searcher=searcher,  # type: ignore[arg-type]
        known_pages=[page("https://www.marcamoney.com/md", long_text)],
    )
    assert searcher.queries  # dedicated search still runs
    assert llm.calls == 1
    verdict = result.value.verdicts[0]
    assert verdict.status == "corroborated"
    assert verdict.evidence_origin == "reused_wave1"
    assert "C01" in llm.user_prompt
    assert "The transition will take effect on January 1, 2026." not in llm.user_prompt
    assert "Use only the independent passages" in llm.system_prompt
    assert "analyst quote" in llm.system_prompt


def test_same_domain_hits_stay_single_source_without_an_llm_call(tmp_path: Path) -> None:
    llm = FakeLLM(CrossCheckDraft(items=[]))
    result = cross_check_claims(
        [claim(urls=["https://www.marcamoney.com/story"])],
        titan_specified(),
        valid_settings(),
        JsonlTracer(tmp_path / "x.jsonl", reset=True),
        llm=llm,  # type: ignore[arg-type]
        searcher=ScriptedSearch(
            [
                SearchHit(
                    title="Mirror",
                    url="https://www.marcamoney.com/other",
                    snippet="",
                    provider="tavily",
                    query="q",
                )
            ]
        ),  # type: ignore[arg-type]
    )
    assert result.value.verdicts[0].status == "single_source"
    assert llm.calls == 0


def test_batched_conflict_maps_to_conflicting(tmp_path: Path) -> None:
    settings = valid_settings()
    tracer = JsonlTracer(tmp_path / "x.jsonl", reset=True)
    llm = FakeLLM(
        CrossCheckDraft(
            items=[
                CrossCheckItemDraft(
                    claim_id="C01",
                    support="conflict",
                    reason="Independent page says 2024 for the same role.",
                )
            ]
        )
    )
    result = cross_check_claims(
        [claim(urls=["https://www.marcamoney.com/story"])],
        titan_specified(),
        settings,
        tracer,
        llm=llm,  # type: ignore[arg-type]
        searcher=ScriptedSearch(
            [
                SearchHit(
                    title="Old",
                    url="https://example.com/old",
                    snippet="",
                    provider="tavily",
                    query="q",
                )
            ]
        ),  # type: ignore[arg-type]
        fetcher=ParallelFetcher(
            settings,
            tracer,
            http_get=lambda url, **_: html(
                url,
                (
                    "Ajoy Chawla became Managing Director of Titan Company "
                    "in 2024 after a board meeting in Mumbai. "
                )
                * 6,
            ),
        ),
    )
    assert result.value.verdicts[0].status == "conflicting"
    assert result.value.verdicts[0].evidence_origin == "new_search"
    assert llm.calls == 1
