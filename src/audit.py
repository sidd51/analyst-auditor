"""Independent Auditor: refetch cited URLs and judge each claim against them."""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlsplit

from src.config import Settings
from src.cost import CostRecord
from src.llm import OpenRouterLLM, StructuredResult
from src.models import (
    AnalystClaim,
    AuditDraft,
    AuditItemDraft,
    AuditReport,
    AuditSourceNote,
    ClaimAudit,
    EvidencePassage,
    FetchedPage,
    SpecifiedQuestion,
)
from src.tools.fetch import ParallelFetcher, is_junk_url, is_login_wall
from src.tools.retrieve import PassageRetriever
from src.trace import JsonlTracer

SYSTEM_PROMPT = """\
You judge whether CITED passages support each claim.

Rules:
- Use only the passages shown for that claim's cited source.
- Ignore the claim wording as evidence. Do not treat an analyst quote as proof.
- support: the passage states the same fact. Wording may differ.
- silent: the passage is empty, a paywall, an error page, or it does not
  state the claim.
- conflict: the passage gives a different value for the SAME fact
  (same person/role/period, different name, date, or number).
- A retirement date in 2025 does not conflict with an effective date in 2026.
- Do not assume a role is current just because a date is missing.
- Judge each (claim_id, source_id) pair on its own.
- Use only the supplied claim IDs and source IDs.
- Do not decide whether the overall answer is complete.
"""

SUPPORT_LABELS = {"support", "silent", "conflict"}
AUDIT_TOKEN_BUDGET_PER_CLAIM = 1_200


def unique_cited_urls(claims: list[AnalystClaim]) -> list[str]:
    """Keep citation order and drop blanks or repeats."""
    seen: set[str] = set()
    urls: list[str] = []
    for claim in claims:
        for url in claim.urls:
            clean = url.strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            urls.append(clean)
    return urls


def assign_source_ids(urls: list[str]) -> dict[str, str]:
    """Stable S01… labels so the model does not have to echo full URLs."""
    return {url: f"S{index:02d}" for index, url in enumerate(urls, start=1)}


def is_usable_cited_page(page: FetchedPage) -> bool:
    """A refetch is only useful if it is open, non-junk, and has body text."""
    if not page.ok or not page.text.strip():
        return False
    url = page.final_url or page.url
    host = urlsplit(url).netloc
    if is_login_wall(host) or is_junk_url(url):
        return False
    title = page.title.casefold()
    if "get full access" in title or "sign in" in title or "log in" in title:
        return False
    return True


def finalize_audit(
    claims: list[AnalystClaim],
    notes: list[AuditSourceNote],
) -> list[ClaimAudit]:
    """Roll per-source notes into one claim verdict. Silence is not conflict."""
    by_claim: dict[str, list[AuditSourceNote]] = defaultdict(list)
    for note in notes:
        by_claim[note.claim_id].append(note)

    verdicts: list[ClaimAudit] = []
    for claim in claims:
        cited = [url.strip() for url in claim.urls if url.strip()]
        claim_notes = by_claim[claim.claim_id]
        if not cited:
            verdicts.append(
                ClaimAudit(
                    claim_id=claim.claim_id,
                    verdict="UNCITED",
                    reason="Claim cites no URLs.",
                )
            )
            continue

        conflicts = [note for note in claim_notes if note.support == "conflict"]
        supports = [note for note in claim_notes if note.support == "support"]
        if conflicts:
            verdict = "CONTRADICTED"
            reason = conflicts[0].reason
        elif supports:
            verdict = "SUPPORTED"
            reason = supports[0].reason
        else:
            verdict = "UNSUPPORTED"
            reason = (
                claim_notes[0].reason
                if claim_notes
                else "Cited pages could not be verified."
            )
        verdicts.append(
            ClaimAudit(
                claim_id=claim.claim_id,
                verdict=verdict,
                reason=reason,
                source_notes=claim_notes,
            )
        )
    return verdicts


