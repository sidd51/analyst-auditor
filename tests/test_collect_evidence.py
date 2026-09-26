"""Offline tests for first-wave search, fetch, and retrieval."""

from pathlib import Path

import httpx

from src.models import (
    PlannedQuery,
    ResearchPlan,
    SearchHit,
    SearchResponse,
)
from src.collect_evidence import collect_evidence, collect_wave2, merge_search_hits
from src.tools.fetch import ParallelFetcher
from src.tools.retrieve import PassageRetriever
from src.trace import JsonlTracer
from tests.test_config import valid_settings
from tests.test_plan_research import titan_specified


class ScriptedSearch:
    """Return prepared hits in the order queries are asked."""

    def __init__(self, by_query: dict[str, list[SearchHit]]) -> None:
        self.by_query = by_query
        self.queries: list[str] = []

    def search(self, query: str, *, max_results: int | None = None) -> SearchResponse:
        self.queries.append(query)
        return SearchResponse(
            query=query,
            hits=self.by_query[query],
            providers_attempted=["tavily"],
        )


def hit(url: str, query: str, title: str = "Story") -> SearchHit:
    return SearchHit(
        title=title,
        url=url,
        snippet="snippet",
        provider="tavily",
        query=query,
    )


def html_response(url: str, text: str) -> httpx.Response:
    body = (
        "<html><body><article>"
        f"<h1>{text}</h1><p>{text}</p>"
        "</article></body></html>"
    )
    return httpx.Response(
        200,
        content=body.encode(),
        headers={"content-type": "text/html"},
        request=httpx.Request("GET", url),
    )


def test_duplicate_hits_are_merged_in_first_seen_order() -> None:
    first = "Titan Company Managing Director 2026"
    second = "Titan Company MD appointment 2026"
    merged = merge_search_hits(
        [
            SearchResponse(
                query=first,
                hits=[
                    hit("https://example.com/a", first, "A"),
                    hit("https://example.com/b", first, "B"),
                ],
                providers_attempted=["tavily"],
            ),
            SearchResponse(
                query=second,
                hits=[
                    hit("https://example.com/a/", second, "A again"),
                    hit("https://example.com/c", second, "C"),
                ],
                providers_attempted=["tavily"],
            ),
        ]
    )

    assert [item.url for item in merged] == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]
    assert merged[0].discovered_by == [first, second]


def test_first_wave_fetches_five_pages_and_keeps_the_rest(tmp_path: Path) -> None:
    settings = valid_settings()
    tracer = JsonlTracer(tmp_path / "collect.jsonl", reset=True)
    query = "Titan Company Managing Director 2026"
    plan = ResearchPlan(
        specified=titan_specified(),
        queries=[
            PlannedQuery(
                query=query,
                targets=["full name"],
                reason="Find the current MD.",
            )
        ],
    )
    urls = [f"https://example.com/page-{index}" for index in range(7)]
    searcher = ScriptedSearch(
        {query: [hit(url, query, f"Page {url}") for url in urls]}
    )
    fetcher = ParallelFetcher(
        settings,
        tracer,
        http_get=lambda url, **_: html_response(
            url,
            "Ajoy Chawla is Managing Director of Titan Company in 2026.",
        ),
    )

    packet = collect_evidence(
        plan,
        settings,
        tracer,
        searcher=searcher,  # type: ignore[arg-type]
        fetcher=fetcher,
        retriever=PassageRetriever(settings, tracer),
    )

    assert searcher.queries == [query]
    assert packet.pages_used == 5
    assert packet.next_wave_size == 4
    assert len(packet.unused_urls) == 2
    assert packet.retrieval.passages_selected >= 1
    assert "Ajoy Chawla" in packet.retrieval.passages[0].text


def test_wave2_fetches_leftover_urls_without_searching(tmp_path: Path) -> None:
    settings = valid_settings()
    tracer = JsonlTracer(tmp_path / "wave2.jsonl", reset=True)
    query = "Titan Company Managing Director 2026"
    plan = ResearchPlan(
        specified=titan_specified(),
        queries=[
            PlannedQuery(
                query=query,
                targets=["full name"],
                reason="Find the current MD.",
            )
        ],
    )
    urls = [f"https://example.com/page-{index}" for index in range(7)]
    searcher = ScriptedSearch(
        {query: [hit(url, query, f"Page {url}") for url in urls]}
    )
    fetched_urls: list[str] = []

    def http_get(url: str, **_: object):
        fetched_urls.append(url)
        return html_response(
            url,
            "C.K. Venkataraman retired as Managing Director of Titan Company.",
        )

    fetcher = ParallelFetcher(settings, tracer, http_get=http_get)
    first = collect_evidence(
        plan,
        settings,
        tracer,
        searcher=searcher,  # type: ignore[arg-type]
        fetcher=fetcher,
        retriever=PassageRetriever(settings, tracer),
    )
    assert first.pages_used == 5
    leftovers = list(first.unused_urls)
    assert leftovers == urls[5:]

    second = collect_wave2(
        first,
        settings,
        tracer,
        ["predecessor's name"],
        fetcher=fetcher,
        retriever=PassageRetriever(settings, tracer),
    )
    assert searcher.queries == [query]
    assert second.pages_used == 7
    assert leftovers[0] in fetched_urls
    assert second.unused_urls == []
    assert any("Venkataraman" in item.text for item in second.retrieval.passages)
