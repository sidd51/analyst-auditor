"""Locked scored set (Q01–Q09). Mixed domains, hard misses, later memory reuse."""

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
            "Who is Infosys's chief executive in office in 2026, and in "
            "which city is the company headquartered?"
        ),
        notes=(
            "Need the incumbent's full name (the person holding CEO/MD "
            "during 2026, not a successor named to take over later) and "
            "the headquarters city. Do not add chosen_figure_count or "
            "chosen_figure_reason.",
        ),
    ),
    EvalQuestion(
        qid="Q03",
        question=(
            "Name the three Indian IT companies with the highest FY26 "
            "consolidated revenue, in rank order, and give each company's "
            "FY26 revenue in rupees crore."
        ),
        notes=(
            "Need three companies and each FY26 consolidated revenue in "
            "rupees crore, in rank order. Parallel rows, same field labels.",
        ),
    ),
    EvalQuestion(
        qid="Q04",
        question=(
            "Given that Infosys already has a named chief executive on file, "
            "whom did that person succeed, and in which year did the current "
            "chief executive take over?"
        ),
        notes=(
            "The current CEO name is already known. Need the predecessor's "
            "full name and a start year or appointment date if a source states one. "
            "Do not add chosen_figure_count or chosen_figure_reason.",
        ),
        reuse=True,
    ),
    EvalQuestion(
        qid="Q05",
        question=(
            "What is the Reserve Bank of India's repo rate after the most "
            "recent Monetary Policy Committee decision in 2026, and what "
            "was the date of that decision?"
        ),
        notes=(
            "Required fields are only the repo rate and the decision date. "
            "Do not add chosen_figure_count or chosen_figure_reason. "
            "Prefer an RBI page over a roundup blog.",
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
            "Required fields are only the MD full name and the appointment "
            "date. Do not add chosen_figure_count, chosen_figure_reason, "
            "or a citation field. URLs on those two claims are the cite. "
            "Need both values from an opened page. Do not paste memory "
            "without a citation.",
        ),
        reuse=True,
    ),
    EvalQuestion(
        qid="Q07",
        question=(
            "Find two different published FY2026 or calendar-2026 India GDP "
            "growth figures from two named institutions (for example RBI, "
            "IMF, World Bank, or MoSPI). Give both with their dates, then "
            "choose which figure to treat as the working estimate and why."
        ),
        notes=(
            "Need two unequal numbers, institution names, dates or publication "
            "months, then one chosen figure and a short reason "
            "(newer print or official statistics beat an undated blog). "
            "Do not report both and shrug.",
        ),
    ),
    EvalQuestion(
        qid="Q08",
        question=(
            "Using stored Reserve Bank of India facts: confirm the repo "
            "rate after the most recent 2026 Monetary Policy Committee "
            "decision and the date of that decision. Cite one page."
        ),
        notes=(
            "Required fields are only the repo rate and the decision date. "
            "Do not add chosen_figure_count or chosen_figure_reason. Need "
            "both values from an opened page.",
        ),
        reuse=True,
    ),
    EvalQuestion(
        qid="Q09",
        question=(
            "What Infosys global employee count is stated in the RBI press "
            "release for the most recent 2026 MPC repo-rate decision?"
        ),
        notes=(
            "The only required field is that employee count. Do not add "
            "chosen_figure fields. Need a headcount only if that RBI release "
            "itself states one. Do not copy an Infosys annual-report number "
            "onto the RBI page. not_found is allowed.",
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
