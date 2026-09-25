"""Offline tests for the Tavily-to-DDGS search policy."""

from pathlib import Path
from typing import Any

from pydantic import SecretStr

from src.config import Settings
from src.tools.search import WebSearch
from src.trace import JsonlTracer


class FakeTavily:
    def __init__(
        self,
        results: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.results = results or []
        self.error = error

    def search(self, **_: Any) -> dict[str, Any]:
        if self.error:
            raise self.error
        return {"results": self.results, "usage": {"credits": 1}}


class FakeDDGS:
    def __init__(
        self,
        results: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.results = results or []
        self.error = error

    def __enter__(self) -> "FakeDDGS":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def text(self, *_: Any, **__: Any) -> list[dict[str, Any]]:
        if self.error:
            raise self.error
        return self.results


def settings() -> Settings:
    return Settings(
        openrouter_api_key=SecretStr("sk-or-v1-test-key-long-enough"),
        openrouter_model="google/gemini-2.5-flash",
        tavily_api_key=SecretStr("tvly-test"),
        usd_inr_rate=95.5,
        input_usd_per_million=0.30,
        output_usd_per_million=2.50,
        max_model_input_tokens=12_000,
        max_model_output_tokens=2_000,
    )


def tracer(tmp_path: Path) -> JsonlTracer:
    return JsonlTracer(tmp_path / "search.jsonl", reset=True)


def test_tavily_success_does_not_use_fallback(tmp_path: Path) -> None:
    def forbidden_ddgs(**_: Any) -> FakeDDGS:
        raise AssertionError("DDGS should not run after Tavily succeeds")

    tool = WebSearch(
        settings(),
        tracer(tmp_path),
        tavily_client=FakeTavily(
            [{"title": "Titan", "url": "https://example.com/titan", "content": "MD"}]
        ),
        ddgs_factory=forbidden_ddgs,
    )

    response = tool.search("Titan managing director")

    assert response.fallback_used is False
    assert response.providers_attempted == ["tavily"]
    assert response.hits[0].provider == "tavily"


def test_tavily_failure_uses_ddgs_once(tmp_path: Path) -> None:
    tool = WebSearch(
        settings(),
        tracer(tmp_path),
        tavily_client=FakeTavily(error=TimeoutError("tavily timed out")),
        ddgs_factory=lambda **_: FakeDDGS(
            [
                {
                    "title": "Titan",
                    "href": "https://example.com/titan",
                    "body": "Managing Director",
                }
            ]
        ),
    )

    response = tool.search("Titan managing director")

    assert response.fallback_used is True
    assert response.providers_attempted == ["tavily", "ddgs"]
    assert response.hits[0].provider == "ddgs"
    assert "tavily failed" in response.errors[0]


def test_duplicate_urls_are_removed(tmp_path: Path) -> None:
    tool = WebSearch(
        settings(),
        tracer(tmp_path),
        tavily_client=FakeTavily(
            [
                {
                    "title": "First",
                    "url": "https://example.com/report/",
                    "content": "one",
                },
                {
                    "title": "Duplicate",
                    "url": "https://example.com/report#section",
                    "content": "two",
                },
            ]
        ),
    )

    response = tool.search("example report")

    assert len(response.hits) == 1
    assert response.hits[0].title == "First"


def test_both_provider_failures_return_an_empty_explained_result(
    tmp_path: Path,
) -> None:
    tool = WebSearch(
        settings(),
        tracer(tmp_path),
        tavily_client=FakeTavily(error=TimeoutError("tavily down")),
        ddgs_factory=lambda **_: FakeDDGS(error=TimeoutError("ddgs down")),
    )

    response = tool.search("unavailable query")

    assert response.hits == []
    assert response.fallback_used is True
    assert len(response.errors) == 2