def audit_claims(
    claims: list[AnalystClaim],
    specified: SpecifiedQuestion,
    settings: Settings,
    tracer: JsonlTracer,
    *,
    llm: OpenRouterLLM | None = None,
    fetcher: ParallelFetcher | None = None,
    retriever: PassageRetriever | None = None,
) -> StructuredResult[AuditReport]:
    """Refetch every unique citation, then judge all claims in one LLM batch.

    The Analyst page cache is never reused. Completeness is not decided here.
    """
    fetcher = fetcher or ParallelFetcher(settings, tracer)
    retriever = retriever or PassageRetriever(settings, tracer)

    cited = unique_cited_urls(claims)
    source_ids = assign_source_ids(cited)
    notes: list[AuditSourceNote] = []
    judged_cost = CostRecord(0, 0, 0, 0.0, 0.0)
    generation_id = ""
    urls_refetched: list[str] = []
    urls_skipped: list[str] = []

    pages_by_url: dict[str, FetchedPage] = {}
    if cited:
        page_limit = min(len(cited), settings.absolute_page_ceiling)
        fetched = fetcher.fetch_many(cited, page_limit=page_limit)
        selected = {page.url for page in fetched.pages}
        urls_refetched = [url for url in cited if url in selected]
        urls_skipped = [url for url in cited if url not in selected]
        for page in fetched.pages:
            pages_by_url[page.url] = page
            if page.final_url:
                pages_by_url[page.final_url] = page

    # Pairs that have retrieved text go to the model. The rest stay silent.
    pending: list[tuple[AnalystClaim, str, str, list[EvidencePassage]]] = []
    next_passage = 1
    for claim in claims:
        pending_for_claim, next_passage = _collect_claim_pairs(
            claim,
            source_ids,
            pages_by_url,
            retriever,
            notes,
            next_passage,
        )
        pending.extend(pending_for_claim)

    if pending:
        if llm is None:
            raise RuntimeError("auditor needs an LLM to judge cited passages")
        judged = llm.complete_structured(
            purpose="audit_claims",
            system_prompt=SYSTEM_PROMPT,
            user_prompt=_user_prompt(specified, pending),
            schema=AuditDraft,
        )
        judged_cost = judged.cost
        generation_id = judged.generation_id
        notes.extend(_apply_judgments(pending, judged.value.items))

    report = AuditReport(
        verdicts=finalize_audit(claims, notes),
        urls_refetched=urls_refetched,
        urls_skipped=urls_skipped,
    )
    tracer.event(
        "audit_report",
        verdicts=[item.model_dump() for item in report.verdicts],
        urls_refetched=urls_refetched,
        urls_skipped=urls_skipped,
    )
    return StructuredResult(
        value=report,
        cost=judged_cost,
        generation_id=generation_id,
    )


def _collect_claim_pairs(
    claim: AnalystClaim,
    source_ids: dict[str, str],
    pages_by_url: dict[str, FetchedPage],
    retriever: PassageRetriever,
    notes: list[AuditSourceNote],
    next_passage: int,
) -> tuple[list[tuple[AnalystClaim, str, str, list[EvidencePassage]]], int]:
    pending: list[tuple[AnalystClaim, str, str, list[EvidencePassage]]] = []
    cited = [url.strip() for url in claim.urls if url.strip()]
    if not cited:
        return pending, next_passage

    usable: list[tuple[str, str, FetchedPage]] = []
    for url in cited:
        source_id = source_ids[url]
        page = pages_by_url.get(url)
        if page is None:
            notes.append(
                _note(
                    claim.claim_id,
                    source_id,
                    url,
                    "silent",
                    "Cited page was skipped or not refetched.",
                    available=False,
                )
            )
            continue
        if not is_usable_cited_page(page):
            why = page.error or "empty, paywall, or unusable refetch"
            notes.append(
                _note(
                    claim.claim_id,
                    source_id,
                    url,
                    "silent",
                    f"Cited page could not be read: {why}",
                    available=False,
                )
            )
            continue
        usable.append((source_id, url, page))

    if not usable:
        return pending, next_passage

    retrieved = retriever.retrieve(
        [page for _, _, page in usable],
        question=claim.text,
        requirements=[
            part
            for part in (claim.field, claim.period or "")
            if part.strip()
        ],
        token_budget=AUDIT_TOKEN_BUDGET_PER_CLAIM,
    )
    remapped, next_passage = _renumber(retrieved.passages, next_passage)
    by_page_url = _group_passages(remapped)

    for source_id, url, page in usable:
        passages = by_page_url.get(_page_key(page), [])
        if not passages:
            notes.append(
                _note(
                    claim.claim_id,
                    source_id,
                    url,
                    "silent",
                    "No relevant passage was retrieved from the refetch.",
                    passage_ids=[],
                )
            )
            continue
        pending.append((claim, source_id, url, passages))
    return pending, next_passage


