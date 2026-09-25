"""Select question-relevant passages without sending whole pages to a model."""

from __future__ import annotations

import argparse
import math
import re
from collections import defaultdict
from typing import Iterable

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import Settings, load_settings
from src.models import EvidencePassage, FetchedPage, RetrievalResponse
from src.tools.fetch import ParallelFetcher
from src.trace import JsonlTracer

WORD_PATTERN = re.compile(r"[a-z0-9]+")
PDF_PAGE_PATTERN = re.compile(r"(?m)^\[PDF page (\d+)\]\s*$")

# Removing generic question words prevents passages from scoring highly merely
# because they contain phrases such as "which company" or "what source".
STOP_WORDS = {
    "about",
    "after",
    "all",
    "and",
    "are",
    "before",
    "between",
    "cite",
    "current",
    "each",
    "every",
    "find",
    "for",
    "from",
    "give",
    "has",
    "have",
    "how",
    "into",
    "most",
    "not",
    "only",
    "question",
    "report",
    "source",
    "state",
    "than",
    "that",
    "the",
    "their",
    "this",
    "through",
    "using",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
}


class PassageRetriever:
    """Chunk, rank, diversify, and budget passages using plain Python."""

    def __init__(self, settings: Settings, tracer: JsonlTracer) -> None:
        self.settings = settings
        self.tracer = tracer
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.retrieval_chunk_size,
            chunk_overlap=settings.retrieval_chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
            length_function=len,
        )

    def retrieve(
        self,
        pages: Iterable[FetchedPage],
        *,
        question: str,
        requirements: list[str] | None = None,
        token_budget: int | None = None,
    ) -> RetrievalResponse:
        clean_question = question.strip()
        if not clean_question:
            raise ValueError("question cannot be empty")

        requirement_list = [
            item.strip()
            for item in (requirements or [])
            if item.strip()
        ]
        budget = token_budget or self.settings.evidence_token_budget
        if budget <= 0:
            raise ValueError("token_budget must be positive")

        usable_pages = [
            page
            for page in pages
            if page.ok and page.text.strip() and page.kind in {"html", "pdf"}
        ]
        terms = _important_terms(clean_question, requirement_list)
        self.tracer.event(
            "retrieval_call",
            question=clean_question,
            requirements=requirement_list,
            documents=len(usable_pages),
            terms=terms,
            token_budget=budget,
        )

        candidates = self._build_candidates(usable_pages, terms)
        selected = self._select_diverse_passages(candidates, budget)
        selected_tokens = sum(item.estimated_tokens for item in selected)

        response = RetrievalResponse(
            question=clean_question,
            requirements=requirement_list,
            documents_considered=len(usable_pages),
            passages_considered=len(candidates),
            passages_selected=len(selected),
            passages_omitted=len(candidates) - len(selected),
            estimated_tokens=selected_tokens,
            token_budget=budget,
            passages=selected,
        )
        # Unlike fetch logs, retrieval logs the selected passages in full. This
        # is the exact evidence packet a future Analyst will be allowed to see.
        self.tracer.event(
            "retrieval_result",
            **response.model_dump(),
        )
        return response

    def _build_candidates(
        self,
        pages: list[FetchedPage],
        terms: list[str],
    ) -> list[EvidencePassage]:
        candidates: list[EvidencePassage] = []
        sequence = 1
        for page in pages:
            for chunk_index, (text, pdf_page) in enumerate(
                self._split_page(page),
                start=1,
            ):
                matched, score = _score_passage(text, page.title, terms)
                candidates.append(
                    EvidencePassage(
                        passage_id=f"P{sequence:04d}",
                        url=page.final_url,
                        title=page.title,
                        document_kind=page.kind,
                        chunk_index=chunk_index,
                        pdf_page=pdf_page,
                        text=text,
                        matched_terms=matched,
                        relevance_score=score,
                        # Metadata and separators also consume prompt space, so
                        # add a conservative 30-token allowance per passage.
                        estimated_tokens=_estimate_tokens(text) + 30,
                    )
                )
                sequence += 1
        return candidates

    def _split_page(
        self,
        page: FetchedPage,
    ) -> list[tuple[str, int | None]]:
        if page.kind == "pdf":
            return self._split_pdf_pages(page.text)
        return [
            (chunk, None)
            for chunk in self.splitter.split_text(page.text)
            if chunk.strip()
        ]

    def _split_pdf_pages(self, text: str) -> list[tuple[str, int | None]]:
        """Split each PDF page separately so chunks never lose page metadata."""
        matches = list(PDF_PAGE_PATTERN.finditer(text))
        if not matches:
            return [
                (chunk, None)
                for chunk in self.splitter.split_text(text)
                if chunk.strip()
            ]

        chunks: list[tuple[str, int | None]] = []
        for index, match in enumerate(matches):
            page_number = int(match.group(1))
            body_start = match.end()
            body_end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(text)
            )
            body = text[body_start:body_end].strip()
            for chunk in self.splitter.split_text(body):
                if chunk.strip():
                    chunks.append(
                        (
                            f"[PDF page {page_number}]\n{chunk}",
                            page_number,
                        )
                    )
        return chunks

    def _select_diverse_passages(
        self,
        candidates: list[EvidencePassage],
        budget: int,
    ) -> list[EvidencePassage]:
        relevant = sorted(
            (item for item in candidates if item.relevance_score > 0),
            key=lambda item: (
                -item.relevance_score,
                item.estimated_tokens,
                item.passage_id,
            ),
        )

        # First consider the strongest passage from every relevant source.
        # The second pass fills remaining space while enforcing a per-source cap.
        best_by_source: dict[str, EvidencePassage] = {}
        for passage in relevant:
            best_by_source.setdefault(passage.url, passage)
        first_pass = sorted(
            best_by_source.values(),
            key=lambda item: (-item.relevance_score, item.passage_id),
        )
        first_ids = {item.passage_id for item in first_pass}
        second_pass = [
            item for item in relevant if item.passage_id not in first_ids
        ]

        selected: list[EvidencePassage] = []
        selected_ids: set[str] = set()
        per_source: defaultdict[str, int] = defaultdict(int)
        used_tokens = 0
        for passage in [*first_pass, *second_pass]:
            if len(selected) >= self.settings.max_selected_passages:
                break
            if passage.passage_id in selected_ids:
                continue
            if (
                per_source[passage.url]
                >= self.settings.max_passages_per_source
            ):
                continue
            if used_tokens + passage.estimated_tokens > budget:
                continue

            selected.append(passage)
            selected_ids.add(passage.passage_id)
            per_source[passage.url] += 1
            used_tokens += passage.estimated_tokens

        return sorted(
            selected,
            key=lambda item: (-item.relevance_score, item.passage_id),
        )


