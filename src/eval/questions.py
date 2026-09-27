"""Locked eight-question set. Increasing difficulty, two reuse Titan/Q3."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalQuestion:
    """One scored question plus the notes the specifier should treat as required."""

    qid: str
    question: str
    notes: tuple[str, ...]
    reuse: bool = False


QUESTIONS: tuple[EvalQuestion, ...] = (
    EvalQuestion(
        qid="Q01",
        question="Who is Titan Company's Managing Director in 2026?",
        notes=("Give the full name and the effective appointment date.",),
    ),
    EvalQuestion(
        qid="Q02",
        question=(
            "What store-network number has Titan or Tanishq most recently "
            "published, and for which date or reporting period?"
        ),
        notes=(
            "Need one published count and the period or date next to it. "
            "A year-end or quarterly figure is enough.",
        ),
    ),
    EvalQuestion(
        qid="Q03",
        question=(
            "Name two Indian jewellery retailers that publicly reported "
            "actual new store openings in 2025, and the counts they stated."
        ),
        notes=(
            "Need retailer name, the opened/added number, and the window "
            "the source used. Plans and targets are not claims. "
            "Do not invent a third rank if only two counts appear.",
        ),
    ),
    EvalQuestion(
        qid="Q04",
        question=(
            "Given what is already known about Titan Company, whom did "
            "Ajoy Chawla succeed as Managing Director, and when did that "
            "predecessor retire or step down?"
        ),
        notes=(
            "Need the predecessor's full name and a retirement or last-day "
            "date if a source states one.",
        ),
        reuse=True,
    ),
    EvalQuestion(
        qid="Q05",
        question=(
            "Name one funding round announced by an Indian jewellery brand "
            "or an Indian quick-commerce company in 2024, 2025, or 2026."
        ),
        notes=(
            "Need company name plus amount and date if the page states them. "
            "Investors if named. not_found is allowed per field. "
            "Do not invent a round.",
        ),
    ),
    EvalQuestion(
        qid="Q06",
        question=(
            "Besides the Managing Director, who is named as CEO or head of "
            "Titan's jewellery division in 2026, and what title does the "
            "source give them?"
        ),
        notes=(
            "Need the person's name and title from an open page. "
            "Do not guess from a LinkedIn URL that was not fetched.",
        ),
        reuse=True,
    ),
    EvalQuestion(
        qid="Q07",
        question=(
            "Find two published Titan or Tanishq store-network figures that "
            "are not the same number. Give both with their dates or periods, "
            "then choose which figure to treat as the latest and why."
        ),
        notes=(
            "Need two different counts, each with a date or period, then "
            "one chosen figure and a short reason (newer period or official "
            "filing beats an undated blog).",
        ),
    ),
    EvalQuestion(
        qid="Q08",
        question=(
            "Using memory plus a small verify pass: is Ajoy Chawla still "
            "described as Titan Company's Managing Director in 2026? Cite "
            "one page. Also name one Titan jewellery brand mentioned on an "
            "official or news page."
        ),
        notes=(
            "Need a yes/no with a citation for the MD role, and one brand "
            "name such as Tanishq, Mia, or CaratLane. Do not paste an old "
            "answer without opening a page.",
        ),
        reuse=True,
    ),
)


def by_id(qid: str) -> EvalQuestion:
    key = qid.strip().upper()
    for item in QUESTIONS:
        if item.qid == key:
            return item
    raise KeyError(f"unknown eval question: {qid}")
