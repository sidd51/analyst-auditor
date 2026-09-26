"""Step 4D: turn selected passages into supported claims only."""

from __future__ import annotations

import argparse
import sys

from src.audit import audit_claims
from src.collect_evidence import collect_evidence, collect_wave2
from src.config import Settings, load_settings
from src.cross_check import cross_check_claims
from src.gate import close_answer, render_answer
from src.llm import OpenRouterLLM, StructuredResult
from src.memory import EntityMemory
from src.models import (
    AnalystClaim,
    AnalystDraft,
    AnalystResult,
    DraftClaim,
    DraftUnanswered,
    EvidencePacket,
    SpecifiedQuestion,
    UnansweredField,
)
from src.plan_research import plan_research
from src.quotes import quote_appears
from src.specify import specify_question
from src.trace import JsonlTracer

SYSTEM_PROMPT = """\
You extract supported facts from evidence passages.

Rules:
- Emit a claim only when a passage states an actual fact, not a plan.
- Words such as will, plans, targets, aims, or anticipates are not enough.
- The fact must fit the resolved time period and geography.
- Copy an exact quote from the passage body or its title. Do not paraphrase.
- Use only the supplied passage IDs.
- One fact per claim. Do not combine several companies into one sentence.
- If a required field or requested rank is not supported, list it under
  unanswered with a short reason. Do not invent a value.
- Do not force a top-N ranking. Return only the rows the passages support.
- A single in-window "opened" or "added" number is still a claim even if
  you cannot complete the full ranking or requested count.
- Write at most three short notes. Notes may mention plans. Notes are not claims.
- Do not decide whether the answer is complete.
"""


def finalize_analyst(
    packet: EvidencePacket,
    drafted: AnalystDraft,
    settings: Settings | None = None,
) -> AnalystResult:
    """Keep only quoted, in-passage claims and fill missing required fields."""
    passages = {item.passage_id: item for item in packet.retrieval.passages}
    claims: list[AnalystClaim] = []
    dropped = 0

    for draft in drafted.claims:
        kept = _keep_claim(draft, passages, len(claims) + 1)
        if kept is None:
            dropped += 1
            continue
        claims.append(kept)

    unanswered = _coverage_records(packet, claims, drafted)
    note_limit = settings.max_analyst_notes if settings else 3
    note_chars = settings.max_analyst_note_chars if settings else 220
    notes = _trim_notes(drafted.notes, limit=note_limit, max_chars=note_chars)
    return AnalystResult(
        claims=claims,
        unanswered=unanswered,
        notes=notes,
        dropped_drafts=dropped,
    )


def _keep_claim(
    draft: DraftClaim,
    passages: dict,
    number: int,
) -> AnalystClaim | None:
    matched_ids: list[str] = []
    urls: list[str] = []
    for passage_id in draft.passage_ids:
        passage = passages.get(passage_id)
        if passage is None:
            continue
        if not quote_appears(draft.quote, passage.text, passage.title):
            continue
        if passage_id not in matched_ids:
            matched_ids.append(passage_id)
            if passage.url not in urls:
                urls.append(passage.url)
    if not matched_ids or not draft.text.strip() or not draft.quote.strip():
        return None
    return AnalystClaim(
        claim_id=f"C{number:02d}",
        field=draft.field.strip(),
        text=draft.text.strip(),
        quote=draft.quote.strip(),
        passage_ids=matched_ids,
        urls=urls,
        period=(draft.period or "").strip() or None,
    )


def _trim_notes(notes: list[str], *, limit: int = 3, max_chars: int = 220) -> list[str]:
    """Keep notes short so they cannot drown the supported claims."""
    cleaned: list[str] = []
    for note in notes:
        text = " ".join(note.split())
        if not text:
            continue
        if len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _coverage_records(
    packet: EvidencePacket,
    claims: list[AnalystClaim],
    drafted: AnalystDraft,
) -> list[UnansweredField]:
    spec = packet.plan.specified.specification
    covered = {claim.field.casefold() for claim in claims}
    records: list[UnansweredField] = []
    seen: set[str] = set()

    for item in drafted.unanswered:
        key = item.field.casefold()
        if key in covered or key in seen:
            continue
        records.append(UnansweredField(field=item.field.strip(), reason=item.reason.strip()))
        seen.add(key)

    for field in spec.required_fields:
        key = field.casefold()
        if key in covered or key in seen:
            continue
        records.append(
            UnansweredField(
                field=field,
                reason="No supported quoted evidence in the selected passages.",
            )
        )
        seen.add(key)

    if (
        spec.ranking
        and spec.required_count
        and len(claims) < spec.required_count
        and "requested count" not in seen
    ):
        records.append(
            UnansweredField(
                field="requested count",
                reason=(
                    f"Passages supported {len(claims)} result(s); "
                    f"{spec.required_count} were requested."
                ),
            )
        )
    return records


