"""Pydantic contracts shared by model calls and web tools."""

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class PingResponse(BaseModel):
    """Tiny Step 2 schema used to prove structured output works."""

    reply: Literal["pong"]
    explanation: str = Field(
        min_length=1,
        max_length=120,
        description="A short confirmation that structured output worked.",
    )


class SearchHit(BaseModel):
    """One normalized result, regardless of which provider returned it."""

    title: str
    url: str
    snippet: str
    provider: Literal["tavily", "ddgs"]
    query: str

    @field_validator("url")
    @classmethod
    def require_http_url(cls, value: str) -> str:
        """Reject empty or non-web links before they reach the fetcher."""
        url = value.strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("search result URL must use http or https")
        return url


class SearchResponse(BaseModel):
    """Results plus enough status information to explain provider failures."""

    query: str
    hits: list[SearchHit] = Field(default_factory=list)
    providers_attempted: list[Literal["tavily", "ddgs"]] = Field(
        default_factory=list
    )
    errors: list[str] = Field(default_factory=list)
    fallback_used: bool = False


class FetchedPage(BaseModel):
    """Readable content and metadata extracted from one URL."""

    url: str
    final_url: str
    ok: bool
    kind: Literal["html", "pdf", "unknown"]
    extractor: Literal["trafilatura", "beautifulsoup", "pypdf", "none"]
    title: str = ""
    published_date: str | None = None
    text: str = ""
    page_count: int | None = None
    status_code: int | None = None
    error: str = ""


class FetchResponse(BaseModel):
    """A bounded group of pages returned in the original URL order."""

    requested_count: int
    selected_count: int
    skipped_count: int
    pages: list[FetchedPage] = Field(default_factory=list)


class EvidencePassage(BaseModel):
    """One source passage selected as possible evidence for a question."""

    passage_id: str
    url: str
    title: str
    document_kind: Literal["html", "pdf"]
    chunk_index: int
    pdf_page: int | None = None
    text: str
    matched_terms: list[str] = Field(default_factory=list)
    relevance_score: float
    estimated_tokens: int


class RetrievalResponse(BaseModel):
    """The bounded evidence packet that a future Analyst will receive."""

    question: str
    requirements: list[str] = Field(default_factory=list)
    documents_considered: int
    passages_considered: int
    passages_selected: int
    passages_omitted: int
    estimated_tokens: int
    token_budget: int
    passages: list[EvidencePassage] = Field(default_factory=list)


class QuestionSpecification(BaseModel):
    """What the question actually asks. Extracted before any search."""

    entities: list[str] = Field(
        min_length=1,
        description="Named companies, people, products, or other subjects.",
    )
    question_type: Literal[
        "identity",
        "multi_field",
        "comparison",
        "ranking",
        "exhaustive",
        "other",
    ] = Field(
        description=(
            "High-level question shape. Used later for planning, never to "
            "pick a page count."
        )
    )
    required_fields: list[str] = Field(
        min_length=1,
        description="Answer fields that must be filled or marked not_found.",
    )
    time_period: str | None = Field(
        default=None,
        description="Year, date, or range such as 2026 or last two years.",
    )
    geography: str | None = Field(
        default=None,
        description="Country or region if the question names one.",
    )
    required_count: int | None = Field(
        default=None,
        ge=1,
        description="How many results are requested, if the question says.",
    )
    ranking: bool = Field(
        default=False,
        description="True if the question asks for a top-N or most/least order.",
    )
    comparison: bool = Field(
        default=False,
        description="True if two or more entities must be compared.",
    )
    exhaustive: bool = Field(
        default=False,
        description="True only if the question asks to list every match.",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Extra limits such as primary sources or as-of dates.",
    )
    not_found_rule: str = Field(
        min_length=1,
        description="When a required field must be reported as not_found.",
    )


class PagePolicy(BaseModel):
    """Python-owned fetch limits. The LLM cannot change these values."""

    initial_pages: int
    wave_size: int
    page_ceiling: int
    stop_when: Literal["requirements_covered"] = "requirements_covered"


class SpecifiedQuestion(BaseModel):
    """Question spec plus the fetch policy attached by Python."""

    question: str
    notes: list[str] = Field(default_factory=list)
    specification: QuestionSpecification
    page_policy: PagePolicy
