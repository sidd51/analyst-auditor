"""Bounded web search with Tavily first and DDGS as the fallback."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from ddgs import DDGS
from pydantic import ValidationError
from tavily import TavilyClient

from src.config import Settings, load_settings
from src.models import SearchHit, SearchResponse
from src.trace import JsonlTracer

SearchProvider = Literal["tavily", "ddgs"]


class WebSearch:
    """Normalize two providers behind one small, predictable interface."""

    def __init__(
        self,
        settings: Settings,
        tracer: JsonlTracer,
        *,
        tavily_client: Any | None = None,
        ddgs_factory: Callable[..., Any] = DDGS,
    ) -> None:
        self.settings = settings
        self.tracer = tracer
        self.ddgs_factory = ddgs_factory

        # Tests inject a fake client. Real runs create Tavily only when a key
        # exists, allowing DDGS to remain a no-key fallback.
        if tavily_client is not None:
            self.tavily_client = tavily_client
        elif settings.tavily_api_key is not None:
            self.tavily_client = TavilyClient(
                api_key=settings.tavily_api_key.get_secret_value()
            )
        else:
            self.tavily_client = None

    def search(self, query: str, *, max_results: int | None = None) -> SearchResponse:
        """Search once with Tavily, then fall back once to DDGS."""
        clean_query = query.strip()
        if not clean_query:
            raise ValueError("search query cannot be empty")

        limit = max_results or self.settings.search_results_per_query
        if not 1 <= limit <= 20:
            raise ValueError("max_results must be between 1 and 20")

        attempted: list[SearchProvider] = []
        errors: list[str] = []

        attempted.append("tavily")
        tavily_hits = self._search_tavily(clean_query, limit, errors)
        if tavily_hits:
            return SearchResponse(
                query=clean_query,
                hits=tavily_hits,
                providers_attempted=attempted,
                errors=errors,
                fallback_used=False,
            )

        self.tracer.event(
            "course_change",
            tool="web_search",
            query=clean_query,
            reason="Tavily returned no usable results; trying DDGS once.",
        )

        attempted.append("ddgs")
        ddgs_hits = self._search_ddgs(clean_query, limit, errors)
        return SearchResponse(
            query=clean_query,
            hits=ddgs_hits,
            providers_attempted=attempted,
            errors=errors,
            fallback_used=True,
        )

    def _search_tavily(
        self,
        query: str,
        limit: int,
        errors: list[str],
    ) -> list[SearchHit]:
        self.tracer.event(
            "tool_call",
            tool="web_search",
            provider="tavily",
            query=query,
            max_results=limit,
        )
        if self.tavily_client is None:
            message = "Tavily skipped because TAVILY_API_KEY is missing."
            errors.append(message)
            self.tracer.event(
                "tool_error",
                tool="web_search",
                provider="tavily",
                query=query,
                error_type="MissingAPIKey",
                error=message,
            )
            return []

        try:
            response = self.tavily_client.search(
                query=query,
                search_depth="basic",
                max_results=limit,
                include_answer=False,
                include_raw_content=False,
                include_usage=True,
                timeout=self.settings.page_timeout_seconds,
            )
        except Exception as exc:
            self._record_provider_error("tavily", query, exc, errors)
            return []

        hits = _normalize_tavily(response.get("results") or [], query)
        self._record_result(
            "tavily",
            query,
            hits,
            usage=response.get("usage"),
        )
        if not hits:
            errors.append("Tavily returned no usable results.")
        return hits

    def _search_ddgs(
        self,
        query: str,
        limit: int,
        errors: list[str],
    ) -> list[SearchHit]:
        self.tracer.event(
            "tool_call",
            tool="web_search",
            provider="ddgs",
            query=query,
            max_results=limit,
        )
        try:
            with self.ddgs_factory(
                timeout=self.settings.page_timeout_seconds
            ) as ddgs:
                rows = ddgs.text(
                    query,
                    max_results=limit,
                    backend="duckduckgo",
                )
        except Exception as exc:
            self._record_provider_error("ddgs", query, exc, errors)
            return []

        hits = _normalize_ddgs(rows or [], query)
        self._record_result("ddgs", query, hits)
        if not hits:
            errors.append("DDGS returned no usable results.")
        return hits

    def _record_result(
        self,
        provider: SearchProvider,
        query: str,
        hits: list[SearchHit],
        *,
        usage: Any = None,
    ) -> None:
        self.tracer.event(
            "tool_result",
            tool="web_search",
            provider=provider,
            query=query,
            result_count=len(hits),
            hits=[hit.model_dump() for hit in hits],
            usage=usage,
        )

    def _record_provider_error(
        self,
        provider: SearchProvider,
        query: str,
        exc: Exception,
        errors: list[str],
    ) -> None:
        message = f"{provider} failed: {type(exc).__name__}: {exc}"
        errors.append(message)
        self.tracer.event(
            "tool_error",
            tool="web_search",
            provider=provider,
            query=query,
            error_type=type(exc).__name__,
            error=str(exc),
        )


def _normalize_tavily(rows: list[dict[str, Any]], query: str) -> list[SearchHit]:
    return _normalize_rows(
        rows,
        query=query,
        provider="tavily",
        title_key="title",
        url_key="url",
        snippet_key="content",
    )


def _normalize_ddgs(rows: list[dict[str, Any]], query: str) -> list[SearchHit]:
    return _normalize_rows(
        rows,
        query=query,
        provider="ddgs",
        title_key="title",
        url_key="href",
        snippet_key="body",
    )


def _normalize_rows(
    rows: list[dict[str, Any]],
    *,
    query: str,
    provider: SearchProvider,
    title_key: str,
    url_key: str,
    snippet_key: str,
) -> list[SearchHit]:
    """Map provider-specific keys and remove duplicate or invalid URLs."""
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for row in rows:
        url = str(row.get(url_key) or "").strip()
        dedupe_key = _url_key(url)
        if not dedupe_key or dedupe_key in seen:
            continue
        try:
            hit = SearchHit(
                title=str(row.get(title_key) or "").strip(),
                url=url,
                snippet=str(row.get(snippet_key) or "").strip(),
                provider=provider,
                query=query,
            )
        except ValidationError:
            continue
        hits.append(hit)
        seen.add(dedupe_key)
    return hits


def _url_key(url: str) -> str:
    """Ignore fragments and a final slash when comparing result URLs."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return ""
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            parts.query,
            "",
        )
    )


def main(argv: list[str] | None = None) -> int:
    """Run one live search from the command line."""
    args = argv if argv is not None else sys.argv[1:]
    query = " ".join(args).strip()
    if not query:
        print('Usage: python -m src.tools.search "your query"')
        return 2

    settings = load_settings()
    trace_path = settings.root / "logs" / "step3-search.jsonl"
    tracer = JsonlTracer(trace_path, reset=True)
    response = WebSearch(settings, tracer).search(query)

    print(f"Query: {response.query}")
    print(f"Providers attempted: {', '.join(response.providers_attempted)}")
    if response.errors:
        print("Provider notes:")
        for error in response.errors:
            print(f"- {error}")
    print(f"Results: {len(response.hits)}")
    for index, hit in enumerate(response.hits, start=1):
        print(f"{index}. {hit.title}")
        print(f"   {hit.url}")
        print(f"   {hit.snippet[:240]}")
    print(f"Trace: {trace_path}")
    return 0 if response.hits else 1


if __name__ == "__main__":
    sys.exit(main())
