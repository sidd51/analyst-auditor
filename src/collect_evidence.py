"""Step 4C: run the plan, fetch the first page wave, and retrieve passages."""

from __future__ import annotations

import argparse
import sys

from src.config import Settings, load_settings
from src.llm import OpenRouterLLM
from src.models import (
    CandidateUrl,
    EvidencePacket,
    FetchResponse,
    ResearchPlan,
    SearchResponse,
)
from src.page_budget import next_fetch_wave
from src.plan_research import plan_research
from src.specify import specify_question
from src.tools.fetch import ParallelFetcher
from src.tools.retrieve import PassageRetriever
from src.tools.search import WebSearch, _url_key
from src.trace import JsonlTracer


def merge_search_hits(searches: list[SearchResponse]) -> list[CandidateUrl]:
    """Keep first-seen URL order and record every query that found it."""
    by_key: dict[str, CandidateUrl] = {}
    order: list[str] = []
    for response in searches:
        for hit in response.hits:
            key = _url_key(hit.url)
            if not key:
                continue
            if key not in by_key:
                by_key[key] = CandidateUrl(
                    url=hit.url,
                    title=hit.title,
                    snippet=hit.snippet,
                    discovered_by=[response.query],
                    providers=[hit.provider],
                )
                order.append(key)
                continue
            existing = by_key[key]
            if response.query not in existing.discovered_by:
                existing.discovered_by.append(response.query)
            if hit.provider not in existing.providers:
                existing.providers.append(hit.provider)
    return [by_key[key] for key in order]


def collect_evidence(
    plan: ResearchPlan,
    settings: Settings,
    tracer: JsonlTracer,
    *,
    searcher: WebSearch | None = None,
    fetcher: ParallelFetcher | None = None,
    retriever: PassageRetriever | None = None,
) -> EvidencePacket:
    """Search sequentially, fetch wave 1, then keep only relevant passages.

    Later leftovers stay in unused_urls. Wave 2 runs only after Analyst 1
    if a required field is still missing.
    """
    searcher = searcher or WebSearch(settings, tracer)
    fetcher = fetcher or ParallelFetcher(settings, tracer)
    retriever = retriever or PassageRetriever(settings, tracer)

    searches: list[SearchResponse] = []
    # Search stays sequential. Parallel DDGS/Tavily calls previously
    # increased timeouts and rate limits.
    for item in plan.queries:
        tracer.event(
            "planned_search",
            query=item.query,
            targets=item.targets,
            reason=item.reason,
        )
        searches.append(searcher.search(item.query))

    candidates = merge_search_hits(searches)
    wave_size = next_fetch_wave(0, settings)
    fetched = fetcher.fetch_many(
        [item.url for item in candidates],
        page_limit=wave_size,
    )
    pages_used = fetched.selected_count
    fetched_keys = {_url_key(page.url) for page in fetched.pages}
    unused_urls = [
        item.url for item in candidates if _url_key(item.url) not in fetched_keys
    ]

    spec = plan.specified.specification
    retrieval = retriever.retrieve(
        fetched.pages,
        question=plan.specified.question,
        requirements=spec.required_fields + plan.specified.notes,
    )
    packet = EvidencePacket(
        plan=plan,
        searches=searches,
        candidates=candidates,
        fetched=fetched,
        retrieval=retrieval,
        pages_used=pages_used,
        next_wave_size=next_fetch_wave(pages_used, settings),
        unused_urls=unused_urls,
    )
    tracer.event(
        "evidence_packet",
        candidate_count=len(candidates),
        pages_used=pages_used,
        next_wave_size=packet.next_wave_size,
        unused_urls=unused_urls,
        passages_selected=retrieval.passages_selected,
    )
    return packet