def _important_terms(question: str, requirements: list[str]) -> list[str]:
    words = WORD_PATTERN.findall(
        " ".join([question, *requirements]).lower()
    )
    return sorted(
        {
            word
            for word in words
            if (len(word) >= 3 or word.isdigit()) and word not in STOP_WORDS
        }
    )


def _score_passage(
    text: str,
    title: str,
    terms: list[str],
) -> tuple[list[str], float]:
    lowered_text = text.lower()
    lowered_title = title.lower()
    matched = []
    score = 0.0
    for term in terms:
        count = len(
            re.findall(rf"\b{re.escape(term)}\b", lowered_text)
        )
        if count == 0:
            continue
        matched.append(term)
        score += 2.0 + min(count - 1, 3) * 0.35
        if term.isdigit():
            score += 1.0
        if re.search(rf"\b{re.escape(term)}\b", lowered_title):
            score += 0.75
    return matched, round(score, 3)


def _estimate_tokens(text: str) -> int:
    """Estimate tokens locally without downloading a model tokenizer.

    OpenRouter can route several model families with different tokenizers.
    Taking the larger of a character and word estimate gives us a conservative
    context safety check while keeping offline tests genuinely offline.
    """
    character_estimate = math.ceil(len(text) / 4)
    word_estimate = math.ceil(len(text.split()) * 1.5)
    return max(1, character_estimate, word_estimate)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch URLs and select question-relevant passages."
    )
    parser.add_argument("--question", required=True)
    parser.add_argument(
        "--requirement",
        action="append",
        default=[],
        help="Repeat this option for each required answer field.",
    )
    parser.add_argument("--token-budget", type=int)
    parser.add_argument("--page-limit", type=int)
    parser.add_argument("urls", nargs="+")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = load_settings()
    trace_path = settings.root / "logs" / "step3-retrieve.jsonl"
    tracer = JsonlTracer(trace_path, reset=True)

    fetched = ParallelFetcher(settings, tracer).fetch_many(
        args.urls,
        page_limit=args.page_limit,
    )
    result = PassageRetriever(settings, tracer).retrieve(
        fetched.pages,
        question=args.question,
        requirements=args.requirement,
        token_budget=args.token_budget,
    )

    print(
        f"Documents: {result.documents_considered} | "
        f"Passages: {result.passages_selected}/"
        f"{result.passages_considered} selected | "
        f"Tokens: {result.estimated_tokens}/{result.token_budget}"
    )
    for passage in result.passages:
        location = (
            f" PDF page {passage.pdf_page}"
            if passage.pdf_page is not None
            else ""
        )
        print(
            f"- {passage.passage_id}{location} "
            f"score={passage.relevance_score} "
            f"tokens≈{passage.estimated_tokens}"
        )
        print(f"  {passage.url}")
        print(f"  matched: {', '.join(passage.matched_terms)}")
        print(f"  {passage.text[:700]}")
    print(f"Trace: {trace_path}")
    return 0 if result.passages else 1


if __name__ == "__main__":
    raise SystemExit(main())
