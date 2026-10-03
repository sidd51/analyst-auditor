"""Deterministic completeness gate and verified-only answer renderer."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from src.cross_check import source_domain
from src.models import (
    AnalystResult,
    AnswerLine,
    AuditReport,
    CrossCheckReport,
    DisputedLine,
    FinalAnswer,
    MissingLine,
    SpecifiedQuestion,
    UnansweredField,
)

CORROBORATION_RANK = {
    "corroborated": 2,
    "skipped_multi_source": 1,
    "single_source": 0,
}

REJECTED_VERDICTS = {"UNSUPPORTED", "UNCITED"}
DISPUTED_VERDICTS = {"CONTRADICTED"}


def citation_label(url: str) -> str:
    """Short host label; PDFs keep an extra marker so filings stand out."""
    label = source_domain(url) or url
    path = urlsplit(url).path.lower()
    if path.endswith(".pdf"):
        return f"{label} PDF"
    return label


def close_answer(
    specified: SpecifiedQuestion,
    analyst: AnalystResult,
    audit: AuditReport,
    cross_check: CrossCheckReport | None = None,
) -> FinalAnswer:
    """Keep SUPPORTED claims only. Completeness is a Python check."""
    audits = {item.claim_id: item for item in audit.verdicts}
    conflicts = {
        item.claim_id
        for item in (cross_check.verdicts if cross_check else [])
        if item.status == "conflicting"
    }

    accepted: list[AnswerLine] = []
    disputed: list[DisputedLine] = []
    rejected_missing: list[MissingLine] = []

    for claim in analyst.claims:
        audit_item = audits.get(claim.claim_id)
        verdict = audit_item.verdict if audit_item else "UNSUPPORTED"
        reason = (
            audit_item.reason
            if audit_item
            else "Auditor omitted this claim; fail closed."
        )
        if claim.claim_id in conflicts and verdict != "SUPPORTED":
            disputed.append(
                DisputedLine(
                    field=claim.field,
                    claim_id=claim.claim_id,
                    reason="Independent source conflicts with this claim.",
                    urls=list(claim.urls),
                )
            )
            continue
        if verdict in DISPUTED_VERDICTS:
            disputed.append(
                DisputedLine(
                    field=claim.field,
                    claim_id=claim.claim_id,
                    reason=reason,
                    urls=list(claim.urls),
                )
            )
            continue
        if verdict in REJECTED_VERDICTS or verdict != "SUPPORTED":
            rejected_missing.append(MissingLine(field=claim.field, reason=reason))
            continue
        accepted.append(
            AnswerLine(
                field=claim.field,
                text=claim.text,
                claim_id=claim.claim_id,
                urls=list(claim.urls),
                sources=_unique_labels(claim.urls),
            )
        )

    accepted, extra_disputed = collapse_duplicate_fields(
        accepted,
        cross_check,
        keep_parallel_rows=_asks_for_multiple(specified.specification),
    )
    disputed.extend(extra_disputed)
    covered = {_key(item.field) for item in accepted}
    disputed_keys = {_key(item.field) for item in disputed}
    missing = _missing_fields(
        specified,
        analyst.unanswered,
        covered | disputed_keys,
        rejected_missing,
    )
    unresolved = [item for item in disputed if _key(item.field) not in covered]
    complete = not missing and not unresolved and _rank_is_filled(specified, accepted)
    if not complete and _asks_for_multiple(specified.specification):
        missing = _ensure_rank_missing(specified, accepted, missing)

    return FinalAnswer(
        complete=complete,
        accepted=accepted,
        missing=missing,
        disputed=disputed,
    )


def collapse_duplicate_fields(
    accepted: list[AnswerLine],
    cross_check: CrossCheckReport | None,
    *,
    keep_parallel_rows: bool = False,
) -> tuple[list[AnswerLine], list[DisputedLine]]:
    """If two verified claims disagree on one field, keep the better-backed one."""
    if keep_parallel_rows:
        return accepted, []
    ranks = {
        item.claim_id: CORROBORATION_RANK.get(item.status, 0)
        for item in (cross_check.verdicts if cross_check else [])
    }
    grouped: dict[str, list[AnswerLine]] = {}
    order: list[str] = []
    for line in accepted:
        key = _key(line.field)
        if key not in grouped:
            order.append(key)
            grouped[key] = []
        grouped[key].append(line)

    kept: list[AnswerLine] = []
    disputed: list[DisputedLine] = []
    for key in order:
        rows = grouped[key]
        unique: list[AnswerLine] = []
        seen_text: set[str] = set()
        for line in rows:
            text_key = line.text.casefold()
            if text_key in seen_text:
                continue
            seen_text.add(text_key)
            unique.append(line)
        if len(unique) == 1:
            kept.append(unique[0])
            continue
        winner = max(
            unique,
            key=lambda item: (
                ranks.get(item.claim_id, 0),
                *_source_quality(item),
                item.claim_id,
            ),
        )
        kept.append(winner)
        for line in unique:
            if line.claim_id == winner.claim_id:
                continue
            disputed.append(
                DisputedLine(
                    field=line.field,
                    claim_id=line.claim_id,
                    reason=(
                        f"Kept {winner.claim_id} for this field "
                        f"(better independent backing). Other value: {line.text}"
                    ),
                    urls=list(line.urls),
                )
            )
    return kept, disputed


def render_answer(answer: FinalAnswer) -> str:
    """Plain text only. The model does not write this block."""
    status = "complete" if answer.complete else "incomplete"
    lines = [f"Answer ({status})"]
    if answer.accepted:
        for item in answer.accepted:
            cites = ", ".join(item.sources)
            suffix = f"  [{cites}]" if cites else ""
            lines.append(f"- {item.field}: {item.text}{suffix}")
    else:
        lines.append("- (no verified claims)")
    if answer.missing:
        lines.append("")
        lines.append("Missing")
        for item in answer.missing:
            lines.append(f"- {item.field}: {item.reason}")
    if answer.disputed:
        lines.append("")
        lines.append("Disputed")
        for item in answer.disputed:
            lines.append(f"- {item.field}: {item.reason}")
    return "\n".join(lines)


def _missing_fields(
    specified: SpecifiedQuestion,
    unanswered: list[UnansweredField],
    covered: set[str],
    rejected_missing: list[MissingLine],
) -> list[MissingLine]:
    missing: list[MissingLine] = []
    seen: set[str] = set()

    for item in unanswered:
        key = _key(item.field)
        if key in covered or key in seen:
            continue
        missing.append(MissingLine(field=item.field, reason=item.reason))
        seen.add(key)

    for field in specified.specification.required_fields:
        key = _key(field)
        if key in covered or key in seen:
            continue
        missing.append(
            MissingLine(
                field=field,
                reason="No verified claim survived the Auditor.",
            )
        )
        seen.add(key)

    for item in rejected_missing:
        key = _key(item.field)
        if key in covered or key in seen:
            continue
        missing.append(item)
        seen.add(key)
    return missing


def _asks_for_multiple(spec) -> bool:
    """Name-N and ranking questions keep one row per result, not one value per field."""
    return bool(
        spec.ranking or spec.comparison or (spec.required_count or 0) >= 2
    )


def _rank_is_filled(specified: SpecifiedQuestion, accepted: list[AnswerLine]) -> bool:
    spec = specified.specification
    if not spec.required_count or not _asks_for_multiple(spec):
        return True
    return _ranked_row_count(accepted) >= spec.required_count


def _ensure_rank_missing(
    specified: SpecifiedQuestion,
    accepted: list[AnswerLine],
    missing: list[MissingLine],
) -> list[MissingLine]:
    spec = specified.specification
    if not spec.required_count:
        return missing
    if _rank_is_filled(specified, accepted):
        return missing
    if any(_key(item.field) in {"ranking", "requested count"} for item in missing):
        return missing
    found = _ranked_row_count(accepted)
    return [
        *missing,
        MissingLine(
            field="requested count",
            reason=(
                f"Verified {found} ranked result(s); "
                f"{spec.required_count} were requested."
            ),
        ),
    ]


def _ranked_row_count(accepted: list[AnswerLine]) -> int:
    """Count name-like rows so split count/name claims are not each a rank slot."""
    names = [
        item
        for item in accepted
        if "name" in _key(item.field) or _key(item.field) in {"retailer", "company"}
    ]
    return len(names) if names else len(accepted)


def _unique_labels(urls: list[str]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for url in urls:
        label = citation_label(url)
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return labels


def _source_quality(line: AnswerLine) -> tuple[int, int]:
    """PDF / filing URLs and dated text beat an undated blog when backing ties."""
    pdf = any(urlsplit(url).path.lower().endswith(".pdf") for url in line.urls)
    dated = bool(
        re.search(r"\b(?:20\d{2}|fy\s?\d{2,4}|q[1-4])\b", line.text, flags=re.I)
    )
    return (1 if pdf else 0, 1 if dated else 0)


def _key(value: str) -> str:
    return value.strip().casefold()