def _apply_judgments(
    pending: list[tuple[AnalystClaim, str, str, list[EvidencePassage]]],
    items: list[AuditItemDraft],
) -> list[AuditSourceNote]:
    by_pair = {(item.claim_id, item.source_id): item for item in items}
    notes: list[AuditSourceNote] = []
    for claim, source_id, url, passages in pending:
        passage_ids = [item.passage_id for item in passages]
        item = by_pair.get((claim.claim_id, source_id))
        if item is None or item.support not in SUPPORT_LABELS:
            notes.append(
                _note(
                    claim.claim_id,
                    source_id,
                    url,
                    "silent",
                    "Batched judge omitted this pair; fail closed.",
                    passage_ids=passage_ids,
                )
            )
            continue
        notes.append(
            _note(
                claim.claim_id,
                source_id,
                url,
                item.support,
                item.reason,
                passage_ids=passage_ids,
            )
        )
    return notes


def _user_prompt(
    specified: SpecifiedQuestion,
    pending: list[tuple[AnalystClaim, str, str, list[EvidencePassage]]],
) -> str:
    blocks: list[str] = []
    pairs: list[str] = []
    seen_claims: set[str] = set()
    for claim, source_id, url, passages in pending:
        if claim.claim_id not in seen_claims:
            period = claim.period or "not specified"
            blocks.append(
                f"{claim.claim_id} [{claim.field}] period={period}\n"
                f"Claim: {claim.text}"
            )
            seen_claims.add(claim.claim_id)
        passage_text = "\n".join(
            f"{item.passage_id} | Title: {item.title}\n{item.text}"
            for item in passages
        )
        blocks.append(f"  {source_id} | {url}\n{passage_text}")
        pairs.append(f"- {claim.claim_id} {source_id}")

    return (
        f"As-of date: {specified.as_of_date}\n"
        f"Resolved period: {specified.resolved_time_period or 'not specified'}\n\n"
        + "\n\n".join(blocks)
        + "\n\nPairs to judge:\n"
        + "\n".join(pairs)
        + "\n"
    )


def _renumber(
    passages: list[EvidencePassage],
    start: int,
) -> tuple[list[EvidencePassage], int]:
    remapped: list[EvidencePassage] = []
    number = start
    for passage in passages:
        remapped.append(passage.model_copy(update={"passage_id": f"A{number:04d}"}))
        number += 1
    return remapped, number


def _group_passages(
    passages: list[EvidencePassage],
) -> dict[str, list[EvidencePassage]]:
    grouped: dict[str, list[EvidencePassage]] = defaultdict(list)
    for passage in passages:
        grouped[_normalize_url(passage.url)].append(passage)
    return grouped


def _page_key(page: FetchedPage) -> str:
    return _normalize_url(page.final_url or page.url)


def _normalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    return (
        f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        f"{parsed.path.rstrip('/') or '/'}"
    )


def _note(
    claim_id: str,
    source_id: str,
    url: str,
    support: str,
    reason: str,
    *,
    passage_ids: list[str] | None = None,
    available: bool = True,
) -> AuditSourceNote:
    return AuditSourceNote(
        claim_id=claim_id,
        source_id=source_id,
        url=url,
        support=support,  # type: ignore[arg-type]
        reason=reason,
        passage_ids=passage_ids or [],
        available=available,
    )
