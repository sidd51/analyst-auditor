"""Step 5: corroborate single-domain claims with one independent page."""

from __future__ import annotations

from urllib.parse import urlsplit

from src.config import Settings
from src.cost import CostRecord
from src.llm import OpenRouterLLM, StructuredResult
from src.models import (
    AnalystClaim,
    CrossCheckDraft,
    CrossCheckReport,
    CrossCheckVerdict,
    FetchedPage,
    SpecifiedQuestion,
)
from src.tools.fetch import ParallelFetcher, is_junk_url, is_login_wall
from src.tools.search import WebSearch
from src.trace import JsonlTracer

MULTI_PART_SUFFIXES = (
    "indiatimes.com",
    "co.uk",
    "co.in",
    "com.au",
)

SUPPORT_MAP = {
    "yes": "corroborated",
    "no": "single_source",
    "conflict": "conflicting",
}

SYSTEM_PROMPT = """\
You judge whether INDEPENDENT passages support each claim.

Rules:
- Use only the independent passages. Ignore the claim wording as evidence.
- Do not treat an analyst quote as proof. If it is not in the passage, it
  does not count.
- yes: the independent passage states the same fact. Wording may differ.
- no: the passage is empty, a paywall, an error page, a login wall, or it
  does not state the claim.
- conflict: the passage gives a different value for the SAME fact
  (same person/role/period, different name, date, or number).
- A retirement date in 2025 does not conflict with an effective date in 2026.
- Do not assume a role is current just because a date is missing.
- Use only the supplied claim IDs.
- Judge each claim on its own.
"""

MIN_INDEPENDENT_CHARS = 200


