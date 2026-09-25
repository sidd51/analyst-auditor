"""Offline tests for bounded parallel HTML/PDF fetching."""

from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from src.config import Settings
from src.tools.fetch import ParallelFetcher, _extract_html
from src.trace import JsonlTracer


def settings() -> Settings:
    return Settings(
        openrouter_api_key=SecretStr("sk-or-v1-test-key-long-enough"),
        openrouter_model="google/gemini-2.5-flash",
        usd_inr_rate=95.5,
        input_usd_per_million=0.30,
        output_usd_per_million=2.50,
        max_model_input_tokens=12_000,
        max_model_output_tokens=2_000,
    )


def tracer(tmp_path: Path) -> JsonlTracer:
    return JsonlTracer(tmp_path / "fetch.jsonl", reset=True)


def response(
    url: str,
    content: str | bytes,
    *,
    content_type: str = "text/html",
    status_code: int = 200,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=content.encode() if isinstance(content, str) else content,
        headers={"content-type": content_type},
        request=httpx.Request("GET", url),
    )


def test_trafilatura_extracts_main_html_content() -> None:
    page = _extract_html(
        "https://example.com/story",
        "https://example.com/story",
        200,
        """
        <html><head><title>Titan update</title></head>
        <body><nav>Menu</nav><article>
        <h1>Titan update</h1>
        <p>Ajoy Chawla is Managing Director of Titan Company.</p>
        </article></body></html>
        """,
    )

    assert page.ok is True
    assert page.kind == "html"
    assert "Ajoy Chawla" in page.text
    assert "Menu" not in page.text


def test_beautifulsoup_is_used_when_trafilatura_returns_nothing(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "src.tools.fetch.trafilatura.bare_extraction",
        lambda *_args, **_kwargs: None,
    )
    fetcher = ParallelFetcher(
        settings(),
        tracer(tmp_path),
        http_get=lambda url, **_: response(
            url,
            "<html><body><main>Fallback text</main></body></html>",
        ),
    )

    result = fetcher.fetch_many(["https://example.com/fallback"])

    assert result.pages[0].extractor == "beautifulsoup"
    assert result.pages[0].text == "Fallback text"


def test_page_budget_and_input_order_are_enforced(tmp_path: Path) -> None:
    urls = [f"https://example.com/{number}" for number in range(4)]
    fetcher = ParallelFetcher(
        settings(),
        tracer(tmp_path),
        http_get=lambda url, **_: response(
            url,
            f"<html><body><article>Page {url}</article></body></html>",
        ),
    )

    result = fetcher.fetch_many(urls, page_limit=2)

    assert result.requested_count == 4
    assert result.selected_count == 2
    assert result.skipped_count == 2
    assert [page.url for page in result.pages] == urls[:2]


def test_pdf_parse_failure_is_returned_not_raised(tmp_path: Path) -> None:
    fetcher = ParallelFetcher(
        settings(),
        tracer(tmp_path),
        http_get=lambda url, **_: response(
            url,
            b"%PDF invalid",
            content_type="application/pdf",
        ),
    )

    result = fetcher.fetch_many(["https://example.com/report.pdf"])

    assert result.pages[0].ok is False
    assert result.pages[0].kind == "pdf"
    assert "PDF extraction failed" in result.pages[0].error


def test_http_error_does_not_discard_other_pages(tmp_path: Path) -> None:
    def fake_get(url: str, **_: Any) -> httpx.Response:
        if url.endswith("/blocked"):
            return response(url, "Forbidden", status_code=403)
        return response(url, "<article>Readable page</article>")

    fetcher = ParallelFetcher(
        settings(),
        tracer(tmp_path),
        http_get=fake_get,
    )
    result = fetcher.fetch_many(
        [
            "https://example.com/blocked",
            "https://example.com/working",
        ]
    )

    assert result.pages[0].ok is False
    assert result.pages[0].status_code == 403
    assert result.pages[1].ok is True