def missing_required_fields(
    result: AnalystResult,
    specified: SpecifiedQuestion,
) -> list[str]:
    """Required spec fields that still have no quoted claim."""
    covered = {claim.field.casefold() for claim in result.claims}
    return [
        field
        for field in specified.specification.required_fields
        if field.casefold() not in covered
    ]


def should_fetch_wave2(
    packet: EvidencePacket,
    result: AnalystResult,
    settings: Settings,
) -> bool:
    """One extra wave only when a required field is open and leftovers remain."""
    if not packet.unused_urls or packet.next_wave_size <= 0:
        return False
    return bool(missing_required_fields(result, packet.plan.specified))


def merge_analyst_results(
    first: AnalystResult,
    second: AnalystResult,
    packet: EvidencePacket,
    settings: Settings | None = None,
) -> AnalystResult:
    """Keep wave-1 claims and append new quoted facts with fresh IDs."""
    claims = list(first.claims)
    seen = {claim.text.casefold() for claim in claims}
    for claim in second.claims:
        if claim.text.casefold() in seen:
            continue
        seen.add(claim.text.casefold())
        claims.append(
            claim.model_copy(update={"claim_id": f"C{len(claims) + 1:02d}"})
        )
    unanswered = _coverage_records(
        packet,
        claims,
        AnalystDraft(
            unanswered=[
                DraftUnanswered(field=item.field, reason=item.reason)
                for item in (*first.unanswered, *second.unanswered)
            ]
        ),
    )
    notes = _trim_notes(
        [*first.notes, *second.notes],
        limit=settings.max_analyst_notes if settings else 3,
        max_chars=settings.max_analyst_note_chars if settings else 220,
    )
    return AnalystResult(
        claims=claims,
        unanswered=unanswered,
        notes=notes,
        dropped_drafts=first.dropped_drafts + second.dropped_drafts,
    )