def source_domain(url: str) -> str:
    """Compare news sites without treating www/m as a new publisher."""
    host = urlsplit(url.strip()).netloc.lower().rstrip(".")
    for prefix in ("www.", "m.", "mobile."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    parts = host.split(".")
    suffix = ".".join(parts[-2:]) if len(parts) >= 2 else host
    if len(parts) >= 3 and suffix in MULTI_PART_SUFFIXES:
        return ".".join(parts[-3:])
    return suffix or host


def claim_domains(claim: AnalystClaim) -> set[str]:
    return {source_domain(url) for url in claim.urls if source_domain(url)}


def _page_url(page: FetchedPage) -> str:
    return page.final_url or page.url


def is_usable_independent_page(page: FetchedPage, blocked: set[str]) -> bool:
    """A leftover wave-1 page is not enough if it is a wall or almost empty."""
    if not page.ok:
        return False
    url = _page_url(page)
    host = urlsplit(url).netloc
    domain = source_domain(url)
    if is_login_wall(host) or is_junk_url(url) or domain in blocked:
        return False
    if len(page.text.strip()) < MIN_INDEPENDENT_CHARS:
        return False
    title = page.title.casefold()
    if "get full access" in title or "sign in" in title or "log in" in title:
        return False
    return True


def _page_by_url(pages: list[FetchedPage], url: str) -> FetchedPage | None:
    target = source_domain(url) + urlsplit(url).path.rstrip("/").casefold()
    for page in pages:
        candidate = _page_url(page)
        key = source_domain(candidate) + urlsplit(candidate).path.rstrip("/").casefold()
        if key == target:
            return page
    return None


def _first_independent_url(hits, *, blocked: set[str]) -> str | None:
    for hit in hits:
        host = urlsplit(hit.url).netloc
        domain = source_domain(hit.url)
        if is_login_wall(host) or is_junk_url(hit.url) or not domain or domain in blocked:
            continue
        return hit.url
    return None


def _passage_block(pages: list[FetchedPage]) -> str:
    chunks = []
    for page in pages:
        text = page.text.strip()
        if len(text) > 2_000:
            text = text[:1_999].rstrip() + "…"
        chunks.append(f"{_page_url(page)}\nTitle: {page.title}\n{text}")
    return "\n\n".join(chunks)


def _map_support(claim_id: str, support: str, reason: str, url: str | None, origin: str) -> CrossCheckVerdict:
    return CrossCheckVerdict(
        claim_id=claim_id,
        status=SUPPORT_MAP[support],
        independent_url=url,
        reason=reason,
        evidence_origin=origin,  # type: ignore[arg-type]
    )


def cross_check_claims(
    claims: list[AnalystClaim],
    specified: SpecifiedQuestion,
    settings: Settings,
    tracer: JsonlTracer,
    *,
    llm: OpenRouterLLM | None = None,
    searcher: WebSearch | None = None,
    fetcher: ParallelFetcher | None = None,
    known_pages: list[FetchedPage] | None = None,
) -> StructuredResult[CrossCheckReport]:
    """One dedicated search, then one fetch or a cached copy of that URL."""
    searcher = searcher or WebSearch(settings, tracer)
    fetcher = fetcher or ParallelFetcher(settings, tracer)

    verdicts: list[CrossCheckVerdict] = []
    loners: list[AnalystClaim] = []
    blocked: set[str] = set()
    for claim in claims:
        domains = claim_domains(claim)
        if len(domains) != 1:
            verdicts.append(
                CrossCheckVerdict(
                    claim_id=claim.claim_id,
                    status="skipped_multi_source",
                    reason="Claim already cites more than one domain.",
                )
            )
            continue
        loners.append(claim)
        blocked.update(domains)

    if not loners:
        return _plain_report(verdicts)

    # Do not grab a random leftover wave-1 HTML page. Search for a second
    # source, then reuse a cache hit only if that exact URL is already good.
    entity = (
        specified.specification.entities[0]
        if specified.specification.entities
        else ""
    )
    query = " ".join(part for part in (entity, loners[0].text) if part).strip()
    tracer.event("cross_check_search", query=query, blocked=sorted(blocked))
    try:
        results = searcher.search(query)
    except Exception as exc:
        for claim in loners:
            verdicts.append(
                CrossCheckVerdict(
                    claim_id=claim.claim_id,
                    status="single_source",
                    reason=f"Search failed: {type(exc).__name__}: {exc}",
                )
            )
        return _plain_report(verdicts)

    other_url = _first_independent_url(results.hits, blocked=blocked)
    pages: list[FetchedPage] = []
    origin = "new_search"
    if other_url:
        cached = _page_by_url(known_pages or [], other_url)
        if cached is not None and is_usable_independent_page(cached, blocked):
            pages = [cached]
            origin = "reused_wave1"
        else:
            fetched = fetcher.fetch_many([other_url], page_limit=1)
            pages = [
                page
                for page in fetched.pages
                if is_usable_independent_page(page, blocked)
            ]

    if not pages:
        for claim in loners:
            verdicts.append(
                CrossCheckVerdict(
                    claim_id=claim.claim_id,
                    status="single_source",
                    reason="No independent page was available.",
                    evidence_origin="none",
                )
            )
        tracer.event("cross_check_report", verdicts=[item.model_dump() for item in verdicts])
        return _plain_report(verdicts)

    if llm is None:
        raise RuntimeError("cross-check needs an LLM to judge independent passages")

    claim_block = "\n".join(
        f"{claim.claim_id}: {claim.text}"
        for claim in loners
    )
    user_prompt = (
        f"As-of date: {specified.as_of_date}\n"
        f"Resolved period: {specified.resolved_time_period or 'not specified'}\n\n"
        f"Claims:\n{claim_block}\n\n"
        f"Independent passages:\n{_passage_block(pages)}\n"
    )
    judged = llm.complete_structured(
        purpose="cross_check",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=CrossCheckDraft,
    )
    by_id = {item.claim_id: item for item in judged.value.items}
    page_url = _page_url(pages[0])
    for claim in loners:
        item = by_id.get(claim.claim_id)
        if item is None or item.support not in SUPPORT_MAP:
            verdicts.append(
                CrossCheckVerdict(
                    claim_id=claim.claim_id,
                    status="single_source",
                    independent_url=page_url,
                    reason="Batched judge omitted this claim; fail closed.",
                    evidence_origin=origin,  # type: ignore[arg-type]
                )
            )
            continue
        verdicts.append(
            _map_support(claim.claim_id, item.support, item.reason, page_url, origin)
        )

    report = CrossCheckReport(verdicts=verdicts)
    tracer.event("cross_check_report", verdicts=[item.model_dump() for item in verdicts])
    return StructuredResult(
        value=report,
        cost=judged.cost,
        generation_id=judged.generation_id,
    )


def _plain_report(verdicts: list[CrossCheckVerdict]) -> StructuredResult[CrossCheckReport]:
    return StructuredResult(
        value=CrossCheckReport(verdicts=verdicts),
        cost=CostRecord(0, 0, 0, 0.0, 0.0),
        generation_id="",
    )
