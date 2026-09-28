"""Locked scored set (Q01–Q09). Increasing difficulty, two reuse Titan/Q3."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalQuestion:
    """One scored question plus the notes the specifier should treat as required."""

    qid: str
    question: str
    notes: tuple[str, ...]
    reuse: bool = False
    plant_unsupported: bool = False


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
            "Given that Ajoy Chawla is already known as Titan Company's "
            "Managing Director, whom did he succeed, and when did that "
            "predecessor retire or step down?"
        ),
        notes=(
            "The current MD name is already known. Need the predecessor's "
            "full name and a retirement or last-day date if a source states one.",
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
            "Using stored Titan facts: confirm Titan Company's Managing "
            "Director full name and the effective appointment date in 2026. "
            "Cite one page."
        ),
        notes=(
            "Need the name and the date from an opened page. "
            "Do not paste memory without a citation.",
        ),
        reuse=True,
    ),
    EvalQuestion(
        qid="Q07",
        question=(
            "Titan or Tanishq already has one store-network figure on file. "
            "Find a second published figure that is not the same number. "
            "Give both with their dates or periods, then choose which "
            "figure to treat as the latest and why."
        ),
        notes=(
            "You may reuse one stored count. Need a second different count, "
            "dates for both, then one chosen figure and a short reason "
            "(newer period or official filing beats an undated blog).",
        ),
        reuse=True,
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
    EvalQuestion(
        qid="Q09",
        question=(
            "What Tanishq store-network number is stated in the Retail4Growth "
            "article about Ajoy Chawla becoming Titan Managing Director?"
        ),
        notes=(
            "Need the store count only if that MD article itself states one. "
            "Do not copy a store number from Wikipedia or a filing onto this "
            "article. not_found is allowed."
        ),
        plant_unsupported=True,
    ),
)


def by_id(qid: str) -> EvalQuestion:
    key = qid.strip().upper()
    for item in QUESTIONS:
        if item.qid == key:
            return item
    raise KeyError(f"unknown eval question: {qid}")