def analyze_evidence(
    packet: EvidencePacket,
    settings: Settings,
    llm: OpenRouterLLM,
    *,
    focus_fields: list[str] | None = None,
) -> StructuredResult[AnalystResult]:
    """Ask the model for drafts, then keep only fail-closed supported claims."""
    specified = packet.plan.specified
    spec = specified.specification
    passage_block = "\n\n".join(
        (
            f"{item.passage_id} | {item.url}\nTitle: {item.title}\n{item.text}"
            for item in packet.retrieval.passages
        )
        or ["No passages were selected."]
    )
    required = ", ".join(focus_fields or spec.required_fields)
    focus_line = ""
    if focus_fields:
        focus_line = (
            f"Focus only on these still-missing fields: {required}\n"
            "Do not repeat facts already found for other fields.\n"
        )
    user_prompt = (
        f"Question:\n{specified.question}\n\n"
        f"As-of date: {specified.as_of_date}\n"
        f"Resolved time period: {specified.resolved_time_period or 'not specified'}\n"
        f"Entities: {', '.join(spec.entities)}\n"
        f"Required fields: {required}\n"
        f"{focus_line}"
        f"Geography: {spec.geography or 'not specified'}\n"
        f"Required count: {spec.required_count or 'not specified'}\n"
        f"Ranking: {spec.ranking}\n"
        f"Not-found rule: {spec.not_found_rule}\n\n"
        f"Evidence passages:\n{passage_block}\n"
    )
    drafted = llm.complete_structured(
        purpose="analyze_evidence",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=AnalystDraft,
    )
    result = finalize_analyst(packet, drafted.value, settings)
    return StructuredResult(
        value=result,
        cost=drafted.cost,
        generation_id=drafted.generation_id,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Specify, plan, collect, extract claims, optional wave 2, "
            "cross-check, then audit. Up to six paid model calls plus live web."
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
    trace_path = settings.root / "logs" / "step4-analyze.jsonl"
    tracer = JsonlTracer(trace_path, reset=True)
    llm = OpenRouterLLM(settings, tracer)

    tracer.event("run_start", step="step4d_analyze", question=args.question)
    memory = EntityMemory.load(settings)
    try:
        specified = specify_question(args.question, args.note, settings, llm)
        recalled = memory.recall(
            specified.value,
            limit=settings.max_memory_prompt_items,
        )
        planned = plan_research(
            specified.value,
            settings,
            llm,
            known_facts=recalled.known_facts,
            disputed_notes=recalled.disputed_notes,
            rejected_notes=recalled.rejected_notes,
        )
        packet = collect_evidence(planned.value, settings, tracer)
        analyzed = analyze_evidence(packet, settings, llm)
        if should_fetch_wave2(packet, analyzed.value, settings):
            gaps = missing_required_fields(analyzed.value, specified.value)
            tracer.event(
                "wave2_start",
                fields=gaps,
                unused_urls=packet.unused_urls,
                next_wave_size=packet.next_wave_size,
            )
            packet = collect_wave2(packet, settings, tracer, gaps)
            if packet.retrieval.passages:
                second = analyze_evidence(
                    packet,
                    settings,
                    llm,
                    focus_fields=gaps,
                )
                analyzed = StructuredResult(
                    value=merge_analyst_results(
                        analyzed.value,
                        second.value,
                        packet,
                        settings,
                    ),
                    cost=analyzed.cost.plus(second.cost),
                    generation_id=second.generation_id,
                )
            tracer.event(
                "wave2_end",
                pages_used=packet.pages_used,
                claims=len(analyzed.value.claims),
                unanswered=[item.field for item in analyzed.value.unanswered],
            )
        checked = cross_check_claims(
            analyzed.value.claims,
            specified.value,
            settings,
            tracer,
            llm=llm,
            known_pages=packet.fetched.pages,
        )
        audited = audit_claims(
            analyzed.value.claims,
            specified.value,
            settings,
            tracer,
            llm=llm,
        )
        final = close_answer(
            specified.value,
            analyzed.value,
            audited.value,
            checked.value,
        )
        memory.update_from_run(
            specified.value,
            analyzed.value,
            final,
            checked.value,
        )
        memory.save()
    except Exception as exc:
        tracer.event("run_end", ok=False)
        print(f"FAIL: {type(exc).__name__}: {exc}")
        print(f"Trace: {trace_path}")
        return 1

    result = analyzed.value
    tracer.event("analyst_result", **result.model_dump())
    tracer.event("final_answer", **final.model_dump())
    tracer.event(
        "memory_write",
        path=str(memory.path),
        facts=len(memory.snapshot.facts),
        rejects=len(memory.snapshot.rejects),
        recalled_facts=recalled.known_facts,
    )
    tracer.event(
        "run_end",
        ok=True,
        complete=final.complete,
        specify_cost=specified.cost.as_dict(),
        plan_cost=planned.cost.as_dict(),
        analyze_cost=analyzed.cost.as_dict(),
        cross_check_cost=checked.cost.as_dict(),
        audit_cost=audited.cost.as_dict(),
    )

    print(
        f"Pages used: {packet.pages_used} | "
        f"Unused leftovers: {len(packet.unused_urls)} | "
        f"Next wave: {packet.next_wave_size}"
    )
    print(f"Supported claims: {len(result.claims)}")
    for claim in result.claims:
        print(f"- {claim.claim_id} [{claim.field}] {claim.text}")
        print(f"  quote: {claim.quote[:240]}")
        print(f"  {', '.join(claim.urls)}")
    print(f"Unanswered: {len(result.unanswered)}")
    for item in result.unanswered:
        print(f"- {item.field}: {item.reason}")
    if result.notes:
        print("Notes:")
        for note in result.notes:
            print(f"- {note}")
    if result.dropped_drafts:
        print(f"Dropped unsupported drafts: {result.dropped_drafts}")
    print("Cross-check:")
    for verdict in checked.value.verdicts:
        extra = f" → {verdict.independent_url}" if verdict.independent_url else ""
        print(f"- {verdict.claim_id} {verdict.status}{extra}")
        print(f"  {verdict.reason}")
    print("Auditor:")
    for verdict in audited.value.verdicts:
        print(f"- {verdict.claim_id} {verdict.verdict}")
        print(f"  {verdict.reason}")
        for note in verdict.source_notes:
            print(f"  {note.source_id} {note.support}: {note.reason}")
    print()
    print(render_answer(final))
    print(
        f"Memory: {len(memory.snapshot.facts)} fact(s), "
        f"{len(memory.snapshot.rejects)} note(s) → {memory.path}"
    )
    print(
        "Tokens: "
        f"specify {specified.cost.total_tokens} | "
        f"plan {planned.cost.total_tokens} | "
        f"analyze {analyzed.cost.total_tokens} | "
        f"cross-check {checked.cost.total_tokens} | "
        f"audit {audited.cost.total_tokens}"
    )
    print(
        "Estimated LLM cost: "
        f"${specified.cost.cost_usd + planned.cost.cost_usd + analyzed.cost.cost_usd + checked.cost.cost_usd + audited.cost.cost_usd:.8f} / "
        f"₹{specified.cost.cost_inr + planned.cost.cost_inr + analyzed.cost.cost_inr + checked.cost.cost_inr + audited.cost.cost_inr:.6f}"
    )
    print(f"Trace: {trace_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
