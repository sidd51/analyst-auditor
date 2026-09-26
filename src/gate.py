"""Deterministic completeness gate and verified-only answer renderer."""

from __future__ import annotations

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
        if claim.claim_id in conflicts:
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

    covered = {_key(item.field) for item in accepted}
    missing = _missing_fields(specified, analyst.unanswered, covered, rejected_missing)
    complete = not missing and not disputed and _rank_is_filled(specified, accepted)
    if not complete and specified.specification.ranking:
        missing = _ensure_rank_missing(specified, accepted, missing)

    return FinalAnswer(
        complete=complete,
        accepted=accepted,
        missing=missing,
        disputed=disputed,
    )


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


def _rank_is_filled(specified: SpecifiedQuestion, accepted: list[AnswerLine]) -> bool:
    spec = specified.specification
    if not spec.ranking or not spec.required_count:
        return True
    return _ranked_row_count(accepted) >= spec.required_count


def _ensure_rank_missing(
    specified: SpecifiedQuestion,
    accepted: list[AnswerLine],
    missing: list[MissingLine],
) -> list[MissingLine]:
    spec = specified.specification
    if not spec.ranking or not spec.required_count:
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


def _key(value: str) -> str:
    return value.strip().casefold()