def collect_wave2(
    packet: EvidencePacket,
    settings: Settings,
    tracer: JsonlTracer,
    gap_fields: list[str],
    *,
    fetcher: ParallelFetcher | None = None,
    retriever: PassageRetriever | None = None,
) -> EvidencePacket:
    """Fetch the next leftover pages. No new search. Stop after this wave."""
    wave_size = next_fetch_wave(packet.pages_used, settings)
    if wave_size <= 0 or not packet.unused_urls:
        return packet

    fetcher = fetcher or ParallelFetcher(settings, tracer)
    retriever = retriever or PassageRetriever(settings, tracer)
    fetched = fetcher.fetch_many(packet.unused_urls, page_limit=wave_size)
    fetched_keys = {_url_key(page.url) for page in fetched.pages}
    unused_urls = [
        url for url in packet.unused_urls if _url_key(url) not in fetched_keys
    ]
    pages_used = packet.pages_used + fetched.selected_count
    merged = FetchResponse(
        requested_count=packet.fetched.requested_count + fetched.requested_count,
        selected_count=packet.fetched.selected_count + fetched.selected_count,
        skipped_count=packet.fetched.skipped_count + fetched.skipped_count,
        pages=[*packet.fetched.pages, *fetched.pages],
    )
    retrieval = retriever.retrieve(
        fetched.pages,
        question=packet.plan.specified.question,
        requirements=gap_fields + packet.plan.specified.notes,
    )
    updated = packet.model_copy(
        update={
            "fetched": merged,
            "retrieval": retrieval,
            "pages_used": pages_used,
            "next_wave_size": next_fetch_wave(pages_used, settings),
            "unused_urls": unused_urls,
        }
    )
    tracer.event(
        "wave2_packet",
        gap_fields=gap_fields,
        pages_fetched=fetched.selected_count,
        pages_used=pages_used,
        unused_urls=unused_urls,
        passages_selected=retrieval.passages_selected,
    )
    return updated


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Specify, plan, search, and fetch wave 1. "
            "This makes two paid model calls plus live web requests."
        )
    )
    parser.add_argument("question")
    parser.add_argument(
        "--note",
        action="append",
        default=[],
        help="Repeat this option for extra required fields or constraints.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = load_settings()
    trace_path = settings.root / "logs" / "step4-collect.jsonl"
    tracer = JsonlTracer(trace_path, reset=True)
    llm = OpenRouterLLM(settings, tracer)

    tracer.event("run_start", step="step4c_collect", question=args.question)
    try:
        specified = specify_question(args.question, args.note, settings, llm)
        planned = plan_research(specified.value, settings, llm)
        packet = collect_evidence(planned.value, settings, tracer)
    except Exception as exc:
        tracer.event("run_end", ok=False)
        print(f"FAIL: {type(exc).__name__}: {exc}")
        print(f"Trace: {trace_path}")
        return 1

    tracer.event(
        "run_end",
        ok=True,
        specify_cost=specified.cost.as_dict(),
        plan_cost=planned.cost.as_dict(),
    )
    _print_packet(packet)
    print(
        "Specify tokens: "
        f"{specified.cost.total_tokens} | "
        f"Plan tokens: {planned.cost.total_tokens}"
    )
    print(
        "Estimated LLM cost: "
        f"${specified.cost.cost_usd + planned.cost.cost_usd:.8f} / "
        f"₹{specified.cost.cost_inr + planned.cost.cost_inr:.6f}"
    )
    print(f"Trace: {trace_path}")
    return 0 if packet.retrieval.passages else 1


def _print_packet(packet: EvidencePacket) -> None:
    """Print a short review, not the full downloaded pages."""
    print(f"Queries searched: {len(packet.searches)}")
    for index, search in enumerate(packet.searches, start=1):
        print(
            f"  {index}. {search.query!r} → {len(search.hits)} hits "
            f"({', '.join(search.providers_attempted)})"
        )
    print(
        f"Unique URLs: {len(packet.candidates)} | "
        f"Wave 1 fetched: {packet.pages_used} | "
        f"Unused: {len(packet.unused_urls)} | "
        f"Next wave size: {packet.next_wave_size}"
    )
    ok_pages = sum(1 for page in packet.fetched.pages if page.ok)
    print(f"Fetched pages OK: {ok_pages}/{len(packet.fetched.pages)}")
    for page in packet.fetched.pages:
        status = "ok" if page.ok else f"fail ({page.error})"
        print(f"  - {status} {page.final_url or page.url}")
    retrieval = packet.retrieval
    print(
        f"Passages: {retrieval.passages_selected}/"
        f"{retrieval.passages_considered} selected | "
        f"Tokens: {retrieval.estimated_tokens}/{retrieval.token_budget}"
    )
    for passage in retrieval.passages:
        print(
            f"- {passage.passage_id} score={passage.relevance_score} "
            f"tokens≈{passage.estimated_tokens}"
        )
        print(f"  {passage.url}")
        print(f"  matched: {', '.join(passage.matched_terms)}")
        print(f"  {passage.text[:400]}")


if __name__ == "__main__":
    sys.exit(main())
