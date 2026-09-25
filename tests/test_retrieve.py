"""Offline tests for relevance, diversity, PDF pages, and token budgets."""

from collections import Counter
from pathlib import Path

from pydantic import SecretStr

from src.config import Settings
from src.models import FetchedPage
from src.tools.retrieve import PassageRetriever
from src.trace import JsonlTracer


def settings(**overrides: object) -> Settings:
    values = {
        "openrouter_api_key": SecretStr("sk-or-v1-test-key-long-enough"),
        "openrouter_model": "google/gemini-2.5-flash",
        "usd_inr_rate": 95.5,
        "input_usd_per_million": 0.30,
        "output_usd_per_million": 2.50,
        "max_model_input_tokens": 12_000,
        "max_model_output_tokens": 2_000,
    }
    values.update(overrides)
    return Settings(**values)


def tracer(tmp_path: Path) -> JsonlTracer:
    return JsonlTracer(tmp_path / "retrieve.jsonl", reset=True)


def page(
    url: str,
    text: str,
    *,
    kind: str = "html",
    ok: bool = True,
) -> FetchedPage:
    return FetchedPage(
        url=url,
        final_url=url,
        ok=ok,
        kind=kind,
        extractor="trafilatura" if kind == "html" else "pypdf",
        title="Titan leadership",
        text=text,
        error="" if ok else "failed",
    )


def test_relevant_text_near_document_end_is_selected(tmp_path: Path) -> None:
    text = ("unrelated material " * 150) + (
        "\n\nAjoy Chawla became Managing Director of Titan Company "
        "on January 1 2026."
    )
    retriever = PassageRetriever(settings(), tracer(tmp_path))

    result = retriever.retrieve(
        [page("https://example.com/leadership", text)],
        question="Who is Titan Company's Managing Director in 2026?",
    )

    assert any("Ajoy Chawla" in item.text for item in result.passages)


def test_irrelevant_document_is_not_selected(tmp_path: Path) -> None:
    retriever = PassageRetriever(settings(), tracer(tmp_path))
    result = retriever.retrieve(
        [
            page(
                "https://example.com/relevant",
                "Ajoy Chawla is Managing Director of Titan in 2026.",
            ),
            page(
                "https://example.com/irrelevant",
                "A recipe describes flour, butter, sugar, and baking.",
            ),
        ],
        question="Who is Titan Managing Director in 2026?",
    )

    assert {item.url for item in result.passages} == {
        "https://example.com/relevant"
    }


def test_selected_passages_never_exceed_token_budget(tmp_path: Path) -> None:
    retriever = PassageRetriever(
        settings(retrieval_chunk_size=220, retrieval_chunk_overlap=20),
        tracer(tmp_path),
    )
    result = retriever.retrieve(
        [
            page(
                "https://example.com/long",
                "Titan managing director 2026 details. " * 100,
            )
        ],
        question="Titan managing director 2026",
        token_budget=150,
    )

    assert result.estimated_tokens <= 150


def test_pdf_page_number_survives_retrieval(tmp_path: Path) -> None:
    retriever = PassageRetriever(settings(), tracer(tmp_path))
    result = retriever.retrieve(
        [
            page(
                "https://example.com/report.pdf",
                (
                    "[PDF page 1]\nUnrelated introduction.\n\n"
                    "[PDF page 2]\nAjoy Chawla is Managing Director "
                    "of Titan Company in 2026."
                ),
                kind="pdf",
            )
        ],
        question="Who is Titan Company Managing Director in 2026?",
    )

    assert result.passages[0].pdf_page == 2
    assert result.passages[0].text.startswith("[PDF page 2]")


def test_source_diversity_cap_is_enforced(tmp_path: Path) -> None:
    retriever = PassageRetriever(
        settings(
            retrieval_chunk_size=120,
            retrieval_chunk_overlap=0,
            max_passages_per_source=2,
        ),
        tracer(tmp_path),
    )
    result = retriever.retrieve(
        [
            page(
                "https://one.example/report",
                "Titan managing director 2026 evidence. " * 50,
            ),
            page(
                "https://two.example/report",
                "Titan managing director 2026 confirmation. " * 30,
            ),
        ],
        question="Titan managing director 2026",
    )

    counts = Counter(item.url for item in result.passages)
    assert set(counts) == {
        "https://one.example/report",
        "https://two.example/report",
    }
    assert max(counts.values()) <= 2


def test_failed_pages_are_ignored(tmp_path: Path) -> None:
    retriever = PassageRetriever(settings(), tracer(tmp_path))
    result = retriever.retrieve(
        [
            page(
                "https://example.com/failed",
                "Titan managing director 2026",
                ok=False,
            )
        ],
        question="Titan managing director 2026",
    )

    assert result.documents_considered == 0
    assert result.passages == []
