"""Entity-scoped JSON memory. Stores facts, not previous final answers."""

from __future__ import annotations

import json
from pathlib import Path

from src.config import Settings
from src.models import (
    AnalystResult,
    AnswerLine,
    CrossCheckReport,
    FinalAnswer,
    MemoryFact,
    MemoryRecall,
    MemoryReject,
    MemorySnapshot,
    SpecifiedQuestion,
)
from src.period import split_entities

CORROBORATION_MAP = {
    "corroborated": "corroborated",
    "skipped_multi_source": "multi_source",
    "single_source": "single_source",
}


def entity_key(name: str) -> str:
    return " ".join(name.casefold().split())


def entities_match(left: str, right: str) -> bool:
    """Treat 'Titan' and 'Titan Company' as the same subject."""
    left_key = entity_key(left)
    right_key = entity_key(right)
    if not left_key or not right_key:
        return False
    return left_key == right_key or left_key in right_key or right_key in left_key


def mentioned_in_question(entity: str, question: str) -> bool:
    text = question.casefold()
    key = entity_key(entity)
    if key and key in text:
        return True
    head = key.split()[0] if key else ""
    return len(head) >= 4 and head in text


def resolve_entity(
    specified: SpecifiedQuestion,
    line: AnswerLine,
    last_name: str = "",
) -> str | None:
    """Bind a claim to a named company, or to a name-row on ranking questions."""
    named, _ = split_entities(specified.specification.entities)
    haystack = f"{line.text} {line.field}"
    for entity in named:
        if entities_match(entity, haystack) or entity.casefold() in haystack.casefold():
            return entity
    if len(named) == 1:
        return named[0]
    if "name" in line.field.casefold() and line.text.strip():
        return line.text.strip()
    return last_name or None


class EntityMemory:
    """Load, recall, and update one JSON file of entity facts and rejects."""

    def __init__(self, path: Path, snapshot: MemorySnapshot | None = None) -> None:
        self.path = path
        self.snapshot = snapshot or MemorySnapshot()

    @classmethod
    def load(cls, settings: Settings, path: Path | None = None) -> EntityMemory:
        store_path = path or settings.memory_path
        if not store_path.exists():
            return cls(store_path)
        raw = json.loads(store_path.read_text(encoding="utf-8"))
        return cls(store_path, MemorySnapshot.model_validate(raw))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            self.snapshot.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )

    def recall(
        self,
        specified: SpecifiedQuestion,
        *,
        limit: int | None = None,
    ) -> MemoryRecall:
        """Return prompt lines for entities named in the spec or question."""
        named, _ = split_entities(specified.specification.entities)
        cap = limit if limit is not None else 8
        facts = [
            item
            for item in self.snapshot.facts
            if _is_relevant(item.entity, named, specified.question)
        ][:cap]
        rejects = [
            item
            for item in self.snapshot.rejects
            if _is_relevant(item.entity, named, specified.question)
        ]
        disputed = [item for item in rejects if item.status == "disputed"][:cap]
        rejected = [item for item in rejects if item.status == "rejected"][:cap]
        return MemoryRecall(
            facts=list(facts),
            known_facts=[_fact_line(item) for item in facts],
            known_fields=[item.field for item in facts],
            disputed_notes=[_reject_line(item) for item in disputed],
            disputed_fields=[item.field for item in disputed],
            rejected_notes=[_reject_line(item) for item in rejected],
        )

    def update_from_run(
        self,
        specified: SpecifiedQuestion,
        analyst: AnalystResult,
        final: FinalAnswer,
        cross_check: CrossCheckReport | None = None,
    ) -> MemorySnapshot:
        """Write accepted facts. Conflicts become disputed, not known facts."""
        claims = {item.claim_id: item for item in analyst.claims}
        statuses = {
            item.claim_id: item.status
            for item in (cross_check.verdicts if cross_check else [])
        }
        last_name = ""
        for line in final.accepted:
            claim = claims.get(line.claim_id)
            entity = resolve_entity(specified, line, last_name)
            if entity and "name" in line.field.casefold():
                last_name = entity
            if entity is None:
                continue
            self._upsert_fact(
                MemoryFact(
                    entity=entity,
                    field=line.field,
                    text=line.text,
                    quote=claim.quote if claim else "",
                    urls=list(line.urls),
                    period=claim.period if claim else None,
                    as_of_date=specified.as_of_date,
                    corroboration=_corroboration(line.claim_id, statuses),
                )
            )

        for item in final.disputed:
            claim = claims.get(item.claim_id)
            entity = resolve_entity(
                specified,
                AnswerLine(
                    field=item.field,
                    text=claim.text if claim else item.reason,
                    claim_id=item.claim_id,
                    urls=list(item.urls),
                ),
                last_name,
            )
            if entity is None:
                continue
            self._drop_facts(entity, item.field)
            self._upsert_reject(
                MemoryReject(
                    entity=entity,
                    field=item.field,
                    text=claim.text if claim else item.reason,
                    status="disputed",
                    reason=item.reason,
                    urls=list(item.urls),
                    as_of_date=specified.as_of_date,
                )
            )

        accepted_ids = {line.claim_id for line in final.accepted}
        disputed_ids = {line.claim_id for line in final.disputed}
        for claim in analyst.claims:
            if claim.claim_id in accepted_ids or claim.claim_id in disputed_ids:
                continue
            entity = resolve_entity(
                specified,
                AnswerLine(
                    field=claim.field,
                    text=claim.text,
                    claim_id=claim.claim_id,
                    urls=list(claim.urls),
                ),
                last_name,
            )
            if entity is None:
                continue
            self._upsert_reject(
                MemoryReject(
                    entity=entity,
                    field=claim.field,
                    text=claim.text,
                    status="rejected",
                    reason="Claim did not survive the Auditor.",
                    urls=list(claim.urls),
                    as_of_date=specified.as_of_date,
                )
            )
        return self.snapshot

    def _upsert_fact(self, fact: MemoryFact) -> None:
        key = _pair_key(fact.entity, fact.field)
        self.snapshot.facts = [
            item
            for item in self.snapshot.facts
            if _pair_key(item.entity, item.field) != key
        ]
        self.snapshot.rejects = [
            item
            for item in self.snapshot.rejects
            if _pair_key(item.entity, item.field) != key
        ]
        self.snapshot.facts.append(fact)

    def _drop_facts(self, entity: str, field: str) -> None:
        key = _pair_key(entity, field)
        self.snapshot.facts = [
            item
            for item in self.snapshot.facts
            if _pair_key(item.entity, item.field) != key
        ]

    def _upsert_reject(self, note: MemoryReject) -> None:
        self.snapshot.rejects = [
            item
            for item in self.snapshot.rejects
            if not (
                _pair_key(item.entity, item.field) == _pair_key(note.entity, note.field)
                and item.text.casefold() == note.text.casefold()
            )
        ]
        self.snapshot.rejects.append(note)


def _is_relevant(entity: str, named: list[str], question: str) -> bool:
    if any(entities_match(entity, item) for item in named):
        return True
    return mentioned_in_question(entity, question)


def _corroboration(claim_id: str, statuses: dict[str, str]) -> str:
    return CORROBORATION_MAP.get(statuses.get(claim_id, ""), "single_source")


def _pair_key(entity: str, field: str) -> tuple[str, str]:
    return (entity_key(entity), field.casefold())


def _fact_line(item: MemoryFact) -> str:
    return f"{item.entity} / {item.field} ({item.corroboration}): {item.text}"


def _reject_line(item: MemoryReject) -> str:
    return f"{item.entity} / {item.field} ({item.status}): {item.text}"
