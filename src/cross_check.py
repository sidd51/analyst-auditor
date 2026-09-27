"""Step 5: corroborate single-domain claims with one independent page."""

from __future__ import annotations

import re
from dataclasses import dataclass
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
from src.quotes import letters_only, quote_appears
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
- yes: the independent passage states the same fact about the SAME
  person or company. Wording may differ.
- no: the passage is empty, a paywall, an error page, a login wall,
  about a different person, or it does not state the claim.
- conflict: the passage gives a different value for the SAME fact
  (same person/role/period, different name, date, or number). Copy a
  short conflict_quote from that passage that contains the different
  value. If you cannot quote it, use no.
- A retirement date in 2025 does not conflict with an effective date in 2026.
- Do not assume a role is current just because a date is missing.
- Use only the supplied claim IDs.
- Judge each claim on its own.
"""

MIN_INDEPENDENT_CHARS = 200
MAX_INDEPENDENT_FETCHES = 3
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "by",
    "company",
    "for",
    "from",
    "had",
    "has",
    "have",
    "in",
    "inc",
    "is",
    "its",
    "limited",
    "ltd",
    "of",
    "on",
    "or",
    "the",
    "their",
    "this",
    "that",
    "to",
    "was",
    "were",
    "will",
    "with",
}
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z.'-]*|\d[\d,]*(?:\.\d+)?")
_NAME_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")


@dataclass(frozen=True)
class ClaimTokens:
    """Short distinctive words used to search and to reject off-topic pages."""

    numbers: tuple[str, ...]
    name_parts: tuple[str, ...]
    words: tuple[str, ...]

    def as_query(self, entity: str = "") -> str:
        parts: list[str] = []
        seen: set[str] = set()
        for token in (entity, *self.name_parts, *self.numbers, *self.words):
            cleaned = " ".join(str(token).split())
            key = cleaned.casefold()
            if not cleaned or key in seen:
                continue
            seen.add(key)
            parts.append(cleaned)
        return " ".join(parts[:10])


def claim_tokens(claims: list[AnalystClaim], entity: str = "") -> ClaimTokens:
    """Keep names, numbers, and a few content words. Drop filler."""
    texts = [entity, *[item.text for item in claims if item.text]]
    numbers: list[str] = []
    words: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for raw in _TOKEN_RE.findall(text):
            token = raw.strip(".'")
            key = token.casefold()
            if len(key) < 2 or key in _STOP_WORDS or key in seen:
                continue
            seen.add(key)
            if token[0].isdigit():
                numbers.append(token)
            else:
                words.append(token)
    names: list[str] = []
    name_seen: set[str] = set()
    for text in texts:
        for match in _NAME_RE.finditer(text):
            for part in match.group(1).split():
                key = part.casefold()
                if key in name_seen:
                    continue
                name_seen.add(key)
                names.append(part)
    return ClaimTokens(
        numbers=tuple(numbers[:6]),
        name_parts=tuple(names[:6]),
        words=tuple(words[:8]),
    )


def page_matches_claim_tokens(page: FetchedPage, tokens: ClaimTokens) -> bool:
    """A stock chart or parts catalog that only shares one number is not on topic."""
    haystack = letters_only(f"{page.title}\n{page.text}")

    def has(token: str) -> bool:
        needle = letters_only(token)
        return bool(needle) and needle in haystack

    name_hits = sum(1 for item in tokens.name_parts if has(item))
    same_person = bool(tokens.name_parts) and name_hits >= min(
        2, len(tokens.name_parts)
    )
    # Same person can still conflict on a date or number, so keep the page.
    if same_person:
        return True
    if tokens.numbers:
        if not any(has(item) for item in tokens.numbers):
            return False
        names = {item.casefold() for item in tokens.name_parts}
        topic = [item for item in tokens.words if item.casefold() not in names]
        return (not topic) or any(has(item) for item in topic)
    hits = sum(1 for item in tokens.words if has(item))
    return hits >= min(2, max(len(tokens.words), 1))


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


def _url_is_blocked(url: str, blocked: set[str]) -> bool:
    host = urlsplit(url).netloc
    domain = source_domain(url)
    return (
        is_login_wall(host)
        or is_junk_url(url)
        or not domain
        or domain in blocked
    )


def _passage_block(pages: list[FetchedPage]) -> str:
    chunks = []
    for page in pages:
        text = page.text.strip()
        if len(text) > 2_000:
            text = text[:1_999].rstrip() + "…"
        chunks.append(f"{_page_url(page)}\nTitle: {page.title}\n{text}")
    return "\n\n".join(chunks)


def _map_support(
    claim_id: str,
    support: str,
    reason: str,
    url: str | None,
    origin: str,
    *,
    conflict_quote: str = "",
    page: FetchedPage | None = None,
) -> CrossCheckVerdict:
    if support == "conflict":
        quote = conflict_quote.strip()
        if (
            not quote
            or page is None
            or not quote_appears(quote, page.text, page.title)
        ):
            return CrossCheckVerdict(
                claim_id=claim_id,
                status="single_source",
                independent_url=url,
                reason=(
                    "Conflict ignored: no quoted conflicting span "
                    "appears on the independent page."
                ),
                evidence_origin=origin,  # type: ignore[arg-type]
            )
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
    tokens = claim_tokens(loners, entity)
    query = tokens.as_query(entity) or " ".join(loners[0].text.split()[:8])
    tracer.event(
        "cross_check_search",
        query=query,
        blocked=sorted(blocked),
        tokens={
            "numbers": list(tokens.numbers),
            "name_parts": list(tokens.name_parts),
            "words": list(tokens.words),
        },
    )
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

    pages, origin = _independent_pages(
        results.hits,
        blocked=blocked,
        tokens=tokens,
        known_pages=known_pages or [],
        fetcher=fetcher,
    )

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
            _map_support(
                claim.claim_id,
                item.support,
                item.reason,
                page_url,
                origin,
                conflict_quote=item.conflict_quote,
                page=pages[0],
            )
        )

    report = CrossCheckReport(verdicts=verdicts)
    tracer.event("cross_check_report", verdicts=[item.model_dump() for item in verdicts])
    return StructuredResult(
        value=report,
        cost=judged.cost,
        generation_id=judged.generation_id,
    )


def _independent_pages(
    hits,
    *,
    blocked: set[str],
    tokens: ClaimTokens,
    known_pages: list[FetchedPage],
    fetcher: ParallelFetcher,
) -> tuple[list[FetchedPage], str]:
    """Walk search hits until one page shares claim tokens. Cap fetches."""
    fetches = 0
    for hit in hits:
        if _url_is_blocked(hit.url, blocked):
            continue
        cached = _page_by_url(known_pages, hit.url)
        if (
            cached is not None
            and is_usable_independent_page(cached, blocked)
            and page_matches_claim_tokens(cached, tokens)
        ):
            return [cached], "reused_wave1"
        if fetches >= MAX_INDEPENDENT_FETCHES:
            break
        fetches += 1
        fetched = fetcher.fetch_many([hit.url], page_limit=1)
        pages = [
            page
            for page in fetched.pages
            if is_usable_independent_page(page, blocked)
            and page_matches_claim_tokens(page, tokens)
        ]
        if pages:
            return pages, "new_search"
    return [], "none"


def _plain_report(verdicts: list[CrossCheckVerdict]) -> StructuredResult[CrossCheckReport]:
    return StructuredResult(
        value=CrossCheckReport(verdicts=verdicts),
        cost=CostRecord(0, 0, 0, 0.0, 0.0),
        generation_id="",
    )
