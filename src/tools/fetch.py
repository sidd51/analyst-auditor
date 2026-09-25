"""Fetch several pages concurrently and extract readable HTML or PDF text."""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
import trafilatura
from bs4 import BeautifulSoup
from pypdf import PdfReader

from src.config import Settings, load_settings
from src.models import FetchedPage, FetchResponse
from src.trace import JsonlTracer

USER_AGENT = "analyst-auditor/1.0 (research take-home)"
KNOWN_LOGIN_WALLS = {
    "instagram.com",
    "linkedin.com",
    "www.instagram.com",
    "www.linkedin.com",
}


class ParallelFetcher:
    """Apply a hard page budget, then fetch selected URLs concurrently."""

    def __init__(
        self,
        settings: Settings,
        tracer: JsonlTracer,
        *,
        http_get: Callable[..., httpx.Response] = httpx.get,
    ) -> None:
        self.settings = settings
        self.tracer = tracer
        self.http_get = http_get

    def fetch_many(
        self,
        urls: Iterable[str],
        *,
        page_limit: int | None = None,
    ) -> FetchResponse:
        requested = list(urls)
        limit = page_limit or self.settings.initial_page_budget
        if not 1 <= limit <= self.settings.absolute_page_ceiling:
            raise ValueError(
                "page_limit must be between 1 and the absolute page ceiling"
            )

        selected = self._select_urls(requested, limit)
        for url in selected:
            # Logging every call before starting the pool makes the overlap
            # visible: several calls exist before the first result arrives.
            self.tracer.event("tool_call", tool="fetch_page", url=url)

        pages_by_url: dict[str, FetchedPage] = {}
        worker_count = min(self.settings.fetch_workers, len(selected)) or 1
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {
                pool.submit(self._fetch_one, url): url
                for url in selected
            }
            for future in as_completed(futures):
                url = futures[future]
                try:
                    page = future.result()
                except Exception as exc:
                    # Tool boundaries fail closed. One broken page must not
                    # discard useful results from the other parallel fetches.
                    page = _failed_page(
                        url,
                        f"{type(exc).__name__}: {exc}",
                    )
                pages_by_url[url] = page
                self._trace_result(page)

        return FetchResponse(
            requested_count=len(requested),
            selected_count=len(selected),
            skipped_count=len(requested) - len(selected),
            pages=[pages_by_url[url] for url in selected],
        )

    def _select_urls(self, urls: list[str], limit: int) -> list[str]:
        selected: list[str] = []
        seen: set[str] = set()
        for url in urls:
            clean_url = url.strip()
            parsed = urlsplit(clean_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                self._trace_skip(clean_url, "invalid URL")
                continue
            if parsed.netloc.lower() in KNOWN_LOGIN_WALLS:
                self._trace_skip(clean_url, "known login wall")
                continue

            key = _url_key(clean_url)
            if key in seen:
                self._trace_skip(clean_url, "duplicate URL")
                continue
            if len(selected) >= limit:
                self._trace_skip(clean_url, "page budget reached")
                continue

            selected.append(clean_url)
            seen.add(key)
        return selected

    def _fetch_one(self, url: str) -> FetchedPage:
        try:
            response = self.http_get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=self.settings.page_timeout_seconds,
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return _failed_page(
                url,
                f"HTTP {exc.response.status_code}",
                final_url=str(exc.response.url),
                status_code=exc.response.status_code,
            )
        except httpx.HTTPError as exc:
            return _failed_page(url, f"{type(exc).__name__}: {exc}")

        final_url = str(response.url)
        status_code = response.status_code
        content = response.content
        if len(content) > self.settings.max_download_bytes:
            return _failed_page(
                url,
                (
                    f"document exceeded {self.settings.max_download_bytes} "
                    "download bytes"
                ),
                final_url=final_url,
                status_code=status_code,
            )

        content_type = response.headers.get("content-type", "").lower()
        if _is_pdf(final_url, content_type, content):
            return _extract_pdf(
                url,
                final_url,
                status_code,
                content,
            )
        return _extract_html(
            url,
            final_url,
            status_code,
            response.text,
        )

    def _trace_skip(self, url: str, reason: str) -> None:
        self.tracer.event(
            "course_change",
            tool="fetch_page",
            url=url,
            reason=f"Skipped page: {reason}.",
        )

    def _trace_result(self, page: FetchedPage) -> None:
        self.tracer.event(
            "tool_result",
            tool="fetch_page",
            url=page.url,
            final_url=page.final_url,
            ok=page.ok,
            status_code=page.status_code,
            document_kind=page.kind,
            extractor=page.extractor,
            title=page.title,
            published_date=page.published_date,
            page_count=page.page_count,
            text_chars=len(page.text),
            # Full documents stay in program memory. The trace stores a short
            # preview; Step 3C will log the exact passages sent to the model.
            text_preview=page.text[:500],
            error=page.error,
        )


def _extract_html(
    original_url: str,
    final_url: str,
    status_code: int,
    html: str,
) -> FetchedPage:
    """Use Trafilatura first, then BeautifulSoup when no main text is found."""
    try:
        document = trafilatura.bare_extraction(
            html,
            url=final_url,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
            with_metadata=True,
        )
    except Exception:
        document = None

    if document is not None:
        text = _clean_text(str(document.text or ""))
        if text:
            return FetchedPage(
                url=original_url,
                final_url=final_url,
                ok=True,
                kind="html",
                extractor="trafilatura",
                title=str(document.title or ""),
                published_date=str(document.date) if document.date else None,
                text=text,
                status_code=status_code,
            )

    # Some company sites have unusual markup that main-content extractors miss.
    # The fallback is less precise but better than incorrectly saying no text.
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = _clean_text(main.get_text("\n", strip=True))
    if text:
        return FetchedPage(
            url=original_url,
            final_url=final_url,
            ok=True,
            kind="html",
            extractor="beautifulsoup",
            title=title,
            text=text,
            status_code=status_code,
        )
    return _failed_page(
        original_url,
        "HTML contained no readable text",
        final_url=final_url,
        status_code=status_code,
        kind="html",
    )


def _extract_pdf(
    original_url: str,
    final_url: str,
    status_code: int,
    content: bytes,
) -> FetchedPage:
    """Extract every readable PDF page and keep page labels for citations."""
    try:
        reader = PdfReader(BytesIO(content))
        passages = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = _clean_text(page.extract_text() or "")
            if text:
                passages.append(f"[PDF page {page_number}]\n{text}")
        full_text = "\n\n".join(passages)
        metadata = reader.metadata
        title = str(metadata.title or "") if metadata else ""
    except Exception as exc:
        return _failed_page(
            original_url,
            f"PDF extraction failed: {type(exc).__name__}: {exc}",
            final_url=final_url,
            status_code=status_code,
            kind="pdf",
        )

    if not full_text:
        return _failed_page(
            original_url,
            "PDF contained no readable text",
            final_url=final_url,
            status_code=status_code,
            kind="pdf",
            page_count=len(reader.pages),
        )
    return FetchedPage(
        url=original_url,
        final_url=final_url,
        ok=True,
        kind="pdf",
        extractor="pypdf",
        title=title,
        text=full_text,
        page_count=len(reader.pages),
        status_code=status_code,
    )


def _failed_page(
    url: str,
    error: str,
    *,
    final_url: str | None = None,
    status_code: int | None = None,
    kind: Literal["html", "pdf", "unknown"] = "unknown",
    page_count: int | None = None,
) -> FetchedPage:
    return FetchedPage(
        url=url,
        final_url=final_url or url,
        ok=False,
        kind=kind,
        extractor="none",
        page_count=page_count,
        status_code=status_code,
        error=error,
    )


def _is_pdf(url: str, content_type: str, content: bytes) -> bool:
    return (
        "application/pdf" in content_type
        or url.lower().split("?")[0].endswith(".pdf")
        or content.startswith(b"%PDF")
    )


def _clean_text(text: str) -> str:
    """Collapse noisy whitespace while preserving paragraph boundaries."""
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _url_key(url: str) -> str:
    parsed = urlsplit(url)
    return (
        f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        f"{parsed.path.rstrip('/') or '/'}?{parsed.query}"
    )


def main(argv: list[str] | None = None) -> int:
    """Fetch URLs passed on the command line."""
    urls = argv if argv is not None else sys.argv[1:]
    if not urls:
        print("Usage: python -m src.tools.fetch URL [URL ...]")
        return 2

    settings = load_settings()
    trace_path = settings.root / "logs" / "step3-fetch.jsonl"
    tracer = JsonlTracer(trace_path, reset=True)
    result = ParallelFetcher(settings, tracer).fetch_many(urls)

    print(
        f"Requested: {result.requested_count} | "
        f"Fetched: {result.selected_count} | "
        f"Skipped: {result.skipped_count}"
    )
    for page in result.pages:
        print(
            f"- ok={page.ok} kind={page.kind} "
            f"extractor={page.extractor} chars={len(page.text)}"
        )
        print(f"  {page.final_url}")
        if page.title:
            print(f"  title: {page.title}")
        if page.error:
            print(f"  error: {page.error}")
        elif page.text:
            print(f"  preview: {page.text[:240]}")
    print(f"Trace: {trace_path}")
    return 0 if any(page.ok for page in result.pages) else 1


if __name__ == "__main__":
    sys.exit(main())
